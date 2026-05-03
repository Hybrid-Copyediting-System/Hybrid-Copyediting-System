from __future__ import annotations

import re

from ets_checker.models import Citation, Paragraph, Section
from ets_checker.parser.sections import is_reference_title

CITATION_PAREN = re.compile(
    r"[\(（](?:(?:see|e\.g\.,?|cf\.)\s+)?(?P<body>[^()（）]+)[\)）]",
    re.UNICODE,
)

PER_CITE = re.compile(
    r"(?P<authors>.+?),?\s*(?P<year>(?:19|20)\d{2}|n\.d\.)(?!\d)(?P<suffix>[a-z])?"
    r"(?:,\s*pp?\.\s*[\d\-–,\s]+)?",
    re.UNICODE,
)

# Author token: ASCII surname (capitalised) or a short CJK run. The CJK
# branch has a negative lookbehind so we don't slurp Chinese prefix text
# (e.g. "研究參考王小明") into the surname — a CJK author must be preceded
# by a delimiter (BOS, whitespace, or punctuation), not by another letter.
# Include U+2019 (RIGHT SINGLE QUOTATION MARK) used by Word smart-quotes
# so possessives like "Vygotsky’s" are captured as a single token.
_LATIN_EXT_UPPER = "ĀĆČĎĐĒĖĘĚĞĠĢĪİĶĹĻĽŁŃŅŇŌŐŒŔŘŚŞŠŢŤŪŮŰŲŸŹŻŽ"
# Comprehensive CJK ranges shared with structure.py and references.py:
# Unified (U+4E00-U+9FFF), Extension A (U+3400-U+4DBF),
# Compatibility Ideographs (U+F900-U+FAFF), Extension B (U+20000-U+2A6DF),
# Extensions C-H (U+2A700-U+323AF).
_CJK = (
    "一-鿿"
    "㐀-䶿"
    "豈-﫿"
    "\U00020000-\U0002A6DF"
    "\U0002A700-\U000323AF"
)
_NAME = (
    r"(?:[A-ZÀ-ÖØ-Þ" + _LATIN_EXT_UPPER + r"][\w\-’’]*"
    + r"|(?<![" + _CJK + r"\w])[" + _CJK + r"]{1,6}?)"
)

CITATION_NARRATIVE = re.compile(
    r"(?P<authors>"
    rf"{_NAME}"
    rf"(?:\s*[,、]\s*{_NAME})*"
    rf"(?:\s*[,、]?\s*(?:and|&|與|及)\s*{_NAME})?"
    r"(?:\s+et\s+al\.|\s*等)?"
    r")\s*"
    r"[\(（](?P<year>(?:19|20)\d{2}|n\.d\.)(?P<suffix>[a-z])?[\)）]",
    re.UNICODE,
)

# "Surname, A. B." — drop the initials so the surname/initial comma is
# not mistaken for an author separator and the surname stays intact
# (including multi-word surnames like "Van Damme").
_INITIALS_AFTER_COMMA = re.compile(r",\s*[A-Z]\.(?:\s*[A-Z]\.)*")
_ET_AL_PATTERN = re.compile(r"\bet\s+al\.?|\s*等\s*$", re.IGNORECASE)
_AUTHOR_SPLIT = re.compile(r"[,&、]|\band\b|\s*[與及]\s*")
# Possessive suffixes added by Word smart-quotes ("’s" / "’s")
_POSSESSIVE = re.compile(r"[‘’]s?$")
# Double quotes (straight or curly) inside an author token mean prose was
# accidentally captured by the citation regex — e.g. the body of
# `(termed "AI guilt" by Chan, 2025)`. Single quotes are NOT rejected:
# legitimate surnames like "O'Brien" contain apostrophes.
_PROSE_QUOTES = re.compile(r"[\"“”]")

# Body of a parenthetical that is a pure list of years, e.g. "2018, 2023",
# "2018a, 2018b", or even a single "2018". Used to detect "(year[-list])"
# parens that may belong to a preceding narrative author block —
# "Bediou et al., (2018, 2023)" or "Bediou et al., (2018)".
_YEAR_ONLY_BODY = re.compile(
    r"^\s*(?:19|20)\d{2}[a-z]?(?:\s*,\s*(?:19|20)\d{2}[a-z]?)*\s*$"
)
_YEAR_TOKEN = re.compile(r"((?:19|20)\d{2})([a-z]?)")
# Trailing narrative-author block immediately before "(": one or more capitalised
# tokens (with optional CJK), an optional "et al.", and an optional comma. Used
# to recover the author when the year-list paren has none of its own.
_NARRATIVE_TRAILER = re.compile(
    rf"((?:{_NAME})(?:\s*[,、]\s*{_NAME})*"
    rf"(?:\s*[,、]?\s*(?:and|&|與|及)\s*{_NAME})?"
    r"(?:\s+et\s+al\.|\s*等)?)\s*,?\s*$",
    re.UNICODE,
)

# Common English discourse markers that can appear before a narrative citation
# (e.g. "Similarly, Smith (2023)") — these are never author surnames.
_DISCOURSE_MARKERS = frozenset({
    "also", "accordingly", "additionally", "comparably", "consequently",
    "conversely", "finally", "furthermore", "generally", "hence",
    "however", "importantly", "interestingly", "likewise", "meanwhile",
    "moreover", "notably", "overall", "particularly", "similarly",
    "specifically", "subsequently", "therefore", "thus",
})


def _normalise_authors(text: str) -> tuple[list[str], bool]:
    has_et_al = bool(_ET_AL_PATTERN.search(text))
    cleaned = _ET_AL_PATTERN.sub("", text).strip()
    cleaned = _INITIALS_AFTER_COMMA.sub("", cleaned)
    parts = _AUTHOR_SPLIT.split(cleaned)
    authors = [_POSSESSIVE.sub("", p.strip()).rstrip(".").lower()
               for p in parts if p.strip()]
    return authors, has_et_al


def _is_prose_contaminated(author_text: str) -> bool:
    """Author text captured from a parenthetical aside like
    `(termed "AI guilt" by Chan, 2025)` contains double quotes that no
    legitimate APA author block would carry. Detected by the call site so
    contaminated matches can be *skipped* (not fall back to the previous
    citation's authors, which would silently mis-attribute the year)."""
    return bool(_PROSE_QUOTES.search(author_text))


def _compute_reference_bounds(
    sections: list[Section],
) -> tuple[int | None, int | None]:
    for i, s in enumerate(sections):
        if is_reference_title(s.title):
            ref_start = s.paragraph_index
            next_start = None
            for j in range(i + 1, len(sections)):
                if sections[j].level == 1:
                    next_start = sections[j].paragraph_index
                    break
            return ref_start, next_start
    return None, None


def extract(
    paragraphs: list[Paragraph],
    sections: list[Section],
) -> list[Citation]:
    results: list[Citation] = []

    ref_start, ref_end = _compute_reference_bounds(sections)

    for p in paragraphs:
        if ref_start is not None and p.index >= ref_start:
            if ref_end is None or p.index < ref_end:
                continue

        # Parenthetical
        for m in CITATION_PAREN.finditer(p.text):
            body = m.group("body")
            if not re.search(r"(?:19|20)\d{2}|n\.d\.", body):
                continue

            # Year-only body: may belong to a narrative author block sitting
            # immediately before the paren. Recover the author and emit one
            # citation per year so "Bediou et al., (2018, 2023)" yields both
            # bediou+2018 and bediou+2023 instead of being lost or producing
            # a phantom "year-as-author" citation.
            #
            # Strong-trailer guard: only accept when the recovered author block
            # unambiguously identifies a real citation source — it ends in
            # "et al." OR includes a co-author conjunction (≥2 authors), OR the
            # body is a multi-year list (single names + multi-year + paren is
            # implausible outside of citations). This rules out sentence
            # starters like "Sometimes, (2020) was a pivotal year." that
            # would otherwise be picked up as a citation by the trailer regex.
            if _YEAR_ONLY_BODY.match(body):
                trailer = _NARRATIVE_TRAILER.search(p.text[:m.start()])
                if trailer and not _is_prose_contaminated(trailer.group(1)):
                    t_authors, t_et_al = _normalise_authors(trailer.group(1))
                    while t_authors and t_authors[0] in _DISCOURSE_MARKERS:
                        t_authors = t_authors[1:]
                    is_strong = t_et_al or len(t_authors) >= 2
                    is_multi_year = len(_YEAR_TOKEN.findall(body)) >= 2
                    if t_authors and (is_strong or is_multi_year):
                        for ym in _YEAR_TOKEN.finditer(body):
                            year = ym.group(1)
                            suffix = ym.group(2) or None
                            results.append(Citation(
                                raw_text=f"{trailer.group(1).strip().rstrip(',')}, {year}{suffix or ''}",
                                authors=t_authors,
                                year=year,
                                year_suffix=suffix,
                                has_et_al=t_et_al,
                                citation_type="narrative",
                                paragraph_index=p.index,
                            ))
                        continue
            # Split compound citations ("Smith, 2020; Jones, 2021") on
            # semicolons before applying PER_CITE so the delimiter never
            # bleeds into the next citation's author token.
            for segment in re.split(r"\s*[;；]\s*", body):
                last_authors: list[str] = []
                last_has_et_al = False
                last_raw_author_text = ""
                for cm in PER_CITE.finditer(segment):
                    raw_authors = cm.group("authors")
                    # Skip prose-contaminated matches outright. Falling back
                    # to last_authors here would attribute the year to a
                    # citation that the user never wrote — e.g. in
                    # `(Smith, 2020, termed "X" by Chan, 2025)` the second
                    # match would otherwise emit a phantom Smith/2025.
                    if _is_prose_contaminated(raw_authors):
                        continue
                    authors, has_et_al = _normalise_authors(raw_authors)
                    # Reject author tokens that contain no letters (pure
                    # digits/punctuation): these come from year-only lists
                    # like "(2018, 2023)" where lazy matching grabs an
                    # earlier year as the "author". Without this filter, the
                    # citation parser produces a phantom citation whose
                    # surname is a year.
                    authors = [a for a in authors if re.search(r"[^\W\d_]", a, re.UNICODE)]
                    if not authors and last_authors:
                        authors = last_authors
                        has_et_al = last_has_et_al
                        suffix = cm.group("suffix")
                        year = cm.group("year")
                        raw = f"{last_raw_author_text}, {year}{suffix or ''}"
                    elif not authors:
                        # No usable authors and no preceding citation in this
                        # segment to inherit from — skip.
                        continue
                    else:
                        last_authors = authors
                        last_has_et_al = has_et_al
                        last_raw_author_text = cm.group("authors").strip().rstrip(",")
                        suffix = cm.group("suffix")
                        year = cm.group("year")
                        raw = cm.group(0).strip().rstrip(",")
                    results.append(Citation(
                        raw_text=raw,
                        authors=authors,
                        year=year,
                        year_suffix=suffix,
                        has_et_al=has_et_al,
                        citation_type="parenthetical",
                        paragraph_index=p.index,
                    ))

        # Narrative
        for m in CITATION_NARRATIVE.finditer(p.text):
            raw_authors = m.group("authors")
            if _is_prose_contaminated(raw_authors):
                continue
            authors, has_et_al = _normalise_authors(raw_authors)
            # Strip leading discourse markers (e.g. "Similarly, Smith (2023)")
            while authors and authors[0] in _DISCOURSE_MARKERS:
                authors = authors[1:]
            if not authors:
                continue
            results.append(Citation(
                raw_text=m.group(0),
                authors=authors,
                year=m.group("year"),
                year_suffix=m.group("suffix"),
                has_et_al=has_et_al,
                citation_type="narrative",
                paragraph_index=p.index,
            ))

    # Dedup citations that were captured by both the narrative regex and the
    # year-only-paren trailer branch (e.g. "Smith and Jones (2020)" — the
    # narrative regex matches the bare paren and the trailer branch matches
    # the same paren via lookback). Keys are by (paragraph, normalised
    # authors, year, suffix) so duplicate text in the same paragraph is
    # collapsed but the same citation in different paragraphs stays distinct.
    seen: set[tuple[int, tuple[str, ...], str, str]] = set()
    deduped: list[Citation] = []
    for c in results:
        key = (c.paragraph_index, tuple(c.authors), c.year, c.year_suffix or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    return deduped
