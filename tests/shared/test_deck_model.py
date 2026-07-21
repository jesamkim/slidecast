import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
from deck_model import (
    slide_key, thumb_key, new_deck_item, add_version, upsert_version,
    set_current, set_status,
)

def test_keys():
    assert slide_key("roadmap", 2) == "slides/roadmap/v2/index.html"
    assert thumb_key("roadmap", 2) == "thumbnails/roadmap/v2.png"

def test_new_deck_item():
    item = new_deck_item("roadmap", "Roadmap", ["biz"], "2026-07-21T00:00:00Z")
    assert item["deckId"] == "roadmap"
    assert item["currentVersion"] == 0
    assert item["versions"] == []
    assert item["status"] == "active"
    assert item["title"] == "Roadmap"
    assert item["tags"] == ["biz"]

def test_add_version_is_immutable_and_increments():
    item = new_deck_item("roadmap", "Roadmap", [], "2026-07-21T00:00:00Z")
    v1 = add_version(item, "thumbnails/roadmap/v1.png", 1234, "2026-07-21T01:00:00Z")
    assert item["currentVersion"] == 0  # original untouched
    assert v1["currentVersion"] == 1
    assert v1["versions"][0]["n"] == 1
    assert v1["versions"][0]["thumbnailKey"] == "thumbnails/roadmap/v1.png"
    assert v1["versions"][0]["sizeBytes"] == 1234
    assert v1["updatedAt"] == "2026-07-21T01:00:00Z"
    v2 = add_version(v1, "thumbnails/roadmap/v2.png", 5678, "2026-07-21T02:00:00Z")
    assert v2["currentVersion"] == 2
    assert [v["n"] for v in v2["versions"]] == [1, 2]

def test_upsert_version_explicit_n_insert_update_and_immutable():
    item = new_deck_item("roadmap", "Roadmap", [], "t0")
    # (a) insert n=3 on a fresh deck
    v = upsert_version(item, 3, "thumbnails/roadmap/v3.png", 100, "t1")
    assert v["currentVersion"] == 3
    assert len(v["versions"]) == 1
    assert v["versions"][0]["n"] == 3
    assert v["versions"][0]["thumbnailKey"] == "thumbnails/roadmap/v3.png"
    # (b) re-upsert same n updates thumbnailKey, no duplicate, preserves createdAt
    v2 = upsert_version(v, 3, "thumbnails/roadmap/v3-new.png", 200, "t2")
    assert len(v2["versions"]) == 1
    assert v2["versions"][0]["thumbnailKey"] == "thumbnails/roadmap/v3-new.png"
    assert v2["versions"][0]["createdAt"] == "t1"  # original createdAt preserved
    assert v2["updatedAt"] == "t2"
    assert v2["currentVersion"] == 3
    # (c) original input dict unchanged (immutability)
    assert item["currentVersion"] == 0
    assert item["versions"] == []


def test_set_current_valid_and_invalid():
    item = add_version(new_deck_item("r", "R", [], "t0"), "k1", 1, "t1")
    item = add_version(item, "k2", 2, "t2")
    rolled = set_current(item, 1, "t3")
    assert rolled["currentVersion"] == 1
    assert rolled["updatedAt"] == "t3"
    try:
        set_current(item, 9, "t4")
        assert False, "expected ValueError"
    except ValueError:
        pass

def test_set_status():
    item = new_deck_item("r", "R", [], "t0")
    archived = set_status(item, "archived", "t1")
    assert archived["status"] == "archived"
    assert item["status"] == "active"
