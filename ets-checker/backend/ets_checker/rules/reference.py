from __future__ import annotations

import re

from ets_checker.models import CheckDetail, Locator, ParsedDocument
from ets_checker.rules.runner import register

ET_AL_PATTERN = re.compile(r"\bet\s+al\.", re.IGNORECASE)


@register("reference.no_et_al", "Reference", "No 'et al.' in reference list", "error")
def check_no_et_al(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []
    for r in doc.references:
        if ET_AL_PATTERN.search(r.raw_text):
            details.append(CheckDetail(
                location=f"Reference #{r.index}",
                locator=Locator(kind="paragraph", paragraph_index=r.paragraph_index),
                message="Reference list must not use 'et al.'; list all authors",
                excerpt=r.raw_text[:200],
            ))
    return details
