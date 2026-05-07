"""Pytest coverage for the structure and font rules.

Migrated from the standalone ``test_edge_cases.py`` script (which lived
outside ``backend/tests/`` and was therefore never collected by CI).
Each ``test_*`` here corresponds to a behavioural case from that script.
"""
from __future__ import annotations

from ets_checker.models import (
    DocumentMetadata,
    Paragraph,
    ParsedDocument,
    Run,
    Section,
)
from ets_checker.rules.fonts import (
    check_abstract_font,
    check_heading_font,
    check_reference_font,
    check_title_font,
)
from ets_checker.rules.structure import check_required_sections


# ─── builders ─────────────────────────────────────────────────────────


def make_doc(**kw) -> ParsedDocument:
    defaults = dict(
        metadata=DocumentMetadata(
            paper_size="A4",
            paper_width_cm=21,
            paper_height_cm=29.7,
            margin_top_cm=2.5,
            margin_bottom_cm=2.5,
            margin_left_cm=2.5,
            margin_right_cm=2.5,
            default_line_spacing=1.0,
        ),
        paragraphs=[],
        sections=[],
        citations=[],
        references=[],
        figures=[],
        tables=[],
    )
    defaults.update(kw)
    return ParsedDocument(**defaults)


def R(text: str, font: str = "Times New Roman", size: float | None = 10.0,
      bold: bool = False, italic: bool | None = False) -> Run:
    return Run(text=text, font_name=font, font_size_pt=size, bold=bold, italic=italic)


def P(idx: int, text: str, runs=None, style=None, in_table: bool = False) -> Paragraph:
    if runs is None:
        runs = [R(text)]
    return Paragraph(
        index=idx, text=text, style_name=style, runs=runs,
        alignment=None, indent_left_cm=None, indent_first_line_cm=None,
        line_spacing=None, is_in_table=in_table,
    )


def S(title: str, level: int, pidx: int, method: str = "style") -> Section:
    return Section(title=title, level=level, paragraph_index=pidx, detection_method=method)


# ─── structure.required_sections ──────────────────────────────────────


class TestRequiredSections:
    def test_empty_doc_three_errors(self) -> None:
        assert len(check_required_sections(make_doc())) == 3

    def test_all_present(self) -> None:
        doc = make_doc(sections=[
            S("Abstract", 1, 0), S("Introduction", 1, 5), S("References", 1, 20),
        ])
        assert check_required_sections(doc) == []

    def test_trailing_punctuation_accepted(self) -> None:
        doc = make_doc(sections=[
            S("Abstract:", 1, 0), S("Introduction.", 1, 5), S("References：", 1, 20),
        ])
        assert check_required_sections(doc) == []

    def test_numbered_introduction(self) -> None:
        doc = make_doc(sections=[
            S("Abstract", 1, 0), S("1. Introduction", 1, 5), S("References", 1, 20),
        ])
        assert check_required_sections(doc) == []

    def test_numbered_subheading(self) -> None:
        doc = make_doc(sections=[
            S("Abstract", 1, 0), S("1.1 Background", 2, 5), S("References", 1, 20),
        ])
        assert check_required_sections(doc) == []

    def test_chinese_titles(self) -> None:
        doc = make_doc(sections=[
            S("摘要", 1, 0), S("緒論", 1, 5), S("參考文獻", 1, 20),
        ])
        assert check_required_sections(doc) == []

    def test_all_caps(self) -> None:
        doc = make_doc(sections=[
            S("ABSTRACT", 1, 0), S("INTRODUCTION", 1, 5), S("REFERENCES", 1, 20),
        ])
        assert check_required_sections(doc) == []

    def test_only_abstract_missing(self) -> None:
        doc = make_doc(sections=[S("Introduction", 1, 5), S("References", 1, 20)])
        details = check_required_sections(doc)
        assert len(details) == 1
        assert "Abstract" in details[0].message


# ─── font.abstract ────────────────────────────────────────────────────


class TestAbstractFont:
    def _basic_paras(self) -> list[Paragraph]:
        return [
            P(0, "Abstract", [R("Abstract", size=12.0, bold=True)], style="Heading 1"),
            P(1, "This is the abstract.", [R("This is the abstract.", italic=True)]),
            P(2, "Keywords: test, foo",
              [R("Keywords:", bold=True), R(" test, foo")]),
            P(3, "Introduction", [R("Introduction", size=12.0, bold=True)],
              style="Heading 1"),
        ]

    def _basic_secs(self) -> list[Section]:
        return [S("Abstract", 1, 0), S("Introduction", 1, 3)]

    def test_correct_italic(self) -> None:
        details = check_abstract_font(make_doc(
            paragraphs=self._basic_paras(), sections=self._basic_secs(),
        ))
        assert details == []

    def test_non_italic_flagged(self) -> None:
        paras = self._basic_paras()
        paras[1] = P(1, "This is the abstract.",
                     [R("This is the abstract.", italic=False)])
        details = check_abstract_font(make_doc(
            paragraphs=paras, sections=self._basic_secs(),
        ))
        assert len(details) >= 1
        # And the Keywords line must NOT be flagged.
        assert not any("Keywords" in (d.excerpt or "") for d in details)

    def test_inline_abstract_label_skipped(self) -> None:
        paras = [
            P(0, "ABSTRACT: This is the abstract text.", [
                R("ABSTRACT: ", bold=True, italic=False),
                R("This is the abstract text.", italic=True),
            ]),
            P(1, "Introduction", [R("Introduction", size=12.0, bold=True)],
              style="Heading 1"),
        ]
        secs = [S("Abstract", 1, 0, "inline_abstract"),
                S("Introduction", 1, 1)]
        assert check_abstract_font(make_doc(paragraphs=paras, sections=secs)) == []

    def test_inline_abstract_body_not_italic_flagged(self) -> None:
        paras = [
            P(0, "ABSTRACT: This is the abstract text.", [
                R("ABSTRACT: ", bold=True, italic=False),
                R("This is the abstract text.", italic=False),
            ]),
            P(1, "Introduction", [R("Introduction", size=12.0, bold=True)],
              style="Heading 1"),
        ]
        secs = [S("Abstract", 1, 0, "inline_abstract"),
                S("Introduction", 1, 1)]
        details = check_abstract_font(make_doc(paragraphs=paras, sections=secs))
        assert len(details) >= 1

    def test_no_abstract_section_graceful(self) -> None:
        details = check_abstract_font(make_doc(
            paragraphs=[P(0, "Hello")], sections=[S("Introduction", 1, 0)],
        ))
        assert details == []

    def test_unresolved_italic_not_flagged(self) -> None:
        paras = [
            P(0, "Abstract", [R("Abstract", size=12.0, bold=True)], style="Heading 1"),
            P(1, "Text here.", [Run(text="Text here.", font_name="Times New Roman",
                                     font_size_pt=10.0, bold=False, italic=None)]),
            P(2, "Introduction", [R("Introduction", size=12.0, bold=True)],
              style="Heading 1"),
        ]
        details = check_abstract_font(make_doc(
            paragraphs=paras,
            sections=[S("Abstract", 1, 0), S("Introduction", 1, 2)],
        ))
        assert details == []


# ─── font.heading ─────────────────────────────────────────────────────


class TestHeadingFont:
    def test_correct_h1(self) -> None:
        details = check_heading_font(make_doc(
            paragraphs=[P(0, "Introduction",
                          [R("Introduction", size=12.0, bold=True)],
                          style="Heading 1")],
            sections=[S("Introduction", 1, 0)],
        ))
        assert details == []

    def test_wrong_h1_size_flagged(self) -> None:
        details = check_heading_font(make_doc(
            paragraphs=[P(0, "Introduction",
                          [R("Introduction", size=14.0, bold=True)],
                          style="Heading 1")],
            sections=[S("Introduction", 1, 0)],
        ))
        assert len(details) >= 1

    def test_title_style_skipped(self) -> None:
        paras = [
            P(0, "My Paper", [R("My Paper", size=14.0, bold=True)], style="Title"),
            P(1, "Abstract", [R("Abstract", size=12.0, bold=True)], style="Heading 1"),
        ]
        details = check_heading_font(make_doc(
            paragraphs=paras,
            sections=[S("My Paper", 1, 0), S("Abstract", 1, 1)],
        ))
        assert not any("My Paper" in (d.excerpt or "") for d in details)

    def test_italic_h1_flagged(self) -> None:
        details = check_heading_font(make_doc(
            paragraphs=[P(0, "Introduction",
                          [R("Introduction", size=12.0, bold=True, italic=True)],
                          style="Heading 1")],
            sections=[S("Introduction", 1, 0)],
        ))
        assert len(details) >= 1
        assert any("italic" in (d.actual or "") for d in details)

    def test_correct_h2(self) -> None:
        details = check_heading_font(make_doc(
            paragraphs=[P(0, "Sub", [R("Sub", size=10.0, bold=True)],
                          style="Heading 2")],
            sections=[S("Sub", 2, 0)],
        ))
        assert details == []

    def test_level_3_skipped(self) -> None:
        details = check_heading_font(make_doc(
            paragraphs=[P(0, "L3",
                          [R("L3", size=10.0, bold=True, italic=True)],
                          style="Heading 3")],
            sections=[S("L3", 3, 0)],
        ))
        assert details == []

    def test_h1_not_bold_flagged(self) -> None:
        details = check_heading_font(make_doc(
            paragraphs=[P(0, "Methods",
                          [R("Methods", size=12.0, bold=False)],
                          style="Heading 1")],
            sections=[S("Methods", 1, 0)],
        ))
        assert len(details) >= 1


# ─── font.reference ───────────────────────────────────────────────────


class TestReferenceFont:
    def test_correct_9pt(self) -> None:
        paras = [
            P(10, "References", [R("References", size=12.0, bold=True)],
              style="Heading 1"),
            P(11, "Smith (2020). Journal.", [
                R("Smith (2020). ", size=9.0),
                R("Journal.", size=9.0, italic=True),
            ]),
        ]
        assert check_reference_font(make_doc(
            paragraphs=paras, sections=[S("References", 1, 10)],
        )) == []

    def test_wrong_size_flagged(self) -> None:
        paras = [
            P(10, "References", [R("References", size=12.0, bold=True)],
              style="Heading 1"),
            P(11, "Smith (2020).", [R("Smith (2020).", size=10.0)]),
        ]
        details = check_reference_font(make_doc(
            paragraphs=paras, sections=[S("References", 1, 10)],
        ))
        assert len(details) >= 1

    def test_appendix_not_flagged(self) -> None:
        paras = [
            P(10, "References", [R("References", size=12.0, bold=True)],
              style="Heading 1"),
            P(11, "Smith.", [R("Smith.", size=9.0)]),
            P(20, "Appendix", [R("Appendix", size=12.0, bold=True)],
              style="Heading 1"),
            P(21, "Appendix content.", [R("Appendix content.", size=10.0)]),
        ]
        details = check_reference_font(make_doc(
            paragraphs=paras,
            sections=[S("References", 1, 10), S("Appendix", 1, 20)],
        ))
        assert not any("Appendix" in (d.excerpt or "") for d in details)

    def test_no_references_section(self) -> None:
        assert check_reference_font(make_doc(
            paragraphs=[P(0, "Hello")], sections=[S("Introduction", 1, 0)],
        )) == []

    def test_italic_journal_name_not_flagged(self) -> None:
        paras = [
            P(10, "References", [R("References", size=12.0, bold=True)],
              style="Heading 1"),
            P(11, "Smith. Journal.",
              [R("Smith. ", size=9.0), R("Journal.", size=9.0, italic=True)]),
        ]
        assert check_reference_font(make_doc(
            paragraphs=paras, sections=[S("References", 1, 10)],
        )) == []


# ─── font.title ───────────────────────────────────────────────────────


class TestTitleFont:
    def test_correct_title(self) -> None:
        paras = [
            P(0, "My Paper Title",
              [R("My Paper Title", size=14.0, bold=True)], style="Title"),
            P(1, "Abstract", [R("Abstract", size=12.0, bold=True)],
              style="Heading 1"),
        ]
        assert check_title_font(make_doc(
            paragraphs=paras,
            sections=[S("My Paper Title", 1, 0), S("Abstract", 1, 1)],
        )) == []

    def test_wrong_font_flagged(self) -> None:
        paras = [
            P(0, "My Paper Title",
              [R("My Paper Title", font="Arial", size=14.0, bold=True)],
              style="Title"),
            P(1, "Abstract", [R("Abstract", size=12.0, bold=True)],
              style="Heading 1"),
        ]
        details = check_title_font(make_doc(
            paragraphs=paras,
            sections=[S("My Paper Title", 1, 0), S("Abstract", 1, 1)],
        ))
        assert len(details) >= 1

    def test_inherited_size_wrong_font_flagged(self) -> None:
        paras = [
            P(0, "My Paper",
              [Run(text="My Paper", font_name="Arial", font_size_pt=None,
                   bold=True, italic=False)], style="Title"),
            P(1, "Abstract", [R("Abstract", size=12.0, bold=True)],
              style="Heading 1"),
        ]
        details = check_title_font(make_doc(
            paragraphs=paras,
            sections=[S("My Paper", 1, 0), S("Abstract", 1, 1)],
        ))
        assert len(details) >= 1

    def test_inherited_size_correct_font_passes(self) -> None:
        paras = [
            P(0, "My Paper",
              [Run(text="My Paper", font_name="Times New Roman",
                   font_size_pt=None, bold=True, italic=False)], style="Title"),
            P(1, "Abstract", [R("Abstract", size=12.0, bold=True)],
              style="Heading 1"),
        ]
        assert check_title_font(make_doc(
            paragraphs=paras,
            sections=[S("My Paper", 1, 0), S("Abstract", 1, 1)],
        )) == []

    def test_front_matter_title_heuristic(self) -> None:
        paras = [
            P(0, "My Paper Title",
              [R("My Paper Title", size=14.0, bold=True)]),
            P(1, "Author Name", [R("Author Name", size=10.0)]),
            P(2, "Abstract", [R("Abstract", size=12.0, bold=True)],
              style="Heading 1"),
        ]
        details = check_title_font(make_doc(
            paragraphs=paras, sections=[S("Abstract", 1, 2)],
        ))
        assert details == []
        assert not any(
            "Author" in (d.excerpt or "") or "University" in (d.excerpt or "")
            for d in details
        )

    def test_misapplied_title_in_body_skipped(self) -> None:
        paras = [
            P(0, "My Paper", [R("My Paper", size=14.0, bold=True)], style="Title"),
            P(1, "Abstract", [R("Abstract", size=12.0, bold=True)],
              style="Heading 1"),
            P(2, "Body text.", [R("Body text.", size=10.0)]),
            P(5, "Oops Title",
              [R("Oops", font="Arial", size=10.0)], style="Title"),
            P(6, "More body.", [R("More body.", size=10.0)]),
        ]
        details = check_title_font(make_doc(
            paragraphs=paras,
            sections=[S("My Paper", 1, 0), S("Abstract", 1, 1)],
        ))
        assert not any("Oops" in (d.excerpt or "") for d in details)

    def test_no_sections_no_check(self) -> None:
        assert check_title_font(make_doc(
            paragraphs=[P(0, "Something",
                          [R("Something", size=14.0, bold=True)])],
        )) == []

    def test_non_title_like_front_matter_skipped(self) -> None:
        paras = [
            P(0, "My Paper", [R("My Paper", size=14.0, bold=True)]),
            P(1, "Subtitle", [R("Subtitle", size=14.0, bold=True)]),
            P(2, "John Doe", [R("John Doe", font="Arial", size=10.0)]),
            P(3, "Abstract", [R("Abstract", size=12.0, bold=True)],
              style="Heading 1"),
        ]
        details = check_title_font(make_doc(
            paragraphs=paras, sections=[S("Abstract", 1, 3)],
        ))
        assert not any("John" in (d.excerpt or "") for d in details)
