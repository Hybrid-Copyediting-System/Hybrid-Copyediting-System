from __future__ import annotations

from typing import Iterator

from ets_checker import ets_profile as p
from ets_checker.models import CheckDetail, Locator, Paragraph, ParsedDocument
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
        dominant = mode(per_para_spacings)
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


# ── Body first-line indent ───────────────────────────────────────────

# Threshold for "looks like a body paragraph". Anything below 30 characters is
# usually a section heading, list item, or fragment.
_MIN_BODY_LEN = 30
MAX_REPORTED = 20


def _body_paragraph_iter(doc: ParsedDocument) -> Iterator[Paragraph]:
    """Iterate body paragraphs: between the first detected section and the
    References section, skipping table cells, headings, and the abstract.
    Falls back to all non-table paragraphs when section detection failed.
    """
    from ets_checker.parser.sections import (
        is_abstract_title,
        is_reference_title,
        KEYWORDS_PREFIX,
    )

    heading_indices = {s.paragraph_index for s in doc.sections}

    abstract_start: int | None = None
    abstract_end: int | None = None
    ref_start: int | None = None
    for i, s in enumerate(doc.sections):
        if abstract_start is None and is_abstract_title(s.title):
            abstract_start = s.paragraph_index
            if i + 1 < len(doc.sections):
                abstract_end = doc.sections[i + 1].paragraph_index
        if ref_start is None and is_reference_title(s.title):
            ref_start = s.paragraph_index

    first_section_idx = min(
        (s.paragraph_index for s in doc.sections), default=None
    )

    for para in doc.paragraphs:
        if para.is_in_table:
            continue
        if para.index in heading_indices:
            continue
        if first_section_idx is not None and para.index < first_section_idx:
            continue
        if abstract_start is not None and abstract_end is not None:
            if abstract_start <= para.index < abstract_end:
                continue
        if ref_start is not None and para.index >= ref_start:
            break
        text = para.text.strip()
        if not text:
            continue
        if KEYWORDS_PREFIX.match(text):
            continue
        if len(text) < _MIN_BODY_LEN:
            continue
        yield para


@register(
    "layout.first_line_indent",
    "Layout",
    "Body first-line indent",
    "info",
)
def check_first_line_indent(doc: ParsedDocument) -> list[CheckDetail]:
    """Body paragraphs should carry a first-line indent matching the ET&S
    profile (1.27 cm / 0.5 inch, APA 7 §2.24).

    Reported at info severity because Word will sometimes strip the indent
    in favour of style-level definitions, and the rule is informative more
    than corrective for editors. We sample only a handful of representative
    paragraphs to avoid drowning the report — once you fix the body style,
    every paragraph repairs at once.
    """
    expected = p.BODY_FIRST_LINE_INDENT_CM
    tol = p.BODY_INDENT_TOLERANCE_CM
    details: list[CheckDetail] = []

    # Without any detected sections we can't reliably distinguish body from
    # title/abstract/references — every paragraph would be treated as body.
    # Suppress the rule rather than risk false positives; structural defects
    # like this are surfaced by structure.required_sections instead.
    if not doc.sections:
        return details

    # We aggregate before reporting so that a single fail covers the entire
    # body if the indent is consistently wrong.
    sampled = list(_body_paragraph_iter(doc))[:80]
    if not sampled:
        return details

    indents = [pa.indent_first_line_cm for pa in sampled]
    explicit = [v for v in indents if v is not None]
    # When most paragraphs have no explicit first-line indent set at all, fall
    # back to a single document-level info message (the body style itself
    # likely lacks the rule).
    if not explicit:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"No first-line indent detected on body paragraphs — APA 7 "
                f"§2.24 / ET&S expect a first-line indent of {expected} cm "
                f"(0.5 inch); verify the Normal style"
            ),
            expected=f"{expected} cm",
            actual="0 cm / unset",
        ))
        return details

    # If the dominant explicit indent is wrong, report once with that value.
    from statistics import mean
    avg = round(mean(explicit), 3)
    if abs(avg - expected) > tol:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"Body first-line indent averages {avg} cm — APA 7 §2.24 / "
                f"ET&S expect {expected} cm (0.5 inch)"
            ),
            expected=f"{expected} cm",
            actual=f"{avg} cm",
        ))

    return details


@register(
    "layout.body_alignment",
    "Layout",
    "Body paragraph alignment",
    "info",
)
def check_body_alignment(doc: ParsedDocument) -> list[CheckDetail]:
    """Body paragraphs should match the ET&S allowed alignments
    (left or justified). A paragraph centered or right-aligned in the body
    is almost always a misformatted heading.
    """
    details: list[CheckDetail] = []
    issue_count = 0
    allowed = p.BODY_ALLOWED_ALIGNMENTS

    if not doc.sections:
        return details

    for para in _body_paragraph_iter(doc):
        if para.alignment in allowed:
            continue
        if issue_count < MAX_REPORTED:
            details.append(CheckDetail(
                location=f"paragraph {para.index}",
                locator=Locator(kind="paragraph", paragraph_index=para.index),
                message=(
                    f"Body paragraph alignment is '{para.alignment}' — "
                    f"ET&S body text uses left or justified alignment"
                ),
                expected="LEFT or JUSTIFY",
                actual=str(para.alignment),
                excerpt=para.text[:120],
            ))
        issue_count += 1

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"... and {issue_count - MAX_REPORTED} more body alignment "
                f"issues"
            ),
        ))
    return details
