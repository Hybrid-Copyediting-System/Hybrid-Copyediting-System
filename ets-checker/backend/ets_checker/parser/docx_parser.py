from __future__ import annotations

from docx import Document

from ets_checker.models import ParsedDocument
from ets_checker.parser import citations, figures, metadata, paragraphs, references, sections


def parse(file_path: str) -> ParsedDocument:
    document = Document(file_path)

    meta = metadata.extract(document)
    paras = paragraphs.iter_all(document)
    secs = sections.detect(paras)
    cits = citations.extract(paras, secs)
    refs = references.extract(paras, secs)
    figs, tbls = figures.detect(paras, document)

    return ParsedDocument(
        metadata=meta,
        paragraphs=paras,
        sections=secs,
        citations=cits,
        references=refs,
        figures=figs,
        tables=tbls,
    )
