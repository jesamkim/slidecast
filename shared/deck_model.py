"""Pure, immutable helpers for the SlideDecks data model.

Every mutator returns a NEW dict and never mutates its input, matching the
project immutability rule.
"""
from copy import deepcopy
from typing import Optional


def slide_key(deck_id: str, n: int) -> str:
    return f"slides/{deck_id}/v{n}/index.html"


def thumb_key(deck_id: str, n: int) -> str:
    return f"thumbnails/{deck_id}/v{n}.png"


def next_version(item: dict) -> int:
    """Monotonic next version number: max existing n + 1 (or 1 if none).

    Using max-of-history (rather than currentVersion+1) preserves version
    immutability across rollbacks — after rolling currentVersion back to v1,
    the next upload becomes v3, not an overwrite of v2.
    """
    return max((v["n"] for v in item.get("versions", [])), default=0) + 1


def add_pending_version(item: dict, n: int, now_iso: str) -> dict:
    """Append a placeholder version record (thumbnail/size not yet known),
    set currentVersion=n, and bump updatedAt. Returns a NEW dict.

    Note: this is called by the API BEFORE the client uploads to S3.
    If the client abandons the upload the placeholder version will point at
    a missing S3 object; a subsequent PUT re-issues the same slot and the
    thumbnail Lambda idempotently fills the metadata. Acceptable for a
    personal tool.
    """
    new_item = deepcopy(item)
    record = {
        "n": n,
        "createdAt": now_iso,
        "thumbnailKey": None,
        "sizeBytes": None,
        "slideCount": None,
        "pdfKey": None,
    }
    existing = next((v for v in new_item["versions"] if v["n"] == n), None)
    if existing is None:
        new_item["versions"].append(record)
    else:
        # Preserve original createdAt on re-issue.
        record["createdAt"] = existing.get("createdAt", now_iso)
        idx = new_item["versions"].index(existing)
        new_item["versions"][idx] = record
    new_item["currentVersion"] = n
    new_item["updatedAt"] = now_iso
    return new_item


def set_version_thumbnail(
    item: dict,
    n: int,
    thumbnail_key: str,
    size_bytes: int,
    now_iso: str,
    slide_count: Optional[int] = None,
) -> dict:
    """Fill thumbnailKey/sizeBytes on an EXISTING version n. Returns a NEW dict.

    Raises KeyError if version n does not exist; callers that must tolerate
    the race where the S3 event beats the API write should fall back to
    upsert_version.
    """
    new_item = deepcopy(item)
    idx = next((i for i, v in enumerate(new_item["versions"]) if v["n"] == n), None)
    if idx is None:
        raise KeyError(f"version {n} not present")
    record = dict(new_item["versions"][idx])
    record["thumbnailKey"] = thumbnail_key
    record["sizeBytes"] = size_bytes
    if slide_count is not None:
        record["slideCount"] = slide_count
    new_item["versions"][idx] = record
    new_item["updatedAt"] = now_iso
    return new_item


def new_deck_item(deck_id: str, title: str, tags: list, now_iso: str) -> dict:
    return {
        "deckId": deck_id,
        "type": "deck",
        "title": title,
        "tags": list(tags),
        "group": None,
        "alias": None,
        "status": "active",
        "currentVersion": 0,
        "versions": [],
        "publicToken": None,
        "createdAt": now_iso,
        "updatedAt": now_iso,
    }


RESERVED_ALIASES = frozenset({"api", "slides", "thumbnails", "s", "assets", "web"})


def group_pk(group_id: str) -> str:
    return f"GROUP#{group_id}"


def alias_pk(alias: str) -> str:
    return f"ALIAS#{alias}"


def new_alias_reservation(alias: str, deck_id: str, now_iso: str) -> dict:
    """Reservation item that OWNS an alias. Uniqueness is enforced by a
    conditional PutItem (attribute_not_exists(deckId)) in the repo.

    Deliberately does NOT carry an `alias` attribute so the item stays OUT
    of the byAlias GSI; resolve continues to find the owning deck (which
    still carries `alias`). The reservation is looked up by primary key
    only (ALIAS#{alias}).
    """
    return {
        "deckId": alias_pk(alias),
        "type": "alias",
        "reservedAlias": alias,
        "ownerDeckId": deck_id,
        "createdAt": now_iso,
    }


def new_group_item(group_id: str, name: str, now_iso: str) -> dict:
    return {
        "deckId": group_pk(group_id),
        "type": "group",
        "groupId": group_id,
        "name": name,
        "status": "active",
        "createdAt": now_iso,
    }


def is_valid_alias(alias: str) -> bool:
    return bool(alias) and alias not in RESERVED_ALIASES


def deck_type(item: dict) -> str:
    return item.get("type") or "deck"


def set_group(item: dict, group_id, now_iso: str) -> dict:
    new_item = deepcopy(item)
    new_item["group"] = group_id
    new_item["updatedAt"] = now_iso
    return new_item


def set_alias(item: dict, alias, now_iso: str) -> dict:
    new_item = deepcopy(item)
    new_item["alias"] = alias
    new_item["updatedAt"] = now_iso
    return new_item


def add_version(
    item: dict,
    thumbnail_key: str,
    size_bytes: int,
    now_iso: str,
    slide_count: Optional[int] = None,
) -> dict:
    new_item = deepcopy(item)
    n = new_item["currentVersion"] + 1
    new_item["versions"].append({
        "n": n,
        "createdAt": now_iso,
        "thumbnailKey": thumbnail_key,
        "sizeBytes": size_bytes,
        "slideCount": slide_count,
    })
    new_item["currentVersion"] = n
    new_item["updatedAt"] = now_iso
    return new_item


def upsert_version(
    item: dict,
    n: int,
    thumbnail_key: str,
    size_bytes: int,
    now_iso: str,
    slide_count: Optional[int] = None,
) -> dict:
    """Insert or update version n explicitly (idempotent), returning a NEW dict.

    Uses the caller-supplied n as the source of truth rather than
    auto-incrementing, so replayed or out-of-order events land on the
    correct version.
    """
    new_item = deepcopy(item)
    record = {
        "n": n,
        "createdAt": now_iso,
        "thumbnailKey": thumbnail_key,
        "sizeBytes": size_bytes,
        "slideCount": slide_count,
    }
    existing = next((v for v in new_item["versions"] if v["n"] == n), None)
    if existing is None:
        new_item["versions"].append(record)
    else:
        record["createdAt"] = existing.get("createdAt", now_iso)
        idx = new_item["versions"].index(existing)
        new_item["versions"][idx] = record
    new_item["currentVersion"] = max(new_item["currentVersion"], n)
    new_item["updatedAt"] = now_iso
    return new_item


def set_current(item: dict, n: int, now_iso: str) -> dict:
    if not any(v["n"] == n for v in item["versions"]):
        raise ValueError(f"version {n} does not exist")
    new_item = deepcopy(item)
    new_item["currentVersion"] = n
    new_item["updatedAt"] = now_iso
    return new_item


def public_pk(token: str) -> str:
    return f"PUBLIC#{token}"


def new_public_reservation(token: str, deck_id: str, public_version: int, now_iso: str) -> dict:
    """Reservation item that OWNS a public share token. Uniqueness is enforced
    by conditional PutItem in the repo.

    Deliberately does NOT carry status/updatedAt/alias attrs so it stays out
    of the byUpdatedAt and byAlias GSIs; looked up by PK only (PUBLIC#{token}).
    """
    return {
        "deckId": public_pk(token),
        "type": "public",
        "ownerDeckId": deck_id,
        "publicVersion": public_version,
        "createdAt": now_iso,
    }


def set_public_token(item: dict, token, now_iso: str) -> dict:
    new_item = deepcopy(item)
    new_item["publicToken"] = token
    new_item["updatedAt"] = now_iso
    return new_item


def set_version_pdf(item: dict, n: int, pdf_key: str, now_iso: str) -> dict:
    new_item = deepcopy(item)
    for v in new_item["versions"]:
        if v["n"] == n:
            v["pdfKey"] = pdf_key
            new_item["updatedAt"] = now_iso
            break
    return new_item


def set_status(item: dict, status: str, now_iso: str) -> dict:
    if status not in ("active", "archived"):
        raise ValueError(f"invalid status: {status}")
    new_item = deepcopy(item)
    new_item["status"] = status
    new_item["updatedAt"] = now_iso
    return new_item
