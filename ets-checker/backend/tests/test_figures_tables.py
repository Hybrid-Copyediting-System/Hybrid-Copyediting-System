"""Pytest coverage for the figures_tables.* rules."""
from __future__ import annotations

from ets_checker.models import (
    DocumentMetadata,
    Figure,
    Paragraph,
    ParsedDocument,
    Run,
    Section,
    Table,
)
from ets_checker.rules.figures_tables import (
    check_caption_position,
    check_referenced_in_text,
    check_table_format,
)


def _doc(
    *,
    paragraphs: list[Paragraph] | None = None,
    sections: list[Section] | None = None,
    figures: list[Figure] | None = None,
    tables: list[Table] | None = None,
) -> ParsedDocument:
    return ParsedDocument(
        metadata=DocumentMetadata(
            paper_size="A4", paper_width_cm=21, paper_height_cm=29.7,
            margin_top_cm=2.5, margin_bottom_cm=2.5,
            margin_left_cm=2.5, margin_right_cm=2.5,
            default_line_spacing=1.0,
        ),
        paragraphs=paragraphs or [],
        sections=sections or [],
        citations=[],
        references=[],
        figures=figures or [],
        tables=tables or [],
    )


def _para(idx: int, text: str) -> Paragraph:
    return Paragraph(
        index=idx, text=text, style_name=None,
        runs=[Run(text=text, font_name="Times New Roman", font_size_pt=10.0,
                  bold=False, italic=False)],
        alignment=None, indent_left_cm=None, indent_first_line_cm=None,
        line_spacing=None, is_in_table=False,
    )


# ─── referenced_in_text ─────────────────────────────────────────────


class TestReferencedInText:
    def test_defined_but_uncited_figure_flagged(self) -> None:
        doc = _doc(
            paragraphs=[_para(0, "Body text without any references.")],
            figures=[Figure(index=0, figure_number=1, caption_text="Figure 1. A.",
                            paragraph_index=5)],
        )
        details = check_referenced_in_text(doc)
        assert any("Figure 1" in d.message and "not referenced" in d.message
                   for d in details)

    def test_cited_figure_passes(self) -> None:
        doc = _doc(
            paragraphs=[_para(0, "As shown in Figure 1, the result holds.")],
            figures=[Figure(index=0, figure_number=1, caption_text="Figure 1. A.",
                            paragraph_index=5)],
        )
        assert all("Figure 1" not in d.message for d in check_referenced_in_text(doc))

    def test_cited_but_undefined_figure_flagged(self) -> None:
        doc = _doc(
            paragraphs=[_para(0, "See Figure 7 for details.")],
            figures=[],
        )
        details = check_referenced_in_text(doc)
        assert any("Figure 7" in d.message and "not found" in d.message
                   for d in details)

    def test_table_variants(self) -> None:
        # "Tables 2" plural form should still match.
        doc = _doc(
            paragraphs=[_para(0, "Tables 2 contains data.")],
            tables=[Table(index=0, table_number=2, caption_text="Table 2. X.",
                          paragraph_index=5)],
        )
        # Cited and defined → no Table 2 finding.
        assert all("Table 2" not in d.message for d in check_referenced_in_text(doc))


# ─── caption_position ───────────────────────────────────────────────


class TestCaptionPosition:
    def test_caption_above_passes(self) -> None:
        doc = _doc(
            figures=[Figure(index=0, figure_number=1, caption_text="Figure 1. X.",
                            paragraph_index=5, caption_position="above")],
        )
        assert check_caption_position(doc) == []

    def test_caption_below_figure_flagged(self) -> None:
        doc = _doc(
            figures=[Figure(index=0, figure_number=1, caption_text="Figure 1. X.",
                            paragraph_index=5, caption_position="below")],
        )
        details = check_caption_position(doc)
        assert len(details) == 1
        assert "Figure 1" in details[0].message
        assert "below" in details[0].actual

    def test_caption_position_unknown_skipped(self) -> None:
        doc = _doc(
            figures=[Figure(index=0, figure_number=1, caption_text="Figure 1. X.",
                            paragraph_index=5, caption_position=None)],
        )
        assert check_caption_position(doc) == []

    def test_table_caption_below_flagged(self) -> None:
        doc = _doc(
            tables=[Table(index=0, table_number=3, caption_text="Table 3. X.",
                          paragraph_index=8, caption_position="below")],
        )
        details = check_caption_position(doc)
        assert len(details) == 1
        assert "Table 3" in details[0].message


# ─── table_format ───────────────────────────────────────────────────


class TestTableFormat:
    def test_caption_without_word_table_flagged(self) -> None:
        """A 'Table N.' caption with no matching parsed Word table should be
        flagged as a likely image-based table."""
        doc = _doc(
            paragraphs=[_para(0, "Table 1. Sample data."),
                        _para(1, "Body following the caption.")],
            tables=[],  # no Word table parsed
        )
        details = check_table_format(doc)
        assert len(details) == 1
        assert "Table 1" in details[0].message
        # Without a nearby image we get the generic "verify..." message.
        assert "editable table format" in details[0].message

    def test_caption_with_matching_word_table_passes(self) -> None:
        doc = _doc(
            paragraphs=[_para(0, "Table 1. Sample data.")],
            tables=[Table(index=0, table_number=1, caption_text="Table 1.",
                          paragraph_index=0, has_vertical_borders=False)],
        )
        assert check_table_format(doc) == []

    def test_vertical_borders_flagged(self) -> None:
        doc = _doc(
            paragraphs=[_para(0, "Table 1. Sample.")],
            tables=[Table(index=0, table_number=1, caption_text="Table 1.",
                          paragraph_index=0, has_vertical_borders=True)],
        )
        details = check_table_format(doc)
        assert len(details) == 1
        assert "vertical borders" in details[0].message

    def test_image_near_orphan_caption_diagnosed_as_image_table(self) -> None:
        doc = _doc(
            paragraphs=[_para(0, "Table 1. Image-based data.")],
            figures=[Figure(index=0, figure_number=None, caption_text=None,
                            paragraph_index=1)],  # image within ±3 paragraphs
        )
        details = check_table_format(doc)
        assert len(details) == 1
        assert "image" in details[0].message.lower()
