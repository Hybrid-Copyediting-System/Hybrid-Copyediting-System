from __future__ import annotations

from pathlib import Path

import pytest

from ets_checker.parser.docx_parser import parse
from ets_checker.rules.runner import run


def _get_fixture(name: str) -> Path:
    p = Path(__file__).parent / "fixtures" / name
    if not p.exists():
        pytest.skip(f"Fixture {name} not found")
    return p


class TestRulesOnTemplate:
    def test_all_rules_run(self) -> None:
        p = _get_fixture("ets_template.docx")
        doc = parse(str(p))
        report = run(doc, "ets_template.docx")
        assert report.summary.total_checks == 8

    def test_most_rules_pass_on_template(self) -> None:
        p = _get_fixture("ets_template.docx")
        doc = parse(str(p))
        report = run(doc, "ets_template.docx")
        assert report.summary.passed >= 5


class TestBrokenMargins:
    def test_margins_fail(self) -> None:
        p = _get_fixture("broken_margins.docx")
        doc = parse(str(p))
        report = run(doc, "broken_margins.docx")
        margin_result = next(
            (r for r in report.results if r.rule_id == "layout.margins"), None
        )
        assert margin_result is not None
        assert margin_result.status == "fail"


class TestBrokenAbstract:
    def test_abstract_length_fail(self) -> None:
        p = _get_fixture("broken_abstract.docx")
        doc = parse(str(p))
        report = run(doc, "broken_abstract.docx")
        result = next(
            (r for r in report.results if r.rule_id == "structure.abstract_length"),
            None,
        )
        assert result is not None
        assert result.status == "fail"
