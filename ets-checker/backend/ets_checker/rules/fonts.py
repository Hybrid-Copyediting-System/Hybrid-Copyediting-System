from __future__ import annotations

import re

from ets_checker import ets_profile as p
from ets_checker.models import CheckDetail, Locator, ParsedDocument, Run
from ets_checker.parser.sections import (
    INLINE_ABSTRACT_PREFIX,
    KEYWORDS_PREFIX,
    is_abstract_title,
    is_reference_title,
)
from ets_checker.rules.runner import register

MAX_REPORTED = 20
ABSTRACT_FALLBACK_PARAGRAPHS = 30

_ONLY_PUNCT_OR_SPACE = re.compile(r"^[\s\W]+$", re.UNICODE)

# Matches statistical symbols (1–3 letters) immediately followed by optional
# spaces then a relational operator, e.g. "t = 2.3", "p < .05", "SD = 0.12".
# Lookbehind ensures the symbol is not part of a longer word.
_STAT_PATTERN = re.compile(
    r"(?<![A-Za-z])([A-Za-z]{1,3})[ \t]*[=<>≤≥]"
)

# Matches the APA df-in-parentheses form: t(79), F(1, 98), z(120), r(38).
# Restricted to _KNOWN_STAT symbols at match time to avoid false positives.
_STAT_PAREN_PATTERN = re.compile(
    r"(?<![A-Za-z])([A-Za-z]{1,3})\s*\(\s*\d"
)

# False-positive filter: common words/abbreviations that match the pattern
# but are not statistical symbols (stored lowercase; matched case-insensitively).
_STAT_EXCLUSIONS = {
    # English prepositions / conjunctions / articles
    "a", "an", "the", "in", "on", "at", "to", "by", "of", "or", "and",
    "if", "is", "as", "no", "so", "be", "do", "he", "we", "it", "me",
    "my", "us", "go", "up", "hi", "ok", "id",
    # Units and HTML/LaTeX tokens
    "em", "en", "pt", "px", "cm", "mm", "kg", "km", "hz",
}

# Known statistical symbols to accept without question (fast path).
_KNOWN_STAT = {
    "N", "n", "M", "SD", "SE", "SEM", "p", "F", "t", "r", "R",
    "d", "b", "B", "df", "CI", "OR", "HR", "ES", "f", "q", "z",
    "DF", "SS", "MS", "AIC", "BIC",
}


def _build_char_run_map(runs: list[Run]) -> tuple[str, list[Run]]:
    """Return (combined_text, char_map) where char_map[i] is the Run that owns
    character i in combined_text.

    Uses run text directly rather than Paragraph.text to avoid misalignment
    when the docx paragraph contains hyperlinks: python-docx includes hyperlink
    text in Paragraph.text but excludes those runs from Paragraph.runs.
    """
    chars: list[Run] = []
    parts: list[str] = []
    for run in runs:
        parts.append(run.text)
        chars.extend([run] * len(run.text))
    return "".join(parts), chars


def _get_body_paragraph_indices(doc: ParsedDocument) -> set[int]:
    heading_indices = {s.paragraph_index for s in doc.sections}

    abstract_start: int | None = None
    abstract_end: int | None = None
    ref_start: int | None = None

    for i, s in enumerate(doc.sections):
        if abstract_start is None and is_abstract_title(s.title):
            abstract_start = s.paragraph_index
            if i + 1 < len(doc.sections):
                abstract_end = doc.sections[i + 1].paragraph_index
        if ref_start is None and is_reference_title(s.title):
            ref_start = s.paragraph_index

    if abstract_start is not None and abstract_end is None:
        for para in doc.paragraphs:
            if (para.index > abstract_start
                    and not para.is_in_table
                    and KEYWORDS_PREFIX.match(para.text.strip())):
                abstract_end = para.index + 1
                break
        if abstract_end is None:
            max_idx = max((p.index for p in doc.paragraphs), default=abstract_start)
            fallback_limit = abstract_start + ABSTRACT_FALLBACK_PARAGRAPHS + 1
            next_heading = next(
                (p.index for p in doc.paragraphs
                 if p.index > abstract_start
                 and p.index < fallback_limit
                 and p.style_name is not None
                 and ("heading" in p.style_name.lower() or "標題" in p.style_name)),
                None,
            )
            abstract_end = min(
                next_heading if next_heading is not None else fallback_limit,
                max_idx + 1,
            )

    # Paragraphs before the first detected section (title, authors, affiliations)
    # are front matter and should not be checked against body font rules.
    first_section_idx = min((s.paragraph_index for s in doc.sections), default=None)

    exclude = set(heading_indices)
    for para in doc.paragraphs:
        if para.is_in_table:
            exclude.add(para.index)
        if first_section_idx is not None and para.index < first_section_idx:
            exclude.add(para.index)
        if abstract_start is not None and abstract_end is not None:
            if abstract_start <= para.index < abstract_end:
                exclude.add(para.index)
        if ref_start is not None and para.index >= ref_start:
            exclude.add(para.index)

    return {para.index for para in doc.paragraphs} - exclude


@register("font.body", "Fonts", "Body font check", "warning")
def check_body_font(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []
    body_indices = _get_body_paragraph_indices(doc)
    expected_name, expected_size = p.FONT_BODY[0], p.FONT_BODY[1]

    if not doc.sections:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                "No section headings detected — font check may include "
                "title/author paragraphs and produce false positives"
            ),
        ))

    count = 0
    unresolved_size_runs = 0
    total_body_runs = 0
    for para in doc.paragraphs:
        if para.index not in body_indices:
            continue
        for r in para.runs:
            if not r.text.strip():
                continue
            if _ONLY_PUNCT_OR_SPACE.match(r.text):
                continue
            total_body_runs += 1
            actual_font = r.font_name or "(unknown)"
            actual_size = r.font_size_pt

            if actual_size is None:
                unresolved_size_runs += 1

            font_mismatch = actual_font != "(unknown)" and actual_font != expected_name
            size_mismatch = actual_size is not None and abs(actual_size - expected_size) > 0.1

            if font_mismatch or size_mismatch:
                if count < MAX_REPORTED:
                    details.append(CheckDetail(
                        location=f"paragraph {para.index}",
                        locator=Locator(kind="paragraph", paragraph_index=para.index),
                        message="Body text font mismatch",
                        expected=f"{expected_name} {expected_size}pt",
                        actual=f"{actual_font} {actual_size}pt" if actual_size else actual_font,
                        excerpt=r.text[:80],
                    ))
                count += 1

    if count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {count - MAX_REPORTED} more font mismatches",
        ))

    if total_body_runs > 0 and unresolved_size_runs / total_body_runs > 0.5:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=(
                f"Font size could not be determined for {unresolved_size_runs} of "
                f"{total_body_runs} body text runs — size check may be incomplete"
            ),
            expected=f"{expected_size}pt",
            actual="unresolvable (inherited from theme/template)",
        ))

    return details


def _is_stat_symbol(sym: str) -> bool:
    """Return True if sym should be treated as a statistical symbol."""
    if sym in _KNOWN_STAT:
        return True
    if sym.lower() in _STAT_EXCLUSIONS:
        return False
    # Accept 1–2 letter uppercase abbreviations not in the exclusion list
    if len(sym) <= 2 and sym[0].isupper():
        return True
    return False


@register("font.stat_italic", "Fonts", "Statistical symbol italics", "warning")
def check_stat_italic(doc: ParsedDocument) -> list[CheckDetail]:
    """Warn when a statistical symbol (non-Greek letter) appears without italic
    formatting, detected by the pattern  <symbol> <whitespace>? <relational-op>.
    """
    details: list[CheckDetail] = []
    body_indices = _get_body_paragraph_indices(doc)
    count = 0

    for para in doc.paragraphs:
        if para.index not in body_indices:
            continue
        if not para.runs:
            continue

        combined_text, char_run = _build_char_run_map(para.runs)
        if not combined_text:
            continue

        # Deduplicate: skip a match whose symbol span was already reported in
        # this paragraph (e.g. "t(79) = " would hit both patterns for "t").
        reported_spans: set[tuple[int, int]] = set()

        def _check_match(m: re.Match, known_only: bool) -> None:
            nonlocal count
            sym = m.group(1)
            if known_only:
                if sym not in _KNOWN_STAT:
                    return
            else:
                if not _is_stat_symbol(sym):
                    return

            span = (m.start(1), m.end(1))
            if span in reported_spans:
                return

            runs_for_sym: list[Run] = []
            for i in range(span[0], span[1]):
                r = char_run[i]
                if not runs_for_sym or runs_for_sym[-1] is not r:
                    runs_for_sym.append(r)

            if any(r.italic is False for r in runs_for_sym):
                reported_spans.add(span)
                if count < MAX_REPORTED:
                    ctx_start = max(0, m.start() - 15)
                    ctx_end = min(len(combined_text), m.end() + 15)
                    excerpt = combined_text[ctx_start:ctx_end].strip()
                    details.append(CheckDetail(
                        location=f"paragraph {para.index}",
                        locator=Locator(kind="paragraph", paragraph_index=para.index),
                        message=f"Statistical symbol \"{sym}\" should be italic",
                        expected="italic",
                        actual="not italic",
                        excerpt=f"…{excerpt}…" if ctx_start > 0 else excerpt,
                    ))
                count += 1

        for m in _STAT_PATTERN.finditer(combined_text):
            _check_match(m, known_only=False)

        # Second pass: APA df-in-parens form, e.g. t(79), F(1, 98)
        for m in _STAT_PAREN_PATTERN.finditer(combined_text):
            _check_match(m, known_only=True)

    if count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {count - MAX_REPORTED} more missing italics on statistical symbols",
        ))

    return details


def _get_abstract_paragraph_indices(doc: ParsedDocument) -> set[int]:
    """Return paragraph indices belonging to the abstract body (excluding Keywords)."""
    abstract_start: int | None = None
    abstract_end: int | None = None

    for i, s in enumerate(doc.sections):
        if is_abstract_title(s.title):
            abstract_start = s.paragraph_index
            if i + 1 < len(doc.sections):
                abstract_end = doc.sections[i + 1].paragraph_index
            break

    if abstract_start is None:
        return set()

    if abstract_end is None:
        for para in doc.paragraphs:
            if (para.index > abstract_start
                    and not para.is_in_table
                    and KEYWORDS_PREFIX.match(para.text.strip())):
                abstract_end = para.index
                break
        if abstract_end is None:
            max_idx = max((pa.index for pa in doc.paragraphs), default=abstract_start)
            fallback_limit = abstract_start + ABSTRACT_FALLBACK_PARAGRAPHS + 1
            next_heading = next(
                (pa.index for pa in doc.paragraphs
                 if pa.index > abstract_start
                 and pa.index < fallback_limit
                 and pa.style_name is not None
                 and ("heading" in pa.style_name.lower() or "標題" in pa.style_name)),
                None,
            )
            abstract_end = min(
                next_heading if next_heading is not None else fallback_limit,
                max_idx + 1,
            )

    indices: set[int] = set()

    section_para = next(
        (pa for pa in doc.paragraphs if pa.index == abstract_start), None
    )
    if section_para and INLINE_ABSTRACT_PREFIX.match(section_para.text.strip()):
        indices.add(abstract_start)

    for para in doc.paragraphs:
        if (para.index > abstract_start
                and para.index < abstract_end
                and not para.is_in_table
                and para.text.strip()
                and not KEYWORDS_PREFIX.match(para.text.strip())):
            indices.add(para.index)

    return indices


# ─── Item 2: Abstract italic check ───────────────────────────────────


def _is_inline_abstract_para(para) -> bool:
    return bool(INLINE_ABSTRACT_PREFIX.match(para.text.strip()))


@register("font.abstract", "Fonts", "Abstract font check (ET&S: italic)", "warning")
def check_abstract_font(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []
    abstract_indices = _get_abstract_paragraph_indices(doc)
    if not abstract_indices:
        return details

    exp_name, exp_size, exp_bold, exp_italic = p.FONT_ABSTRACT
    count = 0

    for para in doc.paragraphs:
        if para.index not in abstract_indices:
            continue

        is_inline = _is_inline_abstract_para(para)
        label_chars_remaining = 0
        if is_inline:
            m = INLINE_ABSTRACT_PREFIX.match(para.text.strip())
            label_chars_remaining = m.end() if m else 0

        for r in para.runs:
            if not r.text.strip() or _ONLY_PUNCT_OR_SPACE.match(r.text):
                continue

            if is_inline and label_chars_remaining > 0:
                label_chars_remaining -= len(r.text)
                continue

            font_ok = r.font_name is None or r.font_name == "(unknown)" or r.font_name == exp_name
            size_ok = r.font_size_pt is None or abs(r.font_size_pt - exp_size) <= 0.1
            italic_ok = r.italic is None or r.italic == exp_italic

            if not (font_ok and size_ok and italic_ok):
                if count < MAX_REPORTED:
                    actual_parts = []
                    if not font_ok:
                        actual_parts.append(r.font_name or "?")
                    if not size_ok:
                        actual_parts.append(f"{r.font_size_pt}pt")
                    if not italic_ok:
                        actual_parts.append("not italic" if not r.italic else "italic")

                    details.append(CheckDetail(
                        location=f"paragraph {para.index}",
                        locator=Locator(kind="paragraph", paragraph_index=para.index),
                        message="Abstract text should be italic (ET&S requirement)",
                        expected=f"{exp_name} {exp_size}pt italic",
                        actual=", ".join(actual_parts),
                        excerpt=r.text[:80],
                    ))
                count += 1

    if count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {count - MAX_REPORTED} more abstract font mismatches",
        ))

    return details


# ─── Item 3: Heading font check ──────────────────────────────────────


_TITLE_STYLES = {"Title", "標題"}


@register("font.heading", "Fonts", "Heading font check", "warning")
def check_heading_font(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []
    count = 0

    for s in doc.sections:
        if s.level == 1:
            exp_name, exp_size, exp_bold, exp_italic = p.FONT_HEADING_1
            level_label = "Heading 1"
        elif s.level == 2:
            exp_name, exp_size, exp_bold, exp_italic = p.FONT_HEADING_2
            level_label = "Heading 2"
        elif s.level == 3:
            exp_name, exp_size, exp_bold, exp_italic = p.FONT_HEADING_3
            level_label = "Heading 3"
        else:
            continue

        para = next(
            (pa for pa in doc.paragraphs if pa.index == s.paragraph_index), None
        )
        if para is None:
            continue

        if para.style_name in _TITLE_STYLES:
            continue

        for r in para.runs:
            if not r.text.strip() or _ONLY_PUNCT_OR_SPACE.match(r.text):
                continue

            font_ok = r.font_name is None or r.font_name == "(unknown)" or r.font_name == exp_name
            size_ok = r.font_size_pt is None or abs(r.font_size_pt - exp_size) <= 0.1
            bold_ok = r.bold is None or r.bold == exp_bold
            italic_ok = r.italic is None or r.italic == exp_italic

            if not (font_ok and size_ok and bold_ok and italic_ok):
                if count < MAX_REPORTED:
                    actual_parts = []
                    if not font_ok:
                        actual_parts.append(r.font_name or "?")
                    if not size_ok:
                        actual_parts.append(f"{r.font_size_pt}pt")
                    if not bold_ok:
                        actual_parts.append("not bold" if not r.bold else "bold")
                    if not italic_ok:
                        actual_parts.append("italic (should not be)")

                    details.append(CheckDetail(
                        location=f"paragraph {para.index} ({level_label})",
                        locator=Locator(kind="paragraph", paragraph_index=para.index),
                        message=f"{level_label} font mismatch",
                        expected=f"{exp_name} {exp_size}pt bold, not italic",
                        actual=", ".join(actual_parts),
                        excerpt=r.text[:80],
                    ))
                count += 1

    if count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {count - MAX_REPORTED} more heading font mismatches",
        ))

    return details


# ─── Item 4: Reference font check ────────────────────────────────────


@register("font.reference", "Fonts", "Reference font check", "warning")
def check_reference_font(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []
    exp_name, exp_size = p.FONT_REFERENCE[0], p.FONT_REFERENCE[1]

    ref_start: int | None = None
    ref_end: int | None = None
    for i, s in enumerate(doc.sections):
        if ref_start is None and is_reference_title(s.title):
            ref_start = s.paragraph_index
            if i + 1 < len(doc.sections):
                ref_end = doc.sections[i + 1].paragraph_index

    if ref_start is None:
        return details

    count = 0
    for para in doc.paragraphs:
        if para.index <= ref_start or para.is_in_table:
            continue
        if ref_end is not None and para.index >= ref_end:
            break
        if not para.text.strip():
            continue

        for r in para.runs:
            if not r.text.strip() or _ONLY_PUNCT_OR_SPACE.match(r.text):
                continue

            actual_font = r.font_name or "(unknown)"
            font_mismatch = actual_font != "(unknown)" and actual_font != exp_name
            size_mismatch = r.font_size_pt is not None and abs(r.font_size_pt - exp_size) > 0.1

            if font_mismatch or size_mismatch:
                if count < MAX_REPORTED:
                    details.append(CheckDetail(
                        location=f"paragraph {para.index}",
                        locator=Locator(kind="paragraph", paragraph_index=para.index),
                        message="Reference font mismatch",
                        expected=f"{exp_name} {exp_size}pt",
                        actual=f"{actual_font} {r.font_size_pt}pt" if r.font_size_pt else actual_font,
                        excerpt=r.text[:80],
                    ))
                count += 1

    if count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {count - MAX_REPORTED} more reference font mismatches",
        ))

    return details


# ─── Item 5: Title font check ────────────────────────────────────────


def _get_title_paragraphs(doc: ParsedDocument) -> tuple[set[int], set[int]]:
    """Identify the paper title paragraph(s).

    Returns (all_title_indices, title_style_indices) where:
    - all_title_indices: paragraphs to check (front-matter + Title-styled in front-matter)
    - title_style_indices: subset that use the "Title" style (bypass heuristic gate)
    """
    first_real_section_idx: int | None = None
    for s in doc.sections:
        para = next((pa for pa in doc.paragraphs if pa.index == s.paragraph_index), None)
        if para is not None and para.style_name not in _TITLE_STYLES:
            first_real_section_idx = s.paragraph_index
            break

    if first_real_section_idx is None and doc.sections:
        first_real_section_idx = doc.sections[-1].paragraph_index + 1

    boundary = first_real_section_idx if first_real_section_idx is not None else 0

    title_style_indices: set[int] = set()
    all_indices: set[int] = set()
    for para in doc.paragraphs:
        if para.index >= boundary:
            break
        if para.is_in_table or not para.text.strip():
            continue
        all_indices.add(para.index)
        if para.style_name in _TITLE_STYLES:
            title_style_indices.add(para.index)

    return all_indices, title_style_indices


@register("font.title", "Fonts", "Title font check", "warning")
def check_title_font(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []
    all_title_indices, title_style_indices = _get_title_paragraphs(doc)
    if not all_title_indices:
        return details

    exp_name, exp_size, exp_bold, exp_italic = p.FONT_TITLE
    count = 0

    for para in doc.paragraphs:
        if para.index not in all_title_indices:
            continue

        is_title_styled = para.index in title_style_indices

        if not is_title_styled:
            has_title_font = False
            for r in para.runs:
                if not r.text.strip() or _ONLY_PUNCT_OR_SPACE.match(r.text):
                    continue
                if (r.font_size_pt is not None and abs(r.font_size_pt - exp_size) <= 0.1
                        and r.bold is True):
                    has_title_font = True
                    break
            if not has_title_font:
                continue

        for r in para.runs:
            if not r.text.strip() or _ONLY_PUNCT_OR_SPACE.match(r.text):
                continue

            font_ok = r.font_name is None or r.font_name == "(unknown)" or r.font_name == exp_name
            size_ok = r.font_size_pt is None or abs(r.font_size_pt - exp_size) <= 0.1
            bold_ok = r.bold is None or r.bold == exp_bold

            if not (font_ok and size_ok and bold_ok):
                if count < MAX_REPORTED:
                    actual_parts = []
                    if not font_ok:
                        actual_parts.append(r.font_name or "?")
                    if not size_ok:
                        actual_parts.append(f"{r.font_size_pt}pt")
                    if not bold_ok:
                        actual_parts.append("not bold" if not r.bold else "bold")

                    details.append(CheckDetail(
                        location=f"paragraph {para.index} (title)",
                        locator=Locator(kind="paragraph", paragraph_index=para.index),
                        message="Paper title font mismatch",
                        expected=f"{exp_name} {exp_size}pt bold",
                        actual=", ".join(actual_parts),
                        excerpt=r.text[:80],
                    ))
                count += 1

    if count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {count - MAX_REPORTED} more title font mismatches",
        ))

    return details
