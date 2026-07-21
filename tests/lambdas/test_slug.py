import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
from slug import slugify

def test_basic_filename():
    assert slugify("2026 Roadmap.html") == "2026-roadmap"

def test_strips_extension_and_path():
    assert slugify("/tmp/My Deck.HTML") == "my-deck"

def test_collapses_and_trims_hyphens():
    assert slugify("--Hello___World!!--.html") == "hello-world"

def test_empty_fallback():
    assert slugify("!!!.html") == "deck"

def test_unicode_dropped_to_hyphen():
    assert slugify("한글 deck.html") == "deck"
