import os
import re
from datetime import datetime, timezone

import boto3

from ddb import DeckRepo
import deck_model as dm

_KEY_RE = re.compile(r"^slides/(?P<deck>[^/]+)/v(?P<n>\d+)/index\.html$")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_key(key: str):
    m = _KEY_RE.match(key)
    if not m:
        raise ValueError(f"unexpected key: {key}")
    return m.group("deck"), int(m.group("n"))


def capture_png(html_bytes: bytes) -> bytes:
    """Render the deck's first frame to a 1920x1080 PNG using headless Chromium.

    Runs inside a container-image Lambda (see lambdas/thumbnail/Dockerfile).
    Playwright manages its own Chromium install under PLAYWRIGHT_BROWSERS_PATH,
    so we let it pick the executable. The playwright import stays inside this
    function so the module remains importable without playwright (tests stub
    capture_png directly).
    """
    import tempfile
    from playwright.sync_api import sync_playwright

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        f.write(html_bytes)
        html_path = f.name
    # Playwright's launch() creates its own temp user-data-dir and removes it
    # on browser.close(); we just tell Chromium to keep on-disk caches tiny.
    launch_args = [
        "--no-sandbox", "--disable-gpu", "--single-process",
        "--disk-cache-size=1", "--media-cache-size=1",
    ]
    launch_kwargs = {"args": launch_args}
    exe = os.environ.get("CHROMIUM_PATH")
    if exe:
        launch_kwargs["executable_path"] = exe
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, **launch_kwargs)
            try:
                page = browser.new_page(viewport={"width": 1920, "height": 1080})
                page.goto(f"file://{html_path}", wait_until="load", timeout=15000)
                # Give @font-face (bundled Noto CJK, embedded base64) a brief moment to apply.
                # Do NOT wait for networkidle: html-slide decks animate continuously and never
                # reach network idle, which would burn the whole Lambda timeout.
                try:
                    page.evaluate("() => document.fonts && document.fonts.ready")
                except Exception:
                    pass
                page.wait_for_timeout(1000)
                png = page.screenshot(type="png")
            finally:
                browser.close()
        return png
    finally:
        try:
            os.unlink(html_path)
        except OSError:
            pass


def capture_pdf(html_bytes: bytes) -> bytes:
    """Render each slide as an on-screen screenshot and assemble a PDF.

    Uses screen media (not print emulation) so the exported PDF matches the
    browser layout exactly, with step-build animations shown in their final
    (fully revealed) state. Falls back to Chromium print-to-PDF for decks
    that don't use the html-slide .slide/#stage structure.
    """
    import tempfile, io
    from playwright.sync_api import sync_playwright
    from PIL import Image

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        f.write(html_bytes)
        html_path = f.name
    # Playwright's launch() creates its own temp user-data-dir and removes it
    # on browser.close(); we just tell Chromium to keep on-disk caches tiny.
    launch_args = [
        "--no-sandbox", "--disable-gpu", "--single-process",
        "--disk-cache-size=1", "--media-cache-size=1",
    ]
    launch_kwargs = {"args": launch_args}
    exe = os.environ.get("CHROMIUM_PATH")
    if exe:
        launch_kwargs["executable_path"] = exe
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, **launch_kwargs)
            try:
                page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
                page.goto(f"file://{html_path}", wait_until="load", timeout=15000)
                try:
                    page.evaluate("() => document.fonts && document.fonts.ready")
                except Exception:
                    pass
                page.wait_for_timeout(1000)

                n = page.evaluate("() => document.querySelectorAll('.slide').length")
                stage = page.query_selector("#stage")
                if not n or stage is None:
                    # Fallback: non-html-slide deck -> print-to-PDF honoring its @page.
                    return page.pdf(print_background=True, prefer_css_page_size=True)

                # Neutralize the on-screen scale transform so #stage is captured 1:1 at 1920x1080.
                page.evaluate("""() => {
                    const st = document.getElementById('stage');
                    if (st) { st.style.transform = 'none'; st.style.margin = '0'; }
                    const vp = document.getElementById('viewport');
                    if (vp) { vp.style.display = 'block'; }
                }""")

                shots = []
                for i in range(n):
                    page.evaluate("""(idx) => {
                        const slides = [...document.querySelectorAll('.slide')];
                        slides.forEach((s, k) => s.classList.toggle('active', k === idx));
                        // reveal every step in the active slide (final animation state)
                        slides[idx].querySelectorAll('[data-step]').forEach(el => {
                            el.classList.add('revealed');
                            el.style.opacity = '1';
                            el.style.transform = 'none';
                            el.style.visibility = 'visible';
                        });
                    }""", i)
                    page.wait_for_timeout(300)  # let layout/reveal settle
                    st = page.query_selector("#stage")
                    shots.append(st.screenshot(type="png"))
            finally:
                browser.close()

        # Assemble PNGs into a single PDF, one 1920x1080 page per slide.
        images = [Image.open(io.BytesIO(b)).convert("RGB") for b in shots]
        out = io.BytesIO()
        images[0].save(out, format="PDF", save_all=True, append_images=images[1:], resolution=96.0)
        return out.getvalue()
    finally:
        try:
            os.unlink(html_path)
        except OSError:
            pass


def handler(event, context=None):
    s3 = boto3.client("s3")
    repo = DeckRepo(os.environ["TABLE_NAME"])
    bucket = os.environ["BUCKET_NAME"]
    for record in event.get("Records", []):
        key = record["s3"]["object"]["key"]
        deck_id, n = parse_key(key)
        html = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        png = capture_png(html)
        tkey = dm.thumb_key(deck_id, n)
        s3.put_object(
            Bucket=bucket, Key=tkey, Body=png, ContentType="image/png",
            CacheControl="public, max-age=31536000, immutable",
        )
        item = repo.get(deck_id)
        now = now_iso()
        if item is None:
            item = dm.new_deck_item(deck_id, deck_id, [], now)
        # API is the owner of version creation; we just fill in thumbnail
        # metadata on the existing pending version. If the S3 event races
        # ahead of the API write, fall back to upsert_version so no data
        # is lost.
        try:
            item = dm.set_version_thumbnail(item, n, tkey, len(html), now)
        except KeyError:
            item = dm.upsert_version(item, n, tkey, len(html), now)
        repo.put(item)

        pdf = capture_pdf(html)
        pkey = dm.pdf_key(deck_id, n)
        s3.put_object(
            Bucket=bucket, Key=pkey, Body=pdf, ContentType="application/pdf",
            CacheControl="public, max-age=31536000, immutable",
        )
        latest = repo.get(deck_id) or item
        latest = dm.set_version_pdf(latest, n, pkey, now_iso())
        repo.put(latest)
