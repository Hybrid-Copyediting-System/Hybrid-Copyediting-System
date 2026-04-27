from __future__ import annotations

import re

from ets_checker import ets_profile as p
from ets_checker.models import CheckDetail, Locator, ParsedDocument
from ets_checker.rules.runner import register


def _count_words(text: str) -> int:
    chinese = len(re.findall(r"[一-鿿㐀-䶿]", text))
    text_no_cjk = re.sub(r"[一-鿿㐀-䶿]", " ", text)
    english = len(text_no_cjk.split())
    return chinese + english


@register("structure.abstract_length", "Structure", "Abstract length check", "warning")
def check_abstract_length(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []

    abstract_section = None
    next_section_idx: int | None = None
    for i, s in enumerate(doc.sections):
        if s.title.lower() == "abstract":
            abstract_section = s
            if i + 1 < len(doc.sections):
                next_section_idx = doc.sections[i + 1].paragraph_index
            break

    if abstract_section is None:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message="Abstract section not detected",
        ))
        return details

    abstract_paras = [
        para for para in doc.paragraphs
        if para.index > abstract_section.paragraph_index
        and (next_section_idx is None or para.index < next_section_idx)
        and not para.is_in_table
        and para.text.strip()
    ]

    full_text = " ".join(para.text for para in abstract_paras)
    word_count = _count_words(full_text)

    if word_count > p.ABSTRACT_MAX_WORDS:
        details.append(CheckDetail(
            location="Abstract",
            locator=Locator(
                kind="paragraph",
                paragraph_index=abstract_section.paragraph_index,
            ),
            message=f"Abstract exceeds {p.ABSTRACT_MAX_WORDS} words",
            expected=f"≤ {p.ABSTRACT_MAX_WORDS} words",
            actual=f"{word_count} words",
        ))

    return details


@register("structure.keywords_count", "Structure", "Keywords count check", "warning")
def check_keywords_count(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []

    kw_pattern = re.compile(r"^key\s*words?\s*[:：]", re.IGNORECASE)

    kw_para = None
    for para in doc.paragraphs:
        if kw_pattern.match(para.text.strip()):
            kw_para = para
            break

    if kw_para is None:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message="Keywords paragraph not detected",
        ))
        return details

    text = re.sub(r"^key\s*words?\s*[:：]\s*", "", kw_para.text.strip(), flags=re.IGNORECASE)

    keywords = [k.strip() for k in re.split(r"[,;]", text) if k.strip()]

    if len(keywords) > p.KEYWORDS_MAX_COUNT:
        details.append(CheckDetail(
            location=f"paragraph {kw_para.index}",
            locator=Locator(kind="paragraph", paragraph_index=kw_para.index),
            message=f"Too many keywords (max {p.KEYWORDS_MAX_COUNT})",
            expected=f"≤ {p.KEYWORDS_MAX_COUNT}",
            actual=str(len(keywords)),
        ))

    return details
