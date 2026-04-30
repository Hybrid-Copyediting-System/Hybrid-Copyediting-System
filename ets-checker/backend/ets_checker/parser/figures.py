from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ets_checker.models import Figure, Paragraph, Table

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument

_FIG_CAPTION = re.compile(r"^Figure\.?\s+(\d+)\s*[.:]", re.IGNORECASE)
_TBL_CAPTION = re.compile(r"^Table\.?\s+(\d+)\s*[.:]", re.IGNORECASE)

def _has_image(docx_para: object) -> bool:
    from docx.oxml.ns import qn

    xml = getattr(docx_para, "_element", None)
    if xml is None:
        return False
    return (
        xml.find(f".//{qn('w:drawing')}") is not None
        or xml.find(f".//{qn('w:pict')}") is not None
    )


def _walk_document_events(
    document: DocxDocument,
    paragraphs: list,
) -> list[dict]:
    """Walk the document XML in order and return a flat list of events
    for every paragraph that is either an image or a figure caption.

    `paragraphs` is the canonical list built by paragraphs.iter_all().
    Its indices are used as the authoritative seq values so that figure
    paragraph_index values stay in sync with the rest of the system even
    if the two walkers' traversal logic ever diverges.
    """
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph as DocxParagraph

    events: list[dict] = []
    pos = 0  # mirrors the Paragraph list index (== Paragraph.index)

    def _visit_para(elem: object, in_table: bool) -> None:
        nonlocal pos
        if pos < len(paragraphs):
            actual_index = paragraphs[pos].index
            text = paragraphs[pos].text.strip()
        else:
            actual_index = pos
            text = (DocxParagraph(elem, document).text or "").strip()
        docx_p = DocxParagraph(elem, document)
        is_img = _has_image(docx_p)
        m = _FIG_CAPTION.match(text)
        if is_img:
            events.append({"kind": "image", "seq": actual_index, "in_table": in_table,
                           "fig_num": None, "text": text})
        if m:
            events.append({"kind": "caption", "seq": actual_index, "in_table": in_table,
                           "fig_num": int(m.group(1)), "text": text})
        pos += 1

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

    events = _walk_document_events(document, paragraphs)

    images = [e for e in events if e["kind"] == "image"]
    captions = [e for e in events if e["kind"] == "caption"]

    caption_by_num: dict[int, dict] = {}
    for cap in captions:
        caption_by_num.setdefault(cap["fig_num"], cap)

    para_by_text: dict[str, list[Paragraph]] = {}
    for p in paragraphs:
        stripped = p.text.strip()
        if stripped:
            para_by_text.setdefault(stripped, []).append(p)

    para_text_used: dict[str, int] = {}

    def _lookup_para(text: str) -> Paragraph | None:
        entries = para_by_text.get(text)
        if not entries:
            return None
        use_idx = para_text_used.get(text, 0)
        if use_idx < len(entries):
            para_text_used[text] = use_idx + 1
            return entries[use_idx]
        return entries[-1]

    MAX_CAPTION_DISTANCE = 10

    used_captions: set[int] = set()

    def _find_nearest_caption(img_event: dict) -> dict | None:
        best: dict | None = None
        best_dist = float("inf")
        for cap in captions:
            if cap["fig_num"] in used_captions:
                continue
            dist = abs(cap["seq"] - img_event["seq"])
            if dist > MAX_CAPTION_DISTANCE:
                continue
            if dist < best_dist:
                best_dist = dist
                best = cap
        return best

    fig_idx = 0
    for img in images:
        cap = _find_nearest_caption(img)
        fig_num: int | None = None
        caption_text: str | None = None
        para_index = img["seq"]
        caption_pos: str | None = None

        if cap is not None:
            fig_num = cap["fig_num"]
            caption_text = cap["text"]
            used_captions.add(fig_num)
            p = _lookup_para(caption_text)
            if p is not None:
                para_index = p.index
            if cap["seq"] < img["seq"]:
                caption_pos = "above"
            elif cap["seq"] > img["seq"]:
                caption_pos = "below"

        if para_index >= len(paragraphs):
            para_index = max(0, len(paragraphs) - 1)

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
            p = _lookup_para(cap["text"])
            figures.append(Figure(
                index=fig_idx,
                figure_number=cap["fig_num"],
                caption_text=cap["text"],
                paragraph_index=p.index if p else cap["seq"],
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
