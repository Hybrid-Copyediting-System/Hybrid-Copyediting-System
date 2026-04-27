from __future__ import annotations

import re

from ets_checker.models import Paragraph, Section
from ets_checker.ets_profile import REFERENCE_LIST_TITLES

_STYLE_MAP: dict[str, int] = {
    "Title": 1,
    "Heading 1": 1,
    "Heading 2": 2,
    "Heading 3": 3,
    "標題 1": 1,
    "標題 2": 2,
    "標題 3": 3,
}

_CANONICAL_HEADINGS = {
    "abstract", "introduction", "method", "methods", "methodology",
    "results", "findings", "discussion", "conclusion", "conclusions",
    "references", "acknowledgment", "acknowledgments",
    "acknowledgement", "acknowledgements",
    "literature review", "background", "related work",
    "theoretical framework", "implications", "limitations",
    "摘要", "關鍵詞", "關鍵字", "引言", "緒論", "前言",
    "方法", "研究方法", "結果", "討論", "結論", "參考文獻", "致謝",
}

ABSTRACT_TITLES = {"abstract", "摘要", "摘 要"}

KEYWORDS_PREFIX = re.compile(
    r"^(?:key\s*words?|關鍵詞|關鍵字|キーワード)\s*[:：]",
    re.IGNORECASE,
)

_TITLE_TRAILING = re.compile(r"[\s:：.。\-—–]+$")


def _normalise_title(title: str) -> str:
    return _TITLE_TRAILING.sub("", title.strip().lower())


def is_abstract_title(title: str) -> bool:
    return _normalise_title(title) in ABSTRACT_TITLES


def is_reference_title(title: str) -> bool:
    return _normalise_title(title) in {t.lower() for t in REFERENCE_LIST_TITLES}

_PERIOD_EXCEPTIONS = re.compile(r"(etc\.|et al\.|[A-Z]\.)\s*$")


def _is_candidate_heading(p: Paragraph) -> bool:
    text = p.text.strip()
    if not text or len(text) > 120:
        return False
    cleaned = _normalise_title(re.sub(r"^\d+(\.\d+)*\.?\s*", "", text))
    if cleaned in _CANONICAL_HEADINGS:
        return True
    # Reject sentence-like paragraphs (anything ending in a period that's not
    # an abbreviation, or a Chinese full stop).
    if text.endswith("。"):
        return False
    if text.endswith(".") and not _PERIOD_EXCEPTIONS.search(text):
        return False
    if not p.runs:
        return False
    return all(r.bold is True for r in p.runs if r.text.strip())


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


def _is_canonical_heading(text: str) -> bool:
    cleaned = _normalise_title(re.sub(r"^\d+(\.\d+)*\.?\s*", "", text.strip()))
    return cleaned in _CANONICAL_HEADINGS


def detect(paragraphs: list[Paragraph]) -> list[Section]:
    style_sections: list[Section] = []
    style_indices: set[int] = set()
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
                style_indices.add(p.index)

    # Always run the heuristic pass too so a partially-styled document still
    # picks up unstyled canonical headings. When styles exist, restrict the
    # heuristic to canonical heading text to avoid flagging bold body lines.
    canonical_only = bool(style_sections)
    heuristic_sections: list[Section] = []
    for p in paragraphs:
        if p.is_in_table or p.index in style_indices:
            continue
        if not _is_candidate_heading(p):
            continue
        if canonical_only and not _is_canonical_heading(p.text):
            continue
        heuristic_sections.append(Section(
            title=p.text.strip(),
            level=1 if canonical_only else _infer_level_from_font(p),
            paragraph_index=p.index,
            detection_method="heuristic",
        ))

    merged = style_sections + heuristic_sections
    merged.sort(key=lambda s: s.paragraph_index)
    return merged
