from __future__ import annotations

import re

from ets_checker import ets_profile as p
from ets_checker.models import CheckDetail, Locator, ParsedDocument
from ets_checker.parser.sections import KEYWORDS_PREFIX, is_abstract_title
from ets_checker.rules.runner import register

ABSTRACT_FALLBACK_PARAGRAPHS = 30


def _count_words(text: str) -> int:
    chinese = len(re.findall(r"[一-鿿㐀-䶿]", text))
    text_no_cjk = re.sub(r"[一-鿿㐀-䶿]", " ", text)
    english = len(text_no_cjk.split())
    return chinese + english


def _abstract_end_index(
    doc: ParsedDocument,
    abstract_idx: int,
    section_pos: int,
) -> int | None:
    if section_pos + 1 < len(doc.sections):
        return doc.sections[section_pos + 1].paragraph_index
    # No following section detected — fall back to the keywords paragraph,
    # else cap at a fixed number of paragraphs to avoid swallowing the body.
    for para in doc.paragraphs:
        if (para.index > abstract_idx
                and not para.is_in_table
                and KEYWORDS_PREFIX.match(para.text.strip())):
            return para.index
    return abstract_idx + ABSTRACT_FALLBACK_PARAGRAPHS + 1


@register("structure.abstract_length", "Structure", "Abstract length check", "warning")
def check_abstract_length(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []

    abstract_section = None
    abstract_pos: int | None = None
    for i, s in enumerate(doc.sections):
        if is_abstract_title(s.title):
            abstract_section = s
            abstract_pos = i
            break

    if abstract_section is None or abstract_pos is None:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message="Abstract section not detected",
        ))
        return details

    next_section_idx = _abstract_end_index(
        doc, abstract_section.paragraph_index, abstract_pos
    )

    abstract_paras = [
        para for para in doc.paragraphs
        if para.index > abstract_section.paragraph_index
        and (next_section_idx is None or para.index < next_section_idx)
        and not para.is_in_table
        and para.text.strip()
        and not KEYWORDS_PREFIX.match(para.text.strip())
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

    kw_para = None
    for para in doc.paragraphs:
        if KEYWORDS_PREFIX.match(para.text.strip()):
            kw_para = para
            break

    if kw_para is None:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message="Keywords paragraph not detected",
        ))
        return details

    text = KEYWORDS_PREFIX.sub("", kw_para.text.strip(), count=1).strip()

    keywords = [k.strip() for k in re.split(r"[,;，；、]", text) if k.strip()]

    if len(keywords) > p.KEYWORDS_MAX_COUNT:
        details.append(CheckDetail(
            location=f"paragraph {kw_para.index}",
            locator=Locator(kind="paragraph", paragraph_index=kw_para.index),
            message=f"Too many keywords (max {p.KEYWORDS_MAX_COUNT})",
            expected=f"≤ {p.KEYWORDS_MAX_COUNT}",
            actual=str(len(keywords)),
        ))

    return details
