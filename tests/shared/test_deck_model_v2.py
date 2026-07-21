import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
from deck_model import (
    RESERVED_ALIASES, group_pk, new_group_item, is_valid_alias,
    set_group, set_alias, deck_type, new_deck_item,
)


def test_group_pk_and_item():
    g = new_group_item("marketing", "Marketing", "2026-07-21T00:00:00Z")
    assert g["deckId"] == "GROUP#marketing"
    assert g["type"] == "group"
    assert g["groupId"] == "marketing"
    assert g["name"] == "Marketing"
    assert g["status"] == "active"


def test_is_valid_alias():
    assert is_valid_alias("roadmap") is True
    assert is_valid_alias("api") is False
    assert is_valid_alias("") is False


def test_set_group_immutable():
    d = new_deck_item("x", "X", [], "t0")
    g = set_group(d, "marketing", "t1")
    assert d.get("group") is None
    assert g["group"] == "marketing"
    assert g["updatedAt"] == "t1"
    assert set_group(g, None, "t2")["group"] is None


def test_set_alias_immutable():
    d = new_deck_item("x", "X", [], "t0")
    a = set_alias(d, "road", "t1")
    assert d.get("alias") is None
    assert a["alias"] == "road"


def test_new_deck_item_has_v2_defaults():
    d = new_deck_item("x", "X", [], "t0")
    assert d["type"] == "deck"
    assert d["group"] is None
    assert d["alias"] is None


def test_deck_type_defaults_to_deck():
    assert deck_type({"deckId": "x"}) == "deck"
    assert deck_type({"type": "group"}) == "group"
