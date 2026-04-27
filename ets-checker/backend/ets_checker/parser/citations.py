from __future__ import annotations

import re

from ets_checker.models import Citation, Paragraph, Section
from ets_checker.ets_profile import REFERENCE_LIST_TITLES

CITATION_PAREN = re.compile(
    r"\((?:(?:see|e\.g\.,?|cf\.)\s+)?(?P<body>[^()]+)\)",
    re.UNICODE,
)

PER_CITE = re.compile(
    r"(?P<authors>.+?),\s*(?P<year>(?:19|20)\d{2})(?P<suffix>[a-z])?"
    r"(?:,\s*pp?\.\s*[\d\-–,\s]+)?",
    re.UNICODE,
)

CITATION_NARRATIVE = re.compile(
    r"(?P<authors>[A-Z][a-zA-Z\-']+(?:\s+(?:and|&)\s+[A-Z][a-zA-Z\-']+)?"
    r"(?:\s+et\s+al\.)?)\s*"
    r"\((?P<year>(?:19|20)\d{2})(?P<suffix>[a-z])?\)",
    re.UNICODE,
)


def _normalise_authors(text: str) -> tuple[list[str], bool]:
    has_et_al = bool(re.search(r"\bet\s+al\.", text, re.IGNORECASE))
    cleaned = re.sub(r"\bet\s+al\.?", "", text, flags=re.IGNORECASE).strip()
    parts = re.split(r"[,&]|\band\b", cleaned)
    authors = [p.strip().rstrip(".").lower() for p in parts if p.strip()]
    return authors, has_et_al


def _is_in_reference_section(
    para_idx: int,
    sections: list[Section],
) -> bool:
    ref_start: int | None = None
    next_section_start: int | None = None
    for i, s in enumerate(sections):
        if s.title.lower() in [t.lower() for t in REFERENCE_LIST_TITLES]:
            ref_start = s.paragraph_index
            if i + 1 < len(sections):
                next_section_start = sections[i + 1].paragraph_index
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
            if not re.search(r"(?:19|20)\d{2}", body):
                continue
            for cm in PER_CITE.finditer(body):
                authors, has_et_al = _normalise_authors(cm.group("authors"))
                results.append(Citation(
                    raw_text=m.group(0),
                    authors=authors,
                    year=cm.group("year"),
                    year_suffix=cm.group("suffix"),
                    has_et_al=has_et_al,
                    citation_type="parenthetical",
                    paragraph_index=p.index,
                ))

        # Narrative
        for m in CITATION_NARRATIVE.finditer(p.text):
            authors, has_et_al = _normalise_authors(m.group("authors"))
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
