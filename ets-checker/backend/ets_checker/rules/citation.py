from __future__ import annotations

import re

from ets_checker.models import CheckDetail, Locator, ParsedDocument
from ets_checker.rules.runner import register

MAX_REPORTED = 20


def _normalise_surname(s: str) -> str:
    return re.sub(r"[\s\-']", "", s).lower()


@register("citation.cross_reference", "Citation", "Citation–reference cross-check", "error")
def check_cross_reference(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []

    ref_index: dict[tuple[str, str, str], int] = {}
    for pos, r in enumerate(doc.references):
        if r.first_author_surname and r.year:
            key = (_normalise_surname(r.first_author_surname), r.year, r.year_suffix or "")
            ref_index[key] = pos

    cited_keys: set[tuple[str, str, str]] = set()
    orphan_count = 0

    for c in doc.citations:
        if not c.authors:
            continue
        key = (_normalise_surname(c.authors[0]), c.year, c.year_suffix or "")
        if key not in ref_index:
            if orphan_count < MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"paragraph {c.paragraph_index}",
                    locator=Locator(kind="paragraph", paragraph_index=c.paragraph_index),
                    message=f"Citation '{c.raw_text}' has no matching reference",
                    excerpt=c.raw_text,
                ))
            orphan_count += 1
        else:
            cited_keys.add(key)

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
