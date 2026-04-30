from __future__ import annotations

from typing import TYPE_CHECKING

from ets_checker.models import DocumentMetadata

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument

EMU_PER_CM = 360000

_A4_W = 21.0
_A4_H = 29.7
_LETTER_W = 21.59
_LETTER_H = 27.94
_SIZE_TOL = 0.5


def _classify_paper_size(width_emu: int, height_emu: int) -> str | None:
    w = width_emu / EMU_PER_CM
    h = height_emu / EMU_PER_CM
    if abs(w - _A4_W) < _SIZE_TOL and abs(h - _A4_H) < _SIZE_TOL:
        return "A4"
    if abs(w - _LETTER_W) < _SIZE_TOL and abs(h - _LETTER_H) < _SIZE_TOL:
        return "Letter"
    return None


def _get_normal_style_line_spacing(document: DocxDocument) -> float | None:
    try:
        from docx.enum.text import WD_LINE_SPACING

        style = document.styles["Normal"]
        pf = style.paragraph_format
        if pf.line_spacing is not None:
            rule = pf.line_spacing_rule
            if rule in (WD_LINE_SPACING.EXACTLY, WD_LINE_SPACING.AT_LEAST):
                return None
            return float(pf.line_spacing)
    except (KeyError, AttributeError):
        pass
    return None


def _has_page_numbers(document: DocxDocument) -> bool:
    """Check if any section header/footer contains a PAGE field code.

    Scans default, first-page, and even-page headers/footers across all
    document sections.
    """
    try:
        from docx.oxml.ns import qn
    except ImportError:
        return False

    def _scan_hf(hf: object) -> bool:
        try:
            if hf.is_linked_to_previous:
                return False
            for p in hf.paragraphs:
                for instr in p._element.iter(qn("w:instrText")):
                    if instr.text and "PAGE" in instr.text.upper():
                        return True
        except Exception:
            pass
        return False

    for section in document.sections:
        if _scan_hf(section.header) or _scan_hf(section.footer):
            return True
        try:
            if section.different_first_page_header_footer:
                if (_scan_hf(section.first_page_header)
                        or _scan_hf(section.first_page_footer)):
                    return True
        except (AttributeError, Exception):
            pass
        try:
            if (_scan_hf(section.even_page_header)
                    or _scan_hf(section.even_page_footer)):
                return True
        except (AttributeError, Exception):
            pass

    return False


def extract(document: DocxDocument) -> DocumentMetadata:
    if not document.sections:
        return DocumentMetadata(
            paper_width_cm=0, paper_height_cm=0, paper_size=None,
            margin_top_cm=0, margin_bottom_cm=0, margin_left_cm=0, margin_right_cm=0,
            default_line_spacing=None,
        )
    s = document.sections[0]
    pw = int(s.page_width or 0)
    ph = int(s.page_height or 0)
    mt = int(s.top_margin or 0)
    mb = int(s.bottom_margin or 0)
    ml = int(s.left_margin or 0)
    mr = int(s.right_margin or 0)
    return DocumentMetadata(
        paper_width_cm=round(pw / EMU_PER_CM, 4),
        paper_height_cm=round(ph / EMU_PER_CM, 4),
        paper_size=_classify_paper_size(pw, ph),
        margin_top_cm=round(mt / EMU_PER_CM, 4),
        margin_bottom_cm=round(mb / EMU_PER_CM, 4),
        margin_left_cm=round(ml / EMU_PER_CM, 4),
        margin_right_cm=round(mr / EMU_PER_CM, 4),
        default_line_spacing=_get_normal_style_line_spacing(document),
        has_page_numbers=_has_page_numbers(document),
    )
