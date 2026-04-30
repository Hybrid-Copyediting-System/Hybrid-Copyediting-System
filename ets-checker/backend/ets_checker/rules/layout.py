from __future__ import annotations

from ets_checker import ets_profile as p
from ets_checker.models import CheckDetail, Locator, ParsedDocument
from ets_checker.rules.runner import register


@register("layout.paper_size", "Layout", "Paper size check", "error")
def check_paper_size(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []
    if doc.metadata.paper_size != p.PAPER_SIZE:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"Paper size should be {p.PAPER_SIZE}",
            expected=f"{p.PAPER_SIZE} ({p.PAPER_WIDTH_CM}×{p.PAPER_HEIGHT_CM} cm)",
            actual=f"{doc.metadata.paper_size or 'Unknown'} ({doc.metadata.paper_width_cm}×{doc.metadata.paper_height_cm} cm)",
        ))
    return details


@register("layout.margins", "Layout", "Margin check", "error")
def check_margins(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []
    expected = {
        "top": p.MARGIN_TOP_CM,
        "bottom": p.MARGIN_BOTTOM_CM,
        "left": p.MARGIN_LEFT_CM,
        "right": p.MARGIN_RIGHT_CM,
    }
    actual = {
        "top": doc.metadata.margin_top_cm,
        "bottom": doc.metadata.margin_bottom_cm,
        "left": doc.metadata.margin_left_cm,
        "right": doc.metadata.margin_right_cm,
    }
    for side in ["top", "bottom", "left", "right"]:
        if abs(actual[side] - expected[side]) > p.MARGIN_TOLERANCE_CM:
            details.append(CheckDetail(
                location="document",
                locator=Locator(kind="document"),
                message=f"{side.capitalize()} margin does not match ET&S ({expected[side]} cm)",
                expected=expected[side],
                actual=round(actual[side], 2),
            ))
    return details


@register("layout.line_spacing", "Layout", "Line spacing check", "error")
def check_line_spacing(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []
    if doc.metadata.default_line_spacing is None:
        per_para_spacings = [
            para.line_spacing for para in doc.paragraphs
            if para.line_spacing is not None and not para.is_in_table
        ]
        if not per_para_spacings:
            # No explicit spacing set anywhere: Word uses its built-in default
            # (single-line = 1.0), which meets the ET&S requirement.
            return details
        from statistics import mode
        try:
            dominant = mode(per_para_spacings)
        except Exception:
            dominant = per_para_spacings[0]
        if abs(dominant - p.LINE_SPACING) > p.LINE_SPACING_TOLERANCE:
            details.append(CheckDetail(
                location="document",
                locator=Locator(kind="document"),
                message=f"Dominant line spacing does not match ET&S ({p.LINE_SPACING})",
                expected=p.LINE_SPACING,
                actual=round(dominant, 2),
            ))
        return details
    if abs(doc.metadata.default_line_spacing - p.LINE_SPACING) > p.LINE_SPACING_TOLERANCE:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"Default line spacing does not match ET&S ({p.LINE_SPACING})",
            expected=p.LINE_SPACING,
            actual=round(doc.metadata.default_line_spacing, 2),
        ))
    return details


# ── Item 11: Page numbers ────────────────────────────────────────────

@register("layout.page_numbers", "Layout", "Page number check", "info")
def check_page_numbers(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []
    if doc.metadata.has_page_numbers is False:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                "No page numbers detected in headers/footers; "
                "APA 7th recommends page numbers in the top-right header "
                "(note: some journals add page numbers during typesetting)"
            ),
        ))
    return details
