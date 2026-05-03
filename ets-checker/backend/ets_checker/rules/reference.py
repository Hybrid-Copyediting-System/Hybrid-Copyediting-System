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

_AUTHOR_KEY_SEP = "\x01"

_SortKey = tuple[tuple[str, ...], int, str]


def _sort_key(r: Reference) -> _SortKey:
    """Build a tuple key that orders references by APA 7 §9.46 rules:
    surname → initials → second-author surname → … → year → year_suffix.

    The key is constructed so that the *natural* tuple comparison gives the
    correct order: a single-author entry with surname "Ali, S." sorts before
    "Ali, S. A." because "s" < "sa"; same first author with different second
    authors orders by the second-author key; same first-author chain orders
    chronologically; same year orders by suffix (a, b, c…).
    """
    keys = list(r.author_sort_keys)
    # Fallback: if the author chain wasn't parsed, use the surname alone
    # so the entry still participates in ordering.
    if not keys and r.first_author_surname:
        keys = [normalise_surname(r.first_author_surname) + _AUTHOR_KEY_SEP]
    year = int(r.year) if r.year and r.year.isdigit() else 0
    suffix = r.year_suffix or ""
    return (tuple(keys), year, suffix)


def _split_author_key(k: str) -> tuple[str, str]:
    surname, _, initials = k.partition(_AUTHOR_KEY_SEP)
    return surname, initials


def _diff_reason(prev: Reference, cur: Reference) -> tuple[str, str]:
    """Return (expected_text, actual_text) describing the first axis on which
    *cur* is sorted before *prev* — used to generate a precise message."""
    cur_authors = cur.author_sort_keys or []
    prev_authors = prev.author_sort_keys or []

    # Compare author by author — the first axis where they differ is the
    # reason for the ordering issue.
    for i in range(max(len(cur_authors), len(prev_authors))):
        c = cur_authors[i] if i < len(cur_authors) else ""
        p = prev_authors[i] if i < len(prev_authors) else ""
        if c == p:
            continue
        # APA 7 §9.46: a one-author entry precedes a multi-author entry that
        # begins with the same first author. The rule only fires when
        # prev_key > cur_key, and tuple comparison ranks shorter chains
        # below longer ones — so the only way one side runs out of authors
        # here is when *cur* is the single-author entry that should sort
        # first. (The reverse, cur=multi after prev=single, is correctly
        # ordered and never reaches this branch.)
        if not c or not p:
            return (
                "single-author entry before multi-author entry with the same first author (APA 7 §9.46)",
                "multi-author entry placed before single-author entry with the same first author",
            )
        c_surname, c_init = _split_author_key(c)
        p_surname, p_init = _split_author_key(p)
        if c_surname != p_surname:
            position = "first author" if i == 0 else f"author #{i + 1}"
            return (
                f"{c_surname} ({position}) before {p_surname}",
                f"{p_surname} before {c_surname}",
            )
        # Same surname, different initials.
        position = "first author" if i == 0 else f"author #{i + 1}"
        return (
            f"initials '{c_init}' ({position}, {c_surname}) before '{p_init}'",
            f"initials '{p_init}' before '{c_init}'",
        )

    # Author chains identical — must be year or suffix.
    if (cur.year or "") != (prev.year or ""):
        return (
            f"{cur.year or '(no year)'} before {prev.year or '(no year)'}",
            f"{prev.year or '(no year)'} before {cur.year or '(no year)'}",
        )
    cur_suf = cur.year_suffix or ""
    prev_suf = prev.year_suffix or ""
    return (
        f"suffix '{cur_suf}' before '{prev_suf}'",
        f"suffix '{prev_suf}' before '{cur_suf}'",
    )


@register(
    "reference.alphabetical_order",
    "Reference",
    "Reference list alphabetical order",
    "warning",
)
def check_alphabetical_order(doc: ParsedDocument) -> list[CheckDetail]:
    """Compare each reference against the previous one using a full APA 7
    sort key (author chain → year → suffix). CJK-leading entries are skipped
    so a mixed Chinese/English bibliography doesn't trigger spurious issues
    when the two scripts are interleaved by the author."""
    details: list[CheckDetail] = []
    issue_count = 0

    last_english: tuple[_SortKey, Reference] | None = None

    for r in doc.references:
        if not r.first_author_surname or r.parse_confidence < 0.5:
            continue
        if _is_cjk(r.first_author_surname):
            continue

        cur_key = _sort_key(r)
        cur_name = r.first_author_surname

        if last_english is not None:
            prev_key, prev_ref = last_english
            if prev_key > cur_key:
                expected, actual = _diff_reason(prev_ref, r)
                issue_count += 1
                if issue_count <= MAX_REPORTED:
                    prev_name = prev_ref.first_author_surname or "(unknown)"
                    details.append(CheckDetail(
                        location=f"Reference #{r.index}",
                        locator=Locator(kind="paragraph", paragraph_index=r.paragraph_index),
                        message=(
                            f"Out of alphabetical order: Reference #{r.index} "
                            f"('{cur_name}', {r.year or 'n.d.'}) should come before "
                            f"Reference #{prev_ref.index} ('{prev_name}', "
                            f"{prev_ref.year or 'n.d.'})"
                        ),
                        expected=expected,
                        actual=actual,
                        excerpt=r.raw_text[:200],
                    ))

        last_english = (cur_key, r)

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
