from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ets_checker.models import DocumentMetadata, ParsedDocument
from ets_checker.parser.docx_parser import parse
from ets_checker.rules.runner import run


def _get_fixture(name: str) -> Path:
    p = Path(__file__).parent / "fixtures" / name
    if not p.exists():
        pytest.skip(f"Fixture {name} not found")
    return p


def _build_minimal_doc() -> ParsedDocument:
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
            has_page_numbers=None,
        ),
        paragraphs=[],
        sections=[],
        citations=[],
        references=[],
        figures=[],
        tables=[],
    )


class TestRulesOnTemplate:
    def test_all_rules_run(self) -> None:
        p = _get_fixture("ets_template.docx")
        doc = parse(str(p))
        report = run(doc, "ets_template.docx")
        assert report.summary.total_checks == 21

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


class TestRunAsync:
    def test_total_checks_includes_async_rules(self) -> None:
        """run_async() report includes sync and async rules combined."""
        from ets_checker.rules.runner import _ASYNC_REGISTRY, _REGISTRY, run_async

        doc = _build_minimal_doc()
        report = asyncio.run(run_async(doc, "test.docx"))
        assert report.summary.total_checks == len(_REGISTRY) + len(_ASYNC_REGISTRY)

    def test_progress_callback_fires_per_rule(self) -> None:
        """Progress callback receives one 'rule' event per sync rule."""
        from ets_checker.rules.runner import _REGISTRY, run_async

        events: list[dict] = []

        async def _cb(evt: dict) -> None:
            events.append(evt)

        asyncio.run(run_async(_build_minimal_doc(), "test.docx", on_progress=_cb))
        rule_events = [e for e in events if e.get("phase") == "rule"]
        assert len(rule_events) == len(_REGISTRY)

    def test_links_start_phase_emitted(self) -> None:
        """links_start phase event is emitted when async rules are registered."""
        from ets_checker.rules.runner import _ASYNC_REGISTRY, run_async

        if not _ASYNC_REGISTRY:
            pytest.skip("No async rules registered")

        events: list[dict] = []

        async def _cb(evt: dict) -> None:
            events.append(evt)

        asyncio.run(run_async(_build_minimal_doc(), "test.docx", on_progress=_cb))
        phases = [e.get("phase") for e in events]
        assert "links_start" in phases

    def test_run_async_without_callback_does_not_raise(self) -> None:
        """run_async() with on_progress=None completes without error."""
        from ets_checker.rules.runner import _REGISTRY, _ASYNC_REGISTRY, run_async

        report = asyncio.run(run_async(_build_minimal_doc(), "test.docx", on_progress=None))
        assert report.summary.total_checks == len(_REGISTRY) + len(_ASYNC_REGISTRY)

    def test_step_numbers_are_sequential(self) -> None:
        """Step numbers in progress events are 1-indexed and non-decreasing."""
        from ets_checker.rules.runner import run_async

        events: list[dict] = []

        async def _cb(evt: dict) -> None:
            events.append(evt)

        asyncio.run(run_async(_build_minimal_doc(), "test.docx", on_progress=_cb))
        steps = [e["step"] for e in events if "step" in e]
        if steps:
            assert steps[0] >= 1
            assert all(b >= a for a, b in zip(steps, steps[1:]))
