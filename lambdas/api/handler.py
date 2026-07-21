import json
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3

from ddb import DeckRepo
from slug import slugify
import deck_model as dm

CORS = {"Content-Type": "application/json"}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_default(o):
    if isinstance(o, Decimal):
        return int(o) if o == int(o) else float(o)
    raise TypeError(f"not serializable: {type(o).__name__}")


def _resp(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": CORS, "body": json.dumps(body, default=_json_default)}


def _repo() -> DeckRepo:
    return DeckRepo(os.environ["TABLE_NAME"])


def _s3():
    return boto3.client("s3")


def _bucket() -> str:
    return os.environ["BUCKET_NAME"]


def _upload_url(deck_id: str, n: int) -> str:
    return _s3().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": _bucket(),
            "Key": dm.slide_key(deck_id, n),
            "ContentType": "text/html",
        },
        ExpiresIn=300,
    )


def _method(event):
    return event["requestContext"]["http"]["method"]


def _path(event):
    return event.get("rawPath") or event["requestContext"]["http"]["path"]


def _body(event):
    raw = event.get("body")
    return json.loads(raw) if raw else {}


def _pid(event):
    return (event.get("pathParameters") or {}).get("id")


def handler(event, context=None):
    method = _method(event)
    path = _path(event)
    qs = event.get("queryStringParameters") or {}
    repo = _repo()

    if method == "GET" and path == "/api/decks":
        status = qs.get("status") or "active"
        return _resp(200, {"decks": repo.list_by_status(status)})

    if method == "GET" and _pid(event) and path.endswith(_pid(event)):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        for v in item["versions"]:
            v["url"] = "/" + dm.slide_key(item["deckId"], v["n"])
        return _resp(200, item)

    if method == "POST" and path == "/api/decks":
        body = _body(event)
        deck_id = slugify(body["filename"])
        item = repo.get(deck_id)
        if item is None:
            item = dm.new_deck_item(deck_id, body.get("title", deck_id), body.get("tags", []), now_iso())
            repo.put(item)
        n = item["currentVersion"] + 1
        return _resp(200, {"deckId": deck_id, "version": n, "uploadUrl": _upload_url(deck_id, n)})

    if method == "PUT" and path.endswith("/current"):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        try:
            updated = dm.set_current(item, int(_body(event)["version"]), now_iso())
        except ValueError as e:
            return _resp(400, {"error": str(e)})
        repo.put(updated)
        return _resp(200, {"ok": True})

    if method == "PUT" and _pid(event):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        n = item["currentVersion"] + 1
        return _resp(200, {"deckId": item["deckId"], "version": n, "uploadUrl": _upload_url(item["deckId"], n)})

    if method == "POST" and path.endswith("/restore"):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        repo.put(dm.set_status(item, "active", now_iso()))
        return _resp(200, {"ok": True})

    if method == "DELETE" and _pid(event):
        deck_id = _pid(event)
        item = repo.get(deck_id)
        if not item:
            return _resp(404, {"error": "not found"})
        if qs.get("hard") == "true":
            s3 = _s3()
            for prefix in (f"slides/{deck_id}/", f"thumbnails/{deck_id}/"):
                listed = s3.list_objects_v2(Bucket=_bucket(), Prefix=prefix)
                keys = [{"Key": o["Key"]} for o in listed.get("Contents", [])]
                if keys:
                    s3.delete_objects(Bucket=_bucket(), Delete={"Objects": keys})
            repo.delete(deck_id)
        else:
            repo.put(dm.set_status(item, "archived", now_iso()))
        return _resp(200, {"ok": True})

    return _resp(404, {"error": "no route"})
