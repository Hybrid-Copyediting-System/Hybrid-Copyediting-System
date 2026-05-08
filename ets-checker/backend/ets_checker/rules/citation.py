from __future__ import annotations

import functools
import re

from ets_checker import ets_profile as P
from ets_checker.models import CheckDetail, Locator, ParsedDocument, Reference
from ets_checker.rules.runner import register
from ets_checker.utils.text import normalise_surname

MAX_REPORTED = 20

_AUTHOR_PART = re.compile(r"^(.+?)\s*[(（](?:(?:19|20)\d{2}|n\.d\.)")


def _ref_is_single_author(ref: Reference) -> bool:
    m = _AUTHOR_PART.match(ref.raw_text)
    author_text = m.group(1) if m else ref.raw_text[:60]
    return "&" not in author_text and " and " not in author_text

# Minimum length for institutional-author prefix matching; avoids false positives
# for very short surnames (e.g. "Li" matching "Lincoln").
_MIN_PREFIX_LEN = 6

# Suffix matching uses a lower threshold: a short surname being the tail of a
# multi-word surname (e.g. "Berg" from "Van der Berg") almost always indicates
# the same person, and both entries must also share the same year.
_MIN_SUFFIX_LEN = 4

def _find_prefix_match(
    cite_norm: str,
    year: str,
    suffix: str,
    surname_index: dict[str, list[tuple[str, str, int]]],
) -> tuple[str, str, str, int] | None:
    """Return (ref_norm, year, suffix, ref_pos) when cite_norm is a short-form
    prefix of a longer reference surname AND year/suffix match exactly.
    Used to match institutional authors cited in abbreviated form
    (e.g. 'State Council' → 'State Council of the People's Republic of China').
    """
    if len(cite_norm) < _MIN_PREFIX_LEN:
        return None
    for ref_norm, entries in surname_index.items():
        if ref_norm != cite_norm and ref_norm.startswith(cite_norm):
            for ref_year, ref_suffix, ref_pos in entries:
                if ref_year == year and ref_suffix == suffix:
                    return (ref_norm, ref_year, ref_suffix, ref_pos)
    return None


def _find_suffix_match(
    cite_norm: str,
    year: str,
    suffix: str,
    surname_index: dict[str, list[tuple[str, str, int]]],
) -> tuple[str, str, str, int] | None:
    """Return (ref_norm, year, suffix, ref_pos) when cite_norm matches the
    tail of a longer reference surname AND year/suffix match exactly.
    Catches multi-word surname inconsistencies where the citation uses only
    the last word (e.g. 'Hashim' citing 'Salah Hashim').
    """
    if len(cite_norm) < _MIN_SUFFIX_LEN:
        return None
    for ref_norm, entries in surname_index.items():
        if ref_norm != cite_norm and ref_norm.endswith(cite_norm):
            for ref_year, ref_suffix, ref_pos in entries:
                if ref_year == year and ref_suffix == suffix:
                    return (ref_norm, ref_year, ref_suffix, ref_pos)
    return None


@functools.lru_cache(maxsize=4096)
def _damerau_levenshtein(s: str, t: str) -> int:
    """Optimal string alignment distance (handles transpositions as single edits)."""
    m, n = len(s), len(t)
    d = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        d[i][0] = i
    for j in range(n + 1):
        d[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if s[i - 1] == t[j - 1] else 1
            d[i][j] = min(
                d[i - 1][j] + 1,
                d[i][j - 1] + 1,
                d[i - 1][j - 1] + cost,
            )
            if i > 1 and j > 1 and s[i - 1] == t[j - 2] and s[i - 2] == t[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + cost)
    return d[m][n]


def _find_near_miss(
    cite_norm: str,
    cite_year: str,
    cite_suffix: str,
    surname_index: dict[str, list[tuple[str, str, int]]],
) -> tuple[str, int] | None:
    """Return (ref_norm, ref_pos) when a reference surname has DL-distance ≤ 1
    from cite_norm AND shares the same year+suffix — a likely author name typo.
    Requires cite_norm ≥ 3 chars to avoid spurious matches on very short names.
    """
    if len(cite_norm) < 3:
        return None
    for ref_norm, entries in surname_index.items():
        if ref_norm == cite_norm:
            continue
        if _damerau_levenshtein(cite_norm, ref_norm) <= 1:
            for ref_year, ref_suffix, ref_pos in entries:
                if ref_year == cite_year and ref_suffix == cite_suffix:
                    return ref_norm, ref_pos
    return None


def _year_diff(y1: str, y2: str) -> int:
    """Compute year difference. n.d. vs numeric is treated as a moderate mismatch (2),
    not an extreme one, so it triggers a year-mismatch warning rather than an orphan."""
    if y1.isdigit() and y2.isdigit():
        return abs(int(y1) - int(y2))
    if y1 == y2:
        return 0
    # One is n.d. and the other is numeric — treat as moderate mismatch
    if y1 == "n.d." or y2 == "n.d.":
        return 2
    return 99


@register("citation.cross_reference", "Citation", "Citation–reference cross-check", "error")
def check_cross_reference(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []

    # Exact-match index: (norm_surname, year, suffix) → list of ref positions.
    # A list (not a single int) so that several references sharing the same
    # surname+year+suffix (e.g. three "Li, 2024" entries with different first
    # initials) are all retained for the uncited-references sweep at the end.
    ref_positions: dict[tuple[str, str, str], list[int]] = {}
    # Surname-only index: norm_surname → [(year, suffix, ref_pos), ...]
    surname_index: dict[str, list[tuple[str, str, int]]] = {}

    unparseable_refs: list[Reference] = []
    for pos, r in enumerate(doc.references):
        if r.first_author_surname and r.year:
            norm = normalise_surname(r.first_author_surname)
            key = (norm, r.year, r.year_suffix or "")
            ref_positions.setdefault(key, []).append(pos)
            surname_index.setdefault(norm, []).append((r.year, r.year_suffix or "", pos))
        elif r.parse_confidence < 0.5:
            unparseable_refs.append(r)

    cited_keys: set[tuple[str, str, str]] = set()
    orphan_count = 0
    year_mismatch_count = 0
    surname_mismatch_count = 0

    for c in doc.citations:
        if not c.authors:
            continue
        cite_norm = normalise_surname(c.authors[0])
        cite_year = c.year
        cite_suffix = c.year_suffix or ""
        key = (cite_norm, cite_year, cite_suffix)

        if key in ref_positions:
            cited_keys.add(key)
            continue

        # ── Year mismatch: same normalised surname, different year/suffix ─────
        if cite_norm in surname_index:
            entries = surname_index[cite_norm]
            if len(entries) == 1:
                ref_year, ref_suffix, ref_pos = entries[0]
                ref = doc.references[ref_pos]
                year_diff = _year_diff(cite_year, ref_year)
                cite_is_multi = c.has_et_al or len(c.authors) > 1
                authorship_mismatch = cite_is_multi == _ref_is_single_author(ref)
                likely_different_person = (
                    (year_diff >= 3 and authorship_mismatch)
                    or year_diff > 5
                )
                if likely_different_person:
                    if orphan_count < MAX_REPORTED:
                        ref_year_str = f"{ref_year}{ref_suffix}" if ref_suffix else ref_year
                        details.append(CheckDetail(
                            location=f"paragraph {c.paragraph_index}",
                            locator=Locator(kind="paragraph", paragraph_index=c.paragraph_index),
                            message=(
                                f"Citation '{c.raw_text}' has no matching reference "
                                f"(Reference #{ref.index} has surname '{ref.first_author_surname}' "
                                f"with year {ref_year_str}, which differs by {year_diff} year(s) "
                                f"from the cited {cite_year} — likely a year typo or a different work)"
                            ),
                            excerpt=c.raw_text,
                        ))
                    orphan_count += 1
                    continue

                ref_year_str = f"{ref_year}{ref_suffix}" if ref_suffix else ref_year
                cite_year_str = f"{cite_year}{cite_suffix}" if cite_suffix else cite_year
                cited_keys.add((cite_norm, ref_year, ref_suffix))
                if year_mismatch_count < MAX_REPORTED:
                    if ref_year == cite_year:
                        msg = (
                            f"Citation year-suffix mismatch: '{c.raw_text}' cites {cite_year_str}, "
                            f"but Reference #{ref.index} ({ref.first_author_surname}) has {ref_year_str}"
                        )
                    else:
                        msg = (
                            f"Citation year mismatch: '{c.raw_text}' cites {cite_year_str}, "
                            f"but Reference #{ref.index} ({ref.first_author_surname}) has {ref_year_str}"
                        )
                    details.append(CheckDetail(
                        location=f"paragraph {c.paragraph_index}",
                        locator=Locator(kind="paragraph", paragraph_index=c.paragraph_index),
                        message=msg,
                        excerpt=c.raw_text,
                    ))
                year_mismatch_count += 1
                continue
            else:
                # Multiple references with same surname — find closest year
                best_entry = min(
                    entries,
                    key=lambda e: _year_diff(e[0], cite_year),
                )
                ref_year, ref_suffix, ref_pos = best_entry
                ref = doc.references[ref_pos]
                year_diff = _year_diff(cite_year, ref_year)
                cite_is_multi = c.has_et_al or len(c.authors) > 1
                authorship_mismatch = cite_is_multi == _ref_is_single_author(ref)
                likely_different_person = (
                    (year_diff >= 3 and authorship_mismatch)
                    or year_diff > 5
                )
                if likely_different_person:
                    if orphan_count < MAX_REPORTED:
                        available = ", ".join(
                            sorted({f"{ry}{rs}" if rs else ry for (ry, rs, _rp) in entries})
                        )
                        details.append(CheckDetail(
                            location=f"paragraph {c.paragraph_index}",
                            locator=Locator(kind="paragraph", paragraph_index=c.paragraph_index),
                            message=(
                                f"Citation '{c.raw_text}' has no matching reference "
                                f"(references with surname '{ref.first_author_surname}' "
                                f"exist for year(s) {available}, but none match the cited "
                                f"{cite_year} — likely a year typo or a different work)"
                            ),
                            excerpt=c.raw_text,
                        ))
                    orphan_count += 1
                    continue

                # When the citation drops the suffix and several references
                # share the same year, list every candidate so the author
                # knows which one to pick (e.g. 2021a vs 2021b).
                same_year_entries = [
                    (ry, rs, rp) for (ry, rs, rp) in entries if ry == cite_year
                ]
                cite_year_str = f"{cite_year}{cite_suffix}" if cite_suffix else cite_year
                cited_keys.add((cite_norm, ref_year, ref_suffix))
                if year_mismatch_count < MAX_REPORTED:
                    if (
                        ref_year == cite_year
                        and not cite_suffix
                        and len(same_year_entries) >= 2
                    ):
                        suffix_list = ", ".join(
                            f"Reference #{doc.references[rp].index} has {ry}{rs}"
                            for (ry, rs, rp) in same_year_entries
                            if rs
                        )
                        msg = (
                            f"Citation year-suffix mismatch: '{c.raw_text}' cites {cite_year_str} "
                            f"but the references list contains multiple {cite_year} entries "
                            f"under '{ref.first_author_surname}' — {suffix_list}; "
                            f"specify the correct suffix in the citation"
                        )
                    elif ref_year == cite_year:
                        ref_year_str = f"{ref_year}{ref_suffix}" if ref_suffix else ref_year
                        msg = (
                            f"Citation year-suffix mismatch: '{c.raw_text}' cites {cite_year_str}, "
                            f"but Reference #{ref.index} ({ref.first_author_surname}) has {ref_year_str}"
                        )
                    else:
                        ref_year_str = f"{ref_year}{ref_suffix}" if ref_suffix else ref_year
                        msg = (
                            f"Citation year mismatch: '{c.raw_text}' cites {cite_year_str}, "
                            f"but Reference #{ref.index} ({ref.first_author_surname}) has {ref_year_str}"
                        )
                    details.append(CheckDetail(
                        location=f"paragraph {c.paragraph_index}",
                        locator=Locator(kind="paragraph", paragraph_index=c.paragraph_index),
                        message=msg,
                        excerpt=c.raw_text,
                    ))
                year_mismatch_count += 1
                continue

        # ── Institutional author prefix match ────────────────────────────────
        # e.g. "State Council (2017)" → "State Council of the People's Republic
        # of China (2017)".  Same year required; no error reported.
        prefix_hit = _find_prefix_match(cite_norm, cite_year, cite_suffix, surname_index)
        if prefix_hit is not None:
            ref_norm, ref_year, ref_suffix, _pos = prefix_hit
            cited_keys.add((ref_norm, ref_year, ref_suffix))
            continue

        # ── Multi-word surname suffix match ──────────────────────────────────
        # e.g. "Hashim (2020)" citing "Salah Hashim, A. (2020)" — the citation
        # uses only the last part of a multi-word surname.
        suffix_hit = _find_suffix_match(cite_norm, cite_year, cite_suffix, surname_index)
        if suffix_hit is not None:
            ref_norm, ref_year, ref_suffix, ref_pos = suffix_hit
            ref = doc.references[ref_pos]
            cited_keys.add((ref_norm, ref_year, ref_suffix))
            if surname_mismatch_count < MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"paragraph {c.paragraph_index}",
                    locator=Locator(kind="paragraph", paragraph_index=c.paragraph_index),
                    message=(
                        f"Surname inconsistency: '{c.raw_text}' cites '{c.authors[0]}', "
                        f"but Reference #{ref.index} lists '{ref.first_author_surname}' — "
                        f"verify the multi-word surname is used consistently in citation and reference"
                    ),
                    excerpt=c.raw_text,
                ))
            surname_mismatch_count += 1
            continue

        # ── Near-miss surname (likely spelling/transposition error) ─────────
        near_hit = _find_near_miss(cite_norm, cite_year, cite_suffix, surname_index)
        if near_hit is not None:
            ref_norm, near_pos = near_hit
            ref = doc.references[near_pos]
            cited_keys.add((ref_norm, cite_year, cite_suffix))
            if surname_mismatch_count < MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"paragraph {c.paragraph_index}",
                    locator=Locator(kind="paragraph", paragraph_index=c.paragraph_index),
                    message=(
                        f"Possible spelling error: Citation '{c.raw_text}' may refer to "
                        f"Reference #{ref.index} ('{ref.first_author_surname}', {cite_year}) — "
                        f"check the author surname spelling"
                    ),
                    excerpt=c.raw_text,
                ))
            surname_mismatch_count += 1
            continue

        # ── True orphan: author not found at all in references ───────────────
        if orphan_count < MAX_REPORTED:
            details.append(CheckDetail(
                location=f"paragraph {c.paragraph_index}",
                locator=Locator(kind="paragraph", paragraph_index=c.paragraph_index),
                message=f"Citation '{c.raw_text}' has no matching reference",
                excerpt=c.raw_text,
            ))
        orphan_count += 1

    if year_mismatch_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {year_mismatch_count - MAX_REPORTED} more citation year mismatches",
        ))
    if surname_mismatch_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {surname_mismatch_count - MAX_REPORTED} more surname inconsistencies",
        ))
    if orphan_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {orphan_count - MAX_REPORTED} more orphan citations",
        ))

    uncited_count = 0
    for key, positions in ref_positions.items():
        if key in cited_keys:
            continue
        for ref_idx in positions:
            ref = doc.references[ref_idx]
            if uncited_count < MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"Reference #{ref.index}",
                    locator=Locator(kind="paragraph", paragraph_index=ref.paragraph_index),
                    message="Reference is not cited in text",
                    excerpt=ref.raw_text[:200],
                ))
            uncited_count += 1

    if uncited_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {uncited_count - MAX_REPORTED} more uncited references",
        ))

    for r in unparseable_refs:
        details.append(CheckDetail(
            location=f"Reference #{r.index}",
            locator=Locator(kind="paragraph", paragraph_index=r.paragraph_index),
            message="Reference could not be parsed (missing author or year)",
            excerpt=r.raw_text[:200],
        ))

    return details


# ── Item 8: et al. usage ────────────────────────────────────────────

@register("citation.et_al_usage", "Citation", "Et al. usage check (APA 7th)", "warning")
def check_et_al_usage(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []
    threshold = P.ET_AL_THRESHOLD

    # Multiple references can share (surname, year, suffix) — e.g. three
    # "Li, 2024" entries with different first-author initials. Keep all of
    # them so the rule can pick the best match instead of arbitrarily flagging
    # whichever one happened to be appended last.
    ref_candidates: dict[tuple[str, str, str], list[Reference]] = {}
    surname_index: dict[str, list[Reference]] = {}
    for r in doc.references:
        if r.first_author_surname and r.year:
            norm = normalise_surname(r.first_author_surname)
            key = (norm, r.year, r.year_suffix or "")
            ref_candidates.setdefault(key, []).append(r)
            surname_index.setdefault(norm, []).append(r)

    issue_count = 0
    # Track already-reported (norm_surname, year, has_et_al) to avoid duplicate
    # messages for the same citation pattern appearing multiple times in text.
    reported: set[tuple[str, str, bool]] = set()

    for c in doc.citations:
        if not c.authors:
            continue
        cite_norm = normalise_surname(c.authors[0])
        key = (cite_norm, c.year, c.year_suffix or "")

        dedup_key = (cite_norm, c.year, c.has_et_al)
        if dedup_key in reported:
            continue

        candidates = ref_candidates.get(key)
        if not candidates:
            # Fall back to surname-only lookup ONLY when a same-year reference
            # exists. Without this guard, "Xu, 2022" would match "Xu, 2024" and
            # produce a misleading et al. warning sourced from the wrong work.
            # Same-year (suffix-only diff) is fine — that handles the common
            # APA pattern where the citation drops the suffix, e.g. cite
            # "Huang, 2022" while the reference is "Huang, 2022a".
            if cite_norm in surname_index:
                same_year_entries = [
                    e for e in surname_index[cite_norm] if (e.year or "") == c.year
                ]
                if not same_year_entries:
                    continue
                candidates = same_year_entries
            else:
                continue

        # Drop candidates with no resolved author count — they can't inform
        # the et al. decision either way.
        candidates = [r for r in candidates if r.author_count is not None]
        if not candidates:
            continue

        if c.has_et_al:
            # Only flag when NO candidate has enough authors to justify et al.
            # If any candidate has ≥ threshold authors, the citation is
            # plausibly correct — don't punish the author for the rule's
            # inability to disambiguate.
            if all(r.author_count < threshold for r in candidates):
                ref = max(candidates, key=lambda r: r.author_count)
                reported.add(dedup_key)
                if issue_count < MAX_REPORTED:
                    details.append(CheckDetail(
                        location=f"paragraph {c.paragraph_index}",
                        locator=Locator(kind="paragraph", paragraph_index=c.paragraph_index),
                        message=(
                            f"Citation '{c.raw_text}' uses 'et al.' but Reference #{ref.index} "
                            f"({ref.first_author_surname}, {ref.year}) has only "
                            f"{ref.author_count} author(s); list all authors "
                            f"when there are fewer than {threshold}"
                        ),
                        expected=f"all {ref.author_count} author(s) listed",
                        actual="et al.",
                        excerpt=c.raw_text,
                    ))
                issue_count += 1

        elif not c.has_et_al and len(c.authors) <= 2:
            # Only flag when EVERY candidate has ≥ threshold authors. If any
            # candidate has ≤ 2 authors, "Smith & Jones, 2024" or "Smith, 2024"
            # is the correct spelled-out form for that reference.
            if all(r.author_count >= threshold for r in candidates):
                ref = min(candidates, key=lambda r: r.author_count)
                reported.add(dedup_key)
                if issue_count < MAX_REPORTED:
                    details.append(CheckDetail(
                        location=f"paragraph {c.paragraph_index}",
                        locator=Locator(kind="paragraph", paragraph_index=c.paragraph_index),
                        message=(
                            f"Citation '{c.raw_text}' should use 'et al.' — Reference #{ref.index} "
                            f"({ref.first_author_surname}, {ref.year}) has "
                            f"{ref.author_count} authors (APA 7th: use et al. for "
                            f"{threshold}+ authors)"
                        ),
                        expected=f"{ref.first_author_surname} et al.",
                        actual=c.raw_text,
                        excerpt=c.raw_text,
                    ))
                issue_count += 1

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {issue_count - MAX_REPORTED} more et al. usage issues",
        ))

    return details


# ── APA 7 §8.17: & inside parens, "and" in narrative ───────────────────


# Two co-authors joined by "and" inside a parenthetical citation. Optional
# discourse-style prefix ("see", "e.g.,", "cf.") is consumed before the
# author block so the rule still fires on "(see Smith and Jones, 2020)".
_PAREN_AND = re.compile(
    r"[(（]\s*"
    r"(?:(?:see|e\.g\.,?|cf\.|i\.e\.,?)\s+)?"
    r"(?P<first>[A-Z][\w\-’']+)"
    r"\s+and\s+"
    r"(?P<second>[A-Z][\w\-’']+)"
    r"(?:\s+et\s+al\.)?"
    r"\s*,\s*(?:19|20)\d{2}"
)
# Two co-authors joined by "&" outside parentheses but with a year in parens
# right after — narrative context in which "and" should have been used:
#   "Smith & Jones (2020)"
_NARRATIVE_AMP = re.compile(
    r"(?<![(（])"
    r"(?P<first>[A-Z][\w\-’']+)"
    r"\s*&\s*"
    r"(?P<second>[A-Z][\w\-’']+)"
    r"(?:\s+et\s+al\.)?"
    r"\s*[(（]\s*(?:19|20)\d{2}"
)


@register(
    "citation.amp_vs_and",
    "Citation",
    "Use & in parens, 'and' in narrative (APA 7 §8.17)",
    "warning",
)
def check_amp_vs_and(doc: ParsedDocument) -> list[CheckDetail]:
    """Detect the two inverse failures of APA 7 §8.17:

    * ``and`` between two authors *inside* a parenthetical citation —
      should be ``&``
    * ``&`` between two authors used in *narrative* form (Year alone in
      parens) — should be ``and``
    """
    details: list[CheckDetail] = []
    issue_count = 0

    # Skip the Reference section to avoid matching authors-of-references that
    # legitimately use "&" everywhere.
    from ets_checker.parser.sections import is_reference_title  # local to avoid cycles

    ref_start: int | None = next(
        (s.paragraph_index for s in doc.sections if is_reference_title(s.title)),
        None,
    )

    for para in doc.paragraphs:
        if ref_start is not None and para.index >= ref_start:
            break
        if para.is_in_table:
            continue
        text = para.text
        if not text or "(" not in text and "（" not in text:
            continue

        for m in _PAREN_AND.finditer(text):
            ctx_start = max(0, m.start() - 12)
            ctx_end = min(len(text), m.end() + 12)
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
                        "Parenthetical citation uses 'and' between authors — "
                        "APA 7 §8.17: use '&' inside parentheses, 'and' in "
                        "narrative text"
                    ),
                    expected=f"{m.group('first')} & {m.group('second')}",
                    actual=f"{m.group('first')} and {m.group('second')}",
                    excerpt=text[ctx_start:ctx_end],
                ))
            issue_count += 1

        for m in _NARRATIVE_AMP.finditer(text):
            ctx_start = max(0, m.start() - 12)
            ctx_end = min(len(text), m.end() + 12)
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
                        "Narrative citation uses '&' between authors — "
                        "APA 7 §8.17: use 'and' in narrative text, '&' inside "
                        "parentheses"
                    ),
                    expected=f"{m.group('first')} and {m.group('second')}",
                    actual=f"{m.group('first')} & {m.group('second')}",
                    excerpt=text[ctx_start:ctx_end],
                ))
            issue_count += 1

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"... and {issue_count - MAX_REPORTED} more & / and citation "
                f"issues"
            ),
        ))

    return details
