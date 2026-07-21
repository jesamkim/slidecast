import os
import re


def slugify(filename: str) -> str:
    base = os.path.basename(filename)
    stem = os.path.splitext(base)[0]
    lowered = stem.lower()
    hyphenated = re.sub(r"[^a-z0-9]+", "-", lowered)
    trimmed = hyphenated.strip("-")
    return trimmed or "deck"
