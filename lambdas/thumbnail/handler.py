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

    Uses the Chromium binary bundled via a Lambda layer at /opt/chromium.
    Isolated here so unit tests can stub it.
    """
    import tempfile
    from playwright.sync_api import sync_playwright

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        f.write(html_bytes)
        html_path = f.name
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("CHROMIUM_PATH", "/opt/chromium/chrome"),
            args=["--no-sandbox", "--disable-gpu", "--single-process"],
        )
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(f"file://{html_path}")
        page.wait_for_timeout(1200)
        png = page.screenshot(type="png")
        browser.close()
    return png


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
        if item is None:
            item = dm.new_deck_item(deck_id, deck_id, [], now_iso())
        existing = next((v for v in item["versions"] if v["n"] == n), None)
        if existing is None:
            item = dm.add_version(item, tkey, len(html), now_iso())
        else:
            existing["thumbnailKey"] = tkey
            item["updatedAt"] = now_iso()
            item["currentVersion"] = max(item["currentVersion"], n)
        repo.put(item)
