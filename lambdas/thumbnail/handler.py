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


def _overlay_link_annotations(image_pdf: bytes, per_page_links: list) -> bytes:
    """Add clickable URI link annotations onto a flat image PDF.

    `per_page_links[i]` is a list of {href,x,y,w,h} in #stage pixel space
    (1920x1080, origin top-left). We map those onto each PDF page's box,
    flipping to PDF's bottom-left origin. This gives the screenshot-assembled
    PDF (which is pixel-identical to the on-screen deck) real clickable links
    without changing a single pixel of the render.
    """
    import io
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (ArrayObject, NumberObject, DictionaryObject,
                               NameObject, TextStringObject)

    STAGE_W, STAGE_H = 1920, 1080
    reader = PdfReader(io.BytesIO(image_pdf))
    writer = PdfWriter()
    for pi, page in enumerate(reader.pages):
        pw = float(page.mediabox.width)
        ph = float(page.mediabox.height)
        sx, sy = pw / STAGE_W, ph / STAGE_H
        for lk in (per_page_links[pi] if pi < len(per_page_links) else []):
            x1 = lk["x"] * sx
            x2 = (lk["x"] + lk["w"]) * sx
            y1 = ph - (lk["y"] + lk["h"]) * sy  # flip to PDF origin (bottom-left)
            y2 = ph - lk["y"] * sy
            annot = DictionaryObject({
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Link"),
                NameObject("/Rect"): ArrayObject(
                    [NumberObject(x1), NumberObject(y1), NumberObject(x2), NumberObject(y2)]),
                NameObject("/Border"): ArrayObject(
                    [NumberObject(0), NumberObject(0), NumberObject(0)]),
                NameObject("/A"): DictionaryObject({
                    NameObject("/S"): NameObject("/URI"),
                    NameObject("/URI"): TextStringObject(lk["href"]),
                }),
            })
            ref = writer._add_object(annot)
            if "/Annots" in page:
                page[NameObject("/Annots")].append(ref)
            else:
                page[NameObject("/Annots")] = ArrayObject([ref])
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def capture_pdf(html_bytes: bytes) -> bytes:
    """Render each slide as an on-screen screenshot, assemble a PDF, then
    overlay clickable link annotations at each `<a href>`'s position.

    The screenshot assembly makes the PDF pixel-identical to the on-screen
    deck (the html-slide engine relies on a CSS `scale()` fit that Chromium's
    print emulation lays out differently, shifting objects and clipping
    nowrap labels — so print-to-PDF is not an option). Screenshots alone
    produce flat pages with no links; we restore clickable source/resource/
    demo links by reading each anchor's rect (in #stage pixel space) and
    writing matching PDF Link annotations via `_overlay_link_annotations`.
    Selectable text is the one thing this can't give (pages are images).
    Falls back to Chromium print-to-PDF for decks without the
    html-slide .slide/#stage structure.
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
                per_page_links = []
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
                    # Collect this slide's <a href> rects relative to #stage (pixel space).
                    per_page_links.append(page.evaluate("""() => {
                        const st = document.getElementById('stage').getBoundingClientRect();
                        return [...document.querySelectorAll('.slide.active a[href]')]
                            .map(a => { const r = a.getBoundingClientRect();
                                return { href: a.href, x: r.left - st.left, y: r.top - st.top,
                                         w: r.width, h: r.height }; })
                            .filter(o => o.w > 0 && o.h > 0);
                    }"""))
            finally:
                browser.close()

        # Assemble PNGs into a single PDF, one 1920x1080 page per slide.
        images = [Image.open(io.BytesIO(b)).convert("RGB") for b in shots]
        out = io.BytesIO()
        images[0].save(out, format="PDF", save_all=True, append_images=images[1:], resolution=96.0)
        # Overlay clickable link annotations at each anchor's position.
        return _overlay_link_annotations(out.getvalue(), per_page_links)
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
