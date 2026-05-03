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
_TAIL_PUNCT = re.compile("[.,;\\]" + _Q + "]+$")
# Recovers a DOI/URL that Word split across lines by inserting a space.
# Matches whitespace + a continuation that starts with lowercase/digit/underscore/(.
# The negative lookahead prevents extending into a new https?:// URL.
_CONT = re.compile(r'[\s ]+(?!https?://)([0-9_(]\S*)')


def _strip_unbalanced_trailing_parens(s: str) -> str:
    while s.endswith(")") and s.count(")") > s.count("("):
        s = s[:-1]
    return s


def _clean(s: str) -> str:
    s = _TAIL_PUNCT.sub("", s)
    return _strip_unbalanced_trailing_parens(s)


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

# Leading author-list markers used in meta-analyses to flag included studies
# (asterisk, dagger, double-dagger). Stripped before surname parsing so
# "*Xu, Y., …" parses the same as "Xu, Y., …". Accepts one or more markers
# so "**Smith" / "*†Smith" also parse cleanly.
_LEADING_MARKER = re.compile(r"^[\*†‡]+\s*")

# Matches the explanatory note that prefaces an asterisk-marked reference list
# in meta-analysis papers, e.g. "References marked with an asterisk (*)
# indicate studies included in the meta-analysis." It looks like a paragraph
# in the References section but is metadata, not a citation.
_REF_NOTE_PREFIX = re.compile(
    r"^\s*References?\s+marked\s+with\b",
    re.IGNORECASE,
)

# Matches "Appendix" / "Appendices" used as a section/caption heading at
# paragraph start. The references parser stops here so the appendix caption
# (which is not styled as a heading) doesn't get pulled in as a reference.
# Hyphen is allowed so captions like "Appendix B. Characteristics … meta-
# analysis" still match.
_APPENDIX_HEADING = re.compile(
    r"^\s*(?:Appendix|Appendices|附錄)\b[\s.:：A-Za-z0-9\-]{0,80}$",
    re.IGNORECASE,
)

_GENERATIONAL_SUFFIX = re.compile(r",?\s*(?:Jr|Sr|III?|IV|V)\.", re.IGNORECASE)

# Detects APA initial groups: ", X." or ", X. Y." or ", X.-Y."
_HAS_INITIALS = re.compile(r",\s*[A-Z]\.")

# Matches " & " used as an APA author separator — requires surrounding
# whitespace (or preceding period) to distinguish from "&" embedded in an
# institutional name (e.g. "Science & Technology").
_APA_AMPERSAND = re.compile(r"(?:\.|,)\s*&\s+")


def _count_authors(author_text: str) -> int | None:
    """Estimate author count from an APA reference author block.

    Each author contributes a "Surname, X." or "Surname, X. Y." block.
    Blocks are separated by "., " (period + comma + space).
    """
    if not author_text or not author_text.strip():
        return None

    cleaned = re.sub(r"\(Eds?\.\)", "", author_text)
    cleaned = _GENERATIONAL_SUFFIX.sub("", cleaned).strip()

    # Primary strategy: split on ". ," boundary between author blocks.
    parts = re.split(r"\.\s*,\s*", cleaned)
    parts = [p for p in parts if p.strip()]
    if not parts:
        return None

    has_initials = any(re.search(r"[A-Z]\.", p) for p in parts)
    if has_initials:
        return len(parts)

    # No initials found — likely institutional / CJK authors.
    # Use APA-style ampersand (requires preceding period/comma + space around &)
    # to distinguish author separators from "&" within organisation names.
    if _APA_AMPERSAND.search(author_text):
        return _APA_AMPERSAND.split(author_text).__len__()

    # Standalone "&" / "and" — only count if the text also contains a comma that
    # looks like an author separator (to avoid miscounting "Science & Technology").
    if ("&" in author_text or " and " in author_text.lower()) and _HAS_INITIALS.search(author_text):
        separators = len(re.findall(r"&|\band\b", author_text, re.IGNORECASE))
        return separators + 1

    # CJK enumeration comma separator
    if "、" in author_text:
        cjk_parts = author_text.split("、")
        return len([p for p in cjk_parts if p.strip()])

    # Chinese full-width comma separator (e.g. "王小明，李大明")
    if "，" in author_text and _CJK_CHAR_RE.search(author_text):
        cjk_parts = re.split(r"[，、]", author_text)
        return len([p for p in cjk_parts if p.strip()])

    return 1

REF_FIRST_AUTHOR = re.compile(
    r"^(?P<surname>[^\W\d_][\w\-' ]*?)\.?\s*(?:[,.]|$)",
    re.UNICODE,
)

_CJK_CHAR_RE = re.compile(
    "[一-鿿㐀-䶿豈-﫿\U00020000-\U0002A6DF\U0002A700-\U000323AF]"
)

# Strip pattern for author-key normalisation: whitespace, hyphens, apostrophes,
# and dots. Mirrors rules.citation.normalise_surname so author keys compare on
# the same basis a citation surname is matched against.
_AUTHOR_KEY_STRIP = re.compile(
    r"[\s\-'." + chr(0x2018) + chr(0x2019) + r"]"
)


def _normalise_for_sort(s: str) -> str:
    """Lowercase + strip diacritics + drop separators (whitespace, hyphens,
    apostrophes, dots) for stable cross-locale ordering."""
    import unicodedata as _ud
    s = _ud.normalize("NFD", s)
    s = "".join(c for c in s if _ud.category(c) != "Mn")
    s = s.replace("ı", "i").lower()
    return _AUTHOR_KEY_STRIP.sub("", s)


def _split_authors(author_text: str) -> list[str]:
    """Split an APA author block into individual "Surname, Initials" parts.

    Handles three common APA layouts:
      - Two authors:    "Smith, J., & Jones, K."
      - Three+ authors: "Smith, J., Jones, K., & Taylor, L."
      - One author:     "Smith, J."
    The trailing " & " before the last author is normalised to ", " so a
    single split-on-".," gives consistent parts.
    """
    if not author_text or not author_text.strip():
        return []
    cleaned = re.sub(r"\(Eds?\.\)", "", author_text)
    cleaned = _GENERATIONAL_SUFFIX.sub("", cleaned).strip()
    # Normalise the final " & "/" and " separator so it splits like the others.
    cleaned = re.sub(r"\s*,?\s*&\s+", ", ", cleaned)
    cleaned = re.sub(r"\s*,?\s+and\s+", ", ", cleaned, flags=re.IGNORECASE)
    parts = re.split(r"\.\s*,\s*", cleaned)
    return [p.strip().rstrip(".").strip() for p in parts if p.strip()]


_AUTHOR_KEY_SEP = "\x01"


def _author_to_sort_key(author: str) -> str | None:
    """Convert one "Surname, X. Y." chunk into a normalised "<surname><SEP><initials>"
    sort token. Returns None if the chunk doesn't look like an APA author.

    The separator is U+0001 (Start Of Heading) — chosen because it sorts
    *before* every letter, so a surname-initials key like "tu\\x01x" sorts
    before "tulli\\x01s" (the right APA order: Tu, X. before Tulli, S.).
    A printable separator like '|' would break that since '|' (0x7C) is
    greater than every lowercase letter."""
    if not author:
        return None
    # Surname is everything before the first comma; initials follow.
    if "," in author:
        surname, rest = author.split(",", 1)
    else:
        # Institutional / single-token author with no initials.
        surname, rest = author, ""
    surname_norm = _normalise_for_sort(surname)
    initials_norm = _normalise_for_sort(rest)
    if not surname_norm:
        return None
    return f"{surname_norm}{_AUTHOR_KEY_SEP}{initials_norm}"


def _build_author_sort_keys(author_text: str) -> list[str]:
    """Return one normalised sort token per author in the block."""
    keys: list[str] = []
    for chunk in _split_authors(author_text):
        key = _author_to_sort_key(chunk)
        if key is not None:
            keys.append(key)
    return keys


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

    ref_paragraphs: list[Paragraph] = []
    for p in paragraphs:
        if p.index <= ref_section_idx:
            continue
        if next_section_idx is not None and p.index >= next_section_idx:
            break
        if p.is_in_table:
            continue
        text = p.text.strip()
        if not text:
            continue
        # Stop at an Appendix caption — even if it isn't styled as a heading,
        # the bibliography ends here. This prevents the Appendix title and
        # any free text before its (in-table) body from being mis-parsed as
        # references.
        if _APPENDIX_HEADING.match(text):
            break
        # Skip the asterisk-explainer note that prefaces some meta-analysis
        # bibliographies; it's metadata, not a reference.
        if _REF_NOTE_PREFIX.match(text):
            continue
        ref_paragraphs.append(p)

    results: list[Reference] = []
    for idx, p in enumerate(ref_paragraphs):
        raw = p.text.strip()
        # Strip leading meta-analysis marker (* / † / ‡) so the surname is
        # parsed from the actual author text. We keep the original raw text
        # in the reference so the rule output still shows the marker.
        marker_match = _LEADING_MARKER.match(raw)
        parse_text = raw[marker_match.end():] if marker_match else raw
        m = REF_AUTHOR_YEAR.match(parse_text)
        year: str | None = None
        year_suffix: str | None = None
        first_author: str | None = None
        confidence = 0.2

        author_count: int | None = None
        author_sort_keys: list[str] = []

        if m:
            year = m.group("year")
            year_suffix = m.group("suffix")
            # Normalize smart apostrophes (U+2018/U+2019) → ASCII ' so
            # REF_FIRST_AUTHOR can match institutional names like
            # "State Council of the People's Republic of China"
            author_text = m.group("authors").strip().replace('‘', "'").replace('’', "'")
            author_count = _count_authors(author_text)
            author_sort_keys = _build_author_sort_keys(author_text)
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
            author_count=author_count,
            author_sort_keys=author_sort_keys,
        ))

    return results
