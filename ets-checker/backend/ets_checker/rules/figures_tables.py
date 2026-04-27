from __future__ import annotations

import re

from ets_checker import ets_profile as p
from ets_checker.models import CheckDetail, ParsedDocument
from ets_checker.rules.runner import register

TEXT_REFS = re.compile(r"\b(Figure|Fig\.|Table)\s+(\d+)", re.IGNORECASE)


@register(
    "figures_tables.referenced_in_text",
    "Figures & Tables",
    "Figures/tables referenced in text",
    "warning",
)
def check_referenced_in_text(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []

    ref_titles = [t.lower() for t in p.REFERENCE_LIST_TITLES]
    ref_start: int | None = None
    for s in doc.sections:
        if s.title.strip().lower() in ref_titles:
            ref_start = s.paragraph_index
            break

    caption_indices: set[int] = set()
    for f in doc.figures:
        if f.caption_text:
            caption_indices.add(f.paragraph_index)
    for t in doc.tables:
        if t.caption_text:
            caption_indices.add(t.paragraph_index)

    cited_figs: set[int] = set()
    cited_tables: set[int] = set()

    for para in doc.paragraphs:
        if para.index in caption_indices:
            continue
        if ref_start is not None and para.index >= ref_start:
            continue
        for kind, num in TEXT_REFS.findall(para.text):
            if kind.lower().startswith("fig"):
                cited_figs.add(int(num))
            else:
                cited_tables.add(int(num))

    defined_figs = {f.figure_number for f in doc.figures if f.figure_number}
    defined_tables = {t.table_number for t in doc.tables if t.table_number}

    for n in sorted(defined_figs - cited_figs):
        details.append(CheckDetail(
            location=f"Figure {n}",
            message=f"Figure {n} is defined but not referenced in body text",
        ))
    for n in sorted(cited_figs - defined_figs):
        details.append(CheckDetail(
            location=f"Figure {n}",
            message=f"Figure {n} is referenced in text but not found in document",
        ))
    for n in sorted(defined_tables - cited_tables):
        details.append(CheckDetail(
            location=f"Table {n}",
            message=f"Table {n} is defined but not referenced in body text",
        ))
    for n in sorted(cited_tables - defined_tables):
        details.append(CheckDetail(
            location=f"Table {n}",
            message=f"Table {n} is referenced in text but not found in document",
        ))

    return details
