from __future__ import annotations

import re

from ets_checker.models import Paragraph, Reference, Section
from ets_checker.parser.sections import is_reference_title

# All ASCII and Unicode smart-quote variants (built with chr() to avoid embedding
# literal quote chars that editors/tools can silently convert to smart-quote variants).
# chr(0x22)=", chr(0x27)=', chr(0x201C)=left-", chr(0x201D)=right-",
# chr(0x2018)=left-', chr(0x2019)=right-'
_Q = chr(0x22) + chr(0x27) + chr(0x201C) + chr(0x201D) + chr(0x2018) + chr(0x2019)

# URL/DOI character class: stops at whitespace, comma, and any quote variant.
# Closing paren ) is intentionally NOT excluded — some DOIs contain parens in their
# path (e.g. ETS journal: 10.30191/ETS.202501_28(1).RP02). _clean() strips any
# trailing ) that belongs to surrounding reference text rather than the URL itself.
_URL_CHARS = "[^\\s," + _Q + "]+"

# DOI from full URL form: https://doi.org/10.XXXX/... or http://dx.doi.org/...
_DOI_URL = re.compile(
    r"https?://(?:dx\.)?doi\.org/(10\.\d{4,}/" + _URL_CHARS + ")",
    re.IGNORECASE,
)
# DOI from prefix form: doi:10.XXXX/...
_DOI_PREFIX = re.compile(
    r"\bdoi:\s*(10\.\d{4,}/" + _URL_CHARS + ")",
    re.IGNORECASE,
)
# Non-DOI URLs
_URL_NONDOI = re.compile(
    r"https?://(?!(?:dx\.)?doi\.org/)" + _URL_CHARS,
    re.IGNORECASE,
)
# Strip trailing punctuation that is part of surrounding reference text, not the
# URL/DOI itself. \] in the string concatenation becomes \] in the pattern,
# which is the escape for ] inside a regex character class.
_TAIL_PUNCT = re.compile("[.,;)\\]" + _Q + "]+$")
# Recovers a DOI/URL that Word split across lines by inserting a space.
# Matches whitespace + a continuation that starts with lowercase/digit/underscore/(.
# The negative lookahead prevents extending into a new https?:// URL.
_CONT = re.compile(r'[\s ]+(?!https?://)([a-z0-9_(]\S*)')


def _clean(s: str) -> str:
    return _TAIL_PUNCT.sub("", s)


def _doi_join(fragment: str, rest: str) -> str:
    """Attempt one line-wrap recovery: if rest starts with a continuation
    token (lowercase/digit/underscore — not a capital or new URL), append it.
    Word sometimes inserts a space when wrapping a long DOI across lines."""
    cont = _CONT.match(rest)
    if cont:
        fragment += cont.group(1)
    return _clean(fragment)


REF_AUTHOR_YEAR = re.compile(
    r"^(?P<authors>.+?)\s*[(（](?P<year>(?:19|20)\d{2}|n\.d\.)(?P<suffix>[a-z])?(?:[,;][^)）]+)?[)）]",
    re.UNICODE,
)

REF_FIRST_AUTHOR = re.compile(
    r"^(?P<surname>[^\W\d_][\w\-' ]*?)\.?\s*(?:,|$)",
    re.UNICODE,
)


def extract(
    paragraphs: list[Paragraph],
    sections: list[Section],
) -> list[Reference]:
    ref_section_idx: int | None = None
    next_section_idx: int | None = None

    for i, s in enumerate(sections):
        if is_reference_title(s.title):
            ref_section_idx = s.paragraph_index
            for j in range(i + 1, len(sections)):
                if sections[j].level == 1:
                    next_section_idx = sections[j].paragraph_index
                    break
            break

    if ref_section_idx is None:
        return []

    ref_paragraphs = [
        p for p in paragraphs
        if p.index > ref_section_idx
        and (next_section_idx is None or p.index < next_section_idx)
        and not p.is_in_table
        and p.text.strip()
    ]

    results: list[Reference] = []
    for idx, p in enumerate(ref_paragraphs):
        raw = p.text.strip()
        m = REF_AUTHOR_YEAR.match(raw)
        year: str | None = None
        year_suffix: str | None = None
        first_author: str | None = None
        confidence = 0.2

        if m:
            year = m.group("year")
            year_suffix = m.group("suffix")
            # Normalize smart apostrophes (U+2018/U+2019) → ASCII ' so
            # REF_FIRST_AUTHOR can match institutional names like
            # "State Council of the People's Republic of China"
            author_text = m.group("authors").strip().replace('‘', "'").replace('’', "'")
            am = REF_FIRST_AUTHOR.match(author_text)
            if am:
                first_author = am.group("surname").strip()
                # Strip a trailing single uppercase initial that gets absorbed when
                # APA comma is missing, e.g. "Wannes M., ..." → "Wannes M" → "Wannes"
                first_author = re.sub(r"\s+[A-Z]$", "", first_author).strip()
                confidence = 1.0
            else:
                confidence = 0.5
        else:
            year_match = re.search(r"[(（](?P<y>(?:19|20)\d{2})(?P<s>[a-z])?[)）]", raw)
            if year_match:
                year = year_match.group("y")
                year_suffix = year_match.group("s")
                confidence = 0.5

        # Extract DOI, recovering any line-wrap space Word may have inserted
        doi: str | None = None
        m_doi = _DOI_URL.search(raw)
        if m_doi:
            doi = _doi_join(m_doi.group(1), raw[m_doi.end():])
        else:
            m_doi2 = _DOI_PREFIX.search(raw)
            if m_doi2:
                doi = _doi_join(m_doi2.group(1), raw[m_doi2.end():])

        # Extract non-DOI URLs
        urls: list[str] = []
        for m_url in _URL_NONDOI.finditer(raw):
            u = _clean(m_url.group(0))
            if u:
                urls.append(u)

        results.append(Reference(
            index=idx + 1,
            raw_text=raw,
            first_author_surname=first_author,
            year=year,
            year_suffix=year_suffix,
            parse_confidence=confidence,
            paragraph_index=p.index,
            doi=doi,
            urls=urls,
        ))

    return results
