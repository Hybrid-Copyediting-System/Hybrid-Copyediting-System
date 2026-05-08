from __future__ import annotations

import re

from ets_checker import ets_profile as p
from ets_checker.models import CheckDetail, Locator, Paragraph, ParsedDocument, Section
from ets_checker.parser.sections import (
    INLINE_ABSTRACT_PREFIX,
    KEYWORDS_PREFIX,
    is_abstract_title,
    is_reference_title,
)
from ets_checker.rules.runner import register

ABSTRACT_FALLBACK_PARAGRAPHS = 30


_CJK_CHAR = re.compile(r"[一-鿿㐀-䶿豈-﫿\U00020000-\U0002A6DF\U0002A700-\U000323AF]")


def _count_words(text: str) -> int:
    chinese = len(_CJK_CHAR.findall(text))
    text_no_cjk = _CJK_CHAR.sub(" ", text)
    english = len(text_no_cjk.split())
    return chinese + english


def _abstract_end_index(
    doc: ParsedDocument,
    abstract_idx: int,
    section_pos: int,
) -> int:
    if section_pos + 1 < len(doc.sections):
        return doc.sections[section_pos + 1].paragraph_index
    # No following section detected — fall back to the keywords paragraph,
    # else cap at a fixed number of paragraphs to avoid swallowing the body.
    for para in doc.paragraphs:
        if (para.index > abstract_idx
                and not para.is_in_table
                and KEYWORDS_PREFIX.match(para.text.strip())):
            return para.index
    max_idx = max((p.index for p in doc.paragraphs), default=abstract_idx)
    fallback_limit = abstract_idx + ABSTRACT_FALLBACK_PARAGRAPHS + 1
    next_heading = next(
        (para.index for para in doc.paragraphs
         if para.index > abstract_idx
         and para.index < fallback_limit
         and para.style_name is not None
         and ("heading" in para.style_name.lower() or "標題" in para.style_name)),
        None,
    )
    return min(
        next_heading if next_heading is not None else fallback_limit,
        max_idx + 1,
    )


@register("structure.abstract_length", "Structure", "Abstract length check", "warning")
def check_abstract_length(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []

    abstract_section = None
    abstract_pos: int | None = None
    for i, s in enumerate(doc.sections):
        if is_abstract_title(s.title):
            abstract_section = s
            abstract_pos = i
            break

    if abstract_section is None or abstract_pos is None:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message="Abstract section not detected",
        ))
        return details

    next_section_idx = _abstract_end_index(
        doc, abstract_section.paragraph_index, abstract_pos
    )

    abstract_paras = [
        para for para in doc.paragraphs
        if para.index > abstract_section.paragraph_index
        and (next_section_idx is None or para.index < next_section_idx)
        and not para.is_in_table
        and para.text.strip()
        and not KEYWORDS_PREFIX.match(para.text.strip())
    ]

    # For inline abstracts ("ABSTRACT: body text..."), the content lives in
    # the section's own paragraph rather than the ones that follow it.
    section_para_text = next(
        (para.text for para in doc.paragraphs
         if para.index == abstract_section.paragraph_index),
        "",
    )
    inline_body = INLINE_ABSTRACT_PREFIX.sub("", section_para_text, count=1)
    inline_body = inline_body if inline_body != section_para_text else ""

    parts = ([inline_body] if inline_body else []) + [para.text for para in abstract_paras]
    full_text = " ".join(parts)
    word_count = _count_words(full_text)

    if word_count > p.ABSTRACT_MAX_WORDS:
        details.append(CheckDetail(
            location="Abstract",
            locator=Locator(
                kind="paragraph",
                paragraph_index=abstract_section.paragraph_index,
            ),
            message=f"Abstract exceeds {p.ABSTRACT_MAX_WORDS} words",
            expected=f"≤ {p.ABSTRACT_MAX_WORDS} words",
            actual=f"{word_count} words",
        ))

    return details


@register("structure.keywords_count", "Structure", "Keywords count check", "warning")
def check_keywords_count(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []

    kw_para = None
    for para in doc.paragraphs:
        if KEYWORDS_PREFIX.match(para.text.strip()):
            kw_para = para
            break

    if kw_para is None:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message="Keywords paragraph not detected",
        ))
        return details

    text = KEYWORDS_PREFIX.sub("", kw_para.text.strip(), count=1).strip()

    keywords = [k.strip() for k in re.split(r"[,;，；、]", text) if k.strip()]

    if len(keywords) > p.KEYWORDS_MAX_COUNT:
        details.append(CheckDetail(
            location=f"paragraph {kw_para.index}",
            locator=Locator(kind="paragraph", paragraph_index=kw_para.index),
            message=f"Too many keywords (max {p.KEYWORDS_MAX_COUNT})",
            expected=f"≤ {p.KEYWORDS_MAX_COUNT}",
            actual=str(len(keywords)),
        ))

    return details


_INTRODUCTION_ALIASES = {
    "introduction", "引言", "緒論", "前言",
    "background", "literature review",
}

_TRAILING_PUNCT = re.compile(r"[\s:：.。\-—–]+$")
_LEADING_NUMBERS = re.compile(r"^\d+(\.\d+)*\.?\s*")


def _normalise_section_title(title: str) -> str:
    cleaned = _LEADING_NUMBERS.sub("", title.strip())
    return _TRAILING_PUNCT.sub("", cleaned.lower())


@register("structure.required_sections", "Structure", "Required sections check", "error")
def check_required_sections(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []
    found_abstract = False
    found_introduction = False
    found_references = False

    for s in doc.sections:
        if is_abstract_title(s.title):
            found_abstract = True
        if _normalise_section_title(s.title) in _INTRODUCTION_ALIASES:
            found_introduction = True
        if is_reference_title(s.title):
            found_references = True

    if not found_abstract:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message="Missing required section: Abstract",
            expected="Abstract section present",
            actual="not found",
        ))
    if not found_introduction:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message="Missing required section: Introduction",
            expected="Introduction section present (or equivalent: Background, Literature Review)",
            actual="not found",
        ))
    if not found_references:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message="Missing required section: References",
            expected="References section present",
            actual="not found",
        ))

    return details


# ── ET&S: footnotes are not allowed (Author Query Form Item 4) ────────


# ── ET&S: placeholder detection (Author Query Form Item 4) ──────────


# Bracketed placeholder body — explicit instructions left in the text.
# Matches "[insert table here]", "[Figure 2 goes here]", "[TBD]",
# "[reference needed]", "[citation needed]", "[Citation]" (Word's auto-
# inserted bibliography placeholder), etc.
_PLACEHOLDER_BRACKETED = re.compile(
    r"\[\s*(?:"
    r"insert[^\]]*"
    r"|(?:figure|fig\.?|table)\s*[a-z0-9]*\s*(?:here|goes\s+here|to\s+be\s+inserted)[^\]]*"
    r"|placeholder[^\]]*"
    r"|to\s*do[^\]]*|todo[^\]]*"
    r"|t\s*b\s*d[^\]]*"
    r"|fix\s*me[^\]]*"
    r"|(?:citation|reference)(?:\s+needed)?\s*"  # bare "[Citation]" or "[Reference]"
    r"|x{3,}[^\]]*"
    r")\]",
    re.IGNORECASE,
)

# Uppercase/lowercase placeholder words on their own (word boundaries).
# "TODO", "FIXME", "TBD" — specific enough that false positives are rare.
# (Lower-case "tbd" without brackets is too common in prose; we require
# uppercase or bracketed forms.)
_PLACEHOLDER_WORD = re.compile(
    r"(?<![A-Za-z])(?:TODO|FIXME|TBD|TKTK)(?![A-Za-z])"
)

# A run of 3+ question marks — almost always a stand-in for a number,
# author, or page that the author meant to fill in later. Skip cases like
# "????" inside quoted dialogue by requiring no surrounding letters.
_PLACEHOLDER_QUESTIONS = re.compile(r"\?{3,}")

# Angle-bracketed placeholder, e.g. "<placeholder>", "<insert citation>".
# Must be followed by a closing > with no embedded whitespace+http to avoid
# colliding with bare URLs like "<https://example.com>".
_PLACEHOLDER_ANGLED = re.compile(
    r"<\s*(?:placeholder|insert|todo|tbd|fixme)[^>]*>",
    re.IGNORECASE,
)

# Lorem-ipsum boilerplate.
_PLACEHOLDER_LOREM = re.compile(r"\blorem\s+ipsum\b", re.IGNORECASE)


def _placeholder_matches(text: str) -> list[tuple[int, int, str]]:
    matches: list[tuple[int, int, str]] = []
    for pat in (
        _PLACEHOLDER_BRACKETED,
        _PLACEHOLDER_WORD,
        _PLACEHOLDER_QUESTIONS,
        _PLACEHOLDER_ANGLED,
        _PLACEHOLDER_LOREM,
    ):
        for m in pat.finditer(text):
            matches.append((m.start(), m.end(), m.group(0)))
    matches.sort()
    return matches


@register("structure.placeholder", "Structure", "Placeholder detection (ET&S)", "error")
def check_placeholders(doc: ParsedDocument) -> list[CheckDetail]:
    """Flag placeholders/TODOs left in the manuscript.

    AQF Item 4 (ET&S): "DO NOT use placeholder in the manuscript, this
    includes for the Figures, Tables and Citations and Reference List."

    The Reference section is excluded so that DOIs containing "tbd" path
    fragments or bracketed editor markers in titles (e.g. "[Reprint]")
    don't generate spurious failures.
    """
    details: list[CheckDetail] = []

    ref_start: int | None = next(
        (s.paragraph_index for s in doc.sections if is_reference_title(s.title)),
        None,
    )

    seen: set[tuple[int, int, int]] = set()
    issue_count = 0
    MAX_REPORTED = 20

    for para in doc.paragraphs:
        if ref_start is not None and para.index >= ref_start:
            break
        text = para.text
        if not text:
            continue
        for start, end, hit in _placeholder_matches(text):
            key = (para.index, start, end)
            if key in seen:
                continue
            seen.add(key)
            ctx_start = max(0, start - 20)
            ctx_end = min(len(text), end + 20)
            if issue_count < MAX_REPORTED:
                details.append(CheckDetail(
                    location=f"paragraph {para.index}",
                    locator=Locator(
                        kind="paragraph",
                        paragraph_index=para.index,
                        char_start=start,
                        char_end=end,
                    ),
                    message=(
                        f"Placeholder detected: '{hit}' — replace with the "
                        f"intended content before submission"
                    ),
                    excerpt=text[ctx_start:ctx_end],
                ))
            issue_count += 1

    if issue_count > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {issue_count - MAX_REPORTED} more placeholder occurrences",
        ))

    return details


# ── APA 7: abstract is one paragraph, no first-line indent ────────────


def _abstract_body_paragraphs(
    doc: ParsedDocument,
) -> tuple[Section | None, list[Paragraph]]:
    """Return the (Section, [Paragraphs]) tuple for the abstract body.

    Paragraphs are limited to non-empty, non-keyword, non-table-cell
    paragraphs strictly between the Abstract heading and the next section
    (or the keywords paragraph if no following section was detected).
    Returns (None, []) when no abstract is found.
    """
    abstract_section = None
    abstract_pos: int | None = None
    for i, s in enumerate(doc.sections):
        if is_abstract_title(s.title):
            abstract_section = s
            abstract_pos = i
            break
    if abstract_section is None or abstract_pos is None:
        return None, []
    end_idx = _abstract_end_index(
        doc, abstract_section.paragraph_index, abstract_pos
    )
    paras = [
        para for para in doc.paragraphs
        if para.index > abstract_section.paragraph_index
        and para.index < end_idx
        and not para.is_in_table
        and para.text.strip()
        and not KEYWORDS_PREFIX.match(para.text.strip())
    ]
    return abstract_section, paras


@register(
    "structure.abstract_single_paragraph",
    "Structure",
    "Abstract must be a single paragraph (APA 7)",
    "warning",
)
def check_abstract_single_paragraph(doc: ParsedDocument) -> list[CheckDetail]:
    """APA 7 §2.9 / §2.27: the abstract is a single paragraph.

    An inline-abstract section ("ABSTRACT: …") trivially satisfies the rule
    and is skipped. We only count paragraphs that are clearly part of the
    abstract body (text-bearing, not in a table, not the keywords line).
    """
    details: list[CheckDetail] = []
    abstract_section, paras = _abstract_body_paragraphs(doc)
    if abstract_section is None:
        return details
    if abstract_section.detection_method == "inline_abstract":
        return details
    if len(paras) <= 1:
        return details

    details.append(CheckDetail(
        location="Abstract",
        locator=Locator(
            kind="paragraph",
            paragraph_index=abstract_section.paragraph_index,
        ),
        message=(
            f"Abstract spans {len(paras)} paragraphs — APA 7 §2.27 requires "
            f"the abstract to be written as a single paragraph"
        ),
        expected="single paragraph",
        actual=f"{len(paras)} paragraphs",
        excerpt=paras[0].text[:200],
    ))
    return details


@register(
    "structure.abstract_no_indent",
    "Structure",
    "Abstract must not be first-line indented (APA 7)",
    "warning",
)
def check_abstract_no_indent(doc: ParsedDocument) -> list[CheckDetail]:
    """APA 7 §2.27: the first line of the abstract is flush left, not
    indented.  We flag paragraphs in the abstract whose first-line indent
    exceeds 0.1 cm (anything smaller is rounding noise from the EMU
    conversion).
    """
    details: list[CheckDetail] = []
    abstract_section, paras = _abstract_body_paragraphs(doc)
    if abstract_section is None or not paras:
        return details
    if abstract_section.detection_method == "inline_abstract":
        return details
    first = paras[0]
    indent = first.indent_first_line_cm
    if indent is None or indent <= 0.1:
        return details

    details.append(CheckDetail(
        location=f"paragraph {first.index}",
        locator=Locator(kind="paragraph", paragraph_index=first.index),
        message=(
            f"Abstract first line is indented {indent:.2f} cm — APA 7 §2.27 "
            f"requires the abstract to be flush left (no first-line indent)"
        ),
        expected="0 cm (flush left)",
        actual=f"{indent:.2f} cm",
        excerpt=first.text[:200],
    ))
    return details


# ── APA 7: paper title length ──────────────────────────────────────────


def _find_title_paragraph(doc: ParsedDocument) -> Paragraph | None:
    """Best-effort title-paragraph picker shared with structure.title_length.

    Strategy:
      1. Section flagged ``detection_method="title"`` by the parser — covers
         both the dedicated ``Title`` style and Heading-1-styled titles.
      2. First non-empty front-matter paragraph (before the first non-title
         section, excluding table cells).
    """
    title_section = next(
        (s for s in doc.sections if s.detection_method == "title"), None,
    )
    if title_section is not None:
        para = next(
            (p for p in doc.paragraphs if p.index == title_section.paragraph_index),
            None,
        )
        if para is not None:
            return para
    first_section_idx = min(
        (s.paragraph_index for s in doc.sections
         if s.detection_method not in ("inline_abstract", "title")),
        default=None,
    )
    if first_section_idx is None:
        return None
    for para in doc.paragraphs:
        if para.is_in_table:
            continue
        if para.index >= first_section_idx:
            break
        if para.text.strip():
            return para
    return None


_TITLE_WORD = re.compile(r"\S+")


@register(
    "structure.title_length",
    "Structure",
    "Paper title length (APA 7 ≤ 12 words)",
    "info",
)
def check_title_length(doc: ParsedDocument) -> list[CheckDetail]:
    """APA 7 §2.4 recommends paper titles of ≤ 12 words.  Reported as info
    rather than warning because well-justified longer titles are common in
    educational technology research.
    """
    from ets_checker import ets_profile as profile

    details: list[CheckDetail] = []
    title_para = _find_title_paragraph(doc)
    if title_para is None:
        return details
    text = title_para.text.strip()
    if not text:
        return details
    word_count = len(_TITLE_WORD.findall(text))
    if word_count <= profile.TITLE_MAX_WORDS:
        return details

    details.append(CheckDetail(
        location=f"paragraph {title_para.index} (title)",
        locator=Locator(kind="paragraph", paragraph_index=title_para.index),
        message=(
            f"Paper title runs {word_count} words — APA 7 §2.4 recommends "
            f"≤ {profile.TITLE_MAX_WORDS} words for clarity and indexing"
        ),
        expected=f"≤ {profile.TITLE_MAX_WORDS} words",
        actual=f"{word_count} words",
        excerpt=text[:200],
    ))
    return details


# ── APA 7: do not use "Introduction" as a section heading ──────────────


_INTRO_TITLES = {"introduction", "引言", "緒論", "前言"}


@register(
    "structure.no_introduction_heading",
    "Structure",
    "Do not label the first section 'Introduction' (APA 7)",
    "info",
)
def check_no_introduction_heading(doc: ParsedDocument) -> list[CheckDetail]:
    """APA 7 §2.27: the introduction is identified by its position (first
    section after the abstract); a literal 'Introduction' heading is
    redundant. Flagged at info severity — many submissions still include
    one and journals vary in tolerance.
    """
    details: list[CheckDetail] = []
    for s in doc.sections:
        if _normalise_section_title(s.title) in _INTRO_TITLES:
            details.append(CheckDetail(
                location=f"paragraph {s.paragraph_index}",
                locator=Locator(
                    kind="paragraph",
                    paragraph_index=s.paragraph_index,
                ),
                message=(
                    f"Section labelled '{s.title}' — APA 7 §2.27: do not label "
                    f"the introduction with a heading; it is identified by its "
                    f"position immediately after the abstract"
                ),
                expected="no 'Introduction' heading",
                actual=s.title,
            ))
            # Flag only the first occurrence to avoid noise from later
            # sections whose own titles happen to start with 'Introduction'.
            break
    return details


# ── APA 7 / ET&S: document section order ───────────────────────────────


# Stage labels in the canonical APA 7 / ET&S order. Earlier entries must
# precede later ones; sections matching the same stage are collapsed.
_STAGE_ABSTRACT = "abstract"
_STAGE_BODY = "body"
_STAGE_REFERENCES = "references"
_STAGE_APPENDIX = "appendix"

_SECTION_STAGE: list[tuple[str, frozenset[str]]] = [
    (_STAGE_ABSTRACT, frozenset({"abstract", "摘要"})),
    (
        _STAGE_REFERENCES,
        frozenset({
            "references", "reference list", "reference",
            "參考文獻", "參考書目",
        }),
    ),
    (
        _STAGE_APPENDIX,
        frozenset({"appendix", "appendices", "附錄"}),
    ),
]


def _stage_for_section_title(title: str) -> str:
    norm = _normalise_section_title(title)
    for stage, names in _SECTION_STAGE:
        if norm in names:
            return stage
        first_word = norm.split(" ", 1)[0] if norm else ""
        if first_word in names:
            return stage
    return _STAGE_BODY


_STAGE_ORDER = [_STAGE_ABSTRACT, _STAGE_BODY, _STAGE_REFERENCES, _STAGE_APPENDIX]


@register(
    "structure.section_order",
    "Structure",
    "Document section order (Abstract → Body → References → Appendix)",
    "warning",
)
def check_section_order(doc: ParsedDocument) -> list[CheckDetail]:
    """APA 7 / ET&S document order:

        Title page → Abstract → Body → References → Appendices

    The MVP parser does not separate the title page from front-matter, so
    we anchor on the four stages that *are* recoverable from the section
    list.  Each top-level section is mapped to its stage and the resulting
    sequence must be non-decreasing in stage index.
    """
    details: list[CheckDetail] = []

    # Track only level-1 sections — sub-headings inside the body don't
    # affect document-level ordering.
    seen: list[tuple[int, int, str]] = []  # (stage_idx, paragraph_index, title)
    for s in doc.sections:
        if s.level != 1:
            continue
        # The paper title sits before the abstract by definition; it is not
        # a body section and must not enter the ordering check, otherwise the
        # abstract that follows it falsely trips "body before abstract".
        if s.detection_method == "title":
            continue
        if s.detection_method == "appendix":
            stage = _STAGE_APPENDIX
        else:
            stage = _stage_for_section_title(s.title)
        seen.append((_STAGE_ORDER.index(stage), s.paragraph_index, s.title))

    issue_count = 0
    last_stage = -1
    last_title = ""
    for stage_idx, para_idx, title in seen:
        if stage_idx < last_stage:
            if issue_count < 5:
                details.append(CheckDetail(
                    location=f"paragraph {para_idx}",
                    locator=Locator(kind="paragraph", paragraph_index=para_idx),
                    message=(
                        f"Section '{title}' ({_STAGE_ORDER[stage_idx]}) appears "
                        f"after '{last_title}' ({_STAGE_ORDER[last_stage]}) — "
                        f"APA 7 / ET&S requires the order: "
                        f"{' → '.join(_STAGE_ORDER)}"
                    ),
                    expected=" → ".join(_STAGE_ORDER),
                    actual=f"{_STAGE_ORDER[last_stage]} before {_STAGE_ORDER[stage_idx]}",
                ))
            issue_count += 1
        last_stage = max(last_stage, stage_idx)
        last_title = title

    return details


@register(
    "structure.no_footnotes",
    "Structure",
    "No footnotes or endnotes (ET&S)",
    "error",
)
def check_no_footnotes(doc: ParsedDocument) -> list[CheckDetail]:
    details: list[CheckDetail] = []
    for fn in doc.footnotes:
        excerpt = fn.text[:200]
        kind = fn.kind  # "footnote" | "endnote"
        if fn.paragraph_index is not None:
            location = f"paragraph {fn.paragraph_index}"
            locator = Locator(kind="paragraph", paragraph_index=fn.paragraph_index)
        else:
            location = f"{kind} #{fn.footnote_id}"
            locator = Locator(kind="document")
        details.append(CheckDetail(
            location=location,
            locator=locator,
            message=(
                f"{kind.capitalize()} detected — ET&S does not allow "
                f"{kind}s; place additional information in the body text "
                f"(AQF Item 4)"
            ),
            excerpt=excerpt,
        ))
    return details
