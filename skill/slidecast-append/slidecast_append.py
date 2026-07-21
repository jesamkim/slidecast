"""Append/update/delete a self-contained HTML deck into Slidecast using
profile2 credentials directly (no API auth needed)."""
import argparse
import os
import sys
from datetime import datetime, timezone

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
import deck_model as dm
from ddb import DeckRepo
from slug import slugify

DEFAULT_TABLE = "SlideDecks"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _capture_local(html: bytes) -> bytes:
    from playwright.sync_api import sync_playwright
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        f.write(html); p = f.name
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--no-sandbox"])
        page = b.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(f"file://{p}"); page.wait_for_timeout(1200)
        png = page.screenshot(type="png"); b.close()
    return png


def resolve_target(repo: DeckRepo, deck_id: str) -> int:
    item = repo.get(deck_id)
    return (item["currentVersion"] + 1) if item else 1


def append(html_path, table=DEFAULT_TABLE, bucket=None, dynamodb=None, s3=None,
           capture=None, title=None, tags=None):
    bucket = bucket or os.environ["BUCKET_NAME"]
    s3 = s3 or boto3.client("s3")
    res = dynamodb or boto3.resource("dynamodb")
    capture = capture or _capture_local
    repo = DeckRepo(table, res)

    deck_id = slugify(html_path)
    n = resolve_target(repo, deck_id)
    html = open(html_path, "rb").read()

    s3.put_object(Bucket=bucket, Key=dm.slide_key(deck_id, n), Body=html,
                  ContentType="text/html",
                  CacheControl="public, max-age=31536000, immutable")
    png = capture(html)
    tkey = dm.thumb_key(deck_id, n)
    s3.put_object(Bucket=bucket, Key=tkey, Body=png, ContentType="image/png",
                  CacheControl="public, max-age=31536000, immutable")

    item = repo.get(deck_id)
    if item is None:
        item = dm.new_deck_item(deck_id, title or deck_id, tags or [], now_iso())
    item = dm.add_version(item, tkey, len(html), now_iso())
    repo.put(item)
    return deck_id, n


def rollback(deck_id, n, table=DEFAULT_TABLE, dynamodb=None):
    repo = DeckRepo(table, dynamodb or boto3.resource("dynamodb"))
    item = repo.get(deck_id)
    if not item:
        raise SystemExit(f"deck not found: {deck_id}")
    repo.put(dm.set_current(item, n, now_iso()))


def soft_delete(deck_id, table=DEFAULT_TABLE, dynamodb=None):
    repo = DeckRepo(table, dynamodb or boto3.resource("dynamodb"))
    item = repo.get(deck_id)
    if not item:
        raise SystemExit(f"deck not found: {deck_id}")
    repo.put(dm.set_status(item, "archived", now_iso()))


def hard_delete(deck_id, table=DEFAULT_TABLE, bucket=None, dynamodb=None, s3=None):
    bucket = bucket or os.environ["BUCKET_NAME"]
    s3 = s3 or boto3.client("s3")
    repo = DeckRepo(table, dynamodb or boto3.resource("dynamodb"))
    for prefix in (f"slides/{deck_id}/", f"thumbnails/{deck_id}/"):
        listed = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
        keys = [{"Key": o["Key"]} for o in listed.get("Contents", [])]
        if keys:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": keys})
    repo.delete(deck_id)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html", nargs="?")
    ap.add_argument("--title")
    ap.add_argument("--tags")
    ap.add_argument("--rollback", nargs=2, metavar=("DECK", "N"))
    ap.add_argument("--delete", metavar="DECK")
    ap.add_argument("--hard", action="store_true")
    a = ap.parse_args()
    table = os.environ.get("SLIDECAST_TABLE", DEFAULT_TABLE)
    if a.rollback:
        rollback(a.rollback[0], int(a.rollback[1]), table)
        return
    if a.delete:
        if a.hard:
            hard_delete(a.delete, table)
        else:
            soft_delete(a.delete, table)
        return
    if a.html:
        tags = a.tags.split(",") if a.tags else []
        deck_id, n = append(a.html, table, title=a.title, tags=tags)
        print(f"uploaded: {deck_id} v{n}")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
