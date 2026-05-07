"""Pytest coverage for the async ``check_reference_links`` rule.

Uses ``respx`` to mock the underlying ``httpx.AsyncClient`` so the tests
are deterministic and run offline.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from ets_checker.models import (
    DocumentMetadata,
    ParsedDocument,
    Reference,
)
from ets_checker.rules import reference_links as rl_module
from ets_checker.rules.reference_links import check_reference_links


def _doc_with_refs(refs: list[Reference]) -> ParsedDocument:
    return ParsedDocument(
        metadata=DocumentMetadata(
            paper_size="A4", paper_width_cm=21, paper_height_cm=29.7,
            margin_top_cm=2.5, margin_bottom_cm=2.5,
            margin_left_cm=2.5, margin_right_cm=2.5,
            default_line_spacing=1.0,
        ),
        paragraphs=[], sections=[], citations=[],
        references=refs, figures=[], tables=[],
    )


def _ref(idx: int, *, urls: list[str] | None = None, doi: str | None = None) -> Reference:
    return Reference(
        index=idx,
        raw_text=f"Smith ({2000 + idx}). Paper #{idx}.",
        first_author_surname="Smith",
        year=str(2000 + idx),
        year_suffix=None,
        parse_confidence=1.0,
        paragraph_index=10 + idx,
        doi=doi,
        urls=urls or [],
    )


# ─── happy paths ────────────────────────────────────────────────────


class TestReferenceLinks:
    def test_no_links_no_findings(self) -> None:
        doc = _doc_with_refs([_ref(1)])
        details = asyncio.run(check_reference_links(doc))
        assert details == []

    @respx.mock
    def test_reachable_url_passes(self) -> None:
        respx.head("https://example.com/paper").mock(
            return_value=httpx.Response(200)
        )
        doc = _doc_with_refs([_ref(1, urls=["https://example.com/paper"])])
        details = asyncio.run(check_reference_links(doc))
        assert details == []

    @respx.mock
    def test_404_flagged(self) -> None:
        respx.head("https://example.com/missing").mock(
            return_value=httpx.Response(404)
        )
        doc = _doc_with_refs([_ref(1, urls=["https://example.com/missing"])])
        details = asyncio.run(check_reference_links(doc))
        assert len(details) == 1
        assert "404" in details[0].message
        assert details[0].actual == "https://example.com/missing"

    @respx.mock
    def test_405_falls_back_to_get(self) -> None:
        # HEAD returns 405; GET succeeds. Must be reachable, not flagged.
        respx.head("https://example.com/no-head").mock(
            return_value=httpx.Response(405)
        )
        respx.get("https://example.com/no-head").mock(
            return_value=httpx.Response(200)
        )
        doc = _doc_with_refs([_ref(1, urls=["https://example.com/no-head"])])
        assert asyncio.run(check_reference_links(doc)) == []

    @respx.mock
    def test_doi_url_built_correctly(self) -> None:
        route = respx.head("https://doi.org/10.1234/test").mock(
            return_value=httpx.Response(200)
        )
        doc = _doc_with_refs([_ref(1, doi="10.1234/test")])
        asyncio.run(check_reference_links(doc))
        assert route.called

    def test_unsupported_scheme_flagged(self) -> None:
        # file:// must be rejected up-front without any HTTP traffic.
        doc = _doc_with_refs([_ref(1, urls=["file:///etc/passwd"])])
        details = asyncio.run(check_reference_links(doc))
        assert len(details) == 1
        assert "unsupported" in details[0].message.lower()

    @respx.mock
    def test_5xx_retried_then_flagged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Persistent 500s must be retried up to MAX_RETRIES then reported."""
        # Eliminate the backoff sleep so retries don't slow the test suite.
        monkeypatch.setattr(rl_module, "RETRY_BASE_DELAY", 0.0)

        route = respx.head("https://example.com/flaky").mock(
            return_value=httpx.Response(500)
        )
        doc = _doc_with_refs([_ref(1, urls=["https://example.com/flaky"])])
        details = asyncio.run(check_reference_links(doc))
        assert route.call_count == rl_module.MAX_RETRIES
        assert len(details) == 1
        assert "500" in details[0].message

    @respx.mock
    def test_5xx_then_recovers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A 500 followed by a 200 must be treated as reachable (no finding)."""
        monkeypatch.setattr(rl_module, "RETRY_BASE_DELAY", 0.0)
        respx.head("https://example.com/recovers").mock(
            side_effect=[httpx.Response(500), httpx.Response(200)]
        )
        doc = _doc_with_refs([_ref(1, urls=["https://example.com/recovers"])])
        assert asyncio.run(check_reference_links(doc)) == []

    @respx.mock
    def test_timeout_flagged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(rl_module, "RETRY_BASE_DELAY", 0.0)
        respx.head("https://example.com/timeout").mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        doc = _doc_with_refs([_ref(1, urls=["https://example.com/timeout"])])
        details = asyncio.run(check_reference_links(doc))
        assert len(details) == 1
        assert "timed out" in details[0].message

    @respx.mock
    def test_progress_callback_fires(self) -> None:
        respx.head("https://example.com/a").mock(return_value=httpx.Response(200))
        respx.head("https://example.com/b").mock(return_value=httpx.Response(200))

        events: list[tuple[int, int]] = []

        async def cb(done: int, total: int) -> None:
            events.append((done, total))

        doc = _doc_with_refs([
            _ref(1, urls=["https://example.com/a"]),
            _ref(2, urls=["https://example.com/b"]),
        ])
        asyncio.run(check_reference_links(doc, on_link_progress=cb))

        # Two URLs → two callback invocations; final must report (2, 2).
        assert len(events) == 2
        assert events[-1] == (2, 2)
        # Total must remain consistent across all events.
        assert all(total == 2 for _, total in events)
        # `done` is monotonically increasing.
        assert [done for done, _ in events] == sorted(done for done, _ in events)
