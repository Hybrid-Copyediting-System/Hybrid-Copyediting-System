"""Quotation-related rules.

Implements:

* ``quotation.pagination`` (AQF Item 4): direct quotations need a page (or
  paragraph/section) locator on the accompanying citation.

* ``quotation.block_format`` (APA 7 §8.27): quoted text running 40 words or
  more must be set as a block quote (indented, no surrounding quotation
  marks). The complement is also flagged: an indented paragraph that quotes
  fewer than 40 words is over-formatted.
"""

from __future__ import annotations

import re

from ets_checker import ets_profile as P
from ets_checker.models import CheckDetail, Locator, Paragraph, ParsedDocument
from ets_checker.parser.sections import is_reference_title
from ets_checker.rules.runner import register

MAX_REPORTED = 20

# Direct-quotation span. Both straight and curly forms; curly forms are
# directional so the pair must match. We require ≥ 12 chars inside to skip
# scare quotes like "modern" or "AI" — those don't trigger AQF Item 4.
_DOUBLE_QUOTE = re.compile(r'"([^"]{12,}?)"', re.DOTALL)
_CURLY_DOUBLE = re.compile(r'“([^”]{12,}?)”', re.DOTALL)

# Page or other locator indicator anywhere in the surrounding window.
# APA 7 §8.13 accepts: p./pp., Section, para., Chapter, ¶, paragraph N.
_PAGE_INDICATOR = re.compile(
    r"\bpp?\.\s*\d"
    r"|\bSection\s+\d"
    r"|\bChapter\s+\d"
    r"|\bpara\.\s*\d"
    r"|\bparagraph\s+\d"
    r"|¶\s*\d",
    re.IGNORECASE,
)

# Citation-like pattern in the surrounding window — at least one author + year.
# Used as a "the writer attributed this quote" signal; without it we don't
# flag (the quoted text might be the author's own emphasis or a scare quote).
_CITATION_LIKE = re.compile(
    r"\(\s*[^()]+?(?:19|20)\d{2}[a-z]?[^()]*\)"
    r"|[A-Z][\w\-]+(?:\s+(?:and|&)\s+[A-Z][\w\-]+)?"
    r"(?:\s+et\s+al\.)?\s*\((?:19|20)\d{2}[a-z]?\)"
)

# Markers that immediately precede a coined term in quotes — APA 7 treats
# these as terminology references, not direct quotations, so they don't
# need a page locator. Matched against the text directly before the quote.
_COINED_TERM_MARKER = re.compile(
    r"(?:\b(?:termed|called|labeled|labelled|named|dubbed|coined|"
    r"known\s+as|referred\s+to\s+as|defined\s+as|the\s+term|"
    r"the\s+concept\s+of|the\s+notion\s+of|the\s+idea\s+of)\s*)$",
    re.IGNORECASE,
)

# Short quotes (≤ 3 words) preceded by a determiner are typically a coined
# term being introduced, not a direct quotation. APA 7 §6.7 lets authors
# put quotation marks around a key term on first use without requiring a
# page locator. Without this guard, sociological terms like
# `the "feeling rules" (Hochschild, 1983)` and `this "third place"` are
# flagged as missing-page-locator quotes.
_DETERMINER_BEFORE = re.compile(
    r"\b(?:the|a|an|this|these|those|such|some|any|one|every)\s+$",
    re.IGNORECASE,
)
_TERM_QUOTE_MAX_WORDS = 3

WINDOW_BEFORE = 80
WINDOW_AFTER = 120


def _quote_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for pat in (_DOUBLE_QUOTE, _CURLY_DOUBLE):
        for m in pat.finditer(text):
            spans.append((m.start(), m.end()))
    spans.sort()
    # De-overlap nested matches by keeping the earliest-starting one.
    deduped: list[tuple[int, int]] = []
    last_end = -1
    for s, e in spans:
        if s < last_end:
            continue
        deduped.append((s, e))
        last_end = e
    return deduped


@register(
    "quotation.pagination",
    "Quotation",
    "Direct quotations need a page locator",
    "warning",
)
def check_quotation_pagination(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []

    # Skip the Reference section — quoted text inside a reference title is
    # not the author quoting a source.
    ref_start: int | None = next(
        (s.paragraph_index for s in doc.sections if is_reference_title(s.title)),
        None,
    )

    issue_count = 0

    for para in doc.paragraphs:
        if ref_start is not None and para.index >= ref_start:
            break
        text = para.text
        spans = _quote_spans(text)
        if not spans:
            continue

        for q_start, q_end in spans:
            window_start = max(0, q_start - WINDOW_BEFORE)
            window_end = min(len(text), q_end + WINDOW_AFTER)
            window = text[window_start:window_end]

            if not _CITATION_LIKE.search(window):
                continue
            if _PAGE_INDICATOR.search(window):
                continue

            # Skip when the quote is immediately preceded by a coined-term
            # marker (e.g. `termed "AI guilt"`). Such quotes name a concept,
            # not reproduce wording, and APA 7 §6.7 doesn't require a page.
            preceding = text[max(0, q_start - 40):q_start]
            if _COINED_TERM_MARKER.search(preceding):
                continue

            # Skip short quotes preceded by a determiner (the/a/this/…) —
            # they look like terminology in scare-quotes, not real quotes.
            quote_inner = text[q_start:q_end].strip("\"“”")
            if (len(quote_inner.split()) <= _TERM_QUOTE_MAX_WORDS
                    and _DETERMINER_BEFORE.search(preceding)):
                continue

            quote = text[q_start:q_end]
            if issue_count < MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"paragraph {para.index}",
                    locator=Locator(
                        kind="paragraph",
                        paragraph_index=para.index,
                        char_start=q_start,
                        char_end=q_end,
                    ),
                    message=(
                        "Direct quotation without a page locator — APA 7 / AQF "
                        "Item 4: cite the source with p./pp. (or Section/para.) "
                        "for any quoted text"
                    ),
                    expected="(Author, Year, p. N) or equivalent locator",
                    actual="citation present, no p./pp.",
                    excerpt=quote[:200],
                ))
            issue_count += 1

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"... and {issue_count - MAX_REPORTED} more quotations missing a "
                f"page locator"
            ),
        ))

    return details


# ── APA 7 §8.27: ≥ 40-word quotes must be block-quoted ────────────────


def _word_count(text: str) -> int:
    """Approximate word count compatible with the abstract counter:
    one word per CJK character + whitespace-split tokens for the rest."""
    cjk = re.findall(
        r"[一-鿿㐀-䶿豈-﫿\U00020000-\U0002A6DF\U0002A700-\U000323AF]",
        text,
    )
    rest = re.sub(
        r"[一-鿿㐀-䶿豈-﫿\U00020000-\U0002A6DF\U0002A700-\U000323AF]",
        " ",
        text,
    )
    return len(cjk) + len(rest.split())


def _has_block_indent(para: Paragraph) -> bool:
    """A block quote is set off from body text via a left indent (APA 7 §8.27).
    Treat any positive left_indent ≥ 0.5 cm as block-quote-indented; this is
    looser than the canonical 1.27 cm and accommodates the common 1 cm /
    0.5 inch variants seen in submitted manuscripts.
    """
    left = para.indent_left_cm
    return left is not None and left >= 0.5


@register(
    "quotation.block_format",
    "Quotation",
    "Long quotations must be block-quoted (≥ 40 words)",
    "warning",
)
def check_block_format(doc: ParsedDocument) -> list[CheckDetail]:
    """Flag two failure modes around block quotations:

    1. A quoted span ≥ 40 words still wrapped in quotation marks AND not
       sitting in an indented paragraph (i.e. inline rather than block).

    2. A heavily-indented paragraph whose quoted content is < 40 words —
       likely over-block-quoted, which APA forbids.
    """
    details: list[CheckDetail] = []

    ref_start: int | None = next(
        (s.paragraph_index for s in doc.sections if is_reference_title(s.title)),
        None,
    )

    threshold = P.BLOCK_QUOTE_WORD_THRESHOLD
    issue_count = 0

    for para in doc.paragraphs:
        if ref_start is not None and para.index >= ref_start:
            break
        if para.is_in_table:
            continue
        text = para.text
        if not text.strip():
            continue

        spans = _quote_spans(text)
        if not spans:
            continue

        block_indented = _has_block_indent(para)

        for q_start, q_end in spans:
            quoted_text = text[q_start:q_end].strip("\"“”")
            words = _word_count(quoted_text)

            window_start = max(0, q_start - WINDOW_BEFORE)
            window_end = min(len(text), q_end + WINDOW_AFTER)
            window = text[window_start:window_end]

            # Mode 1: ≥ 40-word inline quote that should be a block quote.
            # Require a citation in the surrounding window so we don't flag
            # long stretches of dialogue / scare-quoted prose.
            if (
                words >= threshold
                and not block_indented
                and _CITATION_LIKE.search(window)
            ):
                if issue_count < MAX_REPORTED:
                    details.append(CheckDetail(
                        location=f"paragraph {para.index}",
                        locator=Locator(
                            kind="paragraph",
                            paragraph_index=para.index,
                            char_start=q_start,
                            char_end=q_end,
                        ),
                        message=(
                            f"Direct quotation runs {words} words but is set "
                            f"inline with quotation marks — APA 7 §8.27: "
                            f"quotations of {threshold} words or more must be "
                            f"set as an indented block (no quotation marks)"
                        ),
                        expected=f"block quote (indented, no quotes) for ≥ {threshold} words",
                        actual=f"inline quote, {words} words",
                        excerpt=text[q_start:q_end][:200],
                    ))
                issue_count += 1

    # Mode 2: indented paragraph whose entire content is a short quote —
    # over-block-quoted. We compare paragraph-level word count rather than
    # individual quote spans so a paragraph with several small quotations
    # doesn't trip the rule.
    for para in doc.paragraphs:
        if ref_start is not None and para.index >= ref_start:
            break
        if para.is_in_table:
            continue
        if not _has_block_indent(para):
            continue
        text = para.text.strip()
        if not text:
            continue
        # The paragraph should *look* like a quotation: opens with a quote
        # mark or is preceded by ":" in the prior paragraph, and contains a
        # citation. Without these gates, regular indented body text (long
        # bullets, signatures) would fire the rule.
        is_quote_open = text[:1] in "\"“"
        has_citation = bool(_CITATION_LIKE.search(text))
        if not (is_quote_open and has_citation):
            continue
        if _word_count(text) >= threshold:
            continue
        if issue_count < MAX_REPORTED:
            details.append(CheckDetail(
                location=f"paragraph {para.index}",
                locator=Locator(
                    kind="paragraph",
                    paragraph_index=para.index,
                ),
                message=(
                    f"Block-indented quotation of {_word_count(text)} words — "
                    f"APA 7 §8.26 reserves block format for quotations of "
                    f"{threshold} words or more; use inline quotation marks "
                    f"for shorter quotes"
                ),
                expected=f"inline quote for < {threshold} words",
                actual=f"block-indented quote, {_word_count(text)} words",
                excerpt=text[:200],
            ))
        issue_count += 1

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"... and {issue_count - MAX_REPORTED} more block-quote "
                f"format issues"
            ),
        ))

    return details
