"""Append/update/delete a self-contained HTML deck into Slidecast using
profile2 credentials directly (no API auth needed)."""
import argparse
import os
import secrets
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
    # Monotonic: max existing version + 1. Prevents overwriting an
    # immutable prior version after rolling currentVersion back.
    return dm.next_version(item) if item else 1


def append(html_path, table=DEFAULT_TABLE, bucket=None, dynamodb=None, s3=None,
           capture=None, title=None, tags=None, group=None, alias=None):
    bucket = bucket or os.environ["BUCKET_NAME"]
    s3 = s3 or boto3.client("s3")
    res = dynamodb or boto3.resource("dynamodb")
    capture = capture or _capture_local
    repo = DeckRepo(table, res)

    deck_id = slugify(html_path)
    n = resolve_target(repo, deck_id)

    # Validate + atomically reserve the alias BEFORE any S3 upload.
    # Otherwise a rejected alias would leave orphan slide/thumbnail
    # objects in the bucket (and trigger the thumbnail S3 event).
    aslug = None
    prior_alias = None
    if alias is not None:
        if not isinstance(alias, str) or not alias.strip():
            raise SystemExit("empty alias")
        aslug = slugify(alias)
        if not dm.is_valid_alias(aslug):
            raise SystemExit(f"invalid or reserved alias: {alias}")
        existing = repo.get(deck_id)
        prior_alias = existing.get("alias") if existing else None
        if prior_alias != aslug:
            if not repo.reserve_alias(aslug, deck_id, now_iso()):
                raise SystemExit(f"alias '{aslug}' already taken")

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
    # Use upsert_version with the pre-resolved n so post-rollback appends
    # land at max+1 rather than overwriting an existing immutable version.
    item = dm.upsert_version(item, n, tkey, len(html), now_iso())

    if group is not None:
        gid = slugify(group)
        if repo.get(dm.group_pk(gid)) is None:
            repo.put(dm.new_group_item(gid, group, now_iso()))
        item = dm.set_group(item, gid, now_iso())

    if aslug is not None:
        if prior_alias and prior_alias != aslug:
            repo.release_alias(prior_alias)
        item = dm.set_alias(item, aslug, now_iso())

    repo.put(item)
    return deck_id, n


def new_group(name, table=DEFAULT_TABLE, dynamodb=None):
    repo = DeckRepo(table, dynamodb or boto3.resource("dynamodb"))
    gid = slugify(name)
    if repo.get(dm.group_pk(gid)) is not None:
        raise SystemExit(f"group already exists: {gid}")
    repo.put(dm.new_group_item(gid, name, now_iso()))
    return gid


def del_group(group_id, table=DEFAULT_TABLE, dynamodb=None):
    repo = DeckRepo(table, dynamodb or boto3.resource("dynamodb"))
    for status in ("active", "archived"):
        for d in repo.list_by_status(status):
            if dm.deck_type(d) == "deck" and d.get("group") == group_id:
                repo.put(dm.set_group(d, None, now_iso()))
    repo.delete(dm.group_pk(group_id))


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


def _delete_prefix(s3, bucket: str, prefix: str) -> None:
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kwargs)
        keys = [{"Key": o["Key"]} for o in resp.get("Contents", [])]
        if keys:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": keys})
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break


def share(deck_id, table=DEFAULT_TABLE, bucket=None, dynamodb=None, s3=None) -> str:
    bucket = bucket or os.environ["BUCKET_NAME"]
    s3 = s3 or boto3.client("s3")
    repo = DeckRepo(table, dynamodb or boto3.resource("dynamodb"))
    item = repo.get(deck_id)
    if not item:
        raise SystemExit(f"deck not found: {deck_id}")
    existing = item.get("publicToken")
    if existing:
        return f"/p/{existing}"
    n = item.get("currentVersion")
    while True:
        token = secrets.token_urlsafe(12)
        if repo.reserve_public(token, deck_id, n, now_iso()):
            break
    s3.copy_object(
        Bucket=bucket,
        Key=f"public/{token}/index.html",
        CopySource={"Bucket": bucket, "Key": dm.slide_key(deck_id, n)},
        MetadataDirective="REPLACE",
        ContentType="text/html",
        CacheControl="no-cache, no-store, must-revalidate",
    )
    repo.put(dm.set_public_token(item, token, now_iso()))
    return f"/p/{token}"


def unshare(deck_id, table=DEFAULT_TABLE, bucket=None, dynamodb=None, s3=None) -> None:
    bucket = bucket or os.environ["BUCKET_NAME"]
    s3 = s3 or boto3.client("s3")
    repo = DeckRepo(table, dynamodb or boto3.resource("dynamodb"))
    item = repo.get(deck_id)
    if not item:
        raise SystemExit(f"deck not found: {deck_id}")
    token = item.get("publicToken")
    if token:
        _delete_prefix(s3, bucket, f"public/{token}/")
        repo.release_public(token)
    repo.put(dm.set_public_token(item, None, now_iso()))


def hard_delete(deck_id, table=DEFAULT_TABLE, bucket=None, dynamodb=None, s3=None):
    bucket = bucket or os.environ["BUCKET_NAME"]
    s3 = s3 or boto3.client("s3")
    repo = DeckRepo(table, dynamodb or boto3.resource("dynamodb"))
    item = repo.get(deck_id)
    prefixes = [f"slides/{deck_id}/", f"thumbnails/{deck_id}/", f"pdfs/{deck_id}/"]
    token = item.get("publicToken") if item else None
    if token:
        prefixes.append(f"public/{token}/")
    for prefix in prefixes:
        _delete_prefix(s3, bucket, prefix)
    if token:
        repo.release_public(token)
    if item and item.get("alias"):
        repo.release_alias(item["alias"])
    repo.delete(deck_id)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html", nargs="?")
    ap.add_argument("--title")
    ap.add_argument("--tags")
    ap.add_argument("--group")
    ap.add_argument("--alias")
    ap.add_argument("--new-group", dest="new_group", metavar="NAME")
    ap.add_argument("--del-group", dest="del_group", metavar="GROUPID")
    ap.add_argument("--rollback", nargs=2, metavar=("DECK", "N"))
    ap.add_argument("--delete", metavar="DECK")
    ap.add_argument("--hard", action="store_true")
    ap.add_argument("--share", metavar="DECK")
    ap.add_argument("--unshare", metavar="DECK")
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
    if a.share:
        print(share(a.share, table))
        return
    if a.unshare:
        unshare(a.unshare, table)
        print(f"unshared: {a.unshare}")
        return
    if a.new_group:
        gid = new_group(a.new_group, table)
        print(f"group created: {gid}")
        return
    if a.del_group:
        del_group(a.del_group, table)
        print(f"group deleted: {a.del_group}")
        return
    if a.html:
        tags = a.tags.split(",") if a.tags else []
        deck_id, n = append(a.html, table, title=a.title, tags=tags,
                            group=a.group, alias=a.alias)
        print(f"uploaded: {deck_id} v{n}")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
