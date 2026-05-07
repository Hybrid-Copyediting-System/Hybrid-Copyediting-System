"""Pytest coverage for ``rules.citation.check_cross_reference`` and
``check_et_al_usage``.

These tests exercise the cross-check logic directly using synthetic
``ParsedDocument`` objects, so behaviour can be verified without needing
representative docx fixtures for every edge case.
"""
from __future__ import annotations

import pytest

from ets_checker.models import (
    Citation,
    DocumentMetadata,
    ParsedDocument,
    Reference,
)
from ets_checker.rules.citation import check_cross_reference, check_et_al_usage


def _doc(
    *,
    citations: list[Citation] | None = None,
    references: list[Reference] | None = None,
) -> ParsedDocument:
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
        paragraphs=[],
        sections=[],
        citations=citations or [],
        references=references or [],
        figures=[],
        tables=[],
    )


def _cite(
    surname: str,
    year: str,
    *,
    suffix: str | None = None,
    has_et_al: bool = False,
    extra_authors: list[str] | None = None,
    paragraph_index: int = 1,
) -> Citation:
    authors = [surname] + (extra_authors or [])
    return Citation(
        raw_text=f"{surname} ({year}{suffix or ''})",
        authors=authors,
        year=year,
        year_suffix=suffix,
        has_et_al=has_et_al,
        citation_type="parenthetical",
        paragraph_index=paragraph_index,
    )


def _ref(
    index: int,
    surname: str,
    year: str,
    *,
    suffix: str | None = None,
    author_count: int = 1,
    paragraph_index: int = 100,
    raw_text: str | None = None,
) -> Reference:
    return Reference(
        index=index,
        raw_text=raw_text or f"{surname} ({year}{suffix or ''}). A paper. Journal.",
        first_author_surname=surname,
        year=year,
        year_suffix=suffix,
        parse_confidence=1.0,
        paragraph_index=paragraph_index,
        author_count=author_count,
    )


# ─── orphans ──────────────────────────────────────────────────────────


class TestOrphanCitations:
    def test_orphan_citation_reported(self) -> None:
        doc = _doc(
            citations=[_cite("Smith", "2020")],
            references=[],
        )
        details = check_cross_reference(doc)
        assert len(details) == 1
        assert "no matching reference" in details[0].message
        assert details[0].excerpt == "Smith (2020)"

    def test_exact_match_no_warning(self) -> None:
        doc = _doc(
            citations=[_cite("Smith", "2020")],
            references=[_ref(1, "Smith", "2020")],
        )
        assert check_cross_reference(doc) == []

    def test_orphan_count_capped(self) -> None:
        # 25 distinct orphans → 20 individual + 1 "and N more" detail.
        cites = [_cite(f"Author{i}", "2020") for i in range(25)]
        details = check_cross_reference(_doc(citations=cites))
        more = [d for d in details if "more orphan" in d.message]
        assert len(more) == 1
        assert "5 more" in more[0].message


# ─── year mismatches ─────────────────────────────────────────────────


class TestYearMismatch:
    def test_year_mismatch_flagged(self) -> None:
        doc = _doc(
            citations=[_cite("Smith", "2019")],
            references=[_ref(1, "Smith", "2020")],
        )
        details = check_cross_reference(doc)
        assert len(details) == 1
        assert "year mismatch" in details[0].message.lower()

    def test_year_suffix_mismatch_flagged(self) -> None:
        doc = _doc(
            citations=[_cite("Smith", "2020", suffix="a")],
            references=[_ref(1, "Smith", "2020", suffix="b")],
        )
        details = check_cross_reference(doc)
        assert len(details) == 1
        assert "suffix mismatch" in details[0].message.lower()

    def test_far_year_diff_flagged_as_orphan(self) -> None:
        # Diff > 5 years AND authorship matches → still likely different person.
        # Two findings expected: the orphan citation, plus the now-uncited reference.
        doc = _doc(
            citations=[_cite("Smith", "2019")],
            references=[_ref(1, "Smith", "2010")],
        )
        details = check_cross_reference(doc)
        orphans = [d for d in details if "no matching reference" in d.message]
        uncited = [d for d in details if "not cited" in d.message]
        assert len(orphans) == 1
        assert len(uncited) == 1

    def test_missing_suffix_with_multiple_year_matches(self) -> None:
        """When the citation drops the suffix and multiple refs share the year,
        the message should enumerate the candidates."""
        doc = _doc(
            citations=[_cite("Smith", "2020")],
            references=[
                _ref(1, "Smith", "2020", suffix="a"),
                _ref(2, "Smith", "2020", suffix="b"),
            ],
        )
        details = check_cross_reference(doc)
        # Should produce a year-suffix mismatch listing both candidates.
        msg = " ".join(d.message for d in details)
        assert "2020a" in msg and "2020b" in msg


# ─── normalisation / institutional / suffix-match ───────────────────


class TestSurnameNormalisation:
    def test_diacritics_normalised(self) -> None:
        doc = _doc(
            citations=[_cite("García", "2020")],
            references=[_ref(1, "Garcia", "2020")],
        )
        assert check_cross_reference(doc) == []

    def test_institutional_prefix_match(self) -> None:
        long_name = "State Council of the People's Republic of China"
        doc = _doc(
            citations=[_cite("State Council", "2017")],
            references=[_ref(1, long_name, "2017")],
        )
        # Exact prefix match → no error reported.
        details = check_cross_reference(doc)
        # No warning for the citation; ref is also considered cited.
        assert all("State Council" not in (d.excerpt or "") for d in details)
        # The reference should not be flagged as uncited either.
        assert not any("not cited" in d.message for d in details)

    def test_multiword_surname_suffix_match_warns(self) -> None:
        """Citation 'Hashim (2020)' against ref 'Salah Hashim (2020)' — the
        surname tail matches; rule warns about inconsistency but still treats
        the reference as cited."""
        doc = _doc(
            citations=[_cite("Hashim", "2020")],
            references=[_ref(1, "Salah Hashim", "2020")],
        )
        details = check_cross_reference(doc)
        assert len(details) == 1
        assert "surname inconsistency" in details[0].message.lower()
        # And not as an uncited reference.
        assert not any("not cited" in d.message for d in details)


# ─── near-miss ──────────────────────────────────────────────────────


class TestNearMissDetection:
    def test_single_char_typo_detected(self) -> None:
        doc = _doc(
            citations=[_cite("Smitn", "2020")],  # typo for Smith
            references=[_ref(1, "Smith", "2020")],
        )
        details = check_cross_reference(doc)
        assert len(details) == 1
        assert "spelling" in details[0].message.lower()

    def test_too_short_no_near_miss(self) -> None:
        # Names < 3 chars don't trigger near-miss; we get a true orphan.
        doc = _doc(
            citations=[_cite("Wu", "2020")],
            references=[_ref(1, "Xu", "2020")],
        )
        details = check_cross_reference(doc)
        assert len(details) == 2  # orphan + uncited ref
        orphans = [d for d in details if "no matching reference" in d.message]
        assert len(orphans) == 1


# ─── uncited references ─────────────────────────────────────────────


class TestUncitedReferences:
    def test_uncited_reference_flagged(self) -> None:
        doc = _doc(
            citations=[],
            references=[_ref(1, "Smith", "2020")],
        )
        details = check_cross_reference(doc)
        assert len(details) == 1
        assert "not cited" in details[0].message


# ─── unparseable references ─────────────────────────────────────────


class TestUnparseableReferences:
    def test_low_confidence_reference_flagged(self) -> None:
        bad = Reference(
            index=1,
            raw_text="garbled text without an obvious author",
            first_author_surname=None,
            year=None,
            year_suffix=None,
            parse_confidence=0.1,
            paragraph_index=10,
        )
        details = check_cross_reference(_doc(references=[bad]))
        assert any(
            "could not be parsed" in d.message for d in details
        )


# ─── et al. usage ────────────────────────────────────────────────────


class TestEtAlUsage:
    def test_et_al_with_two_authors_flagged(self) -> None:
        doc = _doc(
            citations=[_cite("Smith", "2020", has_et_al=True)],
            references=[_ref(1, "Smith", "2020", author_count=2)],
        )
        details = check_et_al_usage(doc)
        assert len(details) == 1
        assert "et al." in details[0].message

    def test_three_plus_authors_should_use_et_al(self) -> None:
        doc = _doc(
            citations=[_cite("Smith", "2020", has_et_al=False)],
            references=[_ref(1, "Smith", "2020", author_count=4)],
        )
        details = check_et_al_usage(doc)
        assert len(details) == 1
        assert "should use 'et al." in details[0].message

    def test_correct_usage_passes(self) -> None:
        # 4 authors + et al. — correct.
        doc = _doc(
            citations=[_cite("Smith", "2020", has_et_al=True)],
            references=[_ref(1, "Smith", "2020", author_count=4)],
        )
        assert check_et_al_usage(doc) == []
