from __future__ import annotations

from typing import TYPE_CHECKING

from docx.shared import Emu

from ets_checker.models import Paragraph, Run

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument
    from docx.text.paragraph import Paragraph as DocxParagraph

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
    pf = p.paragraph_format
    if pf.line_spacing is not None:
        return float(pf.line_spacing)
    return None


def _get_indent_left_cm(p: DocxParagraph) -> float | None:
    pf = p.paragraph_format
    val = pf.left_indent
    if val is not None:
        return round(int(Emu(val)) / EMU_PER_CM, 4)
    return None


def _get_alignment(p: DocxParagraph) -> str | None:
    a = p.alignment
    if a is not None:
        return str(a).split(".")[-1].split("(")[0]
    return None


def _build_paragraph(p: DocxParagraph, index: int, is_in_table: bool) -> Paragraph:
    return Paragraph(
        index=index,
        text=p.text or "",
        style_name=p.style.name if p.style else None,
        runs=[_build_run(r) for r in p.runs],
        alignment=_get_alignment(p),
        indent_left_cm=_get_indent_left_cm(p),
        line_spacing=_get_line_spacing(p),
        is_in_table=is_in_table,
    )


def iter_all(document: DocxDocument) -> list[Paragraph]:
    result: list[Paragraph] = []
    idx = 0
    for p in document.paragraphs:
        result.append(_build_paragraph(p, idx, False))
        idx += 1
    for t in document.tables:
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    result.append(_build_paragraph(p, idx, True))
                    idx += 1
    return result
