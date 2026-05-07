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
        # ``run()`` is sync so it only executes the sync rule registry. Total
        # checks must equal that registry's size — no async rules are included.
        from ets_checker.rules.runner import _REGISTRY

        p = _get_fixture("ets_template.docx")
        doc = parse(str(p))
        report = run(doc, "ets_template.docx")
        assert report.summary.total_checks == len(_REGISTRY.sync_rules)

    def test_most_rules_pass_on_template(self) -> None:
        from ets_checker.rules.runner import _REGISTRY

        p = _get_fixture("ets_template.docx")
        doc = parse(str(p))
        report = run(doc, "ets_template.docx")
        # The vetted ET&S template should pass the bulk of the rules — more
        # than two-thirds. A weak ``>= 5`` would silently mask regressions.
        assert report.summary.passed >= int(len(_REGISTRY.sync_rules) * 2 / 3)


class TestBrokenMargins:
    def test_margins_fail(self) -> None:
        p = _get_fixture("broken_margins.docx")
        doc = parse(str(p))
        # Sanity check: the fixture really is set up with 4 cm margins so a
        # status==fail outcome is provably caused by the margin numbers and
        # not by a missing-section or parser failure.
        assert abs(doc.metadata.margin_top_cm - 4.0) < 0.05
        assert abs(doc.metadata.margin_left_cm - 4.0) < 0.05

        report = run(doc, "broken_margins.docx")
        margin_result = next(
            (r for r in report.results if r.rule_id == "layout.margins"), None
        )
        assert margin_result is not None
        assert margin_result.status == "fail"
        # The detail message should reference the actual measured margin, not
        # some other unrelated reason that also happens to fail the rule.
        all_text = " ".join(d.message for d in margin_result.details)
        assert any(
            keyword in all_text.lower()
            for keyword in ("margin", "top", "bottom", "left", "right")
        ), f"margin failure message did not mention margins: {all_text!r}"
        # The fixture uses 4.0 cm margins. At least one detail must surface
        # that measured value so we know the rule reports the real numbers
        # rather than failing for some unrelated reason.
        rendered = " ".join(
            f"{d.message} {d.actual} {d.expected}" for d in margin_result.details
        )
        assert "4" in rendered, (
            f"margin detail did not surface the fixture's 4.0 cm value: {rendered!r}"
        )


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
        # The fixture deliberately has 260 words. Verify the rule reports
        # exactly that count via its ``actual`` field — a generic word-count
        # failure for some other reason wouldn't satisfy this.
        actuals = [str(d.actual or "") for d in result.details]
        assert any("260" in a for a in actuals), (
            f"abstract-length detail.actual did not contain measured count 260: {actuals!r}"
        )


class TestRunAsync:
    def test_total_checks_includes_async_rules(self) -> None:
        """run_async() report includes sync and async rules combined."""
        from ets_checker.rules.runner import _REGISTRY, run_async

        doc = _build_minimal_doc()
        report = asyncio.run(run_async(doc, "test.docx"))
        assert report.summary.total_checks == len(_REGISTRY.sync_rules) + len(_REGISTRY.async_rules)

    def test_progress_callback_fires_per_rule(self) -> None:
        """Progress callback receives one 'rule' event per sync rule."""
        from ets_checker.rules.runner import _REGISTRY, run_async

        events: list[dict] = []

        async def _cb(evt: dict) -> None:
            events.append(evt)

        asyncio.run(run_async(_build_minimal_doc(), "test.docx", on_progress=_cb))
        rule_events = [e for e in events if e.get("phase") == "rule"]
        assert len(rule_events) == len(_REGISTRY.sync_rules)

    def test_links_start_phase_emitted(self) -> None:
        """links_start phase event is emitted when async rules are registered."""
        from ets_checker.rules.runner import _REGISTRY, run_async

        if not _REGISTRY.async_rules:
            pytest.skip("No async rules registered")

        events: list[dict] = []

        async def _cb(evt: dict) -> None:
            events.append(evt)

        asyncio.run(run_async(_build_minimal_doc(), "test.docx", on_progress=_cb))
        phases = [e.get("phase") for e in events]
        assert "links_start" in phases

    def test_run_async_without_callback_does_not_raise(self) -> None:
        """run_async() with on_progress=None completes without error AND runs every rule."""
        from ets_checker.rules.runner import _REGISTRY, run_async

        report = asyncio.run(run_async(_build_minimal_doc(), "test.docx", on_progress=None))
        expected_total = len(_REGISTRY.sync_rules) + len(_REGISTRY.async_rules)
        assert report.summary.total_checks == expected_total

        # Every registered rule must appear in the result set — a silent skip
        # would otherwise hide behind the bare "did not raise" assertion.
        result_ids = {r.rule_id for r in report.results}
        registered_ids = {rid for rid, *_ in _REGISTRY.sync_rules} | {
            rid for rid, *_ in _REGISTRY.async_rules
        }
        assert result_ids == registered_ids

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
