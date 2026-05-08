"""Statistics-related APA 7 rules.

Two checks live here:

* ``statistics.operator_spacing`` — relational operators (``=``, ``<``, ``>``,
  ``≤``, ``≥``) must have whitespace on both sides when used as part of a
  statistical statement (APA 7 §6.45). The rule fires only when the operator
  sits next to a known statistical symbol so that prose like "x<y" inside a
  formula or non-statistical context isn't flagged.

* ``statistics.p_value_format`` — p values follow APA 7 §6.44:
  no leading zero (``p = .045``, not ``p = 0.045``); values smaller than .001
  are written ``p < .001`` and never ``p = .000``.

Both rules ignore the Reference section (DOI / volume numbers can mimic the
patterns) and table-cell paragraphs.
"""

from __future__ import annotations

import re
from typing import Iterator

from ets_checker.models import CheckDetail, Locator, Paragraph, ParsedDocument
from ets_checker.parser.sections import is_reference_title
from ets_checker.rules.runner import register

MAX_REPORTED = 20

# Statistical symbols this rule cares about (kept narrow on purpose; broader
# matching belongs in font.stat_italic which has its own exclusion list).
_STAT_SYMBOLS = {
    "p", "t", "F", "r", "z", "M", "SD", "SE", "SEM",
    "N", "n", "df", "DF", "MS", "SS", "CI", "OR", "HR",
    "d", "η", "χ", "β",
}
_STAT_ALT = "|".join(sorted(_STAT_SYMBOLS, key=len, reverse=True))

# Operator without a space on at least one side, immediately adjacent to a
# statistical symbol on the left. Examples that match: "p=.05", "t=2.3",
# "F (1, 28)=4.2", "p< .001". The look-around captures only the offending
# character span so the message can quote the exact token.
_TIGHT_OP = re.compile(
    r"(?<![A-Za-z0-9])(?P<sym>" + _STAT_ALT + r")"
    r"(?P<gap>\s*)"
    r"(?P<op>[=<>≤≥])"
    r"(?P<after>\s*)"
    r"(?=[\d.\-+])",
)

# p value with leading zero: "p = 0.045" / "p<0.05".
_P_LEADING_ZERO = re.compile(
    r"(?<![A-Za-z])p\s*[=<>≤≥]\s*(?P<val>0\.\d+)",
)

# p = .000 (or 0.000) — should be "p < .001" instead.
_P_ZERO_VALUE = re.compile(
    r"(?<![A-Za-z])p\s*=\s*(?P<val>0?\.0+)\b",
)


def _body_paragraphs(doc: ParsedDocument) -> Iterator[Paragraph]:
    ref_start: int | None = next(
        (s.paragraph_index for s in doc.sections if is_reference_title(s.title)),
        None,
    )
    for para in doc.paragraphs:
        if para.is_in_table:
            continue
        if ref_start is not None and para.index >= ref_start:
            break
        if para.text.strip():
            yield para


@register(
    "statistics.operator_spacing",
    "Statistics",
    "Relational operator spacing",
    "warning",
)
def check_operator_spacing(doc: ParsedDocument) -> list[CheckDetail]:
    """Flag stat-symbol/operator pairs missing whitespace on at least one side.

    APA 7 §6.45: insert a space before and after operators (=, <, >, ≤, ≥)
    used in mathematical and statistical expressions.
    """
    details: list[CheckDetail] = []
    issue_count = 0
    seen: set[tuple[int, int]] = set()

    for para in _body_paragraphs(doc):
        text = para.text
        for m in _TIGHT_OP.finditer(text):
            gap_before = m.group("gap")
            gap_after = m.group("after")
            if gap_before and gap_after:
                continue  # spaces present on both sides — fine
            key = (para.index, m.start())
            if key in seen:
                continue
            seen.add(key)
            ctx_start = max(0, m.start() - 12)
            ctx_end = min(len(text), m.end() + 12)
            sym = m.group("sym")
            op = m.group("op")
            offending = text[m.start():m.end()].strip()
            if issue_count < MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"paragraph {para.index}",
                    locator=Locator(
                        kind="paragraph",
                        paragraph_index=para.index,
                        char_start=m.start(),
                        char_end=m.end(),
                    ),
                    message=(
                        f"Missing space around relational operator "
                        f"in statistical expression '{offending}' — "
                        f"APA 7 §6.45: write '{sym} {op} ...' with spaces"
                    ),
                    expected=f"{sym} {op} ...",
                    actual=offending,
                    excerpt=text[ctx_start:ctx_end],
                ))
            issue_count += 1

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"... and {issue_count - MAX_REPORTED} more operator-spacing "
                f"issues"
            ),
        ))

    return details


@register(
    "statistics.p_value_format",
    "Statistics",
    "p-value formatting (APA 7 §6.44)",
    "warning",
)
def check_p_value_format(doc: ParsedDocument) -> list[CheckDetail]:
    """Flag p values written with a leading zero or as 'p = .000'.

    APA 7 §6.44: p never carries a leading zero (it cannot exceed 1.0); values
    below .001 are reported as ``p < .001`` rather than ``p = .000``.
    """
    details: list[CheckDetail] = []
    issue_count = 0
    seen: set[tuple[int, int]] = set()

    for para in _body_paragraphs(doc):
        text = para.text
        for m in _P_ZERO_VALUE.finditer(text):
            key = (para.index, m.start())
            if key in seen:
                continue
            seen.add(key)
            val = m.group("val")
            if issue_count < MAX_REPORTED:
                ctx_start = max(0, m.start() - 12)
                ctx_end = min(len(text), m.end() + 12)
                details.append(CheckDetail(
                    location=f"paragraph {para.index}",
                    locator=Locator(
                        kind="paragraph",
                        paragraph_index=para.index,
                        char_start=m.start(),
                        char_end=m.end(),
                    ),
                    message=(
                        f"'p = {val}' should be written 'p < .001' (APA 7 §6.44 "
                        f"— a p value below .001 is reported as p < .001, not "
                        f"as a literal zero)"
                    ),
                    expected="p < .001",
                    actual=f"p = {val}",
                    excerpt=text[ctx_start:ctx_end],
                ))
            issue_count += 1

        for m in _P_LEADING_ZERO.finditer(text):
            key = (para.index, m.start())
            if key in seen:
                continue
            seen.add(key)
            val = m.group("val")
            if issue_count < MAX_REPORTED:
                ctx_start = max(0, m.start() - 12)
                ctx_end = min(len(text), m.end() + 12)
                stripped = val[1:]  # remove leading "0"
                details.append(CheckDetail(
                    location=f"paragraph {para.index}",
                    locator=Locator(
                        kind="paragraph",
                        paragraph_index=para.index,
                        char_start=m.start(),
                        char_end=m.end(),
                    ),
                    message=(
                        f"p value with leading zero ('{val}') — APA 7 §6.44: "
                        f"omit the leading zero for statistics that cannot "
                        f"exceed 1.0 (write '{stripped}')"
                    ),
                    expected=stripped,
                    actual=val,
                    excerpt=text[ctx_start:ctx_end],
                ))
            issue_count += 1

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"... and {issue_count - MAX_REPORTED} more p-value formatting "
                f"issues"
            ),
        ))

    return details
