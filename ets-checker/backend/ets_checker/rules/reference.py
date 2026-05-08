from __future__ import annotations

import re

from ets_checker import ets_profile as P
from ets_checker.models import CheckDetail, Locator, ParsedDocument, Paragraph, Reference, Run
from ets_checker.rules.citation import normalise_surname
from ets_checker.rules.runner import register

ET_AL_PATTERN = re.compile(r"\bet\s+al\.", re.IGNORECASE)
MAX_REPORTED = 20

# Page range like "129-65", "129–165", "1–10" — captures both numbers and the
# matched span so we can excerpt + suggest a fix. Restricted to runs of digits
# 1–4 long, which covers virtually all journal pagination without matching DOI
# fragments or year ranges (which APA wraps in parens).
_PAGE_RANGE = re.compile(r"\b(\d{1,4})\s*[-–—]\s*(\d{1,4})\b")

# Full APA journal pagination: ", 5(2), 129–145" or ", 5, 129–145" (some
# journals don't issue numbers). Either form satisfies AQF Item 6's
# "Volume (Issue), [page]" requirement.
_JOURNAL_PAGINATION = re.compile(
    r",\s*\d+(?:\(\s*[^)]+\s*\))?\s*,\s*\d{1,5}\s*[-–—]\s*\d{1,5}",
)
# Article number form ", 12345" (modern e-journals replace pages with one).
# Two flavours: explicit "Article 45" / "e1234" prefix, OR a bare single page
# number when followed by a terminator ('.', end-of-string, or a DOI/URL) —
# this catches Frontiers/MDPI-style entries like "9, 401." or "12(4), 493."
# where a single article number stands in for a page range.
_ARTICLE_NUMBER = re.compile(
    r",\s*\d+(?:\(\s*[^)]+\s*\))?\s*,\s*(?:Article|Article\s+No\.?|e)\s*\d+",
    re.IGNORECASE,
)
_SINGLE_PAGE_ARTICLE = re.compile(
    # Up to 7 digits — modern e-journal article numbers run 5-6 digits
    # (e.g. Acta Psychologica "104402", Frontiers "106096").
    r",\s*\d+(?:\(\s*[^)]+\s*\))?\s*,\s*\d{1,7}(?=\s*(?:\.|$|https?://|doi:|10\.\d{4,}/))",
    re.IGNORECASE,
)
# Book / chapter / dissertation / proceedings markers — APA does not strictly
# require DOI/URL for these, so we exclude them to keep the rule focused on
# the AQF target (journal articles missing Volume(Issue), pages and a DOI).
_BOOK_LIKE = re.compile(
    r"\b(?:"
    r"Press|Publisher|Publishers|Publishing|Inc\.|Ltd\.|Co\.|Company|"
    r"Routledge|Wiley|Springer|Sage|Pearson|Elsevier|Norton|"
    r"Academic\s+Press|University\s+Press|"
    r"\(Eds?\.\)|\(Ed\.\)|"
    r"Dissertation|Thesis|"
    r"Proceedings|Conference|Symposium|Workshop|"
    r"Tech(?:nical)?\.?\s+(?:Rep|Report)|Report\s+No\.|"
    r"Retrieved\s+from"
    r")\b",
    re.IGNORECASE,
)

# Trailing "City[, State]: Publisher." pattern — covers books whose publisher
# brand has no Press/Wiley/Springer/etc. keyword (e.g. "Garden City, New York:
# Doubleday Anchor."). The colon must be preceded by capitalised word(s) (the
# place of publication) and followed by capitalised word(s) ending the entry.
# Anchored to end of string so a mid-entry colon (subtitles like "Title:
# Subtitle. Journal, …") never matches.
_BOOK_PUBLISHER_END = re.compile(
    r"[A-Z][\w’'.\-]+(?:[\s,]+[A-Z][\w’'.\-]+)*\s*:\s*"
    r"[A-Z][\w&’'.\-]+(?:\s+(?:and\s+|&\s+)?[A-Z]?[\w&’'.\-]+)*"
    r"\s*\.\s*$",
)


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
    # Filter empty / whitespace-only entries so a malformed key chain doesn't
    # short-circuit past the surname fallback.
    keys = [k for k in r.author_sort_keys if k and k.strip()]
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
                if issue_count < MAX_REPORTED:
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
                issue_count += 1

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
        # Guard against both out-of-range and negative indices. Python's
        # negative-index wrap-around would silently point at the wrong
        # paragraph for a malformed reference index, masking the real bug.
        if not (0 <= r.paragraph_index < len(doc.paragraphs)):
            continue

        para = doc.paragraphs[r.paragraph_index]
        first_line = para.indent_first_line_cm
        left = para.indent_left_cm

        if first_line is None and left is None:
            if issue_count < MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"Reference #{r.index}",
                    locator=Locator(kind="paragraph", paragraph_index=r.paragraph_index),
                    message="Reference is missing hanging indent",
                    expected=f"hanging indent of {expected} cm",
                    actual="no indent set",
                    excerpt=r.raw_text[:200],
                ))
            issue_count += 1
            continue

        has_hanging = first_line is not None and first_line < 0
        if not has_hanging:
            if issue_count < MAX_REPORTED:
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
            issue_count += 1
            continue

        hanging_cm = abs(first_line)
        if abs(hanging_cm - expected) > tol:
            if issue_count < MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"Reference #{r.index}",
                    locator=Locator(kind="paragraph", paragraph_index=r.paragraph_index),
                    message=f"Hanging indent is {hanging_cm:.2f} cm, expected {expected} cm",
                    expected=f"{expected} cm",
                    actual=f"{hanging_cm:.2f} cm",
                    excerpt=r.raw_text[:200],
                ))
            issue_count += 1

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {issue_count - MAX_REPORTED} more hanging indent issues",
        ))

    return details


# ── Item 8: Page-number completeness ──────────────────────────────────


def _expand_abbreviated_end(start: int, end_str: str) -> int:
    """Reconstruct the full end-page number when the author abbreviated it,
    e.g. start=129, end_str="65" → 165. APA 7 §10.1 forbids this style;
    the journal asks for the unabbreviated form ("129–165").

    Strategy: pad the end string with the matching prefix from the start
    until the result is numerically larger than start.
    """
    s = str(start)
    e = end_str
    # Try replacing the last len(e) digits of start with e; if that's > start,
    # we have the intended end page.
    if len(e) < len(s):
        candidate = int(s[: len(s) - len(e)] + e)
        if candidate > start:
            return candidate
    return start  # caller will treat this as "couldn't expand"


def _looks_like_year_range(text: str, span_start: int, span_end: int) -> bool:
    """Skip page ranges that are actually year ranges (e.g. "(2018-2020)")."""
    pre = text[max(0, span_start - 1) : span_start]
    post = text[span_end : span_end + 1]
    return pre == "(" or post == ")"


def _looks_like_year_shorthand(start: int, end_str: str) -> bool:
    """Reject academic-year shorthand like "2018-19" or "2018-9".

    A 4-digit start in the publication-plausible range followed by a 1-2
    digit end is universally read as elided year notation, not abbreviated
    pagination. Mis-flagging this would suggest "2018–2019" — the same
    thing the author meant — confusing readers and obscuring the real
    page-range bugs.
    """
    if not (1900 <= start <= 2099):
        return False
    return len(end_str) <= 2


# Span detector for DOIs and URLs in reference text. Numeric ranges sitting
# inside one of these are part of the identifier (e.g. "10.30191/ETS.5-67.8"
# or "page=129-145"), not pagination, and must not be expanded.
_DOI_OR_URL_SPAN = re.compile(
    r"https?://\S+|\bdoi:\s*\S+|\b10\.\d{4,}/\S+",
    re.IGNORECASE,
)


def _identifier_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _DOI_OR_URL_SPAN.finditer(text)]


def _inside_any(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    s, e = span
    for ws, we in spans:
        if s >= ws and e <= we:
            return True
    return False


@register(
    "reference.page_number_complete",
    "Reference",
    "Reference page-number completeness",
    "warning",
)
def check_page_number_complete(doc: ParsedDocument) -> list[CheckDetail]:
    """Detect abbreviated page ranges in reference entries.

    AQF Item 6 (ET&S): "Incomplete page number. e.g., pp. 129-65, this should
    be pp. 129-165." We flag ranges where the end number has fewer digits
    *and* is numerically less than the start number — the unambiguous case.
    """
    details: list[CheckDetail] = []
    issue_count = 0

    for r in doc.references:
        flagged_spans: set[tuple[int, int]] = set()
        identifier_spans = _identifier_spans(r.raw_text)
        for m in _PAGE_RANGE.finditer(r.raw_text):
            if _looks_like_year_range(r.raw_text, m.start(), m.end()):
                continue
            if _inside_any((m.start(), m.end()), identifier_spans):
                continue
            start_str, end_str = m.group(1), m.group(2)
            start, end = int(start_str), int(end_str)
            if _looks_like_year_shorthand(start, end_str):
                continue
            # The exact AQF pattern: "129-65" (end < start AND fewer digits).
            if end < start and len(end_str) < len(start_str):
                expanded = _expand_abbreviated_end(start, end_str)
                if expanded == start:
                    continue
                span = (m.start(), m.end())
                if span in flagged_spans:
                    continue
                flagged_spans.add(span)
                excerpt_start = max(0, m.start() - 20)
                excerpt_end = min(len(r.raw_text), m.end() + 20)
                if issue_count < MAX_REPORTED:
                    details.append(CheckDetail(
                        location=f"Reference #{r.index}",
                        locator=Locator(
                            kind="paragraph",
                            paragraph_index=r.paragraph_index,
                        ),
                        message=(
                            f"Abbreviated page range '{start_str}–{end_str}' — "
                            f"APA 7 requires the full end page (likely '{start}–{expanded}')"
                        ),
                        expected=f"{start}–{expanded}",
                        actual=f"{start_str}–{end_str}",
                        excerpt=r.raw_text[excerpt_start:excerpt_end],
                    ))
                issue_count += 1

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"... and {issue_count - MAX_REPORTED} more "
                f"abbreviated page-range issues"
            ),
        ))

    return details


# ── Item 9: DOI / URL identifier presence ─────────────────────────────


def _looks_like_book_or_chapter(text: str) -> bool:
    if _BOOK_LIKE.search(text):
        return True
    return bool(_BOOK_PUBLISHER_END.search(text.strip()))


def _has_journal_pagination(text: str) -> bool:
    return (
        bool(_JOURNAL_PAGINATION.search(text))
        or bool(_ARTICLE_NUMBER.search(text))
        or bool(_SINGLE_PAGE_ARTICLE.search(text))
    )


@register(
    "reference.doi_or_url",
    "Reference",
    "Reference DOI / URL presence",
    "warning",
)
def check_doi_or_url(doc: ParsedDocument) -> list[CheckDetail]:
    """Warn when a journal-article-shaped reference lacks both a DOI/URL and
    complete ``Volume(Issue), pages`` pagination.

    AQF Item 6: "Journal references with missing information on Volume
    (Issue), [page]. If unavailable, DOI link should be provided."

    Books, edited volumes, dissertations, and similar non-article references
    are heuristically excluded because APA 7 does not require a DOI/URL
    for them.
    """
    details: list[CheckDetail] = []
    issue_count = 0

    for r in doc.references:
        if r.doi or r.urls:
            continue
        if r.parse_confidence < 0.5:
            # Skip references the parser couldn't confidently structure —
            # the no_et_al / page_number rules will surface other defects,
            # and this one would mostly produce noise.
            continue
        if _looks_like_book_or_chapter(r.raw_text):
            continue
        if _has_journal_pagination(r.raw_text):
            continue

        if issue_count < MAX_REPORTED:
            details.append(CheckDetail(
                location=f"Reference #{r.index}",
                locator=Locator(
                    kind="paragraph",
                    paragraph_index=r.paragraph_index,
                ),
                message=(
                    "Journal-article reference is missing both a DOI/URL and a "
                    "complete Volume(Issue), pages — APA 7 / ET&S require one "
                    "of the two so the work can be located"
                ),
                expected="DOI or URL, or full Volume(Issue), pages",
                actual="neither present",
                excerpt=r.raw_text[:200],
            ))
        issue_count += 1

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"... and {issue_count - MAX_REPORTED} more references "
                f"missing DOI/URL"
            ),
        ))

    return details


# ── Item 10: Same-surname-same-year disambiguation in reference list ──


@register(
    "citation.disambiguate",
    "Citation",
    "Reference suffix disambiguation (a, b, c)",
    "error",
)
def check_disambiguate(doc: ParsedDocument) -> list[CheckDetail]:
    """Detect reference-list entries that share first-author surname and year
    without the required ``a``/``b``/``c`` suffix.

    AQF Item 5 (ET&S): "Citation with similar first author last name and
    publication year was not differentiated clearly. For example in the
    reference list, there exist TWO references with first author's last name
    Smith and publication year of 2017. The citation should be differentiated
    by Smith et al., 2017a and Smith et al., 2017b."

    The complementary citation-side check ('citation.cross_reference')
    already flags citations that drop the suffix when the reference list
    has it. This rule catches the inverse: the reference list itself
    failing to assign suffixes.
    """
    details: list[CheckDetail] = []

    groups: dict[tuple[str, str], list[Reference]] = {}
    for r in doc.references:
        if not r.first_author_surname or not r.year:
            continue
        if r.parse_confidence < 0.5:
            continue
        key = (normalise_surname(r.first_author_surname), r.year)
        groups.setdefault(key, []).append(r)

    issue_count = 0
    for (norm, year), entries in groups.items():
        if len(entries) < 2:
            continue
        suffixes = [e.year_suffix or "" for e in entries]
        unsuffixed = [e for e in entries if not e.year_suffix]
        # Three group-states need flagging:
        #   1. All distinct, all present (a, b, c)        → OK, skip
        #   2. Some entries have no suffix                → flag the unsuffixed
        #   3. Suffixes collide (e.g. both "a")           → flag the duplicates
        # Distinct-and-complete is the only acceptance criterion.
        all_have_distinct = (
            all(s for s in suffixes) and len(set(suffixes)) == len(suffixes)
        )
        if all_have_distinct:
            continue

        entry_indices = ", ".join(f"#{e.index}" for e in entries)

        # State 2: bare entries get the canonical "add a year suffix" message.
        for r in unsuffixed:
            if issue_count < MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"Reference #{r.index}",
                    locator=Locator(
                        kind="paragraph",
                        paragraph_index=r.paragraph_index,
                    ),
                    message=(
                        f"Reference shares surname '{r.first_author_surname}' and "
                        f"year {year} with other entries ({entry_indices}); "
                        f"add a year suffix (e.g. {year}a / {year}b) so citations "
                        f"can disambiguate"
                    ),
                    expected=f"{year}a, {year}b, …",
                    actual=year,
                    excerpt=r.raw_text[:200],
                ))
            issue_count += 1

        # State 3: duplicate suffix (e.g. two refs both labelled "2020a") —
        # different message because adding "a more" doesn't help; the author
        # has to renumber.
        suffix_counts: dict[str, list[Reference]] = {}
        for e in entries:
            if e.year_suffix:
                suffix_counts.setdefault(e.year_suffix, []).append(e)
        for suffix_val, dup_entries in suffix_counts.items():
            if len(dup_entries) < 2:
                continue
            for r in dup_entries:
                if issue_count < MAX_REPORTED:
                    details.append(CheckDetail(
                        location=f"Reference #{r.index}",
                        locator=Locator(
                            kind="paragraph",
                            paragraph_index=r.paragraph_index,
                        ),
                        message=(
                            f"Reference duplicates the suffix '{year}{suffix_val}' "
                            f"with other entries ({entry_indices}); each entry "
                            f"sharing this surname/year must use a unique suffix"
                        ),
                        expected=f"unique {year}a, {year}b, …",
                        actual=f"{year}{suffix_val}",
                        excerpt=r.raw_text[:200],
                    ))
                issue_count += 1

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"... and {issue_count - MAX_REPORTED} more references "
                f"missing disambiguation suffix"
            ),
        ))

    return details


# ── Item 11: APA format structural check (rule-part) ───────────────────


# Year paren must be followed by ". " (period + space) per APA 7 §9. Anything
# else (",", "(", " " bare) means the author block / year boundary is wrong.
# The year token also accepts "n.d." per APA §9.16.
_YEAR_TOKEN = r"(?:(?:19|20)\d{2}[a-z]?|n\.d\.)"
_YEAR_PAREN_FOLLOWUP = re.compile(
    rf"[(（]{_YEAR_TOKEN}(?:[,;][^)）]+)?[)）]"
    r"(?P<after>.{0,3})",
)
# Sentence-terminal punctuation considered acceptable at the end of a reference.
# Period or closing paren cover virtually all valid APA endings; URLs/DOIs are
# handled separately by the doi/urls fields short-circuit at the rule level.
# CJK references end with the full-width period 。 or ideographic full-stop ．,
# which are equally valid terminators.
_TERMINAL_PUNCT = re.compile(r"[.)。．]\s*$")
# A title-shape segment after "(Year). " — at least a few words / characters
# before the next period. We're lenient: the rule fires only when the title
# slot is conspicuously empty. Allow full-width period after CJK year-parens.
_AFTER_YEAR_HAS_TITLE = re.compile(
    rf"[(（]{_YEAR_TOKEN}(?:[,;][^)）]+)?[)）][.。．]\s*\S"
)
# Minimum reasonable length for a real APA reference. Anything shorter is
# certainly malformed (a real entry is typically ≥ 60 chars).
_MIN_REF_LEN = 30


@register(
    "reference.apa_format",
    "Reference",
    "Reference APA structural format",
    "warning",
)
def check_apa_format(doc: ParsedDocument) -> list[CheckDetail]:
    """Catch obvious APA structural defects that other rules don't:
    missing period after the year paren, missing title slot, suspiciously
    short entries, and unterminated entries.

    Deeper APA validation (type-specific required fields, journal-name
    abbreviation, author-name order) is intentionally out of scope here —
    AQF Item 6's nuanced cases are deferred to the AI pass.
    """
    details: list[CheckDetail] = []
    issue_count = 0

    for r in doc.references:
        text = r.raw_text.strip()
        if not text:
            continue

        # Skip the parser-caught cases — cross_reference already reports those.
        if r.parse_confidence < 0.5:
            continue

        problems: list[str] = []

        if len(text) < _MIN_REF_LEN:
            problems.append("entry is suspiciously short for an APA reference")

        # Period must follow the year paren.  Look at the first 3 chars after
        # the closing paren of the *first* year parenthetical. Accept Latin
        # period ".", full-width period "。", or ideographic full-stop "．"
        # so CJK references (which use full-width punctuation) aren't flagged.
        m = _YEAR_PAREN_FOLLOWUP.search(text)
        if m is not None:
            after = m.group("after")
            if not after or after[0] not in (".", "。", "．"):
                problems.append(
                    "missing '.' after year (APA: 'Author. (Year). Title.')"
                )

        # Title slot after the year must be non-empty.
        if m is not None and not _AFTER_YEAR_HAS_TITLE.search(text):
            # Only complain when the year-followup also looked OK — otherwise
            # the period-missing message above already explains it.
            if not problems or "missing '.'" not in problems[-1]:
                problems.append("title is missing or empty after the year")

        # Reference should end with terminal punctuation, a closing paren, or
        # a URL/DOI character. URLs already cleared by parser strip end punct,
        # so an entry ending in a digit/letter from a DOI is also fine.
        if (
            not _TERMINAL_PUNCT.search(text)
            and not r.doi
            and not r.urls
        ):
            problems.append("entry does not end with a period")

        for problem in problems:
            if issue_count < MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"Reference #{r.index}",
                    locator=Locator(
                        kind="paragraph",
                        paragraph_index=r.paragraph_index,
                    ),
                    message=f"APA format issue: {problem}",
                    excerpt=text[:200],
                ))
            issue_count += 1

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"... and {issue_count - MAX_REPORTED} more APA format issues"
            ),
        ))

    return details


# ── Italics: journal name + volume ─────────────────────────────────────


# Period or comma followed by a journal name candidate (Title Case words),
# then a comma and a volume number — possibly with an issue in parens.
# Captures spans so we can map them to runs and check italic formatting.
#   ". Journal of Education, 12(3), 45–60."
#   ", Educational Technology, 28, 1234567."
_JOURNAL_VOLUME_SPAN = re.compile(
    r"(?P<lead>(?<=\.\s)|(?<=\?\s)|(?<=!\s))"
    r"(?P<journal>(?:[A-Z][A-Za-z'’\-&]*"
    r"(?:\s+(?:of|and|for|in|on|the|de|la|der|und)\s+|\s+&\s+|\s+))*"
    r"[A-Z][A-Za-z'’\-&]*)"
    r",\s*"
    r"(?P<volume>\d+)"
    r"(?:\s*\(\s*(?P<issue>[^)]+?)\s*\))?",
)


def _runs_covering(para: Paragraph, start: int, end: int) -> list[Run]:
    """Return the runs intersecting the [start, end) char range in para.text."""
    cursor = 0
    out = []
    for r in para.runs:
        rlen = len(r.text)
        rstart = cursor
        rend = cursor + rlen
        cursor = rend
        if rend <= start:
            continue
        if rstart >= end:
            break
        out.append(r)
    return out


@register(
    "reference.italics_journal_volume",
    "Reference",
    "Reference italics: journal name + volume",
    "warning",
)
def check_italics_journal_volume(doc: ParsedDocument) -> list[CheckDetail]:
    """Verify APA 7 §10.1 italics in journal references.

    APA 7 italicises the journal name and the volume number; the issue number
    in parentheses is **not** italicised. The check reports two failure modes:

    - journal name OR volume number is set in roman (not italic)
    - issue number (the parenthesised digits) is italicised

    Only references the parser confidently structured are checked; the runs
    backing each span are sampled and their ``italic`` attribute (resolved
    through the run-level fallback chain) drives the decision.
    """
    details: list[CheckDetail] = []
    issue_count = 0
    para_by_index = {p.index: p for p in doc.paragraphs}

    for r in doc.references:
        if r.parse_confidence < 0.5:
            continue
        para = para_by_index.get(r.paragraph_index)
        if para is None or not para.runs:
            continue
        # Reconstruct paragraph text from runs so positions line up. The
        # raw_text on Reference may have been folded across paragraphs; we
        # check italic-ness on the actual paragraph content.
        text = "".join(run.text for run in para.runs)
        if not text:
            continue

        m = _JOURNAL_VOLUME_SPAN.search(text)
        if m is None:
            continue
        # Ignore matches where the "journal" portion is implausibly short
        # (e.g. matching a stray Title Case word).
        if len(m.group("journal")) < 4:
            continue

        # Heuristic: a book reference shaped like "Title. Publisher, Year." can
        # produce a false positive. Skip when other strong book markers appear.
        if _looks_like_book_or_chapter(text):
            continue

        problems: list[str] = []
        excerpt_window = text[max(0, m.start() - 10) : min(len(text), m.end() + 10)]

        # Journal name italic check.
        j_start, j_end = m.start("journal"), m.end("journal")
        j_runs = _runs_covering(para, j_start, j_end)
        # Skip when font information is unresolved for the entire span — there
        # is nothing to assert and warning would be noise.
        j_resolvable = [run for run in j_runs if run.italic is not None]
        if j_resolvable and not all(run.italic for run in j_resolvable):
            problems.append(
                f"journal name '{m.group('journal')}' should be italic"
            )

        # Volume italic check.
        v_start, v_end = m.start("volume"), m.end("volume")
        v_runs = _runs_covering(para, v_start, v_end)
        v_resolvable = [run for run in v_runs if run.italic is not None]
        if v_resolvable and not all(run.italic for run in v_resolvable):
            problems.append(
                f"volume number '{m.group('volume')}' should be italic"
            )

        # Issue (in parens) must NOT be italic.
        if m.group("issue") is not None:
            i_start, i_end = m.start("issue"), m.end("issue")
            i_runs = _runs_covering(para, i_start, i_end)
            i_resolvable = [run for run in i_runs if run.italic is not None]
            if i_resolvable and all(run.italic for run in i_resolvable):
                problems.append(
                    f"issue number '({m.group('issue')})' must not be italic"
                )

        for problem in problems:
            if issue_count < MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"Reference #{r.index}",
                    locator=Locator(
                        kind="paragraph",
                        paragraph_index=r.paragraph_index,
                    ),
                    message=f"APA italics: {problem}",
                    expected="journal + volume italic; issue number roman",
                    actual=problem,
                    excerpt=excerpt_window.strip(),
                ))
            issue_count += 1

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"... and {issue_count - MAX_REPORTED} more italics issues "
                f"in references"
            ),
        ))

    return details


# ── URL / DOI terminal punctuation ─────────────────────────────────────


# Match a DOI/URL ending followed by a period (possibly preceded by a closing
# bracket or quote). APA 7 §9.36: do not place a period after a DOI or URL.
_URL_TRAILING_DOT = re.compile(
    r"(https?://\S*?[^\s.,;:'\"”’\]\)])"
    r"\s*\.\s*$",
)
_DOI_TRAILING_DOT = re.compile(
    r"(\bdoi:\s*\S*?[^\s.,;:'\"”’\]\)])\s*\.\s*$",
    re.IGNORECASE,
)


@register(
    "reference.url_terminal_punctuation",
    "Reference",
    "DOI/URL must not end with a period",
    "warning",
)
def check_url_terminal_punctuation(doc: ParsedDocument) -> list[CheckDetail]:
    """APA 7 §9.36: a reference ending in a DOI or URL takes no terminal
    period because the dot is easy to mistake for part of the link.
    """
    details: list[CheckDetail] = []
    issue_count = 0

    for r in doc.references:
        text = r.raw_text.rstrip()
        if not text:
            continue
        if not (r.doi or r.urls):
            continue
        if not text.endswith("."):
            continue
        # Only flag when the trailing period directly abuts the link, not
        # when there's intervening punctuation/text.
        m = _URL_TRAILING_DOT.search(text)
        m_doi = _DOI_TRAILING_DOT.search(text)
        if m is None and m_doi is None:
            continue

        excerpt = text[-80:]
        if issue_count < MAX_REPORTED:
            details.append(CheckDetail(
                location=f"Reference #{r.index}",
                locator=Locator(
                    kind="paragraph",
                    paragraph_index=r.paragraph_index,
                ),
                message=(
                    "Reference ends with a period after the DOI/URL — APA 7 "
                    "§9.36: omit the terminal period (it can be misread as "
                    "part of the link)"
                ),
                expected="no period after DOI/URL",
                actual="trailing period",
                excerpt=excerpt,
            ))
        issue_count += 1

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"... and {issue_count - MAX_REPORTED} more references with "
                f"a stray period after the DOI/URL"
            ),
        ))

    return details


# ── Author-list rules (APA 7 §9.8) ─────────────────────────────────────


_ELLIPSIS_TOKEN = re.compile(r"(?:\.\s*\.\s*\.\s*\.|…|\.\s*\.\s*\.)")


def _author_block(raw_text: str) -> str:
    """Return everything before the year-paren, which is the author block.
    Falls back to the first 200 characters when no year-paren is found."""
    m = re.search(r"\(\s*(?:(?:19|20)\d{2}|n\.d\.)", raw_text)
    if m is None:
        return raw_text[:200]
    return raw_text[: m.start()]


@register(
    "reference.author_count_rule",
    "Reference",
    "Author-list APA 7 §9.8 (≤ 20 list all; 21+ uses ellipsis + last)",
    "warning",
)
def check_author_count_rule(doc: ParsedDocument) -> list[CheckDetail]:
    """Detect the two failure modes of APA 7 §9.8:

    1. A reference with > 20 authors that uses ``...`` truncation as if it
       had only 20 — the parser would still split this short, but the raw
       text marker (``...`` / ``…``) reveals the omission.
    2. A reference with ≥ 21 authors but no ``...`` marker — the author list
       is meant to elide authors 20 to N-1; without the marker, the entry
       silently truncates whatever Word will fit.

    Because counting authors precisely requires the same parsing the rest of
    the rule set already performs, we lean on the existing ``author_count``
    field plus the presence/absence of an ellipsis marker.
    """
    details: list[CheckDetail] = []
    issue_count = 0
    threshold_ellipsis = P.AUTHOR_LIST_ELLIPSIS_THRESHOLD
    # Mode A is intentionally conservative: a *correctly* formatted 21+
    # author reference (first 19 + ellipsis + last) shows ~20 visible
    # author chunks to the parser, indistinguishable from a wrongly-
    # truncated 20-author list. Only flag when the visible chunk count
    # is clearly far below 19 — that's unambiguous truncation. A few
    # legitimate truncations in the 15-19 range will be missed; that's
    # the cost of avoiding noise on every correct 21+-author entry.
    obvious_truncation_max = P.AUTHOR_LIST_ELLIPSIS_KEEP - 5  # = 14

    for r in doc.references:
        if r.parse_confidence < 0.5:
            continue
        if r.author_count is None:
            continue
        author_block = _author_block(r.raw_text)
        has_ellipsis = bool(_ELLIPSIS_TOKEN.search(author_block))
        n = r.author_count

        # Mode A: very few visible authors but author block contains "..." —
        # the writer truncated mid-list when APA requires listing everyone.
        if n <= obvious_truncation_max and has_ellipsis:
            if issue_count < MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"Reference #{r.index}",
                    locator=Locator(
                        kind="paragraph",
                        paragraph_index=r.paragraph_index,
                    ),
                    message=(
                        f"Only {n} visible author(s) but the list uses '...' — "
                        f"APA 7 §9.8 reserves the ellipsis for ≥ "
                        f"{threshold_ellipsis}-author papers (first 19 + ... + "
                        f"final author); for shorter lists, list every author"
                    ),
                    expected=f"all {n} authors listed",
                    actual="author list contains '...'",
                    excerpt=author_block.strip()[:200],
                ))
            issue_count += 1
            continue

        # Mode B: ≥ 21 authors but no ellipsis — the list either truncates
        # silently or actually contains all 21+ authors. APA 7 §9.8 mandates
        # the ``first 19, ..., last`` shape; flag either case.
        if n >= threshold_ellipsis and not has_ellipsis:
            if issue_count < MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"Reference #{r.index}",
                    locator=Locator(
                        kind="paragraph",
                        paragraph_index=r.paragraph_index,
                    ),
                    message=(
                        f"Reference has {n} author(s) but lacks the APA 7 §9.8 "
                        f"ellipsis form — list the first "
                        f"{P.AUTHOR_LIST_ELLIPSIS_KEEP} authors, then '...', "
                        f"then the final author"
                    ),
                    expected=(
                        f"first {P.AUTHOR_LIST_ELLIPSIS_KEEP} authors, ..., "
                        f"final author"
                    ),
                    actual=f"{n} authors listed without ellipsis",
                    excerpt=author_block.strip()[:200],
                ))
            issue_count += 1

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"... and {issue_count - MAX_REPORTED} more author-count "
                f"issues"
            ),
        ))

    return details
