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

    # --- groups ---
    if method == "GET" and path == "/api/groups":
        return _resp(200, {"groups": repo.list_groups()})

    if method == "POST" and path == "/api/groups":
        name = _body(event)["name"]
        gid = slugify(name)
        if repo.get(dm.group_pk(gid)) is not None:
            return _resp(409, {"error": "group exists"})
        repo.put(dm.new_group_item(gid, name, now_iso()))
        return _resp(200, {"groupId": gid, "name": name})

    if method == "DELETE" and "/api/groups/" in path:
        gid = (event.get("pathParameters") or {}).get("groupId") or path.rsplit("/", 1)[-1]
        for status in ("active", "archived"):
            for d in repo.list_by_status(status):
                if dm.deck_type(d) == "deck" and d.get("group") == gid:
                    repo.put(dm.set_group(d, None, now_iso()))
        repo.delete(dm.group_pk(gid))
        return _resp(200, {"ok": True})

    # --- resolve ---
    if method == "GET" and "/api/resolve/" in path:
        alias = (event.get("pathParameters") or {}).get("alias") or path.rsplit("/", 1)[-1]
        item = repo.query_by_alias(alias)
        if not item:
            return _resp(404, {"error": "not found"})
        for v in item["versions"]:
            v["url"] = "/" + dm.slide_key(item["deckId"], v["n"])
        return _resp(200, item)

    # --- deck group/alias assignment (before generic PUT) ---
    if method == "PUT" and path.endswith("/group"):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        gid = _body(event).get("groupId")
        if gid is not None and repo.get(dm.group_pk(gid)) is None:
            return _resp(400, {"error": "group does not exist"})
        repo.put(dm.set_group(item, gid, now_iso()))
        return _resp(200, {"ok": True})

    if method == "PUT" and path.endswith("/alias"):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        raw = _body(event).get("alias")
        now = now_iso()
        if raw is None:
            old = item.get("alias")
            if old:
                repo.release_alias(old)
            repo.put(dm.set_alias(item, None, now))
            return _resp(200, {"ok": True})
        # slugify("") returns the "deck" fallback, so an empty/whitespace
        # alias would silently be accepted. Reject up front.
        if not isinstance(raw, str) or not raw.strip():
            return _resp(400, {"error": "empty alias"})
        alias = slugify(raw)
        if not dm.is_valid_alias(alias):
            return _resp(400, {"error": "invalid or reserved alias"})
        old = item.get("alias")
        if old == alias:
            return _resp(200, {"ok": True})
        # Atomic reservation is the source of truth for uniqueness.
        if not repo.reserve_alias(alias, item["deckId"], now):
            return _resp(409, {"error": "alias taken"})
        # Deck.put immediately after so the reservation and the deck's
        # `alias` attribute stay consistent. On the rare failure between
        # these two writes the reservation would be dangling until the
        # next set/clear/hard-delete of this deck — acceptable for a
        # personal tool.
        if old:
            repo.release_alias(old)
        repo.put(dm.set_alias(item, alias, now))
        return _resp(200, {"ok": True})

    if method == "GET" and path == "/api/decks":
        status = qs.get("status") or "active"
        group = qs.get("group")
        decks = [d for d in repo.list_by_status(status) if dm.deck_type(d) == "deck"]
        if group is not None:
            key = None if group == "__unassigned__" else group
            decks = [d for d in decks if d.get("group") == key]
        return _resp(200, {"decks": decks})

    if method == "GET" and _pid(event) and path.endswith("/" + _pid(event)):
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
        now = now_iso()
        if item is None:
            item = dm.new_deck_item(deck_id, body.get("title", deck_id), body.get("tags", []), now)
        n = dm.next_version(item)
        # API owns version creation: persist the pending version BEFORE
        # returning the presigned URL, so a deck without a completed thumbnail
        # is still playable / recoverable.
        item = dm.add_pending_version(item, n, now)
        repo.put(item)
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

    if method == "POST" and path.endswith("/restore"):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        repo.put(dm.set_status(item, "active", now_iso()))
        return _resp(200, {"ok": True})

    if method == "PUT" and _pid(event):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        now = now_iso()
        n = dm.next_version(item)
        item = dm.add_pending_version(item, n, now)
        repo.put(item)
        return _resp(200, {"deckId": item["deckId"], "version": n, "uploadUrl": _upload_url(item["deckId"], n)})

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
            alias = item.get("alias")
            if alias:
                repo.release_alias(alias)
            repo.delete(deck_id)
        else:
            repo.put(dm.set_status(item, "archived", now_iso()))
        return _resp(200, {"ok": True})

    return _resp(404, {"error": "no route"})
