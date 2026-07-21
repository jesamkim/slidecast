# v3 PDF Layout Fix Report

## Problem
`capture_pdf` used `page.pdf(print_background=True, prefer_css_page_size=True)`, which
triggers Chromium's PRINT emulation. That path applied the html-slide deck's `@media print`
CSS: `#stage` flattened to `height:auto`, slides went `position:relative`, and every
`[data-step]` element rendered simultaneously. Absolutely-positioned step blocks then
overflowed to the next page, producing garbled layouts where text bled onto the wrong
page. The print stylesheet did not reproduce the on-screen browser view.

## New approach
Screenshot each slide on SCREEN (no print emulation) and assemble the PNGs into a PDF.

Steps in `capture_pdf`:
1. Launch headless Chromium with a 1920x1080 viewport and `device_scale_factor=1`.
2. Load the HTML from a temp file, let fonts settle.
3. Count `.slide` elements and grab `#stage`. If either is missing, fall back to
   Chromium print-to-PDF (`page.pdf(prefer_css_page_size=True)`) so non-html-slide
   decks still get a reasonable export.
4. Neutralize the on-screen scale transform on `#stage` (set `transform:none`,
   `margin:0`) and make `#viewport` `display:block` so the stage renders 1:1
   at 1920x1080.
5. For each slide index, toggle `.active` on that slide only, and force every
   `[data-step]` descendant into its final revealed state (add `.revealed`,
   set `opacity:1`, `transform:none`, `visibility:visible`).
6. Screenshot the `#stage` element as PNG (1920x1080).
7. Assemble the PNGs into a single PDF via Pillow (`Image.save(..., save_all=True,
   append_images=..., resolution=96.0)`), one page per slide.

Because the export path is now identical to what the browser paints, the exported
PDF matches the on-screen layout exactly and step-build slides show their final
state without overflow.

## Fallback
Non-html-slide decks (no `.slide`/`#stage`) fall back to Chromium's native
`page.pdf()` honoring the deck's own `@page` size.

## Files touched
- `lambdas/thumbnail/handler.py` — rewrote `capture_pdf`. `capture_png` and
  `handler()` unchanged.
- `lambdas/thumbnail/Dockerfile` — added `Pillow==10.4.0` to the pip install
  line.
- Tests unchanged (unit tests stub `capture_pdf`).

## Tests
- `tests/lambdas/test_thumbnail_v3.py` and `tests/lambdas/test_thumbnail.py`:
  6 passed.
- Full suite: 104 passed.
