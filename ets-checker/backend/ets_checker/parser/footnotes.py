"""Footnote and endnote extraction.

python-docx exposes no API for footnotes/endnotes, so we parse the
``word/footnotes.xml`` and ``word/endnotes.xml`` parts directly. Word
always emits two synthetic entries per part (``separator`` and
``continuationSeparator``) — those are skipped. The remaining entries
are real author-authored notes.

ET&S forbids both forms (AQF Item 4: "DO NO use foot notes ... For
additional information, please place them in the text instead.") so we
treat endnotes the same as footnotes for reporting purposes.

Paragraph attribution is best-effort: each ``<w:footnoteReference>`` /
``<w:endnoteReference>`` in the document body is associated with the
index of the body paragraph that contains it. The body-walk uses the
same iteration order as ``paragraphs.iter_all`` so the indices align
across both modules.
"""

from __future__ import annotations

import logging
import zipfile
from typing import TYPE_CHECKING

from lxml import etree

from ets_checker.models import Footnote

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument

logger = logging.getLogger(__name__)

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _qn(tag: str) -> str:
    return f"{{{_W_NS}}}{tag}"


def _has_drawing(elem: object) -> bool:
    """Return True when an entry contains a drawing or picture but no text."""
    for d in elem.iter():
        local = etree.QName(d).localname
        if local in ("drawing", "pict"):
            return True
    return False


def _read_entries(
    docx_path: str,
    part_name: str,
    container_tag: str,
    entry_tag: str,
) -> list[tuple[int, str]]:
    """Read entries from a footnotes/endnotes part.

    Returns a list of ``(id, text)`` tuples in document order. Synthetic
    separator entries are filtered. Empty entries that contain a drawing or
    picture are kept with placeholder text so AQF Item 4 still flags them.
    """
    try:
        with zipfile.ZipFile(docx_path) as z:
            if part_name not in z.namelist():
                return []
            xml = z.read(part_name)
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        logger.warning("Could not read %s: %s", part_name, exc)
        return []

    try:
        tree = etree.fromstring(xml)
    except etree.XMLSyntaxError as exc:
        logger.warning("%s is malformed: %s", part_name, exc)
        return []

    # Validate root tag — guards against feeding the wrong part to the wrong
    # caller (e.g. footnotes.xml passed as endnotes.xml).
    root_local = etree.QName(tree).localname
    if root_local != container_tag:
        logger.warning(
            "%s has unexpected root <%s>, expected <%s>",
            part_name, root_local, container_tag,
        )
        return []

    out: list[tuple[int, str]] = []
    for entry in tree.findall(_qn(entry_tag)):
        entry_type = entry.get(_qn("type"))
        if entry_type in ("separator", "continuationSeparator"):
            continue
        id_attr = entry.get(_qn("id"))
        if id_attr is None:
            continue
        try:
            entry_id = int(id_attr)
        except ValueError:
            continue
        if entry_id < 0:
            continue
        text_parts = [t.text or "" for t in entry.findall(f".//{_qn('t')}")]
        text = "".join(text_parts).strip()
        if not text:
            if _has_drawing(entry):
                # Word allows image-only footnotes; ET&S still forbids them.
                text = "[image-only note]"
            else:
                continue
        out.append((entry_id, text))
    return out


def _build_id_to_paragraph_map(
    document: DocxDocument,
    note_kinds: tuple[str, ...],
) -> dict[tuple[str, int], int]:
    """Walk the body in iter_all order, recording the first paragraph index
    for each ``(kind, id)`` reference encountered.

    ``note_kinds`` are the local names of the reference tags to look for —
    ``footnoteReference`` and/or ``endnoteReference``. Only the first
    occurrence is recorded, matching how authors typically place a note
    once at its discussion site.
    """
    target_tags = {_qn(k): k.replace("Reference", "") for k in note_kinds}

    mapping: dict[tuple[str, int], int] = {}
    idx = 0

    def visit_paragraph(p_elem: object) -> None:
        nonlocal idx
        for ref in p_elem.iter():
            kind = target_tags.get(ref.tag)
            if kind is None:
                continue
            id_attr = ref.get(_qn("id"))
            if id_attr is None:
                continue
            try:
                ref_id = int(id_attr)
            except ValueError:
                continue
            key = (kind, ref_id)
            if key not in mapping:
                mapping[key] = idx
        idx += 1

    def visit_table(tbl_elem: object) -> None:
        for tr in tbl_elem.iterchildren(_qn("tr")):
            for tc in tr.iterchildren(_qn("tc")):
                for child in tc.iterchildren():
                    if child.tag == _qn("p"):
                        visit_paragraph(child)
                    elif child.tag == _qn("tbl"):
                        visit_table(child)

    for child in document.element.body.iterchildren():
        if child.tag == _qn("p"):
            visit_paragraph(child)
        elif child.tag == _qn("tbl"):
            visit_table(child)

    return mapping


def extract(document: DocxDocument, file_path: str) -> list[Footnote]:
    """Extract footnotes and endnotes from the docx package."""
    foot_entries = _read_entries(
        file_path, "word/footnotes.xml", "footnotes", "footnote",
    )
    end_entries = _read_entries(
        file_path, "word/endnotes.xml", "endnotes", "endnote",
    )
    if not foot_entries and not end_entries:
        return []

    mapping = _build_id_to_paragraph_map(
        document, ("footnoteReference", "endnoteReference"),
    )

    results: list[Footnote] = []
    for fn_id, text in foot_entries:
        results.append(Footnote(
            footnote_id=fn_id,
            text=text,
            paragraph_index=mapping.get(("footnote", fn_id)),
            kind="footnote",
        ))
    for en_id, text in end_entries:
        results.append(Footnote(
            footnote_id=en_id,
            text=text,
            paragraph_index=mapping.get(("endnote", en_id)),
            kind="endnote",
        ))
    return results
