"""Tests for the quotation rules."""
from __future__ import annotations

from ets_checker.models import (
    DocumentMetadata,
    Paragraph,
    ParsedDocument,
    Run,
    Section,
)
from ets_checker.rules.quotation import check_quotation_pagination


def _para(idx: int, text: str) -> Paragraph:
    return Paragraph(
        index=idx,
        text=text,
        style_name=None,
        runs=[Run(text=text, font_name=None, font_size_pt=None,
                  bold=None, italic=None)],
        alignment=None,
        indent_left_cm=None,
        indent_first_line_cm=None,
        line_spacing=None,
        is_in_table=False,
    )


def _doc(*texts: str, ref_at: int | None = None) -> ParsedDocument:
    secs: list[Section] = []
    if ref_at is not None:
        secs.append(Section(
            title="References", level=1, paragraph_index=ref_at,
            detection_method="style",
        ))
    return ParsedDocument(
        metadata=DocumentMetadata(
            paper_size="A4",
            paper_width_cm=21.0,
            paper_height_cm=29.7,
            margin_top_cm=2.5,
            margin_bottom_cm=2.5,
            margin_left_cm=2.5,
            margin_right_cm=2.5,
            default_line_spacing=1.0,
        ),
        paragraphs=[_para(i, t) for i, t in enumerate(texts)],
        sections=secs,
        citations=[],
        references=[],
        figures=[],
        tables=[],
    )


class TestQuotationPagination:
    def test_quote_with_page_passes(self) -> None:
        doc = _doc(
            'According to Smith, "the rain in Spain falls mainly on the '
            'plain" (Smith, 2020, p. 15).'
        )
        assert check_quotation_pagination(doc) == []

    def test_quote_with_curly_quotes_and_pp_passes(self) -> None:
        doc = _doc(
            'Smith concluded that “motivation drives all learning behaviours” '
            '(Smith, 2020, pp. 15–17).'
        )
        assert check_quotation_pagination(doc) == []

    def test_quote_without_page_flagged(self) -> None:
        doc = _doc(
            'According to Smith, "the rain in Spain falls mainly on the '
            'plain" (Smith, 2020).'
        )
        details = check_quotation_pagination(doc)
        assert len(details) == 1
        assert "page locator" in details[0].message

    def test_short_scare_quote_not_flagged(self) -> None:
        # Scare quotes / single-word quotes do not count as direct quotations.
        doc = _doc('This is what we call "modern" (Smith, 2020).')
        assert check_quotation_pagination(doc) == []

    def test_quote_without_citation_not_flagged(self) -> None:
        # Without a nearby citation we don't know whose quote it is, and
        # AQF Item 4 only fires when a citation is present but lacks a page.
        doc = _doc('"This is just emphasis without attribution at all here."')
        assert check_quotation_pagination(doc) == []

    def test_section_locator_accepted(self) -> None:
        doc = _doc(
            '"The principle of least effort governs all reading" '
            '(Smith, 2020, Section 3).'
        )
        assert check_quotation_pagination(doc) == []

    def test_para_locator_accepted(self) -> None:
        doc = _doc(
            '"Children develop language structures iteratively" '
            '(Smith, 2020, para. 4).'
        )
        assert check_quotation_pagination(doc) == []

    def test_reference_section_skipped(self) -> None:
        doc = _doc(
            'Body text without quotes.',
            'References',
            'Smith, J. (2020). "A famous quote in a title". Journal, 1(1).',
            ref_at=1,
        )
        # Reference titles can themselves contain quoted strings — we don't
        # flag those.
        assert check_quotation_pagination(doc) == []
