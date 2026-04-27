from __future__ import annotations

import re

from ets_checker.models import Paragraph, Reference, Section
from ets_checker.ets_profile import REFERENCE_LIST_TITLES

REF_AUTHOR_YEAR = re.compile(
    r"^(?P<authors>.+?)\s*\((?P<year>(?:19|20)\d{2}|n\.d\.)(?P<suffix>[a-z])?\)\.\s",
    re.UNICODE,
)

REF_FIRST_AUTHOR = re.compile(r"^(?P<surname>[A-Z][a-zA-Z\-']+),")


def extract(
    paragraphs: list[Paragraph],
    sections: list[Section],
) -> list[Reference]:
    ref_section_idx: int | None = None
    next_section_idx: int | None = None

    for i, s in enumerate(sections):
        if s.title.strip().lower() in [t.lower() for t in REFERENCE_LIST_TITLES]:
            ref_section_idx = s.paragraph_index
            for j in range(i + 1, len(sections)):
                if sections[j].level == 1:
                    next_section_idx = sections[j].paragraph_index
                    break
            break

    if ref_section_idx is None:
        return []

    ref_paragraphs = [
        p for p in paragraphs
        if p.index > ref_section_idx
        and (next_section_idx is None or p.index < next_section_idx)
        and not p.is_in_table
        and p.text.strip()
    ]

    results: list[Reference] = []
    for idx, p in enumerate(ref_paragraphs):
        raw = p.text.strip()
        m = REF_AUTHOR_YEAR.match(raw)
        year: str | None = None
        year_suffix: str | None = None
        first_author: str | None = None
        confidence = 0.2

        if m:
            year = m.group("year")
            year_suffix = m.group("suffix")
            am = REF_FIRST_AUTHOR.match(m.group("authors").strip())
            if am:
                first_author = am.group("surname")
                confidence = 1.0
            else:
                confidence = 0.5
        else:
            year_match = re.search(r"\((?P<y>(?:19|20)\d{2})(?P<s>[a-z])?\)", raw)
            if year_match:
                year = year_match.group("y")
                year_suffix = year_match.group("s")
                confidence = 0.5

        results.append(Reference(
            index=idx,
            raw_text=raw,
            first_author_surname=first_author,
            year=year,
            year_suffix=year_suffix,
            parse_confidence=confidence,
        ))

    return results
