"""Tests for the 18 ET&S / APA 7 rules added in the comprehensive
implementation pass. One test class per rule, each covering at least the
positive (pass) and negative (fail) paths.
"""
from __future__ import annotations

from ets_checker.models import (
    DocumentMetadata,
    Figure,
    Paragraph,
    ParsedDocument,
    Reference,
    Run,
    Section,
    Table,
)
from ets_checker.rules.citation import check_amp_vs_and
from ets_checker.rules.figures_tables import (
    check_caption_format,
    check_numbering_sequence,
)
from ets_checker.rules.headings import check_level_order, check_no_numbering
from ets_checker.rules.layout import (
    check_body_alignment,
    check_first_line_indent,
)
from ets_checker.rules.quotation import check_block_format
from ets_checker.rules.reference import (
    check_author_count_rule,
    check_italics_journal_volume,
    check_url_terminal_punctuation,
)
from ets_checker.rules.statistics import (
    check_operator_spacing,
    check_p_value_format,
)
from ets_checker.rules.structure import (
    check_abstract_no_indent,
    check_abstract_single_paragraph,
    check_no_introduction_heading,
    check_section_order,
    check_title_length,
)


# ─── builders ─────────────────────────────────────────────────────────


def _meta(**kw):
    defaults = dict(
        paper_size="A4",
        paper_width_cm=21.0,
        paper_height_cm=29.7,
        margin_top_cm=2.5,
        margin_bottom_cm=2.5,
        margin_left_cm=2.5,
        margin_right_cm=2.5,
        default_line_spacing=1.0,
    )
    defaults.update(kw)
    return DocumentMetadata(**defaults)


def R(text: str, **kw) -> Run:
    return Run(
        text=text,
        font_name=kw.get("font", "Times New Roman"),
        font_size_pt=kw.get("size", 10.0),
        bold=kw.get("bold"),
        italic=kw.get("italic"),
    )


def P(idx: int, text: str, runs=None, *,
      style=None, in_table: bool = False,
      indent_first: float | None = None,
      indent_left: float | None = None,
      alignment: str | None = None) -> Paragraph:
    if runs is None:
        runs = [R(text)]
    return Paragraph(
        index=idx,
        text=text,
        style_name=style,
        runs=runs,
        alignment=alignment,
        indent_left_cm=indent_left,
        indent_first_line_cm=indent_first,
        line_spacing=None,
        is_in_table=in_table,
    )


def S(title: str, level: int, idx: int, method: str = "style") -> Section:
    return Section(
        title=title, level=level, paragraph_index=idx,
        detection_method=method,
    )


def make_doc(**kw) -> ParsedDocument:
    defaults = dict(
        metadata=_meta(),
        paragraphs=[],
        sections=[],
        citations=[],
        references=[],
        figures=[],
        tables=[],
    )
    defaults.update(kw)
    return ParsedDocument(**defaults)


def _ref(idx: int, text: str, **kw) -> Reference:
    defaults = dict(
        index=idx,
        raw_text=text,
        first_author_surname=kw.get("surname", "Smith"),
        year=kw.get("year", "2020"),
        year_suffix=None,
        parse_confidence=kw.get("confidence", 1.0),
        paragraph_index=kw.get("paragraph_index", idx + 100),
        doi=kw.get("doi"),
        urls=kw.get("urls", []),
        author_count=kw.get("author_count"),
        author_sort_keys=kw.get("author_sort_keys", []),
    )
    return Reference(**defaults)


# ─── #1 statistics.operator_spacing ───────────────────────────────────


class TestOperatorSpacing:
    def test_proper_spacing_passes(self) -> None:
        doc = make_doc(paragraphs=[
            P(0, "We found that p = .04 and t = 2.31 in this analysis."),
        ])
        assert check_operator_spacing(doc) == []

    def test_missing_space_flagged(self) -> None:
        doc = make_doc(paragraphs=[
            P(0, "We found p=.04 and t<2.31 in this analysis test results."),
        ])
        details = check_operator_spacing(doc)
        assert len(details) >= 1
        assert any("p=" in (d.actual or "") for d in details)

    def test_reference_section_skipped(self) -> None:
        doc = make_doc(
            paragraphs=[
                P(0, "Some body text here without any statistics at all."),
                P(1, "References"),
                P(2, "Smith, J. (2020). Vol. 5, p=345 (link)."),
            ],
            sections=[S("References", 1, 1)],
        )
        assert check_operator_spacing(doc) == []


# ─── #2 statistics.p_value_format ─────────────────────────────────────


class TestPValueFormat:
    def test_proper_p_passes(self) -> None:
        doc = make_doc(paragraphs=[
            P(0, "We found that p = .04 and the effect was robust here."),
            P(1, "Some other paragraph testing p < .001 lower bound."),
        ])
        assert check_p_value_format(doc) == []

    def test_leading_zero_flagged(self) -> None:
        doc = make_doc(paragraphs=[
            P(0, "We found that p = 0.04 across all conditions tested."),
        ])
        details = check_p_value_format(doc)
        assert len(details) == 1
        assert "leading zero" in details[0].message

    def test_p_equals_zero_flagged(self) -> None:
        doc = make_doc(paragraphs=[
            P(0, "The contrast was significant with p = .000 in this test."),
        ])
        details = check_p_value_format(doc)
        assert len(details) == 1
        assert "p < .001" in details[0].message


# ─── #3 quotation.block_format ────────────────────────────────────────


class TestBlockFormat:
    def test_short_inline_quote_passes(self) -> None:
        doc = make_doc(paragraphs=[
            P(0, 'Smith said, "this is a short quote" (Smith, 2020, p. 15).'),
        ])
        assert check_block_format(doc) == []

    def test_long_inline_quote_flagged(self) -> None:
        long_text = " ".join(["word"] * 50)
        doc = make_doc(paragraphs=[
            P(0, f'According to Smith, "{long_text}" (Smith, 2020, p. 15).'),
        ])
        details = check_block_format(doc)
        assert len(details) == 1
        assert "block" in details[0].message.lower()

    def test_long_block_quote_passes(self) -> None:
        # An indented long quote without quote marks should pass.
        long_text = " ".join(["word"] * 50)
        doc = make_doc(paragraphs=[
            P(0, f"{long_text} (Smith, 2020, p. 15).", indent_left=1.27),
        ])
        assert check_block_format(doc) == []

    def test_short_block_indented_with_quote_marks_flagged(self) -> None:
        doc = make_doc(paragraphs=[
            P(0, '"a short attributed quote" (Smith, 2020, p. 15).',
              indent_left=1.27),
        ])
        details = check_block_format(doc)
        assert len(details) == 1
        assert "block-indented" in details[0].message.lower()


# ─── #4 reference.italics_journal_volume ──────────────────────────────


class TestRefItalics:
    def test_correct_italics_passes(self) -> None:
        # "Educational Technology" italic, "5" italic, "(2)" not italic.
        runs = [
            R("Smith, J. (2020). A study of fonts. ", italic=False),
            R("Educational Technology", italic=True),
            R(", ", italic=False),
            R("5", italic=True),
            R("(2), 100–120.", italic=False),
        ]
        para = P(11, "Smith, J. (2020). A study of fonts. Educational Technology, 5(2), 100–120.",
                 runs=runs)
        ref = _ref(1, para.text, paragraph_index=11)
        doc = make_doc(paragraphs=[para], references=[ref])
        assert check_italics_journal_volume(doc) == []

    def test_journal_not_italic_flagged(self) -> None:
        runs = [
            R("Smith, J. (2020). A study of fonts. ", italic=False),
            R("Educational Technology", italic=False),
            R(", ", italic=False),
            R("5", italic=True),
            R("(2), 100–120.", italic=False),
        ]
        para = P(11, "Smith, J. (2020). A study of fonts. Educational Technology, 5(2), 100–120.",
                 runs=runs)
        ref = _ref(1, para.text, paragraph_index=11)
        doc = make_doc(paragraphs=[para], references=[ref])
        details = check_italics_journal_volume(doc)
        assert any("journal" in d.message for d in details)


# ─── #5 reference.url_terminal_punctuation ────────────────────────────


class TestUrlTerminalPunctuation:
    def test_no_period_passes(self) -> None:
        ref = _ref(
            1,
            "Smith, J. (2020). A paper. Journal. https://doi.org/10.1234/abc",
            doi="10.1234/abc",
        )
        doc = make_doc(references=[ref])
        assert check_url_terminal_punctuation(doc) == []

    def test_trailing_period_flagged(self) -> None:
        ref = _ref(
            1,
            "Smith, J. (2020). A paper. Journal. https://doi.org/10.1234/abc.",
            doi="10.1234/abc",
        )
        doc = make_doc(references=[ref])
        details = check_url_terminal_punctuation(doc)
        assert len(details) == 1


# ─── #6 reference.author_count_rule ───────────────────────────────────


class TestAuthorCountRule:
    def test_5_authors_full_list_passes(self) -> None:
        ref = _ref(
            1,
            "Smith, J., Jones, K., Brown, L., Lee, M., & Park, N. (2020). "
            "A paper. Journal, 5(2), 100.",
            author_count=5,
        )
        doc = make_doc(references=[ref])
        assert check_author_count_rule(doc) == []

    def test_5_authors_with_ellipsis_flagged(self) -> None:
        ref = _ref(
            1,
            "Smith, J., Jones, K., ..., & Park, N. (2020). A paper. Journal, 5(2), 100.",
            author_count=4,
        )
        doc = make_doc(references=[ref])
        details = check_author_count_rule(doc)
        assert len(details) == 1
        assert "..." in details[0].message or "ellipsis" in details[0].message.lower()

    def test_correct_21_plus_format_not_flagged(self) -> None:
        """A reference correctly using APA 7 §9.8 (first 19 + ... + last)
        shows ~20 visible chunks to the parser. That must NOT be flagged
        as 'too few authors with ellipsis' — the ambiguous-zone fix.
        """
        ref = _ref(
            1,
            "A1, A2, A3, A4, A5, A6, A7, A8, A9, A10, A11, A12, A13, A14, "
            "A15, A16, A17, A18, A19, ..., Last, F. (2020). Paper. Journal.",
            author_count=20,
        )
        doc = make_doc(references=[ref])
        assert check_author_count_rule(doc) == []

    def test_25_authors_without_ellipsis_flagged(self) -> None:
        # Note: the raw text contains "..." so it would NOT trip mode B; reword.
        ref = _ref(
            1,
            "A1, A. A., A2, B. B., A3, C., A4, D., A5, E., A6, F., A7, G., "
            "A8, H., A9, I., A10, J. (2020). Paper.",
            author_count=25,
        )
        doc = make_doc(references=[ref])
        details = check_author_count_rule(doc)
        assert any("ellipsis" in d.message.lower() for d in details)


# ─── #7 citation.amp_vs_and ───────────────────────────────────────────


class TestAmpVsAnd:
    def test_correct_usage_passes(self) -> None:
        doc = make_doc(paragraphs=[
            P(0, "Smith and Jones (2020) found something. "
                 "Other research (Brown & Lee, 2019) confirmed."),
        ])
        assert check_amp_vs_and(doc) == []

    def test_paren_with_and_flagged(self) -> None:
        doc = make_doc(paragraphs=[
            P(0, "Other research (Brown and Lee, 2019) confirmed it."),
        ])
        details = check_amp_vs_and(doc)
        assert len(details) >= 1
        assert "&" in details[0].expected

    def test_narrative_with_amp_flagged(self) -> None:
        doc = make_doc(paragraphs=[
            P(0, "Smith & Jones (2020) found something significant."),
        ])
        details = check_amp_vs_and(doc)
        assert len(details) >= 1
        assert "and" in details[0].expected

    def test_paren_with_see_prefix_flagged(self) -> None:
        doc = make_doc(paragraphs=[
            P(0, "Other research (see Smith and Jones, 2020) confirmed."),
        ])
        details = check_amp_vs_and(doc)
        assert len(details) >= 1

    def test_paren_with_eg_prefix_flagged(self) -> None:
        doc = make_doc(paragraphs=[
            P(0, "Several studies (e.g., Smith and Jones, 2020)."),
        ])
        details = check_amp_vs_and(doc)
        assert len(details) >= 1

    def test_reference_section_skipped(self) -> None:
        doc = make_doc(
            paragraphs=[
                P(0, "Body text."),
                P(1, "References"),
                P(2, "Smith, J. & Jones, K. (2020). Title."),
            ],
            sections=[S("References", 1, 1)],
        )
        assert check_amp_vs_and(doc) == []


# ─── #8 structure.abstract_single_paragraph ───────────────────────────


class TestAbstractSingleParagraph:
    def test_single_para_passes(self) -> None:
        doc = make_doc(
            paragraphs=[
                P(0, "Abstract"),
                P(1, "This is the entire abstract in a single paragraph."),
                P(2, "Keywords: a, b"),
                P(3, "Introduction"),
            ],
            sections=[S("Abstract", 1, 0), S("Introduction", 1, 3)],
        )
        assert check_abstract_single_paragraph(doc) == []

    def test_multi_para_flagged(self) -> None:
        doc = make_doc(
            paragraphs=[
                P(0, "Abstract"),
                P(1, "First abstract paragraph."),
                P(2, "Second abstract paragraph."),
                P(3, "Keywords: a, b"),
                P(4, "Introduction"),
            ],
            sections=[S("Abstract", 1, 0), S("Introduction", 1, 4)],
        )
        details = check_abstract_single_paragraph(doc)
        assert len(details) == 1


# ─── #9 structure.abstract_no_indent ──────────────────────────────────


class TestAbstractNoIndent:
    def test_no_indent_passes(self) -> None:
        doc = make_doc(
            paragraphs=[
                P(0, "Abstract"),
                P(1, "Abstract body.", indent_first=0.0),
                P(2, "Introduction"),
            ],
            sections=[S("Abstract", 1, 0), S("Introduction", 1, 2)],
        )
        assert check_abstract_no_indent(doc) == []

    def test_indented_flagged(self) -> None:
        doc = make_doc(
            paragraphs=[
                P(0, "Abstract"),
                P(1, "Abstract body.", indent_first=1.27),
                P(2, "Introduction"),
            ],
            sections=[S("Abstract", 1, 0), S("Introduction", 1, 2)],
        )
        details = check_abstract_no_indent(doc)
        assert len(details) == 1


# ─── #10 structure.section_order ──────────────────────────────────────


class TestSectionOrder:
    def test_correct_order_passes(self) -> None:
        doc = make_doc(sections=[
            S("Abstract", 1, 0),
            S("Introduction", 1, 5),
            S("Methods", 1, 10),
            S("References", 1, 50),
            S("Appendix A", 1, 80),
        ])
        assert check_section_order(doc) == []

    def test_appendix_before_references_flagged(self) -> None:
        doc = make_doc(sections=[
            S("Abstract", 1, 0),
            S("Introduction", 1, 5),
            S("Appendix A", 1, 50),
            S("References", 1, 80),
        ])
        details = check_section_order(doc)
        assert len(details) >= 1


# ─── #11 headings.no_numbering ────────────────────────────────────────


class TestHeadingsNoNumbering:
    def test_unnumbered_passes(self) -> None:
        doc = make_doc(sections=[S("Methods", 1, 5)])
        assert check_no_numbering(doc) == []

    def test_dotted_number_flagged(self) -> None:
        doc = make_doc(sections=[S("1.1 Background", 2, 5)])
        details = check_no_numbering(doc)
        assert len(details) == 1

    def test_chapter_word_flagged(self) -> None:
        doc = make_doc(sections=[S("Chapter 3 Discussion", 1, 5)])
        details = check_no_numbering(doc)
        assert len(details) == 1


# ─── #12 headings.level_order ─────────────────────────────────────────


class TestHeadingsLevelOrder:
    def test_in_order_passes(self) -> None:
        doc = make_doc(sections=[
            S("Intro", 1, 0), S("Sub", 2, 5), S("SubSub", 3, 10),
        ])
        assert check_level_order(doc) == []

    def test_h1_to_h3_skip_flagged(self) -> None:
        doc = make_doc(sections=[
            S("Intro", 1, 0), S("Skipped sub", 3, 5),
        ])
        details = check_level_order(doc)
        assert len(details) >= 1


# ─── #13 structure.no_introduction_heading ────────────────────────────


class TestNoIntroductionHeading:
    def test_no_intro_heading_passes(self) -> None:
        doc = make_doc(sections=[
            S("Abstract", 1, 0), S("Methods", 1, 5),
        ])
        assert check_no_introduction_heading(doc) == []

    def test_explicit_intro_flagged(self) -> None:
        doc = make_doc(sections=[
            S("Abstract", 1, 0), S("Introduction", 1, 5),
        ])
        details = check_no_introduction_heading(doc)
        assert len(details) == 1


# ─── #14 figures_tables.numbering_sequence ────────────────────────────


class TestNumberingSequence:
    def _fig(self, n: int, idx: int) -> Figure:
        return Figure(
            index=idx, figure_number=n,
            caption_text=f"Figure {n}.", paragraph_index=idx,
        )

    def _tbl(self, n: int, idx: int) -> Table:
        return Table(
            index=idx, table_number=n,
            caption_text=f"Table {n}.", paragraph_index=idx,
        )

    def test_sequential_passes(self) -> None:
        doc = make_doc(figures=[
            self._fig(1, 0), self._fig(2, 1), self._fig(3, 2),
        ])
        assert check_numbering_sequence(doc) == []

    def test_gap_flagged(self) -> None:
        doc = make_doc(figures=[
            self._fig(1, 0), self._fig(3, 1),
        ])
        details = check_numbering_sequence(doc)
        assert len(details) >= 1

    def test_duplicate_flagged(self) -> None:
        doc = make_doc(tables=[
            self._tbl(1, 0), self._tbl(2, 1), self._tbl(2, 2),
        ])
        details = check_numbering_sequence(doc)
        assert any("defined 2 times" in d.message or "appears 2" in (d.actual or "")
                   for d in details)


# ─── #15 figures_tables.caption_format ────────────────────────────────


class TestCaptionFormat:
    def test_correct_caption_passes(self) -> None:
        # "Figure 1." bold + title italic.
        runs = [
            R("Figure 1", bold=True),
            R(". ", bold=False),
            R("A descriptive title", italic=True),
        ]
        para = P(5, "Figure 1. A descriptive title", runs=runs)
        fig = Figure(index=0, figure_number=1, caption_text=para.text,
                     paragraph_index=5)
        doc = make_doc(paragraphs=[para], figures=[fig])
        assert check_caption_format(doc) == []

    def test_non_bold_number_flagged(self) -> None:
        runs = [
            R("Figure 1. ", bold=False),
            R("A descriptive title", italic=True),
        ]
        para = P(5, "Figure 1. A descriptive title", runs=runs)
        fig = Figure(index=0, figure_number=1, caption_text=para.text,
                     paragraph_index=5)
        doc = make_doc(paragraphs=[para], figures=[fig])
        details = check_caption_format(doc)
        assert any("bold" in d.message for d in details)


# ─── #16 layout.first_line_indent ─────────────────────────────────────


class TestFirstLineIndent:
    def _body_paras(self, indent: float | None) -> list[Paragraph]:
        # Need ≥ 30 char body paragraphs after the first section.
        text = "This is sufficiently long body text content " * 2
        return [
            P(0, "Introduction", style="Heading 1"),
            P(1, text, indent_first=indent),
            P(2, text, indent_first=indent),
        ]

    def test_correct_indent_passes(self) -> None:
        doc = make_doc(
            paragraphs=self._body_paras(1.27),
            sections=[S("Introduction", 1, 0)],
        )
        assert check_first_line_indent(doc) == []

    def test_no_indent_flagged(self) -> None:
        doc = make_doc(
            paragraphs=self._body_paras(None),
            sections=[S("Introduction", 1, 0)],
        )
        details = check_first_line_indent(doc)
        assert len(details) == 1

    def test_wrong_indent_flagged(self) -> None:
        doc = make_doc(
            paragraphs=self._body_paras(0.5),
            sections=[S("Introduction", 1, 0)],
        )
        details = check_first_line_indent(doc)
        assert len(details) == 1


# ─── #17 layout.body_alignment ────────────────────────────────────────


class TestBodyAlignment:
    def _body(self, alignment: str | None) -> list[Paragraph]:
        text = "This is a body paragraph long enough to qualify " * 2
        return [
            P(0, "Introduction", style="Heading 1"),
            P(1, text, alignment=alignment),
        ]

    def test_left_passes(self) -> None:
        doc = make_doc(
            paragraphs=self._body("LEFT"),
            sections=[S("Introduction", 1, 0)],
        )
        assert check_body_alignment(doc) == []

    def test_justify_passes(self) -> None:
        doc = make_doc(
            paragraphs=self._body("JUSTIFY"),
            sections=[S("Introduction", 1, 0)],
        )
        assert check_body_alignment(doc) == []

    def test_center_flagged(self) -> None:
        doc = make_doc(
            paragraphs=self._body("CENTER"),
            sections=[S("Introduction", 1, 0)],
        )
        details = check_body_alignment(doc)
        assert len(details) == 1


# ─── #18 structure.title_length ───────────────────────────────────────


class TestTitleLength:
    def test_short_title_passes(self) -> None:
        doc = make_doc(
            paragraphs=[
                P(0, "A Short Five Word Title", style="Title"),
                P(1, "Abstract"),
            ],
            sections=[S("Abstract", 1, 1)],
        )
        assert check_title_length(doc) == []

    def test_long_title_flagged(self) -> None:
        long = "A Very Very Very Very Very Very Very Very Very Very Very Very Long Title"
        doc = make_doc(
            paragraphs=[
                P(0, long, style="Title"),
                P(1, "Abstract"),
            ],
            sections=[S("Abstract", 1, 1)],
        )
        details = check_title_length(doc)
        assert len(details) == 1
