from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ets_checker.models import Paragraph, Run

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument
    from docx.text.paragraph import Paragraph as DocxParagraph

logger = logging.getLogger(__name__)

EMU_PER_CM = 360000
EMU_PER_PT = 12700


def _build_run(r: object) -> Run:
    font = getattr(r, "font", None)
    return Run(
        text=getattr(r, "text", "") or "",
        font_name=getattr(font, "name", None) if font else None,
        font_size_pt=round(font.size / EMU_PER_PT, 1) if font and font.size else None,
        bold=getattr(font, "bold", None) if font else None,
        italic=getattr(font, "italic", None) if font else None,
    )


def _get_line_spacing(p: DocxParagraph) -> float | None:
    from docx.enum.text import WD_LINE_SPACING

    pf = p.paragraph_format
    if pf.line_spacing is not None:
        rule = pf.line_spacing_rule
        if rule in (WD_LINE_SPACING.EXACTLY, WD_LINE_SPACING.AT_LEAST):
            return None
        return float(pf.line_spacing)
    return None


def _resolve_style_indent(style: object, attr: str) -> int | None:
    """Walk the paragraph style chain looking for an inherited indent value
    (paragraph_format.left_indent or first_line_indent). Returns the EMU value
    of the first explicit setting found, or None if the chain has none."""
    s = style
    seen: set[int] = set()
    while s is not None and id(s) not in seen:
        seen.add(id(s))
        pf = getattr(s, "paragraph_format", None)
        if pf is not None:
            val = getattr(pf, attr, None)
            if val is not None:
                return int(val)
        s = getattr(s, "base_style", None)
    return None


def _get_indent_left_cm(p: DocxParagraph) -> float | None:
    val = p.paragraph_format.left_indent
    if val is None:
        val = _resolve_style_indent(p.style, "left_indent")
    if val is not None:
        return round(int(val) / EMU_PER_CM, 4)
    return None


def _get_indent_first_line_cm(p: DocxParagraph) -> float | None:
    val = p.paragraph_format.first_line_indent
    if val is None:
        val = _resolve_style_indent(p.style, "first_line_indent")
    if val is not None:
        return round(int(val) / EMU_PER_CM, 4)
    return None


def _get_alignment(p: DocxParagraph) -> str | None:
    a = p.alignment
    if a is not None:
        return str(a).split(".")[-1].split("(")[0]
    return None


def _resolve_style_font(
    style: object,
) -> tuple[str | None, float | None]:
    """Walk the paragraph style chain to find inherited font name and size."""
    font_name: str | None = None
    font_size_pt: float | None = None
    s = style
    seen: set[int] = set()
    while s is not None and id(s) not in seen:
        seen.add(id(s))
        f = getattr(s, "font", None)
        if f is not None:
            if font_name is None and f.name:
                font_name = f.name
            if font_size_pt is None and f.size:
                font_size_pt = round(int(f.size) / EMU_PER_PT, 1)
        if font_name is not None and font_size_pt is not None:
            break
        s = getattr(s, "base_style", None)
    return font_name, font_size_pt


def _resolve_style_italic(style: object) -> bool:
    """Walk the paragraph style chain to find the inherited italic setting.

    Returns the first explicit True/False found; if the entire chain has no
    explicit setting, returns False (matching Word's document default).
    """
    s = style
    seen: set[int] = set()
    while s is not None and id(s) not in seen:
        seen.add(id(s))
        f = getattr(s, "font", None)
        if f is not None:
            italic = getattr(f, "italic", None)
            if italic is not None:
                return bool(italic)
        s = getattr(s, "base_style", None)
    return False


def _build_paragraph(
    p: DocxParagraph,
    index: int,
    is_in_table: bool,
    default_font_name: str | None = None,
    default_font_size_pt: float | None = None,
) -> Paragraph:
    style_font_name, style_font_size_pt = _resolve_style_font(p.style)
    fallback_name = style_font_name or default_font_name
    fallback_size = style_font_size_pt or default_font_size_pt
    style_italic = _resolve_style_italic(p.style)

    built_runs: list[Run] = []
    for r in p.runs:
        run = _build_run(r)
        resolved_name = run.font_name if run.font_name is not None else fallback_name
        resolved_size = run.font_size_pt if run.font_size_pt is not None else fallback_size
        # Resolve italic: explicit run value > paragraph style chain > False
        resolved_italic = run.italic if run.italic is not None else style_italic
        if resolved_name != run.font_name or resolved_size != run.font_size_pt or resolved_italic != run.italic:
            run = Run(
                text=run.text,
                font_name=resolved_name,
                font_size_pt=resolved_size,
                bold=run.bold,
                italic=resolved_italic,
            )
        built_runs.append(run)

    return Paragraph(
        index=index,
        text=p.text or "",
        style_name=p.style.name if p.style else None,
        runs=built_runs,
        alignment=_get_alignment(p),
        indent_left_cm=_get_indent_left_cm(p),
        indent_first_line_cm=_get_indent_first_line_cm(p),
        line_spacing=_get_line_spacing(p),
        is_in_table=is_in_table,
    )


def _get_doc_default_font(document: DocxDocument) -> tuple[str | None, float | None]:
    """Extract default font from Normal style chain and docDefaults."""
    font_name, font_size_pt = _resolve_style_font(
        document.styles["Normal"] if "Normal" in document.styles else None,
    )
    if font_name is not None and font_size_pt is not None:
        return font_name, font_size_pt

    from docx.oxml.ns import qn

    _styles_elem = getattr(document.styles, "element", None)
    if _styles_elem is None:
        _styles_elem = getattr(document.styles, "_element", None)
    rpr = (
        _styles_elem.find(f"{qn('w:docDefaults')}/{qn('w:rPrDefault')}/{qn('w:rPr')}")
        if _styles_elem is not None else None
    )
    if rpr is not None:
        if font_name is None:
            rfonts = rpr.find(qn("w:rFonts"))
            if rfonts is not None:
                font_name = rfonts.get(qn("w:ascii"))
                if font_name is None:
                    theme_attr = rfonts.get(qn("w:asciiTheme"))
                    if theme_attr is not None:
                        font_name = _resolve_theme_font(document, theme_attr)
        if font_size_pt is None:
            sz = rpr.find(qn("w:sz"))
            if sz is not None:
                val = sz.get(qn("w:val"))
                if val:
                    font_size_pt = round(int(val) / 2, 1)
    if font_size_pt is None:
        font_size_pt = 10.0

    return font_name, font_size_pt


def _resolve_theme_font(document: DocxDocument, theme_attr: str) -> str | None:
    """Resolve a w:asciiTheme value (e.g. 'minorHAnsi') to an actual font name
    by reading the document's theme XML."""
    try:
        from docx.oxml.ns import qn
        theme_part = document.part.package.part_related_by(
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"
        )
        theme_elem = getattr(theme_part, 'element', None) or getattr(theme_part, '_element', None)
        if theme_elem is None:
            return None
        ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        mapping = {
            "minorHAnsi": ".//a:minorFont/a:latin",
            "majorHAnsi": ".//a:majorFont/a:latin",
            "minorEastAsia": ".//a:minorFont/a:ea",
            "majorEastAsia": ".//a:majorFont/a:ea",
        }
        xpath = mapping.get(theme_attr)
        if xpath is not None:
            elem = theme_elem.find(xpath, ns)
            if elem is not None:
                return elem.get("typeface")
    except (KeyError, AttributeError, ValueError):
        pass
    except Exception:
        logger.warning("Unexpected error resolving theme font '%s'", theme_attr, exc_info=True)
    return None


def iter_all(document: DocxDocument) -> list[Paragraph]:
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph as DocxParagraph

    default_font_name, default_font_size_pt = _get_doc_default_font(document)

    result: list[Paragraph] = []
    idx = 0

    def visit_paragraph(p: DocxParagraph, in_table: bool) -> None:
        nonlocal idx
        result.append(
            _build_paragraph(p, idx, in_table, default_font_name, default_font_size_pt),
        )
        idx += 1

    def visit_table(tbl_elem: object) -> None:
        for tr in tbl_elem.iterchildren(qn("w:tr")):
            for tc in tr.iterchildren(qn("w:tc")):
                for child in tc.iterchildren():
                    if child.tag == qn("w:p"):
                        visit_paragraph(DocxParagraph(child, document), True)
                    elif child.tag == qn("w:tbl"):
                        visit_table(child)

    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            visit_paragraph(DocxParagraph(child, document), False)
        elif child.tag == qn("w:tbl"):
            visit_table(child)

    return result
