from __future__ import annotations

import re
from typing import TYPE_CHECKING

from lxml import etree

from ets_checker.models import Figure, Paragraph, Table

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument

_FIG_CAPTION = re.compile(r"^Figure\.?\s+(\d+)", re.IGNORECASE)
_TBL_CAPTION = re.compile(r"^Table\.?\s+(\d+)", re.IGNORECASE)

NSMAP = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _has_image(docx_para: object) -> bool:
    xml = getattr(docx_para, "_element", None)
    if xml is None:
        return False
    xml_str = etree.tostring(xml, encoding="unicode")
    return "<w:drawing" in xml_str or "<w:pict" in xml_str


def detect(
    paragraphs: list[Paragraph],
    document: DocxDocument,
) -> tuple[list[Figure], list[Table]]:
    figures: list[Figure] = []
    tables: list[Table] = []

    # Detect figures from document paragraphs that contain images
    docx_paras = list(document.paragraphs)
    image_indices: list[int] = []
    for i, dp in enumerate(docx_paras):
        if _has_image(dp):
            image_indices.append(i)

    non_table_paras = [p for p in paragraphs if not p.is_in_table]

    fig_idx = 0
    for img_i in image_indices:
        caption_text: str | None = None
        fig_num: int | None = None
        # Use the actual Paragraph.index (which accounts for table paragraphs that
        # shift indices in iter_all) rather than the list position.
        para_index = non_table_paras[img_i].index if img_i < len(non_table_paras) else 0

        for offset in range(-2, 3):
            check_i = img_i + offset
            if 0 <= check_i < len(non_table_paras):
                m = _FIG_CAPTION.match(non_table_paras[check_i].text.strip())
                if m:
                    fig_num = int(m.group(1))
                    caption_text = non_table_paras[check_i].text.strip()
                    para_index = non_table_paras[check_i].index
                    break

        figures.append(Figure(
            index=fig_idx,
            figure_number=fig_num,
            caption_text=caption_text,
            paragraph_index=para_index,
        ))
        fig_idx += 1

    # Build a map from XML element → python-docx paragraph to get clean text
    # (elem.itertext() can include bookmark/field-code duplicates in Word docs).
    _elem_to_docx_para = {dp._element: dp for dp in document.paragraphs}

    # Detect tables
    for tbl_idx, _tbl in enumerate(document.tables):
        tbl_caption: str | None = None
        tbl_num: int | None = None
        p_idx = 0

        tbl_elem = _tbl._element
        prev = tbl_elem.getprevious()
        next_elem = tbl_elem.getnext()

        for elem in [prev, next_elem]:
            if elem is not None and elem.tag.endswith("}p"):
                # Use python-docx .text to avoid field-code/bookmark duplicates
                dp = _elem_to_docx_para.get(elem)
                text = dp.text.strip() if dp is not None else "".join(str(t) for t in elem.itertext()).strip()
                m = _TBL_CAPTION.match(text)
                if m:
                    tbl_num = int(m.group(1))
                    tbl_caption = text
                    break

        if tbl_caption:
            for pp in non_table_paras:
                if pp.text.strip() == tbl_caption:
                    p_idx = pp.index
                    break

        tables.append(Table(
            index=tbl_idx,
            table_number=tbl_num,
            caption_text=tbl_caption,
            paragraph_index=p_idx,
        ))

    return figures, tables
