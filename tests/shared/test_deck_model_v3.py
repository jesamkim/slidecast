import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
from deck_model import (
    public_pk, new_public_reservation, set_public_token, set_version_pdf,
    new_deck_item, add_pending_version,
)

def test_public_pk_and_reservation():
    r = new_public_reservation("tok123", "roadmap", 2, "2026-07-21T00:00:00Z")
    assert r["deckId"] == "PUBLIC#tok123"
    assert r["type"] == "public"
    assert r["ownerDeckId"] == "roadmap"
    assert r["publicVersion"] == 2
    assert "status" not in r and "alias" not in r  # stays out of GSIs

def test_set_public_token_immutable():
    d = new_deck_item("x", "X", [], "t0")
    on = set_public_token(d, "tok", "t1")
    assert d.get("publicToken") is None
    assert on["publicToken"] == "tok"
    assert set_public_token(on, None, "t2")["publicToken"] is None

def test_new_deck_item_has_public_default():
    assert new_deck_item("x", "X", [], "t0")["publicToken"] is None

def test_set_version_pdf():
    d = new_deck_item("x", "X", [], "t0")
    d = add_pending_version(d, 1, "t1")
    d2 = set_version_pdf(d, 1, "pdfs/x/v1.pdf", "t2")
    v = next(v for v in d2["versions"] if v["n"] == 1)
    assert v["pdfKey"] == "pdfs/x/v1.pdf"
    # original untouched
    assert next(v for v in d["versions"] if v["n"] == 1).get("pdfKey") is None

def test_set_version_pdf_absent_version_noop():
    d = new_deck_item("x", "X", [], "t0")
    d2 = set_version_pdf(d, 9, "pdfs/x/v9.pdf", "t2")
    assert d2["versions"] == []
