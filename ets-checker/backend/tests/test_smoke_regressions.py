"""Regression tests for bugs found by the ETS-2025-1900 smoke test.

Each test pins one bug fix:

1. ``parser.citations`` — name particle (Le/le/de/van…) cannot start a
   match in the middle of a word ("While Ahadzadeh" must yield
   "Ahadzadeh", not "le Ahadzadeh").

2. ``rules.reference._looks_like_book_or_chapter`` — the trailing
   "City: Publisher." pattern is recognised as book-like even when the
   publisher name has no Press/Wiley/Sage keyword.

3. ``parser.sections._CANONICAL_HEADINGS`` — "Declaration of competing
   interest" is recognised as a section heading.

4. ``rules.quotation`` — short quoted phrases that follow a determiner
   ("the", "this", …) are treated as terminology references, not direct
   quotations, and don't trip the missing-page-locator rule.
"""
from __future__ import annotations

import pytest

from ets_checker.models import (
    Citation,
    DocumentMetadata,
    Paragraph,
    ParsedDocument,
    Reference,
    Run,
    Section,
)
from ets_checker.parser.citations import extract as extract_citations
from ets_checker.parser.sections import _CANONICAL_HEADINGS, detect as detect_sections
from ets_checker.rules.quotation import check_quotation_pagination
from ets_checker.rules.reference import _looks_like_book_or_chapter


def _para(idx: int, text: str, *, style: str | None = "Normal") -> Paragraph:
    return Paragraph(
        index=idx,
        text=text,
        style_name=style,
        runs=[Run(text=text, font_name="Times New Roman",
                  font_size_pt=10.0, bold=False, italic=False)],
        alignment=None,
        indent_left_cm=None,
        indent_first_line_cm=None,
        line_spacing=1.0,
        is_in_table=False,
    )


def _doc(paragraphs: list[Paragraph], *,
         sections: list[Section] | None = None,
         references: list[Reference] | None = None,
         citations: list[Citation] | None = None) -> ParsedDocument:
    return ParsedDocument(
        metadata=DocumentMetadata(
            paper_size="A4", paper_width_cm=21.0, paper_height_cm=29.7,
            margin_top_cm=2.5, margin_bottom_cm=2.5,
            margin_left_cm=2.5, margin_right_cm=2.5,
            default_line_spacing=1.0,
        ),
        paragraphs=paragraphs,
        sections=sections or [],
        citations=citations or [],
        references=references or [],
        figures=[],
        tables=[],
    )


# ── Bug 1: citation parser absorbs trailing letters into name particle ──

class TestCitationParticleBoundary:
    def test_while_ahadzadeh_not_le_ahadzadeh(self) -> None:
        # "While" ends in "le" — without a word-boundary guard, the
        # narrative-citation regex would treat "le" as a French/Dutch name
        # particle and capture "le Ahadzadeh" as a multi-word surname.
        para = _para(0, "While Ahadzadeh et al. (2026) found that...")
        cites = extract_citations([para], sections=[])
        assert len(cites) == 1
        c = cites[0]
        assert c.authors == ["ahadzadeh"], c.authors
        assert c.has_et_al is True
        assert c.year == "2026"
        assert "le " not in c.raw_text.lower()

    def test_legitimate_le_particle_at_sentence_start(self) -> None:
        # A real "le X" surname at the start of a sentence still works —
        # there's no preceding word character so the lookbehind passes.
        para = _para(0, "le Bourgeois (2020) noted...")
        cites = extract_citations([para], sections=[])
        assert len(cites) == 1
        assert cites[0].authors == ["le bourgeois"], cites[0].authors

    def test_legitimate_le_particle_after_comma(self) -> None:
        # "Smith and le Bourgeois (2020)" — the second author is preceded
        # by a space (non-word char) so the particle is allowed.
        para = _para(0, "Smith and le Bourgeois (2020) noted...")
        cites = extract_citations([para], sections=[])
        assert len(cites) == 1
        assert "le bourgeois" in cites[0].authors

    def test_paragraph_starting_with_capital_word_ending_in_particle(
        self,
    ) -> None:
        # Other words ending in a particle: "Multiple Smith (2020)" — the
        # "le" of "Multiple" must not be absorbed into the surname.
        para = _para(0, "Multiple Smith (2020) studies confirmed this.")
        cites = extract_citations([para], sections=[])
        assert len(cites) == 1
        assert cites[0].authors == ["smith"], cites[0].authors


# ── Bug 2: book-like detection misses "City: Publisher." pattern ────────

class TestBookCityPublisherPattern:
    def test_goffman_garden_city_doubleday(self) -> None:
        # The publisher "Doubleday Anchor" lacks any Press/Wiley/Sage
        # keyword, but the trailing "City, State: Publisher." pattern is
        # the canonical APA book format.
        text = (
            "Goffman, E. (1959). The presentation of self in everyday life. "
            "Garden City, New York: Doubleday Anchor."
        )
        assert _looks_like_book_or_chapter(text) is True

    def test_simple_city_publisher(self) -> None:
        text = "Smith, J. (2020). A book. London: Faber and Faber."
        assert _looks_like_book_or_chapter(text) is True

    def test_journal_with_subtitle_colon_not_matched(self) -> None:
        # "Title: Subtitle. Journal, 5(2), 1-10." — colon is mid-string,
        # not at end, so it must not be treated as a book pattern.
        text = (
            "Smith, J. (2020). Title: A subtitle. Journal of X, 5(2), 1-10."
        )
        assert _looks_like_book_or_chapter(text) is False


# ── Bug 3: "Declaration of competing interest" missing as canonical ────

class TestSectionDeclarationOfCompetingInterest:
    def test_canonical_set_contains_variants(self) -> None:
        for variant in (
            "declaration of competing interest",
            "declaration of competing interests",
            "declaration of conflict of interest",
            "declaration of conflicts of interest",
            "declaration of conflicting interest",
            "declaration of conflicting interests",
        ):
            assert variant in _CANONICAL_HEADINGS

    def test_heuristic_detects_unstyled_bold_declaration_heading(
        self,
    ) -> None:
        # Simulate a body paragraph (so the heuristic enters canonical-only
        # mode) plus an unstyled-but-bold "Declaration of competing
        # interest" line.
        body = Paragraph(
            index=0, text="The body of the paper.", style_name="Heading 1",
            runs=[Run(text="The body of the paper.",
                      font_name="Times New Roman", font_size_pt=12.0,
                      bold=True, italic=False)],
            alignment=None, indent_left_cm=None, indent_first_line_cm=None,
            line_spacing=1.0, is_in_table=False,
        )
        body2 = Paragraph(
            index=1, text="text", style_name="Normal",
            runs=[Run(text="text", font_name="Times New Roman",
                      font_size_pt=10.0, bold=False, italic=False)],
            alignment=None, indent_left_cm=None, indent_first_line_cm=None,
            line_spacing=1.0, is_in_table=False,
        )
        decl = Paragraph(
            index=2, text="Declaration of competing interest",
            style_name="Normal",
            runs=[Run(text="Declaration of competing interest",
                      font_name="Times New Roman", font_size_pt=12.0,
                      bold=True, italic=False)],
            alignment=None, indent_left_cm=None, indent_first_line_cm=None,
            line_spacing=1.0, is_in_table=False,
        )
        sections = detect_sections([body, body2, decl])
        decl_section = next(
            (s for s in sections if s.paragraph_index == 2), None,
        )
        assert decl_section is not None
        assert "declaration" in decl_section.title.lower()


# ── Bug 4: short determiner-quote false-positive in quotation rule ─────

class TestQuotationDeterminerShortQuote:
    def test_the_short_quote_with_citation_is_skipped(self) -> None:
        # "the 'feeling rules' (Hochschild, 1983)" — coined-term reference,
        # not a direct quote. APA 7 §6.7 doesn't require a page locator.
        para = _para(
            0,
            "Students comply with the “feeling rules” (Hochschild, 1983) "
            "of the classroom.",
        )
        details = check_quotation_pagination(_doc([para]))
        assert details == []

    def test_termed_marker_with_short_quote_is_skipped(self) -> None:
        para = _para(
            0,
            "moral discomfort (termed “AI guilt over-time” by Chan, 2025), "
            "and so on.",
        )
        details = check_quotation_pagination(_doc([para]))
        assert details == []

    def test_long_quote_after_determiner_is_still_flagged(self) -> None:
        # A determiner ("the") + a long (>3-word) quote is unlikely to be
        # terminology — keep flagging when a citation is nearby.
        long_quote = (
            "the “a substantial multi-word direct quotation that is more "
            "than three words long” (Smith, 2020) shows..."
        )
        para = _para(0, long_quote)
        details = check_quotation_pagination(_doc([para]))
        assert len(details) == 1

    def test_real_direct_quote_after_said_is_still_flagged(self) -> None:
        para = _para(
            0,
            'The author wrote, "this is a real direct quote of multiple '
            'words" (Smith, 2020).',
        )
        details = check_quotation_pagination(_doc([para]))
        assert len(details) == 1
