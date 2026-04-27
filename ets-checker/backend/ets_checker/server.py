from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ets_checker.models import CheckReport
from ets_checker.parser.docx_parser import parse
from ets_checker.rules.runner import run

# Import rule modules so they register via decorators
import ets_checker.rules.layout  # noqa: F401
import ets_checker.rules.fonts  # noqa: F401
import ets_checker.rules.structure  # noqa: F401
import ets_checker.rules.citation  # noqa: F401
import ets_checker.rules.reference  # noqa: F401
import ets_checker.rules.figures_tables  # noqa: F401

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

app = FastAPI(title="ET&S Format Checker", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8080"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/check", response_model=CheckReport)
async def check(file: UploadFile = File(...)) -> CheckReport:
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

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            parsed = parse(tmp_path)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Could not parse file: {e}",
            )

        report = run(parsed, file.filename)
        return report

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# Mount frontend dist if it exists (production mode)
_frontend_dist = Path(__file__).parent / "frontend_dist"
if _frontend_dist.is_dir() and any(_frontend_dist.iterdir()):
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
