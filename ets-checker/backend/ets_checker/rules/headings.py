"""Heading-structure rules.

Two checks:

* ``headings.no_numbering`` — APA 7 (and ET&S) headings carry no numeric
  prefix (no "1.", "1.1", "Chapter 3", etc.). Section detection happily
  passes such prefixes through; this rule reports them.

* ``headings.level_order`` — heading levels must not skip; once an L1 is
  established, the first sub-heading must be L2 (not L3), and so on.
"""

from __future__ import annotations

import re

from ets_checker.models import CheckDetail, Locator, ParsedDocument
from ets_checker.parser.sections import (
    is_abstract_title,
    is_reference_title,
)
from ets_checker.rules.runner import register

MAX_REPORTED = 20

# A leading numeric prefix on a heading: "1.", "1.1.", "1.2.3.", "Chapter 5",
# "Section 2:". Captures only the prefix span so the message can quote it.
_NUMBERING_PATTERN = re.compile(
    r"^(?:"
    r"(?P<dotted>\d+(?:\.\d+)*)\.?\s+"
    r"|"
    r"(?P<word>(?:Chapter|Section|Part|第)\s*\d+[.:：]?)\s+"
    r")",
    re.IGNORECASE,
)


@register(
    "headings.no_numbering",
    "Structure",
    "Headings must not be numbered (APA 7)",
    "info",
)
def check_no_numbering(doc: ParsedDocument) -> list[CheckDetail]:
    """APA 7 §2.27 / §2.18: section headings are not numbered.

    Heuristic: a section title that opens with "1.", "1.1", "Chapter 2:"
    etc. is flagged. Inline-abstract / appendix-detected sections are
    skipped because they aren't true author-applied headings.
    """
    details: list[CheckDetail] = []
    issue_count = 0

    for s in doc.sections:
        if s.detection_method in ("inline_abstract", "appendix", "title"):
            continue
        # A bare "Abstract" / "References" never carries a number; matching
        # them would only surface false positives from the heuristic pass.
        if is_abstract_title(s.title) or is_reference_title(s.title):
            continue
        m = _NUMBERING_PATTERN.match(s.title)
        if m is None:
            continue
        prefix = m.group(0).rstrip()
        if issue_count < MAX_REPORTED:
            details.append(CheckDetail(
                location=f"paragraph {s.paragraph_index}",
                locator=Locator(
                    kind="paragraph",
                    paragraph_index=s.paragraph_index,
                ),
                message=(
                    f"Heading '{s.title}' has a numeric prefix '{prefix}' — "
                    f"APA 7 §2.27 forbids numbered section headings"
                ),
                expected="heading without numeric prefix",
                actual=f"prefix: '{prefix}'",
                excerpt=s.title[:200],
            ))
        issue_count += 1

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"... and {issue_count - MAX_REPORTED} more numbered headings"
            ),
        ))

    return details


@register(
    "headings.level_order",
    "Structure",
    "Heading levels must not skip",
    "warning",
)
def check_level_order(doc: ParsedDocument) -> list[CheckDetail]:
    """APA 7 §2.27: heading levels are used in order — H1, then H2, then H3.
    A jump from H1 directly to H3 indicates a malformed outline. The rule
    fires when any section's level is more than one greater than the
    deepest level reached so far.
    """
    details: list[CheckDetail] = []
    deepest = 0
    issue_count = 0

    for s in doc.sections:
        # Skip pseudo-sections that aren't author-authored headings.
        if s.detection_method in ("inline_abstract", "appendix", "title"):
            continue
        # Skip the literal abstract heading: it sits before any "depth"
        # has been established, and its level (always 1 in our model) is
        # never the source of a skip.
        if is_abstract_title(s.title) or is_reference_title(s.title):
            deepest = max(deepest, s.level)
            continue
        if deepest == 0:
            deepest = s.level
            continue
        if s.level > deepest + 1:
            if issue_count < MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"paragraph {s.paragraph_index}",
                    locator=Locator(
                        kind="paragraph",
                        paragraph_index=s.paragraph_index,
                    ),
                    message=(
                        f"Heading '{s.title}' jumps from level {deepest} to "
                        f"level {s.level} — APA 7 §2.27: use heading levels "
                        f"in order (do not skip)"
                    ),
                    expected=f"level {deepest + 1}",
                    actual=f"level {s.level}",
                    excerpt=s.title[:200],
                ))
            issue_count += 1
        deepest = max(deepest, s.level)

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"... and {issue_count - MAX_REPORTED} more heading-level "
                f"skips"
            ),
        ))

    return details
