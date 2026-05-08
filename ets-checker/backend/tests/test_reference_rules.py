"""Tests for the new reference-list rules.

Covers ``reference.page_number_complete`` (and later
``reference.doi_or_url``, ``reference.apa_format``) using synthetic
``ParsedDocument`` instances so each rule can be exercised in isolation.
"""
from __future__ import annotations

from ets_checker.models import (
    DocumentMetadata,
    ParsedDocument,
    Reference,
)
from ets_checker.rules.reference import (
    check_apa_format,
    check_disambiguate,
    check_doi_or_url,
    check_page_number_complete,
)


def _doc(*, references: list[Reference]) -> ParsedDocument:
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
        citations=[],
        references=references,
        figures=[],
        tables=[],
    )


def _ref(
    idx: int,
    raw_text: str,
    *,
    doi: str | None = None,
    urls: list[str] | None = None,
    parse_confidence: float = 1.0,
    surname: str = "Smith",
    year: str = "2020",
    year_suffix: str | None = None,
) -> Reference:
    return Reference(
        index=idx,
        raw_text=raw_text,
        first_author_surname=surname,
        year=year,
        year_suffix=year_suffix,
        parse_confidence=parse_confidence,
        paragraph_index=100 + idx,
        doi=doi,
        urls=urls or [],
    )


class TestPageNumberComplete:
    def test_full_range_passes(self) -> None:
        r = _ref(1, "Smith, J. (2020). A paper. Journal, 5(2), 129–165.")
        assert check_page_number_complete(_doc(references=[r])) == []

    def test_abbreviated_range_flagged(self) -> None:
        r = _ref(1, "Smith, J. (2020). A paper. Journal, 5(2), 129–65.")
        details = check_page_number_complete(_doc(references=[r]))
        assert len(details) == 1
        assert "129–65" in details[0].actual
        assert details[0].expected == "129–165"

    def test_abbreviated_range_three_digit(self) -> None:
        # 1245-67 → 1267
        r = _ref(1, "Smith, J. (2020). A paper. Journal, 5(2), 1245–67.")
        details = check_page_number_complete(_doc(references=[r]))
        assert details and details[0].expected == "1245–1267"

    def test_year_range_in_parens_ignored(self) -> None:
        # "(2018-2020)" must not be flagged as a page range
        r = _ref(1, "Smith, J. (2020). A paper covering (2018-2010). Journal, 5, 100.")
        assert check_page_number_complete(_doc(references=[r])) == []

    def test_ascending_range_passes(self) -> None:
        # End larger than start, even with fewer-digit start, is fine
        r = _ref(1, "Smith, J. (2020). A paper. Journal, 5(2), 9–145.")
        assert check_page_number_complete(_doc(references=[r])) == []

    def test_equal_digit_count_descending_not_flagged(self) -> None:
        # 145–129 is just wrong, but not the AQF-named "abbreviated" pattern;
        # we only flag the unambiguous case (fewer digits in end-page).
        r = _ref(1, "Smith, J. (2020). A paper. Journal, 5(2), 145–129.")
        assert check_page_number_complete(_doc(references=[r])) == []

    def test_multiple_refs_each_reported(self) -> None:
        r1 = _ref(1, "A. (2020). T. J, 1(1), 100–22.")
        r2 = _ref(2, "B. (2021). T. J, 2(1), 250–80.")
        details = check_page_number_complete(_doc(references=[r1, r2]))
        assert len(details) == 2

    def test_doi_digit_range_not_flagged(self) -> None:
        # 10.1234/journal.567-89.abc has "567-89" inside the DOI path; the
        # rule must not interpret that as abbreviated pagination.
        r = _ref(
            1,
            "Smith, J. (2020). A paper. Journal, 5(2), 129–145. "
            "https://doi.org/10.1234/journal.567-89.abc",
        )
        assert check_page_number_complete(_doc(references=[r])) == []

    def test_year_shorthand_2018_19_not_flagged(self) -> None:
        r = _ref(
            1,
            "Smith, J. (2020). The 2018-19 academic year. Journal, 5(2), 1–10.",
        )
        assert check_page_number_complete(_doc(references=[r])) == []

    def test_year_shorthand_2018_9_not_flagged(self) -> None:
        r = _ref(
            1,
            "Smith, J. (2020). The 2018-9 study. Journal, 5(2), 1–10.",
        )
        assert check_page_number_complete(_doc(references=[r])) == []

    def test_doi_with_legit_abbreviated_page_still_flagged(self) -> None:
        # The DOI is excluded but the actual page range outside it is flagged.
        r = _ref(
            1,
            "Smith, J. (2020). A paper. Journal, 5(2), 129–65. "
            "https://doi.org/10.1234/abc.567-89",
        )
        details = check_page_number_complete(_doc(references=[r]))
        assert len(details) == 1
        assert details[0].expected == "129–165"


class TestDoiOrUrl:
    def test_full_pagination_passes(self) -> None:
        r = _ref(1, "Smith, J. (2020). A paper. Journal, 5(2), 129–145.")
        assert check_doi_or_url(_doc(references=[r])) == []

    def test_doi_passes(self) -> None:
        r = _ref(
            1,
            "Smith, J. (2020). A paper. Journal. https://doi.org/10.1/abc",
            doi="10.1/abc",
        )
        assert check_doi_or_url(_doc(references=[r])) == []

    def test_url_passes(self) -> None:
        r = _ref(
            1,
            "Smith, J. (2020). A web piece. Site. https://example.org/x",
            urls=["https://example.org/x"],
        )
        assert check_doi_or_url(_doc(references=[r])) == []

    def test_journal_missing_pagination_and_doi_flagged(self) -> None:
        r = _ref(1, "Smith, J. (2020). Untraceable article. Some Journal.")
        details = check_doi_or_url(_doc(references=[r]))
        assert len(details) == 1
        assert "DOI" in details[0].message

    def test_book_excluded(self) -> None:
        r = _ref(1, "Smith, J. (2020). The big book. Routledge.")
        assert check_doi_or_url(_doc(references=[r])) == []

    def test_edited_volume_excluded(self) -> None:
        r = _ref(
            1,
            "Smith, J. (Eds.). (2020). A handbook. Springer.",
        )
        assert check_doi_or_url(_doc(references=[r])) == []

    def test_unparseable_skipped(self) -> None:
        r = _ref(
            1,
            "Garbage line that the parser failed on.",
            parse_confidence=0.2,
        )
        assert check_doi_or_url(_doc(references=[r])) == []

    def test_article_number_passes(self) -> None:
        r = _ref(
            1,
            "Smith, J. (2020). E-only paper. Journal, 12, Article 45.",
        )
        assert check_doi_or_url(_doc(references=[r])) == []

    def test_proceedings_excluded(self) -> None:
        r = _ref(
            1,
            "Smith, J. (2020). A talk. In Proceedings of the X Symposium.",
        )
        assert check_doi_or_url(_doc(references=[r])) == []

    def test_tech_report_excluded(self) -> None:
        r = _ref(
            1,
            "Smith, J. (2020). A study (Tech. Rep. No. 42). Lab name.",
        )
        assert check_doi_or_url(_doc(references=[r])) == []


class TestDisambiguate:
    def test_distinct_years_or_surnames_pass(self) -> None:
        refs = [
            _ref(1, "A. (2020).", surname="Smith", year="2020"),
            _ref(2, "B. (2020).", surname="Jones", year="2020"),
            _ref(3, "C. (2021).", surname="Smith", year="2021"),
        ]
        assert check_disambiguate(_doc(references=refs)) == []

    def test_collision_without_suffix_flagged(self) -> None:
        refs = [
            _ref(1, "Smith (2017). One.", surname="Smith", year="2017"),
            _ref(2, "Smith (2017). Two.", surname="Smith", year="2017"),
        ]
        details = check_disambiguate(_doc(references=refs))
        assert len(details) == 2
        assert all("year suffix" in d.message for d in details)

    def test_partial_suffix_flags_only_unsuffixed(self) -> None:
        refs = [
            _ref(1, "Smith (2017a).", surname="Smith", year="2017",
                 year_suffix="a"),
            _ref(2, "Smith (2017).", surname="Smith", year="2017"),
        ]
        details = check_disambiguate(_doc(references=refs))
        assert len(details) == 1
        assert "Reference #2" in details[0].location

    def test_distinct_suffixes_all_pass(self) -> None:
        refs = [
            _ref(1, "Smith (2017a).", surname="Smith", year="2017",
                 year_suffix="a"),
            _ref(2, "Smith (2017b).", surname="Smith", year="2017",
                 year_suffix="b"),
        ]
        assert check_disambiguate(_doc(references=refs)) == []

    def test_three_collisions_all_unsuffixed_all_flagged(self) -> None:
        refs = [
            _ref(i, f"Smith (2017). #{i}", surname="Smith", year="2017")
            for i in range(1, 4)
        ]
        details = check_disambiguate(_doc(references=refs))
        assert len(details) == 3

    def test_duplicate_suffixes_flagged(self) -> None:
        # Both labelled "2017a" — the suffixes exist but collide.
        refs = [
            _ref(1, "Smith (2017a). One.", surname="Smith", year="2017",
                 year_suffix="a"),
            _ref(2, "Smith (2017a). Two.", surname="Smith", year="2017",
                 year_suffix="a"),
        ]
        details = check_disambiguate(_doc(references=refs))
        assert len(details) == 2
        assert all("duplicates the suffix" in d.message for d in details)


class TestApaFormat:
    def test_well_formed_journal_passes(self) -> None:
        r = _ref(
            1,
            "Smith, J. (2020). A study of learning. Educational Technology, 5(2), 129–145.",
        )
        assert check_apa_format(_doc(references=[r])) == []

    def test_well_formed_book_passes(self) -> None:
        r = _ref(1, "Smith, J. (2020). The big book. Routledge.")
        assert check_apa_format(_doc(references=[r])) == []

    def test_missing_period_after_year_flagged(self) -> None:
        r = _ref(1, "Smith, J. (2020) A study of learning. Journal, 5(2), 1–10.")
        details = check_apa_format(_doc(references=[r]))
        assert any("missing '.' after year" in d.message for d in details)

    def test_missing_terminal_period_flagged(self) -> None:
        r = _ref(1, "Smith, J. (2020). A study of learning. Journal, 5(2), 1–10")
        details = check_apa_format(_doc(references=[r]))
        assert any("does not end with a period" in d.message for d in details)

    def test_url_ending_accepted(self) -> None:
        r = _ref(
            1,
            "Smith, J. (2020). A study. https://example.org/paper",
            urls=["https://example.org/paper"],
        )
        details = check_apa_format(_doc(references=[r]))
        # URL ending is fine — no missing-period complaint.
        assert not any("does not end with a period" in d.message for d in details)

    def test_unparseable_skipped(self) -> None:
        r = _ref(
            1,
            "Frag of text",
            parse_confidence=0.2,
        )
        # parse_confidence < 0.5 → other rules surface this; apa_format stays quiet.
        assert check_apa_format(_doc(references=[r])) == []

    def test_short_entry_flagged(self) -> None:
        r = _ref(1, "Smith. (2020).")
        details = check_apa_format(_doc(references=[r]))
        assert any("suspiciously short" in d.message for d in details)

    def test_n_d_year_with_period_passes(self) -> None:
        # Reference with "(n.d.)" must satisfy the period-after-year check too.
        r = _ref(1, "Smith, J. (n.d.). Untitled webpage. Site name.")
        details = check_apa_format(_doc(references=[r]))
        # Only the missing-period complaint would be triggered if (n.d.) was
        # not recognized as a year token.  Here the period IS present.
        assert not any("missing '.' after year" in d.message for d in details)

    def test_n_d_missing_period_flagged(self) -> None:
        r = _ref(1, "Smith, J. (n.d.) Untitled. Site name.")
        details = check_apa_format(_doc(references=[r]))
        assert any("missing '.' after year" in d.message for d in details)

    def test_cjk_reference_with_full_width_punctuation_passes(self) -> None:
        # CJK refs use full-width parens "（）" and full-width period "。"
        r = _ref(
            1,
            "王小明（2020）。學習動機與學業成就。教育心理學報，5(2)，1–10。",
            surname="王小明",
            year="2020",
        )
        details = check_apa_format(_doc(references=[r]))
        assert details == []
