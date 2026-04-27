from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from lxml.etree import _Element  # noqa: PLC2701

from ets_checker.models import CheckDetail

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument


def build_paragraph_element_index(document: DocxDocument) -> list[_Element]:
    """
    Build the same combined paragraph list that ``parser/paragraphs.iter_all``
    builds, but return the underlying lxml ``<w:p>`` elements instead of
    ``Paragraph`` models.

    Order MUST match ``parser/paragraphs.iter_all`` exactly: walk
    ``<w:body>`` children in document order, entering each ``<w:tbl>``
    immediately when encountered (depth-first). Any change to that walk
    order must be mirrored in both files.
    """
    from docx.oxml.ns import qn

    out: list[_Element] = []

    def _visit_table(tbl_elem: _Element) -> None:
        for row in tbl_elem.iterchildren(qn("w:tr")):
            for cell in row.iterchildren(qn("w:tc")):
                for child in cell.iterchildren():
                    if child.tag == qn("w:p"):
                        out.append(child)
                    elif child.tag == qn("w:tbl"):
                        _visit_table(child)

    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            out.append(child)
        elif child.tag == qn("w:tbl"):
            _visit_table(child)

    return out


def resolve_anchor(
    detail: CheckDetail,
    para_index: list[_Element],
) -> _Element | None:
    """
    Map a ``CheckDetail.locator`` to the ``<w:p>`` element it should attach
    to. Document-level findings — and any out-of-range or missing locator —
    fall back to the first paragraph. Returns ``None`` only if the document
    has no paragraphs at all.
    """
    if not para_index:
        return None
    loc = detail.locator
    if loc is None or loc.kind == "document":
        return para_index[0]
    if loc.kind == "paragraph":
        idx = loc.paragraph_index
        if idx is None or idx < 0 or idx >= len(para_index):
            logger.warning(
                "Locator paragraph_index=%r out of range [0, %d); "
                "falling back to first paragraph. message=%s",
                idx,
                len(para_index),
                detail.message,
            )
            return para_index[0]
        return para_index[idx]
    logger.warning(
        "Unknown locator kind %r; falling back to first paragraph.", loc.kind
    )
    return para_index[0]
