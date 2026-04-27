from __future__ import annotations

from io import BytesIO

from docx import Document

from ets_checker.exporter._comments_xml import (
    CommentsManager,
    ensure_comment_reference_style,
    wrap_paragraph_with_comment,
)
from ets_checker.exporter.anchor import build_paragraph_element_index, resolve_anchor
from ets_checker.models import CheckDetail, CheckReport, CheckResult


def _format_comment_text(result: CheckResult, detail: CheckDetail) -> str:
    lines = [f"[{result.severity}] {result.rule_id} — {detail.message}"]
    if detail.expected is not None:
        lines.append(f"Expected: {detail.expected}")
    if detail.actual is not None:
        lines.append(f"Actual: {detail.actual}")
    if detail.excerpt:
        lines.append(f"Excerpt: {detail.excerpt}")
    return "\n".join(lines)


def annotate(
    src_path: str,
    report: CheckReport,
    author: str = "ET&S Checker",
) -> bytes:
    """
    Open ``src_path``, inject one Word comment per failed ``CheckDetail``,
    and return the bytes of the resulting ``.docx``.

    The source file is not modified.
    """
    document = Document(src_path)

    ensure_comment_reference_style(document)
    para_index = build_paragraph_element_index(document)
    comments = CommentsManager(document)

    for result in report.results:
        if result.status != "fail":
            continue
        for detail in result.details:
            anchor = resolve_anchor(detail, para_index)
            if anchor is None:
                continue
            cid = comments.add_comment(
                _format_comment_text(result, detail),
                author=author,
            )
            wrap_paragraph_with_comment(anchor, cid)

    comments.flush()

    out = BytesIO()
    document.save(out)
    return out.getvalue()
