from __future__ import annotations

import re

from ets_checker.models import CheckDetail, Locator, ParsedDocument
from ets_checker.parser.sections import is_reference_title
from ets_checker.rules.runner import register

TEXT_REFS = re.compile(r"\b(Figures?|Figs?\.?|Tables?)\s+(\d+)", re.IGNORECASE)


@register(
    "figures_tables.referenced_in_text",
    "Figures & Tables",
    "Figures/tables referenced in text",
    "warning",
)
def check_referenced_in_text(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []

    ref_start: int | None = None
    for s in doc.sections:
        if is_reference_title(s.title):
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

    fig_para_by_number = {
        f.figure_number: f.paragraph_index for f in doc.figures if f.figure_number
    }
    tbl_para_by_number = {
        t.table_number: t.paragraph_index for t in doc.tables if t.table_number
    }

    for n in sorted(defined_figs - cited_figs):
        details.append(CheckDetail(
            location=f"Figure {n}",
            locator=Locator(kind="paragraph", paragraph_index=fig_para_by_number[n]),
            message=f"Figure {n} is defined but not referenced in body text",
        ))
    for n in sorted(cited_figs - defined_figs):
        details.append(CheckDetail(
            location=f"Figure {n}",
            locator=Locator(kind="document"),
            message=f"Figure {n} is referenced in text but not found in document",
        ))
    for n in sorted(defined_tables - cited_tables):
        details.append(CheckDetail(
            location=f"Table {n}",
            locator=Locator(kind="paragraph", paragraph_index=tbl_para_by_number[n]),
            message=f"Table {n} is defined but not referenced in body text",
        ))
    for n in sorted(cited_tables - defined_tables):
        details.append(CheckDetail(
            location=f"Table {n}",
            locator=Locator(kind="document"),
            message=f"Table {n} is referenced in text but not found in document",
        ))

    return details
