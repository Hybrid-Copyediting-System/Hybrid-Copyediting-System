from __future__ import annotations

import re
import unicodedata

# Strips: whitespace, hyphens, ASCII apostrophe, smart apostrophes, dots.
# Dots are stripped so that surname normalisation and per-author sort-key
# normalisation share the same canonical form (a surname like "St." and an
# initials chunk "J. K." both collapse to a separator-free token). Built
# with chr() so editors cannot silently rewrite the literal quotes.
_STRIP_RE = re.compile(r"[\s\-'." + chr(0x2018) + chr(0x2019) + r"]")


def normalise_surname(s: str) -> str:
    """Canonical surname/author-token normalisation.

    Lowercases, strips diacritics, and removes whitespace, hyphens,
    apostrophe variants, and dots so the same surname compares equal
    regardless of how the citation or reference happens to spell it.
    Used by both the citation rule and the reference sort-key builder.
    """
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("ı", "i")
    return _STRIP_RE.sub("", s).lower()
