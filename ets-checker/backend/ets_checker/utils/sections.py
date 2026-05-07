from __future__ import annotations

from ets_checker.models import Section
from ets_checker.parser.sections import is_reference_title


def compute_reference_bounds(
    sections: list[Section],
) -> tuple[int | None, int | None]:
    """Locate the bibliography in the section list.

    Returns ``(ref_start, next_section_start)`` — both are paragraph
    indices. ``next_section_start`` is the paragraph index of the first
    level-1 section after the references (used as an exclusive upper
    bound), or None when references run to end-of-document.
    """
    for i, s in enumerate(sections):
        if is_reference_title(s.title):
            ref_start = s.paragraph_index
            next_start: int | None = None
            for j in range(i + 1, len(sections)):
                if sections[j].level == 1:
                    next_start = sections[j].paragraph_index
                    break
            return ref_start, next_start
    return None, None
