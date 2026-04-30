from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ets_checker.exporter import annotate
from ets_checker.models import CheckReport
from ets_checker.parser.docx_parser import parse
from ets_checker.rules.runner import run_async

# Import rule modules so they register via decorators
import ets_checker.rules.layout  # noqa: F401
import ets_checker.rules.fonts  # noqa: F401
import ets_checker.rules.structure  # noqa: F401
import ets_checker.rules.citation  # noqa: F401
import ets_checker.rules.reference  # noqa: F401
import ets_checker.rules.figures_tables  # noqa: F401
import ets_checker.rules.reference_links  # noqa: F401

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

app = FastAPI(title="ET&S Format Checker", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8080"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _validate_and_save(file: UploadFile) -> tuple[str, str]:
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

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
        tmp_path = tmp.name
        try:
            tmp.write(content)
        except Exception:
            os.unlink(tmp_path)
            raise

    return tmp_path, file.filename


@app.post("/api/check", response_model=CheckReport)
async def check(file: UploadFile = File(...)) -> CheckReport:
    tmp_path, filename = await _validate_and_save(file)
    try:
        try:
            parsed = parse(tmp_path)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Could not parse file: {e}",
            )

        return await run_async(parsed, filename)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.post("/api/check/stream")
async def check_stream(file: UploadFile = File(...)) -> StreamingResponse:
    tmp_path, filename = await _validate_and_save(file)

    async def generate():
        runner_task: asyncio.Task[None] | None = None
        try:
            yield _sse("progress", {"phase": "parsing", "message": "Parsing document..."})

            try:
                parsed = parse(tmp_path)
            except Exception as e:
                yield _sse("error", {"message": f"Could not parse file: {e}"})
                return

            queue: asyncio.Queue[dict] = asyncio.Queue()

            async def on_progress(event: dict) -> None:
                await queue.put(event)

            async def _run() -> None:
                try:
                    report = await run_async(parsed, filename, on_progress=on_progress)
                    await queue.put({"_done": True, "report": report.model_dump(mode="json")})
                except Exception as exc:
                    await queue.put({"_done": True, "_error": str(exc)})

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
            # Cancel the background runner if the client disconnected early.
            if runner_task is not None and not runner_task.done():
                runner_task.cancel()
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/check/annotated")
async def check_annotated(file: UploadFile = File(...)) -> Response:
    tmp_path, filename = await _validate_and_save(file)
    try:
        try:
            parsed = parse(tmp_path)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Could not parse file: {e}",
            )

        report = await run_async(parsed, filename)

        try:
            blob = annotate(tmp_path, report)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Could not annotate file: {e}",
            )

        stem = filename.rsplit(".", 1)[0]
        out_name = f"{stem}.annotated.docx"
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
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# Mount frontend dist if it exists (production mode)
_frontend_dist = Path(__file__).parent / "frontend_dist"
if _frontend_dist.is_dir() and any(_frontend_dist.iterdir()):
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
