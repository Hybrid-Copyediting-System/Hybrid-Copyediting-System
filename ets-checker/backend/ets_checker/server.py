from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import deque
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ets_checker.models import CheckReport
from ets_checker.services import (
    DocumentParseError,
    annotate_document,
    cleanup_temp,
    parse_document,
    process_document,
    save_temp,
)
from ets_checker.rules.runner import run_async

import ets_checker.rules  # noqa: F401 — triggers rule registration via __init__

logger = logging.getLogger(__name__)

app = FastAPI(title="ET&S Format Checker", version="0.1.0")

_ets_port = os.environ.get("ETS_PORT", "8080")
_cors_origins = [
    "http://localhost:5173",
    "http://localhost:8080",
    f"http://localhost:{_ets_port}",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(set(_cors_origins)),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)


_PARSE_ERROR_DETAIL = (
    "Could not parse the uploaded document. Ensure it is a valid .docx file."
)


@app.exception_handler(DocumentParseError)
async def _parse_error_handler(request: Request, exc: DocumentParseError) -> JSONResponse:
    # The originating exception was already logged at the source (services.parse_document);
    # the handler just translates it into a uniform HTTP response.
    return JSONResponse(status_code=422, content={"detail": _PARSE_ERROR_DETAIL})


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ── Per-IP sliding-window rate limiter ───────────────────────────────────
# Lightweight in-memory throttle for the upload endpoints. Sized for the
# single-process deployment this app targets; for a multi-worker / multi-host
# rollout, swap in a Redis-backed limiter (e.g. slowapi). Defaults can be
# overridden via env vars without a redeploy.
_RATE_LIMIT_REQUESTS = int(os.environ.get("ETS_RATE_LIMIT_REQUESTS", "20"))
_RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("ETS_RATE_LIMIT_WINDOW", "60"))
_rate_buckets: dict[str, deque[float]] = {}
_rate_lock = asyncio.Lock()


async def _enforce_rate_limit(request: Request) -> None:
    client = request.client
    ip = client.host if client else "unknown"
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW_SECONDS
    async with _rate_lock:
        bucket = _rate_buckets.setdefault(ip, deque())
        while bucket and bucket[0] < window_start:
            bucket.popleft()
        if len(bucket) >= _RATE_LIMIT_REQUESTS:
            retry_after = max(1, int(bucket[0] + _RATE_LIMIT_WINDOW_SECONDS - now))
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please slow down.",
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/check", response_model=CheckReport)
async def check(request: Request, file: UploadFile = File(...)) -> CheckReport:
    await _enforce_rate_limit(request)
    tmp_path, filename = await save_temp(file)
    try:
        return await process_document(tmp_path, filename)
    finally:
        cleanup_temp(tmp_path)


@app.post("/api/check/stream")
async def check_stream(request: Request, file: UploadFile = File(...)) -> StreamingResponse:
    await _enforce_rate_limit(request)
    tmp_path, filename = await save_temp(file)

    async def generate():
        runner_task: asyncio.Task[None] | None = None
        try:
            yield _sse("progress", {"phase": "parsing", "message": "Parsing document..."})

            try:
                parsed = parse_document(tmp_path)
            except DocumentParseError:
                yield _sse("error", {"message": _PARSE_ERROR_DETAIL})
                return

            queue: asyncio.Queue[dict] = asyncio.Queue()

            async def on_progress(event: dict) -> None:
                await queue.put(event)

            async def _run() -> None:
                try:
                    report = await run_async(parsed, filename, on_progress=on_progress)
                    await queue.put({"_done": True, "report": report.model_dump(mode="json")})
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Rule runner failed during streaming check")
                    await queue.put({"_done": True, "_error": "Internal error while running checks"})

            runner_task = asyncio.create_task(_run())

            while True:
                event = await queue.get()
                if event.get("_done"):
                    if "_error" in event:
                        yield _sse("error", {"message": event["_error"]})
                    else:
                        yield _sse("complete", event["report"])
                    return
                yield _sse("progress", event)

        finally:
            # Cancel the background runner if the client disconnected early
            # and await it so the CancelledError is consumed and any held
            # resources (httpx clients, file handles) are released.
            if runner_task is not None and not runner_task.done():
                runner_task.cancel()
                try:
                    await runner_task
                except (asyncio.CancelledError, Exception):
                    pass
            cleanup_temp(tmp_path)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/check/annotated")
async def check_annotated(
    request: Request,
    file: UploadFile = File(...),
    report_json: str | None = Form(default=None),
) -> Response:
    await _enforce_rate_limit(request)
    tmp_path, filename = await save_temp(file)
    try:
        report: CheckReport | None = None
        if report_json:
            try:
                report = CheckReport.model_validate_json(report_json)
            except ValueError:
                logger.warning("Invalid report_json provided; re-running checks")

        if report is None:
            report = await process_document(tmp_path, filename)

        try:
            blob = annotate_document(tmp_path, report)
        except Exception:
            logger.exception("Failed to annotate document")
            raise HTTPException(
                status_code=500,
                detail="Could not generate annotated document.",
            )

        # Sanitize the upload's stem before splicing it into a Content-Disposition
        # header. Strips header-injection vectors (CR/LF, quotes) and path-traversal
        # patterns, and bounds the length so a hostile filename can't inflate the
        # response header.
        raw_stem = filename.rsplit(".", 1)[0]
        # ASCII-only allowlist matches the audit recommendation. Non-ASCII
        # filenames are still preserved in the RFC 5987 `filename*` form
        # (which is percent-encoded below); this only governs the legacy
        # ASCII `filename=` parameter and the path-safety of `out_name`.
        safe_stem = re.sub(r"[^a-zA-Z0-9._\-]", "_", raw_stem)[:100] or "document"
        out_name = f"{safe_stem}.annotated.docx"
        encoded_name = quote(out_name)
        return Response(
            content=blob,
            media_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            headers={
                "Content-Disposition": (
                    f"attachment; filename=\"{out_name.encode('ascii', 'replace').decode()}\"; "
                    f"filename*=UTF-8''{encoded_name}"
                ),
            },
        )
    finally:
        cleanup_temp(tmp_path)


# Mount frontend dist if it exists (production mode)
_frontend_dist = Path(__file__).parent / "frontend_dist"
if _frontend_dist.is_dir() and any(_frontend_dist.iterdir()):
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
