from __future__ import annotations

import re

from ets_checker import ets_profile as P
from ets_checker.models import CheckDetail, Locator, ParsedDocument
from ets_checker.parser.figures import _TBL_CAPTION
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


# ── Item 9: Caption position ────────────────────────────────────────

@register(
    "figures_tables.caption_position",
    "Figures & Tables",
    "Caption position check (ET&S requirement)",
    "info",
)
def check_caption_position(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []

    expected_fig = P.CAPTION_POSITION_FIGURE
    expected_tbl = P.CAPTION_POSITION_TABLE

    for f in doc.figures:
        if f.caption_position is None:
            continue
        if f.caption_position != expected_fig:
            label = f"Figure {f.figure_number}" if f.figure_number else f"Figure (index {f.index})"
            details.append(CheckDetail(
                location=label,
                locator=Locator(kind="paragraph", paragraph_index=f.paragraph_index),
                message=(
                    f"{label} caption is {f.caption_position} the figure; "
                    f"ET&S requires the caption {expected_fig}"
                ),
                expected=f"caption {expected_fig}",
                actual=f"caption {f.caption_position}",
                excerpt=f.caption_text[:120] if f.caption_text else None,
            ))

    for t in doc.tables:
        if t.caption_position is None:
            continue
        if t.caption_position != expected_tbl:
            label = f"Table {t.table_number}" if t.table_number else f"Table (index {t.index})"
            details.append(CheckDetail(
                location=label,
                locator=Locator(kind="paragraph", paragraph_index=t.paragraph_index),
                message=(
                    f"{label} caption is {t.caption_position} the table; "
                    f"ET&S requires the caption {expected_tbl}"
                ),
                expected=f"caption {expected_tbl}",
                actual=f"caption {t.caption_position}",
                excerpt=t.caption_text[:120] if t.caption_text else None,
            ))

    return details


# ── Item 10: Table format ───────────────────────────────────────────

@register(
    "figures_tables.table_format",
    "Figures & Tables",
    "Table format check",
    "warning",
)
def check_table_format(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []

    # Determine reference section start so we skip captions inside references
    ref_start: int | None = None
    for s in doc.sections:
        if is_reference_title(s.title):
            ref_start = s.paragraph_index
            break

    # Phase 1: Detect table captions with no matching Word Table object
    # (likely an image-based table, which ET&S explicitly forbids).
    # Also check for nearby images to strengthen the diagnosis.
    defined_table_nums = {t.table_number for t in doc.tables if t.table_number}

    # Build a set of paragraph indices that contain images (from parsed figures)
    image_para_indices: set[int] = set()
    for f in doc.figures:
        image_para_indices.add(f.paragraph_index)

    for para in doc.paragraphs:
        if ref_start is not None and para.index >= ref_start:
            continue
        m = _TBL_CAPTION.match(para.text.strip())
        if not m:
            continue
        num = int(m.group(1))
        if num in defined_table_nums:
            continue

        # Check if an image exists within ±3 paragraphs of the caption
        has_nearby_image = any(
            abs(para.index - img_idx) <= 3
            for img_idx in image_para_indices
        )
        if has_nearby_image:
            msg = (
                f"Table {num} appears to be an image rather than a Word table; "
                f"ET&S requires tables in editable table format, not as images"
            )
        else:
            msg = (
                f"Table {num} caption found but no corresponding Word table detected; "
                f"verify the table is in editable table format (ET&S requirement)"
            )
        details.append(CheckDetail(
            location=f"Table {num}",
            locator=Locator(kind="paragraph", paragraph_index=para.index),
            message=msg,
            excerpt=para.text.strip()[:120],
        ))

    # Phase 2: Detect vertical borders (APA 7th requires horizontal rules only)
    # Skip tables without a "Table N." caption — those are layout/utility tables
    # (page-grid scaffolding, image positioning, etc.), not data tables that the
    # APA border rule applies to. Anchoring would also be wrong: with no caption
    # paragraph, the locator falls back to paragraph 0 (document start), which
    # produces useless annotations.
    for t in doc.tables:
        if t.has_vertical_borders and t.table_number is not None:
            label = f"Table {t.table_number}"
            details.append(CheckDetail(
                location=label,
                locator=Locator(kind="paragraph", paragraph_index=t.paragraph_index),
                message=(
                    f"{label} has vertical borders; "
                    f"APA 7th requires tables to use horizontal rules only"
                ),
                expected="no vertical borders",
                actual="vertical borders detected",
                excerpt=t.caption_text[:120] if t.caption_text else None,
            ))

    return details
