from __future__ import annotations

import re

from ets_checker import ets_profile as P
from ets_checker.models import CheckDetail, Locator, ParsedDocument, Reference
from ets_checker.rules.citation import normalise_surname
from ets_checker.rules.runner import register

ET_AL_PATTERN = re.compile(r"\bet\s+al\.", re.IGNORECASE)
MAX_REPORTED = 20


def _is_cjk(s: str) -> bool:
    return any(
        "㐀" <= c <= "䶿"   # CJK Extension A
        or "一" <= c <= "鿿"   # CJK Unified Ideographs
        or "豈" <= c <= "﫿"   # CJK Compatibility Ideographs
        for c in s
    )


@register("reference.no_et_al", "Reference", "No 'et al.' in reference list", "error")
def check_no_et_al(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []
    for r in doc.references:
        if ET_AL_PATTERN.search(r.raw_text):
            details.append(CheckDetail(
                location=f"Reference #{r.index}",
                locator=Locator(kind="paragraph", paragraph_index=r.paragraph_index),
                message="Reference list must not use 'et al.'; list all authors",
                excerpt=r.raw_text[:200],
            ))
    return details


# ── Item 6: Alphabetical order ────────────────────────────────────────

@register(
    "reference.alphabetical_order",
    "Reference",
    "Reference list alphabetical order",
    "warning",
)
def check_alphabetical_order(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []
    issue_count = 0

    last_english: tuple[str, str, Reference] | None = None

    for r in doc.references:
        if not r.first_author_surname or r.parse_confidence < 0.5:
            continue

        name = r.first_author_surname

        if _is_cjk(name):
            continue

        norm = normalise_surname(name)
        if not norm:
            continue

        if last_english is not None:
            prev_norm, prev_name, prev_ref = last_english

            if prev_norm > norm:
                issue_count += 1
                if issue_count <= MAX_REPORTED:
                    details.append(CheckDetail(
                        location=f"Reference #{r.index}",
                        locator=Locator(kind="paragraph", paragraph_index=r.paragraph_index),
                        message=(
                            f"Out of alphabetical order: '{name}' (Reference #{r.index}) "
                            f"should come before '{prev_name}' (Reference #{prev_ref.index})"
                        ),
                        expected=f"{name} before {prev_name}",
                        actual=f"{prev_name} before {name}",
                        excerpt=r.raw_text[:200],
                    ))
            elif prev_norm == norm:
                prev_year = int(prev_ref.year) if prev_ref.year and prev_ref.year.isdigit() else 0
                cur_year = int(r.year) if r.year and r.year.isdigit() else 0
                if prev_year > cur_year > 0:
                    issue_count += 1
                    if issue_count <= MAX_REPORTED:
                        details.append(CheckDetail(
                            location=f"Reference #{r.index}",
                            locator=Locator(kind="paragraph", paragraph_index=r.paragraph_index),
                            message=(
                                f"Same author '{name}': year {r.year} (Reference #{r.index}) "
                                f"should come before {prev_ref.year} (Reference #{prev_ref.index})"
                            ),
                            expected=f"{r.year} before {prev_ref.year}",
                            actual=f"{prev_ref.year} before {r.year}",
                            excerpt=r.raw_text[:200],
                        ))
                elif prev_year == cur_year and prev_year > 0:
                    prev_suffix = prev_ref.year_suffix or ""
                    cur_suffix = r.year_suffix or ""
                    if prev_suffix > cur_suffix and cur_suffix:
                        issue_count += 1
                        if issue_count <= MAX_REPORTED:
                            details.append(CheckDetail(
                                location=f"Reference #{r.index}",
                                locator=Locator(kind="paragraph", paragraph_index=r.paragraph_index),
                                message=(
                                    f"Same author '{name}', same year {r.year}: "
                                    f"suffix '{cur_suffix}' (Reference #{r.index}) "
                                    f"should come before '{prev_suffix}' (Reference #{prev_ref.index})"
                                ),
                                expected=f"{r.year}{cur_suffix} before {prev_ref.year}{prev_suffix}",
                                actual=f"{prev_ref.year}{prev_suffix} before {r.year}{cur_suffix}",
                                excerpt=r.raw_text[:200],
                            ))

        last_english = (norm, name, r)

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {issue_count - MAX_REPORTED} more alphabetical order issues",
        ))

    return details


# ── Item 7: Hanging indent ────────────────────────────────────────────

@register(
    "reference.hanging_indent",
    "Reference",
    "Reference hanging indent",
    "warning",
)
def check_hanging_indent(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []
    expected = P.REFERENCE_HANGING_INDENT_CM
    tol = P.REFERENCE_INDENT_TOLERANCE_CM
    issue_count = 0

    for r in doc.references:
        if r.paragraph_index >= len(doc.paragraphs):
            continue

        para = doc.paragraphs[r.paragraph_index]
        first_line = para.indent_first_line_cm
        left = para.indent_left_cm

        if first_line is None and left is None:
            issue_count += 1
            if issue_count <= MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"Reference #{r.index}",
                    locator=Locator(kind="paragraph", paragraph_index=r.paragraph_index),
                    message="Reference is missing hanging indent",
                    expected=f"hanging indent of {expected} cm",
                    actual="no indent set",
                    excerpt=r.raw_text[:200],
                ))
            continue

        has_hanging = first_line is not None and first_line < 0
        if not has_hanging:
            issue_count += 1
            if issue_count <= MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"Reference #{r.index}",
                    locator=Locator(kind="paragraph", paragraph_index=r.paragraph_index),
                    message="Reference is missing hanging indent",
                    expected=f"hanging indent of {expected} cm",
                    actual=(
                        f"first-line indent of {first_line} cm"
                        if first_line is not None
                        else "no first-line indent"
                    ),
                    excerpt=r.raw_text[:200],
                ))
            continue

        hanging_cm = abs(first_line)
        if abs(hanging_cm - expected) > tol:
            issue_count += 1
            if issue_count <= MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"Reference #{r.index}",
                    locator=Locator(kind="paragraph", paragraph_index=r.paragraph_index),
                    message=f"Hanging indent is {hanging_cm:.2f} cm, expected {expected} cm",
                    expected=f"{expected} cm",
                    actual=f"{hanging_cm:.2f} cm",
                    excerpt=r.raw_text[:200],
                ))

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {issue_count - MAX_REPORTED} more hanging indent issues",
        ))

    return details
