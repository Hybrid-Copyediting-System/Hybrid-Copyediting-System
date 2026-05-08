from __future__ import annotations

import re

from ets_checker import ets_profile as P
from ets_checker.models import CheckDetail, Locator, Paragraph, ParsedDocument, Run
from ets_checker.parser.figures import _FIG_CAPTION, _TBL_CAPTION, _caption_number
from ets_checker.parser.sections import is_reference_title
from ets_checker.rules.runner import register

# Body-text references to figures/tables. Accepts both the canonical form
# "Figure 1" / "Fig. 2" / "Table 3" and the mistyped variant "Figure. 1" /
# "Table. 3" (period before the number). The parser's caption matcher tolerates
# the same mistyping, so the body matcher must too — otherwise a document that
# uses "Figure. N" consistently shows every figure as "defined but never
# referenced".
TEXT_REFS = re.compile(
    r"\b(Figures?|Figs?\.?|Tables?)\.?\s+(\d+)",
    re.IGNORECASE,
)


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

    # Caption-only numbers (a "Figure N."/"Table N." paragraph with no Word
    # object beneath it) are owned by figures_tables.table_format, which gives
    # a more actionable diagnosis ("caption found but no corresponding Word
    # table — verify the table is editable, not an image"). Skipping them
    # here avoids reporting the same root cause twice with different framings.
    caption_only_figs: set[int] = set()
    caption_only_tables: set[int] = set()
    for para in doc.paragraphs:
        if ref_start is not None and para.index >= ref_start:
            continue
        text = para.text.strip()
        m = _FIG_CAPTION.match(text)
        if m:
            num = _caption_number(m)
            if num not in defined_figs:
                caption_only_figs.add(num)
            continue
        m = _TBL_CAPTION.match(text)
        if m:
            num = _caption_number(m)
            if num not in defined_tables:
                caption_only_tables.add(num)

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
    for n in sorted(cited_figs - defined_figs - caption_only_figs):
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
    for n in sorted(cited_tables - defined_tables - caption_only_tables):
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
        num = _caption_number(m)
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


# ── Figure / Table numbering must be sequential from 1 ─────────────────


@register(
    "figures_tables.numbering_sequence",
    "Figures & Tables",
    "Figure / table numbering sequence",
    "warning",
)
def check_numbering_sequence(doc: ParsedDocument) -> list[CheckDetail]:
    """APA 7 §7.10 / §7.24: figures and tables are numbered in the order
    they are first mentioned, starting from 1, with no gaps and no
    duplicates within each kind.

    Reports three failure modes per kind:
      - missing 1 / sequence does not start at 1
      - duplicated number (e.g. two "Figure 2" captions)
      - gap (e.g. Figure 1, Figure 2, Figure 4)
    """
    details: list[CheckDetail] = []

    def _check(numbers: list[int], kind: str) -> None:
        if not numbers:
            return
        if min(numbers) != 1:
            details.append(CheckDetail(
                location="document",
                locator=Locator(kind="document"),
                message=(
                    f"{kind} numbering does not start at 1 — first "
                    f"{kind.lower()} is numbered {min(numbers)}"
                ),
                expected=f"{kind} 1, {kind} 2, ...",
                actual=f"first {kind.lower()} is {min(numbers)}",
            ))
        seen: dict[int, int] = {}
        for n in numbers:
            seen[n] = seen.get(n, 0) + 1
        for n, count in sorted(seen.items()):
            if count > 1:
                details.append(CheckDetail(
                    location=f"{kind} {n}",
                    locator=Locator(kind="document"),
                    message=(
                        f"{kind} {n} is defined {count} times — APA 7 §7.10 "
                        f"requires unique sequential numbering"
                    ),
                    expected=f"unique {kind.lower()} numbers",
                    actual=f"{kind} {n} appears {count}×",
                ))
        full_range = set(range(min(numbers), max(numbers) + 1))
        missing = sorted(full_range - set(numbers))
        for n in missing:
            details.append(CheckDetail(
                location="document",
                locator=Locator(kind="document"),
                message=(
                    f"{kind} numbering has a gap at {n} — sequence jumps "
                    f"from {n - 1} to {min(x for x in numbers if x > n - 1)}"
                ),
                expected=f"contiguous {kind.lower()} numbering",
                actual=f"{kind} {n} missing",
            ))

    fig_nums = sorted(f.figure_number for f in doc.figures if f.figure_number)
    tbl_nums = sorted(t.table_number for t in doc.tables if t.table_number)
    _check(fig_nums, "Figure")
    _check(tbl_nums, "Table")
    return details


# ── Caption format: number bold, title italic ─────────────────────────


# "Figure 1.", "Figure 1:", "Figure. 1" — same shapes the parser already
# accepts. Captures (number_text, separator_text, title_text) so each can be
# resolved to the underlying runs and their formatting checked.
_CAPTION_PARTS = re.compile(
    r"^(?P<head>(?:Figure|Table)\s+\d+|"
    r"(?:Figure|Table)\.\s+\d+)"
    r"(?P<sep>[.:]\s*|\s+)"
    r"(?P<title>.+)$",
    re.IGNORECASE,
)


def _runs_covering(para: Paragraph, start: int, end: int) -> list[Run]:
    """Return runs intersecting [start, end) by character position."""
    cursor = 0
    out = []
    for r in para.runs:
        rlen = len(r.text)
        rstart, rend = cursor, cursor + rlen
        cursor = rend
        if rend <= start:
            continue
        if rstart >= end:
            break
        out.append(r)
    return out


@register(
    "figures_tables.caption_format",
    "Figures & Tables",
    "Caption format: number bold, title italic",
    "info",
)
def check_caption_format(doc: ParsedDocument) -> list[CheckDetail]:
    """APA 7 §7.10 / §7.24 caption format:

    * Caption number ("Figure 1") is bold.
    * Caption title text is italic and runs on the line below the number;
      the MVP renderer collapses both onto one line, so we look at the
      title segment after the number.

    The check is reported at info severity because cross-platform DOCX
    rendering frequently strips run-level italics, and ET&S accepts plain
    captions during the editorial workflow.
    """
    details: list[CheckDetail] = []

    para_by_index = {p.index: p for p in doc.paragraphs}
    caption_parts = (
        [(f.figure_number, f.paragraph_index, "Figure") for f in doc.figures
         if f.figure_number and f.caption_text]
        + [(t.table_number, t.paragraph_index, "Table") for t in doc.tables
           if t.table_number and t.caption_text]
    )

    issue_count = 0
    for number, para_idx, kind in caption_parts:
        para = para_by_index.get(para_idx)
        if para is None or not para.runs:
            continue
        text = "".join(r.text for r in para.runs)
        m = _CAPTION_PARTS.match(text.strip())
        if m is None:
            continue
        offset = len(text) - len(text.lstrip())
        head_start = offset + m.start("head")
        head_end = offset + m.end("head")
        title_start = offset + m.start("title")
        title_end = offset + m.end("title")

        head_runs = _runs_covering(para, head_start, head_end)
        title_runs = _runs_covering(para, title_start, title_end)
        head_resolvable = [r for r in head_runs if r.bold is not None]
        title_resolvable = [r for r in title_runs if r.italic is not None]

        if head_resolvable and not all(r.bold for r in head_resolvable):
            if issue_count < 20:
                details.append(CheckDetail(
                    location=f"{kind} {number}",
                    locator=Locator(kind="paragraph", paragraph_index=para_idx),
                    message=(
                        f"{kind} number '{m.group('head')}' is not bold — "
                        f"APA 7 §7.10 / §7.24 sets the caption number in bold"
                    ),
                    expected="bold",
                    actual="not bold",
                    excerpt=text[:200],
                ))
            issue_count += 1

        if title_resolvable and not all(r.italic for r in title_resolvable):
            if issue_count < 20:
                details.append(CheckDetail(
                    location=f"{kind} {number}",
                    locator=Locator(kind="paragraph", paragraph_index=para_idx),
                    message=(
                        f"{kind} {number} caption title is not italic — "
                        f"APA 7 §7.10 / §7.24 italicises the descriptive title"
                    ),
                    expected="italic title",
                    actual="title not italic",
                    excerpt=text[:200],
                ))
            issue_count += 1

    if issue_count > 20:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"... and {issue_count - 20} more caption-format issues"
            ),
        ))

    return details
