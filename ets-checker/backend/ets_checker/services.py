"""Service layer that owns document parsing, rule running, and annotation.

Endpoint handlers in ``server.py`` deal with HTTP concerns (file upload,
rate limiting, response shaping); the actual document workflow lives
here so each step can be exercised without spinning up FastAPI.
"""
from __future__ import annotations

import logging
import os
import tempfile

from fastapi import HTTPException, UploadFile

from ets_checker.exporter import annotate
from ets_checker.models import CheckReport
from ets_checker.parser.docx_parser import parse
from ets_checker.rules.runner import ProgressCallback, run_async

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


class DocumentParseError(Exception):
    """Raised when a .docx upload cannot be parsed.

    Translated to a 422 by the FastAPI exception handler in ``server.py``;
    the streaming endpoint catches it directly so it can emit the failure
    as an SSE ``error`` event instead of an HTTP error.
    """


async def save_temp(file: UploadFile) -> tuple[str, str]:
    """Validate the upload and stream it to a private temp file.

    Returns ``(tmp_path, original_filename)``. The caller owns the temp
    file and is responsible for unlinking it.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    if not file.filename.lower().endswith(".docx"):
        if file.filename.lower().endswith(".doc"):
            raise HTTPException(
                status_code=400,
                detail="Please save as .docx and try again. "
                       "ET&S MVP only accepts .docx files. "
                       "Open in Word and use Save As → .docx.",
            )
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Please upload a .docx file.",
        )

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="File too large (max 50 MB)")
        chunks.append(chunk)
    content = b"".join(chunks)

    # Restrictive umask so the temp file isn't world-readable between
    # write completion and cleanup in the request's `finally` block.
    prev_umask = os.umask(0o077)
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
            tmp_path = tmp.name
            try:
                tmp.write(content)
            except Exception:
                os.unlink(tmp_path)
                raise
    finally:
        os.umask(prev_umask)

    return tmp_path, file.filename


def parse_document(tmp_path: str):
    """Parse a saved .docx, raising ``DocumentParseError`` on failure."""
    try:
        return parse(tmp_path)
    except Exception as e:
        logger.exception("Failed to parse uploaded document")
        raise DocumentParseError(str(e)) from e


async def process_document(
    tmp_path: str,
    filename: str,
    on_progress: ProgressCallback | None = None,
) -> CheckReport:
    """Parse + run all rules. Raises ``DocumentParseError`` if parsing fails."""
    parsed = parse_document(tmp_path)
    return await run_async(parsed, filename, on_progress=on_progress)


def annotate_document(tmp_path: str, report: CheckReport) -> bytes:
    """Apply the report's findings as Word comments and return the bytes."""
    return annotate(tmp_path, report)


def cleanup_temp(tmp_path: str) -> None:
    if tmp_path and os.path.exists(tmp_path):
        os.unlink(tmp_path)
