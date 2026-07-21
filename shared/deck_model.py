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


def new_deck_item(deck_id: str, title: str, tags: list, now_iso: str) -> dict:
    return {
        "deckId": deck_id,
        "title": title,
        "tags": list(tags),
        "status": "active",
        "currentVersion": 0,
        "versions": [],
        "createdAt": now_iso,
        "updatedAt": now_iso,
    }


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


def set_current(item: dict, n: int, now_iso: str) -> dict:
    if not any(v["n"] == n for v in item["versions"]):
        raise ValueError(f"version {n} does not exist")
    new_item = deepcopy(item)
    new_item["currentVersion"] = n
    new_item["updatedAt"] = now_iso
    return new_item


def set_status(item: dict, status: str, now_iso: str) -> dict:
    if status not in ("active", "archived"):
        raise ValueError(f"invalid status: {status}")
    new_item = deepcopy(item)
    new_item["status"] = status
    new_item["updatedAt"] = now_iso
    return new_item
