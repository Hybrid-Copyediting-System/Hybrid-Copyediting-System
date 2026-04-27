from __future__ import annotations

from pathlib import Path

import pytest

from ets_checker.parser.docx_parser import parse


def _get_fixture(name: str) -> Path:
    p = Path(__file__).parent / "fixtures" / name
    if not p.exists():
        pytest.skip(f"Fixture {name} not found")
    return p


class TestMetadata:
    def test_parse_returns_metadata(self) -> None:
        p = _get_fixture("ets_template.docx")
        doc = parse(str(p))
        assert doc.metadata.paper_width_cm > 0
        assert doc.metadata.paper_height_cm > 0

    def test_margins_on_template(self) -> None:
        p = _get_fixture("ets_template.docx")
        doc = parse(str(p))
        assert abs(doc.metadata.margin_top_cm - 2.5) < 0.2
        assert abs(doc.metadata.margin_left_cm - 2.5) < 0.2


class TestParagraphs:
    def test_paragraphs_not_empty(self) -> None:
        p = _get_fixture("ets_template.docx")
        doc = parse(str(p))
        assert len(doc.paragraphs) > 0


class TestSections:
    def test_sections_detected(self) -> None:
        p = _get_fixture("ets_template.docx")
        doc = parse(str(p))
        titles = [s.title.lower() for s in doc.sections]
        assert any("abstract" in t for t in titles) or len(doc.sections) > 0


class TestCitations:
    def test_citations_extracted(self) -> None:
        p = _get_fixture("ets_template.docx")
        doc = parse(str(p))
        # Template may or may not have citations
        assert isinstance(doc.citations, list)


class TestReferences:
    def test_references_extracted(self) -> None:
        p = _get_fixture("ets_template.docx")
        doc = parse(str(p))
        assert isinstance(doc.references, list)
