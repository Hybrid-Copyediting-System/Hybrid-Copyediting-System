from __future__ import annotations

import re
from typing import TYPE_CHECKING

from lxml import etree

from ets_checker.models import Figure, Paragraph, Table

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument

_FIG_CAPTION = re.compile(r"^Figure\.?\s+(\d+)\s*[.:]", re.IGNORECASE)
_TBL_CAPTION = re.compile(r"^Table\.?\s+(\d+)\s*[.:]", re.IGNORECASE)

NSMAP = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _has_image(docx_para: object) -> bool:
    xml = getattr(docx_para, "_element", None)
    if xml is None:
        return False
    xml_str = etree.tostring(xml, encoding="unicode")
    return "<w:drawing" in xml_str or "<w:pict" in xml_str


def _walk_document_events(
    document: DocxDocument,
) -> list[dict]:
    """Walk the document XML in order and return a flat list of events
    for every paragraph that is either an image or a figure caption."""
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph as DocxParagraph

    events: list[dict] = []
    seq = 0

    def _visit_para(elem: object, in_table: bool) -> None:
        nonlocal seq
        p = DocxParagraph(elem, document)
        text = (p.text or "").strip()
        is_img = _has_image(p)
        m = _FIG_CAPTION.match(text)
        if is_img:
            events.append({"kind": "image", "seq": seq, "in_table": in_table,
                           "fig_num": None, "text": text})
        if m:
            events.append({"kind": "caption", "seq": seq, "in_table": in_table,
                           "fig_num": int(m.group(1)), "text": text})
        seq += 1

    def _walk_table(tbl_elem: object) -> None:
        for tr in tbl_elem.iterchildren(qn("w:tr")):
            for tc in tr.iterchildren(qn("w:tc")):
                for child in tc.iterchildren():
                    if child.tag == qn("w:p"):
                        _visit_para(child, True)
                    elif child.tag == qn("w:tbl"):
                        _walk_table(child)

    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            _visit_para(child, False)
        elif child.tag == qn("w:tbl"):
            _walk_table(child)

    return events


def detect(
    paragraphs: list[Paragraph],
    document: DocxDocument,
) -> tuple[list[Figure], list[Table]]:
    figures: list[Figure] = []
    tables: list[Table] = []

    events = _walk_document_events(document)

    images = [e for e in events if e["kind"] == "image"]
    captions = [e for e in events if e["kind"] == "caption"]

    caption_by_num: dict[int, dict] = {}
    for cap in captions:
        caption_by_num.setdefault(cap["fig_num"], cap)

    para_by_text: dict[str, Paragraph] = {}
    for p in paragraphs:
        if p.text.strip() and p.text.strip() not in para_by_text:
            para_by_text[p.text.strip()] = p

    used_captions: set[int] = set()

    def _find_nearest_caption(img_event: dict) -> dict | None:
        best: dict | None = None
        best_dist = float("inf")
        for cap in captions:
            if cap["fig_num"] in used_captions:
                continue
            dist = abs(cap["seq"] - img_event["seq"])
            if dist < best_dist:
                best_dist = dist
                best = cap
        return best

    fig_idx = 0
    for img in images:
        cap = _find_nearest_caption(img)
        fig_num: int | None = None
        caption_text: str | None = None
        para_index = 0

        if cap is not None:
            fig_num = cap["fig_num"]
            caption_text = cap["text"]
            used_captions.add(fig_num)
            p = para_by_text.get(caption_text)
            if p is not None:
                para_index = p.index

        figures.append(Figure(
            index=fig_idx,
            figure_number=fig_num,
            caption_text=caption_text,
            paragraph_index=para_index,
        ))
        fig_idx += 1

    for cap in captions:
        if cap["fig_num"] not in used_captions:
            p = para_by_text.get(cap["text"])
            figures.append(Figure(
                index=fig_idx,
                figure_number=cap["fig_num"],
                caption_text=cap["text"],
                paragraph_index=p.index if p else 0,
            ))
            fig_idx += 1
            used_captions.add(cap["fig_num"])

    # ── Table detection ───────────────────────────────────────────────────

    _elem_to_docx_para = {dp._element: dp for dp in document.paragraphs}
    non_table_paras = [p for p in paragraphs if not p.is_in_table]

    for tbl_idx, _tbl in enumerate(document.tables):
        tbl_caption: str | None = None
        tbl_num: int | None = None
        p_idx = 0

        tbl_elem = _tbl._element
        prev = tbl_elem.getprevious()
        next_elem = tbl_elem.getnext()

        for elem in [prev, next_elem]:
            if elem is not None and elem.tag.endswith("}p"):
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
