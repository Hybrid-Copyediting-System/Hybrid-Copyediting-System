from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from docx.opc.constants import CONTENT_TYPE, RELATIONSHIP_TYPE
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from lxml import etree
from lxml.etree import _Element  # noqa: PLC2701

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NSMAP = {"w": W_NS}

logger = logging.getLogger(__name__)


def _q(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def _empty_comments_root() -> _Element:
    return etree.Element(_q("comments"), nsmap=NSMAP)


def _serialize(root: _Element) -> bytes:
    return etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def ensure_comment_reference_style(document: DocxDocument) -> None:
    """
    Make sure ``word/styles.xml`` defines a ``CommentReference`` character
    style. Without it, some Word builds drop the marker glyph entirely.
    """
    styles_el = document.styles._element
    existing = styles_el.find(
        f"{{{W_NS}}}style[@{{{W_NS}}}styleId='CommentReference']"
    )
    if existing is not None:
        return

    style_xml = (
        f'<w:style xmlns:w="{W_NS}" w:type="character" w:styleId="CommentReference">'
        '<w:name w:val="annotation reference"/>'
        '<w:rPr><w:sz w:val="16"/><w:szCs w:val="16"/></w:rPr>'
        "</w:style>"
    )
    styles_el.append(etree.fromstring(style_xml))


class CommentsManager:
    """
    Owns the ``word/comments.xml`` part lifecycle for one annotation pass.

    On construction it either reuses the existing comments part on the
    document or creates a fresh one. Comment ids are allocated above any
    existing id to avoid collisions in pre-commented sources.
    """

    def __init__(self, document: DocxDocument) -> None:
        self.document = document
        self.part: Part = self._get_or_create_part()
        # python-docx loads a pre-existing word/comments.xml as the
        # specialized ``CommentsPart`` (an ``XmlPart`` subclass) whose
        # serialized blob is rebuilt from ``_element`` on save. For those
        # parts we MUST mutate ``_element`` directly — writing ``_blob`` is
        # silently discarded. For freshly-created generic ``Part`` objects
        # there is no ``_element``, and we round-trip via the blob instead.
        existing_element = getattr(self.part, "_element", None)
        if existing_element is not None:
            self.root = existing_element
            self._owns_root = False
        else:
            self.root = etree.fromstring(self.part.blob)
            self._owns_root = True
        self._next_id: int = self._max_existing_id() + 1

    def _get_or_create_part(self) -> Part:
        for rel in self.document.part.rels.values():
            if rel.reltype == RELATIONSHIP_TYPE.COMMENTS and not rel.is_external:
                target: Part = rel.target_part
                return target

        blob = _serialize(_empty_comments_root())
        new_part = Part(
            partname=PackURI("/word/comments.xml"),
            content_type=CONTENT_TYPE.WML_COMMENTS,
            blob=blob,
            package=self.document.part.package,
        )
        self.document.part.relate_to(new_part, RELATIONSHIP_TYPE.COMMENTS)
        return new_part

    def _max_existing_id(self) -> int:
        # ``self.root`` may be a python-docx ``BaseOxmlElement`` (when
        # reusing an existing CommentsPart), which overrides ``xpath`` and
        # rejects the ``namespaces`` kwarg. Stay with ``findall`` for
        # portability.
        out = -1
        for c in self.root.findall(_q("comment")):
            raw = c.get(_q("id"))
            if raw is None:
                continue
            try:
                out = max(out, int(raw))
            except ValueError:
                logger.warning("Non-numeric comment id %r in source document; skipped.", raw)
                continue
        return out

    def add_comment(
        self,
        text: str,
        author: str = "ET&S Checker",
        initials: str = "ETS",
    ) -> int:
        cid = self._next_id
        self._next_id += 1

        comment = etree.SubElement(self.root, _q("comment"))
        comment.set(_q("id"), str(cid))
        comment.set(_q("author"), author)
        comment.set(_q("initials"), initials)
        comment.set(
            _q("date"),
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

        for line in (text.split("\n") if text else [""]):
            p = etree.SubElement(comment, _q("p"))
            r = etree.SubElement(p, _q("r"))
            t = etree.SubElement(r, _q("t"))
            t.text = line
            t.set(f"{{{XML_NS}}}space", "preserve")

        return cid

    def flush(self) -> None:
        """
        Make sure the modified tree is what gets written on save. For
        XmlPart-backed comments parts the mutations are already on
        ``_element`` and nothing needs to happen. For fresh generic parts
        we own a detached tree and must push it back to ``_blob``.
        """
        if self._owns_root:
            # ``Part.blob`` has no public setter on the python-docx versions
            # we support, so update the underlying attribute directly.
            self.part._blob = _serialize(self.root)


def wrap_paragraph_with_comment(p_elem: _Element, comment_id: int) -> None:
    """
    Insert ``<w:commentRangeStart>`` before the first run of ``p_elem``,
    ``<w:commentRangeEnd>`` after the last child, and append a run carrying
    ``<w:commentReference>`` at the end.
    """
    cid = str(comment_id)

    range_start = etree.Element(_q("commentRangeStart"))
    range_start.set(_q("id"), cid)

    range_end = etree.Element(_q("commentRangeEnd"))
    range_end.set(_q("id"), cid)

    ref_run = etree.Element(_q("r"))
    rpr = etree.SubElement(ref_run, _q("rPr"))
    rstyle = etree.SubElement(rpr, _q("rStyle"))
    rstyle.set(_q("val"), "CommentReference")
    ref = etree.SubElement(ref_run, _q("commentReference"))
    ref.set(_q("id"), cid)

    insert_idx = len(p_elem)
    for i, child in enumerate(p_elem):
        if child.tag != _q("pPr"):
            insert_idx = i
            break

    p_elem.insert(insert_idx, range_start)
    p_elem.append(range_end)
    p_elem.append(ref_run)
