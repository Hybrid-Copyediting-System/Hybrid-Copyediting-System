from __future__ import annotations

import re

from ets_checker.models import Paragraph, Section

_STYLE_MAP: dict[str, int] = {
    "Title": 1,
    "Heading 1": 1,
    "Heading 2": 2,
    "Heading 3": 3,
}

_CANONICAL_HEADINGS = {
    "abstract", "introduction", "method", "methods", "methodology",
    "results", "findings", "discussion", "conclusion", "conclusions",
    "references", "acknowledgment", "acknowledgments",
    "acknowledgement", "acknowledgements",
    "literature review", "background", "related work",
    "theoretical framework", "implications", "limitations",
}

_PERIOD_EXCEPTIONS = re.compile(r"(etc\.|et al\.|[A-Z]\.)\s*$")


def _is_candidate_heading(p: Paragraph) -> bool:
    text = p.text.strip()
    if not text or len(text) > 120:
        return False
    if text.endswith(".") and not _PERIOD_EXCEPTIONS.search(text):
        return False
    all_bold = all(r.bold is True for r in p.runs if r.text.strip()) if p.runs else False
    is_canonical = text.lower() in _CANONICAL_HEADINGS
    return all_bold or is_canonical


def _infer_level_from_font(p: Paragraph) -> int:
    sizes = [r.font_size_pt for r in p.runs if r.font_size_pt is not None and r.text.strip()]
    if not sizes:
        return 1
    avg = sum(sizes) / len(sizes)
    if avg >= 13:
        return 1
    if avg >= 11:
        return 2
    return 3


def detect(paragraphs: list[Paragraph]) -> list[Section]:
    # Pass 1: style-based
    style_sections: list[Section] = []
    for p in paragraphs:
        if p.is_in_table:
            continue
        if p.style_name and p.style_name in _STYLE_MAP:
            text = p.text.strip()
            if text:
                style_sections.append(Section(
                    title=text,
                    level=_STYLE_MAP[p.style_name],
                    paragraph_index=p.index,
                    detection_method="style",
                ))

    if style_sections:
        return style_sections

    # Pass 2: heuristic
    heuristic_sections: list[Section] = []
    for p in paragraphs:
        if p.is_in_table:
            continue
        if _is_candidate_heading(p):
            text = p.text.strip()
            heuristic_sections.append(Section(
                title=text,
                level=_infer_level_from_font(p),
                paragraph_index=p.index,
                detection_method="heuristic",
            ))

    return heuristic_sections
