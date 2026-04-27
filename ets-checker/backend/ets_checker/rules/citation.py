from __future__ import annotations

import re
import unicodedata

from ets_checker.models import CheckDetail, Locator, ParsedDocument
from ets_checker.rules.runner import register

MAX_REPORTED = 20

# Minimum length for institutional-author prefix matching; avoids false positives
# for very short surnames (e.g. "Li" matching "Lincoln").
_MIN_PREFIX_LEN = 6

# Suffix matching uses a lower threshold: a short surname being the tail of a
# multi-word surname (e.g. "Berg" from "Van der Berg") almost always indicates
# the same person, and both entries must also share the same year.
_MIN_SUFFIX_LEN = 4

# Strip pattern for surname normalisation: whitespace, hyphens, and all
# apostrophe variants (ASCII U+0027, smart U+2018/U+2019).
# Built with chr() so editors cannot silently convert the literal quotes.
_STRIP_RE = re.compile(r"[\s\-'" + chr(0x2018) + chr(0x2019) + r"]")


def _normalise_surname(s: str) -> str:
    # NFD decomposition strips combining diacritics (e.g. Bašić→Basic, Pérez→Perez)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    # Turkish dotless-i (U+0131) is a base letter not handled by NFD; map to plain i
    s = s.replace("ı", "i")
    return _STRIP_RE.sub("", s).lower()


def _find_prefix_match(
    cite_norm: str,
    year: str,
    suffix: str,
    surname_index: dict[str, list[tuple[str, str, int]]],
) -> tuple[str, str, str, int] | None:
    """Return (ref_norm, year, suffix, ref_pos) when cite_norm is a short-form
    prefix of a longer reference surname AND year/suffix match exactly.
    Used to match institutional authors cited in abbreviated form
    (e.g. 'State Council' → 'State Council of the People's Republic of China').
    """
    if len(cite_norm) < _MIN_PREFIX_LEN:
        return None
    for ref_norm, entries in surname_index.items():
        if ref_norm != cite_norm and ref_norm.startswith(cite_norm):
            for ref_year, ref_suffix, ref_pos in entries:
                if ref_year == year and ref_suffix == suffix:
                    return (ref_norm, ref_year, ref_suffix, ref_pos)
    return None


def _find_suffix_match(
    cite_norm: str,
    year: str,
    suffix: str,
    surname_index: dict[str, list[tuple[str, str, int]]],
) -> tuple[str, str, str, int] | None:
    """Return (ref_norm, year, suffix, ref_pos) when cite_norm matches the
    tail of a longer reference surname AND year/suffix match exactly.
    Catches multi-word surname inconsistencies where the citation uses only
    the last word (e.g. 'Hashim' citing 'Salah Hashim').
    """
    if len(cite_norm) < _MIN_SUFFIX_LEN:
        return None
    for ref_norm, entries in surname_index.items():
        if ref_norm != cite_norm and ref_norm.endswith(cite_norm):
            for ref_year, ref_suffix, ref_pos in entries:
                if ref_year == year and ref_suffix == suffix:
                    return (ref_norm, ref_year, ref_suffix, ref_pos)
    return None


@register("citation.cross_reference", "Citation", "Citation–reference cross-check", "error")
def check_cross_reference(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []

    # Exact-match index: (norm_surname, year, suffix) → ref position
    ref_index: dict[tuple[str, str, str], int] = {}
    # Surname-only index: norm_surname → [(year, suffix, ref_pos), ...]
    surname_index: dict[str, list[tuple[str, str, int]]] = {}

    for pos, r in enumerate(doc.references):
        if r.first_author_surname and r.year:
            norm = _normalise_surname(r.first_author_surname)
            key = (norm, r.year, r.year_suffix or "")
            ref_index[key] = pos
            surname_index.setdefault(norm, []).append((r.year, r.year_suffix or "", pos))

    cited_keys: set[tuple[str, str, str]] = set()
    orphan_count = 0
    year_mismatch_count = 0
    surname_mismatch_count = 0

    for c in doc.citations:
        if not c.authors:
            continue
        cite_norm = _normalise_surname(c.authors[0])
        cite_year = c.year
        cite_suffix = c.year_suffix or ""
        key = (cite_norm, cite_year, cite_suffix)

        if key in ref_index:
            cited_keys.add(key)
            continue

        # ── Year mismatch: same normalised surname, different year/suffix ─────
        if cite_norm in surname_index:
            entries = surname_index[cite_norm]
            # Report the first (and usually only) candidate; mark it as cited so
            # it does not also appear in the "uncited references" list.
            ref_year, ref_suffix, ref_pos = entries[0]
            ref = doc.references[ref_pos]
            ref_year_str = f"{ref_year}{ref_suffix}" if ref_suffix else ref_year
            cite_year_str = f"{cite_year}{cite_suffix}" if cite_suffix else cite_year
            cited_keys.add((cite_norm, ref_year, ref_suffix))
            year_mismatch_count += 1
            if year_mismatch_count <= MAX_REPORTED:
                # Distinguish between a true year change vs only a letter-suffix change
                if ref_year == cite_year:
                    msg = (
                        f"Citation year-suffix mismatch: '{c.raw_text}' cites {cite_year_str}, "
                        f"but Reference #{ref.index} ({ref.first_author_surname}) has {ref_year_str}"
                    )
                else:
                    msg = (
                        f"Citation year mismatch: '{c.raw_text}' cites {cite_year_str}, "
                        f"but Reference #{ref.index} ({ref.first_author_surname}) has {ref_year_str}"
                    )
                details.append(CheckDetail(
                    location=f"paragraph {c.paragraph_index}",
                    locator=Locator(kind="paragraph", paragraph_index=c.paragraph_index),
                    message=msg,
                    excerpt=c.raw_text,
                ))
            continue

        # ── Institutional author prefix match ────────────────────────────────
        # e.g. "State Council (2017)" → "State Council of the People's Republic
        # of China (2017)".  Same year required; no error reported.
        prefix_hit = _find_prefix_match(cite_norm, cite_year, cite_suffix, surname_index)
        if prefix_hit is not None:
            ref_norm, ref_year, ref_suffix, _pos = prefix_hit
            cited_keys.add((ref_norm, ref_year, ref_suffix))
            continue

        # ── Multi-word surname suffix match ──────────────────────────────────
        # e.g. "Hashim (2020)" citing "Salah Hashim, A. (2020)" — the citation
        # uses only the last part of a multi-word surname.
        suffix_hit = _find_suffix_match(cite_norm, cite_year, cite_suffix, surname_index)
        if suffix_hit is not None:
            ref_norm, ref_year, ref_suffix, ref_pos = suffix_hit
            ref = doc.references[ref_pos]
            cited_keys.add((ref_norm, ref_year, ref_suffix))
            surname_mismatch_count += 1
            if surname_mismatch_count <= MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"paragraph {c.paragraph_index}",
                    locator=Locator(kind="paragraph", paragraph_index=c.paragraph_index),
                    message=(
                        f"Surname inconsistency: '{c.raw_text}' cites '{c.authors[0]}', "
                        f"but Reference #{ref.index} lists '{ref.first_author_surname}' — "
                        f"verify the multi-word surname is used consistently in citation and reference"
                    ),
                    excerpt=c.raw_text,
                ))
            continue

        # ── True orphan: author not found at all in references ───────────────
        orphan_count += 1
        if orphan_count <= MAX_REPORTED:
            details.append(CheckDetail(
                location=f"paragraph {c.paragraph_index}",
                locator=Locator(kind="paragraph", paragraph_index=c.paragraph_index),
                message=f"Citation '{c.raw_text}' has no matching reference",
                excerpt=c.raw_text,
            ))

    if year_mismatch_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {year_mismatch_count - MAX_REPORTED} more citation year mismatches",
        ))
    if surname_mismatch_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {surname_mismatch_count - MAX_REPORTED} more surname inconsistencies",
        ))
    if orphan_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {orphan_count - MAX_REPORTED} more orphan citations",
        ))

    uncited_count = 0
    for key, ref_idx in ref_index.items():
        if key not in cited_keys:
            ref = doc.references[ref_idx]
            if uncited_count < MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"Reference #{ref.index}",
                    locator=Locator(kind="paragraph", paragraph_index=ref.paragraph_index),
                    message="Reference is not cited in text",
                    excerpt=ref.raw_text[:200],
                ))
            uncited_count += 1

    if uncited_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {uncited_count - MAX_REPORTED} more uncited references",
        ))

    return details
