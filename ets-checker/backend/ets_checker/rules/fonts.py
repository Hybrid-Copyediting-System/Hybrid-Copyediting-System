from __future__ import annotations

from ets_checker import ets_profile as p
from ets_checker.models import CheckDetail, Locator, ParsedDocument
from ets_checker.rules.runner import register

MAX_REPORTED = 20


def _get_body_paragraph_indices(doc: ParsedDocument) -> set[int]:
    heading_indices = {s.paragraph_index for s in doc.sections}
    ref_titles = [t.lower() for t in p.REFERENCE_LIST_TITLES]

    abstract_start: int | None = None
    abstract_end: int | None = None
    ref_start: int | None = None

    for i, s in enumerate(doc.sections):
        if s.title.lower() == "abstract":
            abstract_start = s.paragraph_index
            if i + 1 < len(doc.sections):
                abstract_end = doc.sections[i + 1].paragraph_index
        if s.title.strip().lower() in ref_titles:
            ref_start = s.paragraph_index

    exclude = set(heading_indices)
    for para in doc.paragraphs:
        if para.is_in_table:
            exclude.add(para.index)
        if abstract_start is not None and abstract_end is not None:
            if abstract_start <= para.index < abstract_end:
                exclude.add(para.index)
        if ref_start is not None and para.index >= ref_start:
            exclude.add(para.index)

    return {para.index for para in doc.paragraphs} - exclude


@register("font.body", "Fonts", "Body font check", "warning")
def check_body_font(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []
    body_indices = _get_body_paragraph_indices(doc)
    expected_name, expected_size = p.FONT_BODY[0], p.FONT_BODY[1]

    count = 0
    for para in doc.paragraphs:
        if para.index not in body_indices:
            continue
        for r in para.runs:
            if not r.text.strip():
                continue
            actual_font = r.font_name or "(unknown)"
            actual_size = r.font_size_pt

            font_mismatch = actual_font != "(unknown)" and actual_font != expected_name
            size_mismatch = actual_size is not None and abs(actual_size - expected_size) > 0.1

            if font_mismatch or size_mismatch:
                if count < MAX_REPORTED:
                    details.append(CheckDetail(
                        location=f"paragraph {para.index}",
                        locator=Locator(kind="paragraph", paragraph_index=para.index),
                        message="Body text font mismatch",
                        expected=f"{expected_name} {expected_size}pt",
                        actual=f"{actual_font} {actual_size}pt" if actual_size else actual_font,
                        excerpt=r.text[:80],
                    ))
                count += 1

    if count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {count - MAX_REPORTED} more font mismatches",
        ))

    return details
