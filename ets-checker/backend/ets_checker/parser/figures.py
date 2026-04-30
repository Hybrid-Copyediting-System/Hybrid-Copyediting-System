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
        caption_pos: str | None = None

        if cap is not None:
            fig_num = cap["fig_num"]
            caption_text = cap["text"]
            used_captions.add(fig_num)
            p = para_by_text.get(caption_text)
            if p is not None:
                para_index = p.index
            if cap["seq"] < img["seq"]:
                caption_pos = "above"
            elif cap["seq"] > img["seq"]:
                caption_pos = "below"

        figures.append(Figure(
            index=fig_idx,
            figure_number=fig_num,
            caption_text=caption_text,
            paragraph_index=para_index,
            caption_position=caption_pos,
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
        tbl_caption_pos: str | None = None

        tbl_elem = _tbl._element
        prev = tbl_elem.getprevious()
        next_elem = tbl_elem.getnext()

        for label, elem in [("above", prev), ("below", next_elem)]:
            if elem is not None and elem.tag.endswith("}p"):
                dp = _elem_to_docx_para.get(elem)
                text = dp.text.strip() if dp is not None else "".join(str(t) for t in elem.itertext()).strip()
                m = _TBL_CAPTION.match(text)
                if m:
                    tbl_num = int(m.group(1))
                    tbl_caption = text
                    tbl_caption_pos = label
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
            caption_position=tbl_caption_pos,
            has_vertical_borders=_has_vertical_borders(tbl_elem),
        ))

    return figures, tables


def _has_vertical_borders(tbl_element: object) -> bool:
    """Check if a Word table has vertical borders at any level.

    Checks three layers (table-level → style-name → cell-level) matching the
    OOXML border-resolution chain described in the gap analysis.
    """
    from docx.oxml.ns import qn

    def _border_active(parent: object, tag: str) -> bool:
        bdr = parent.find(qn(tag))
        if bdr is None:
            return False
        val = bdr.get(qn("w:val"))
        return bool(val and val not in ("none", "nil"))

    # Layer 1: table-level explicit borders
    tbl_pr = tbl_element.find(qn("w:tblPr"))
    if tbl_pr is not None:
        tbl_borders = tbl_pr.find(qn("w:tblBorders"))
        if tbl_borders is not None:
            for tag in ["w:insideV", "w:left", "w:right"]:
                if _border_active(tbl_borders, tag):
                    return True

        # Layer 2: known grid-type styles whose definitions include vertical borders
        tbl_style = tbl_pr.find(qn("w:tblStyle"))
        if tbl_style is not None:
            style_id = tbl_style.get(qn("w:val")) or ""
            if "Grid" in style_id:
                return True

    # Layer 3: cell-level borders — catches manual per-cell formatting
    for tc in tbl_element.iter(qn("w:tc")):
        tc_pr = tc.find(qn("w:tcPr"))
        if tc_pr is None:
            continue
        tc_borders = tc_pr.find(qn("w:tcBorders"))
        if tc_borders is None:
            continue
        for tag in ["w:left", "w:right"]:
            if _border_active(tc_borders, tag):
                return True

    return False
