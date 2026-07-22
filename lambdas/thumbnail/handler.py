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
    """Export the deck to PDF via Chromium print-to-PDF.

    Uses print emulation honoring the deck's `@page { size: 1920px 1080px }`
    so each slide lands on its own page, AND emits real, selectable text with
    clickable `<a>` link annotations (source citations, resource lists, the
    demo link). This replaced an earlier screenshot-assembly path, which
    produced flat PNG pages with no links; text/links matter more than
    pixel-exact animation state, and fonts are embedded (base64), so the CJK
    tofu that first motivated the screenshot path no longer occurs.

    Before printing we force every slide `.active` and reveal all `data-step`
    elements to their final state, so step-built content isn't hidden in the
    printout. The deck's `@media print` block already lays slides out one per
    page and hides the animated aurora background.
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
                page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
                page.goto(f"file://{html_path}", wait_until="load", timeout=15000)
                try:
                    page.evaluate("() => document.fonts && document.fonts.ready")
                except Exception:
                    pass
                page.wait_for_timeout(1000)

                # For html-slide decks, reveal every slide + every step so the
                # print (which lays out all .slide blocks via @media print) shows
                # fully-built content. No-op for decks without .slide/[data-step].
                page.evaluate("""() => {
                    document.querySelectorAll('.slide').forEach(s => s.classList.add('active'));
                    document.querySelectorAll('[data-step]').forEach(el => {
                        el.classList.add('revealed');
                        el.style.opacity = '1';
                        el.style.transform = 'none';
                        el.style.visibility = 'visible';
                    });
                }""")
                page.wait_for_timeout(300)

                # print-to-PDF honors the deck's @page size (1920x1080) and
                # emits selectable text + clickable link annotations.
                return page.pdf(print_background=True, prefer_css_page_size=True)
            finally:
                browser.close()
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
