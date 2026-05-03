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
    "appendix", "appendices",
    # End-matter sections common in journal articles. Without these, bold
    # standalone headings like "Funding" get filtered out by the canonical-only
    # gate when the doc otherwise uses styled headings, and the next paragraph
    # then trips font.body / structure rules with a ghost heading mismatch.
    "funding", "data availability", "data availability statement",
    "author contributions", "authors contributions",
    "conflict of interest", "conflicts of interest",
    "declaration of interest", "declarations of interest",
    "ethics statement", "ethics approval", "ethical approval",
    "supplementary material", "supplementary materials",
    "competing interests", "disclosure",
    "摘要", "關鍵詞", "關鍵字", "引言", "緒論", "前言",
    "方法", "研究方法", "結果", "討論", "結論", "參考文獻", "致謝",
    "附錄", "經費", "資金", "致謝詞", "利益衝突",
}

ABSTRACT_TITLES = {"abstract", "摘要", "摘 要"}

KEYWORDS_PREFIX = re.compile(
    r"^(?:key\s*words?|關鍵詞|關鍵字|キーワード)\s*[:：]",
    re.IGNORECASE,
)

# Matches inline abstract labels like "ABSTRACT:" or "摘要：" at paragraph start.
INLINE_ABSTRACT_PREFIX = re.compile(
    r"^(?:ABSTRACT|摘要|摘\s*要)\s*[:：]\s*",
    re.IGNORECASE,
)

# Matches an "Appendix" / "Appendices" / "附錄" caption used as an end-matter
# section heading, even when the paragraph isn't styled or bold. Stops at
# any reasonable caption length so a paragraph that *mentions* "Appendix" mid-
# sentence isn't promoted to a section.
_APPENDIX_CAPTION = re.compile(
    r"^\s*(?:Appendix|Appendices|附錄)\b[\s.:：A-Za-z0-9\-]{0,80}$",
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
    text_runs = [r for r in p.runs if r.text.strip()]
    if not text_runs:
        return False
    return all(r.bold is True for r in text_runs)


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


# Detects an APA-style numeric heading prefix and reports its depth:
# "1." → 1, "1.1." → 2, "1.1.1." → 3. Used to pick the correct heading
# level for sub-headings that are detected by the heuristic pass (the body of
# the paper rarely styles every "5.4." as Heading 2, but we still need to
# evaluate it against the right font expectations).
_NUMERIC_PREFIX = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+\S")


def _level_from_numbering(text: str) -> int | None:
    m = _NUMERIC_PREFIX.match(text)
    if not m:
        return None
    depth = m.group(1).count(".") + 1
    # Cap at the deepest level our font profile defines (Heading 3).
    return min(depth, 3)


def _is_canonical_heading(text: str) -> bool:
    cleaned = _normalise_title(re.sub(r"^\d+(\.\d+)*\.?\s*", "", text.strip()))
    if cleaned in _CANONICAL_HEADINGS:
        return True
    # Match "Appendix A: ..." style — first word is the canonical keyword
    first_word = cleaned.split()[0] if cleaned.split() else ""
    return first_word in _CANONICAL_HEADINGS


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
        # Prefer numeric-prefix depth ("5.4." → L2) over the canonical-only
        # default of L1, so sub-headings detected by the heuristic don't get
        # graded against the L1 font profile.
        numbered_level = _level_from_numbering(p.text)
        if numbered_level is not None:
            level = numbered_level
        elif canonical_only:
            level = 1
        else:
            level = _infer_level_from_font(p)
        heuristic_sections.append(Section(
            title=p.text.strip(),
            level=level,
            paragraph_index=p.index,
            detection_method="heuristic",
        ))

    # Detect inline abstract pattern: "ABSTRACT: <body text>" in one paragraph.
    already_indexed = style_indices | {s.paragraph_index for s in heuristic_sections}
    for p in paragraphs:
        if p.is_in_table or p.index in already_indexed:
            continue
        if INLINE_ABSTRACT_PREFIX.match(p.text.strip()):
            heuristic_sections.append(Section(
                title="Abstract",
                level=1,
                paragraph_index=p.index,
                detection_method="inline_abstract",
            ))

    # Detect "Appendix [letter/number]" captions even when they aren't bold.
    # These are de facto end-matter section boundaries that several rules
    # (font.reference scope, references parser) use to know when the body
    # ends. Italics-only captions (e.g. "Appendix B. Characteristics …")
    # are common and would otherwise leak into the references scan.
    already_indexed = style_indices | {s.paragraph_index for s in heuristic_sections}
    for p in paragraphs:
        if p.is_in_table or p.index in already_indexed:
            continue
        if _APPENDIX_CAPTION.match(p.text.strip()):
            heuristic_sections.append(Section(
                title=p.text.strip(),
                level=1,
                paragraph_index=p.index,
                detection_method="appendix",
            ))

    merged = style_sections + heuristic_sections
    merged.sort(key=lambda s: s.paragraph_index)
    return merged
