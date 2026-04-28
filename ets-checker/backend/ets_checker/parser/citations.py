from __future__ import annotations

import re

from ets_checker.models import Citation, Paragraph, Section
from ets_checker.parser.sections import is_reference_title

CITATION_PAREN = re.compile(
    r"[\(（](?:(?:see|e\.g\.,?|cf\.)\s+)?(?P<body>[^()（）]+)[\)）]",
    re.UNICODE,
)

PER_CITE = re.compile(
    r"(?P<authors>.+?),?\s*(?P<year>(?:19|20)\d{2}|n\.d\.)(?!\d)(?P<suffix>[a-z])?"
    r"(?:,\s*pp?\.\s*[\d\-–,\s]+)?",
    re.UNICODE,
)

# Author token: ASCII surname (capitalised) or a short CJK run. The CJK
# branch has a negative lookbehind so we don't slurp Chinese prefix text
# (e.g. "研究參考王小明") into the surname — a CJK author must be preceded
# by a delimiter (BOS, whitespace, or punctuation), not by another letter.
# Include U+2019 (RIGHT SINGLE QUOTATION MARK) used by Word smart-quotes
# so possessives like "Vygotsky’s" are captured as a single token.
_LATIN_EXT_UPPER = "ĀĆČĎĐĒĖĘĚĞĠĢĪİĶĹĻĽŁŃŅŇŌŐŒŔŘŚŞŠŢŤŪŮŰŲŸŹŻŽ"
_NAME = (
    r"(?:[A-ZÀ-ÖØ-Þ" + _LATIN_EXT_UPPER + r"][\w\-’’]*"
    r"|(?<![一-鿿\w])[一-鿿]{1,6}?)"
)

CITATION_NARRATIVE = re.compile(
    r"(?P<authors>"
    rf"{_NAME}"
    rf"(?:\s*[,、]\s*{_NAME})*"
    rf"(?:\s*[,、]?\s*(?:and|&|與|及)\s*{_NAME})?"
    r"(?:\s+et\s+al\.|\s*等)?"
    r")\s*"
    r"[\(（](?P<year>(?:19|20)\d{2}|n\.d\.)(?P<suffix>[a-z])?[\)）]",
    re.UNICODE,
)

# "Surname, A. B." — drop the initials so the surname/initial comma is
# not mistaken for an author separator and the surname stays intact
# (including multi-word surnames like "Van Damme").
_INITIALS_AFTER_COMMA = re.compile(r",\s*[A-Z]\.(?:\s*[A-Z]\.)*")
_ET_AL_PATTERN = re.compile(r"\bet\s+al\.?|\s*等\s*$", re.IGNORECASE)
_AUTHOR_SPLIT = re.compile(r"[,&、]|\band\b|\s*[與及]\s*")
# Possessive suffixes added by Word smart-quotes ("’s" / "’s")
_POSSESSIVE = re.compile(r"[‘’]s?$")

# Common English discourse markers that can appear before a narrative citation
# (e.g. "Similarly, Smith (2023)") — these are never author surnames.
_DISCOURSE_MARKERS = frozenset({
    "also", "accordingly", "additionally", "comparably", "consequently",
    "conversely", "finally", "furthermore", "generally", "hence",
    "however", "importantly", "interestingly", "likewise", "meanwhile",
    "moreover", "notably", "overall", "particularly", "similarly",
    "specifically", "subsequently", "therefore", "thus",
})


def _normalise_authors(text: str) -> tuple[list[str], bool]:
    has_et_al = bool(_ET_AL_PATTERN.search(text))
    cleaned = _ET_AL_PATTERN.sub("", text).strip()
    cleaned = _INITIALS_AFTER_COMMA.sub("", cleaned)
    parts = _AUTHOR_SPLIT.split(cleaned)
    authors = [_POSSESSIVE.sub("", p.strip()).rstrip(".").lower()
               for p in parts if p.strip()]
    return authors, has_et_al


def _is_in_reference_section(
    para_idx: int,
    sections: list[Section],
) -> bool:
    ref_start: int | None = None
    next_section_start: int | None = None
    for i, s in enumerate(sections):
        if is_reference_title(s.title):
            ref_start = s.paragraph_index
            for j in range(i + 1, len(sections)):
                if sections[j].level == 1:
                    next_section_start = sections[j].paragraph_index
                    break
            break
    if ref_start is None:
        return False
    if next_section_start is not None:
        return ref_start <= para_idx < next_section_start
    return para_idx >= ref_start


def extract(
    paragraphs: list[Paragraph],
    sections: list[Section],
) -> list[Citation]:
    results: list[Citation] = []

    for p in paragraphs:
        if _is_in_reference_section(p.index, sections):
            continue

        # Parenthetical
        for m in CITATION_PAREN.finditer(p.text):
            body = m.group("body")
            if not re.search(r"(?:19|20)\d{2}|n\.d\.", body):
                continue
            # Split compound citations ("Smith, 2020; Jones, 2021") on
            # semicolons before applying PER_CITE so the delimiter never
            # bleeds into the next citation's author token.
            for segment in re.split(r"\s*[;；]\s*", body):
                last_authors: list[str] = []
                last_has_et_al = False
                last_raw_author_text = ""
                for cm in PER_CITE.finditer(segment):
                    authors, has_et_al = _normalise_authors(cm.group("authors"))
                    if not authors and last_authors:
                        authors = last_authors
                        has_et_al = last_has_et_al
                        suffix = cm.group("suffix")
                        year = cm.group("year")
                        raw = f"{last_raw_author_text}, {year}{suffix or ''}"
                    else:
                        last_authors = authors
                        last_has_et_al = has_et_al
                        last_raw_author_text = cm.group("authors").strip().rstrip(",")
                        suffix = cm.group("suffix")
                        year = cm.group("year")
                        raw = cm.group(0).strip().rstrip(",")
                    results.append(Citation(
                        raw_text=raw,
                        authors=authors,
                        year=year,
                        year_suffix=suffix,
                        has_et_al=has_et_al,
                        citation_type="parenthetical",
                        paragraph_index=p.index,
                    ))

        # Narrative
        for m in CITATION_NARRATIVE.finditer(p.text):
            authors, has_et_al = _normalise_authors(m.group("authors"))
            # Strip leading discourse markers (e.g. "Similarly, Smith (2023)")
            while authors and authors[0] in _DISCOURSE_MARKERS:
                authors = authors[1:]
            if not authors:
                continue
            results.append(Citation(
                raw_text=m.group(0),
                authors=authors,
                year=m.group("year"),
                year_suffix=m.group("suffix"),
                has_et_al=has_et_al,
                citation_type="narrative",
                paragraph_index=p.index,
            ))

    return results
