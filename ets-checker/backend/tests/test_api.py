from __future__ import annotations

import io
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from ets_checker.server import app


def _get_fixture(name: str) -> Path:
    p = Path(__file__).parent / "fixtures" / name
    if not p.exists():
        pytest.skip(f"Fixture {name} not found")
    return p


@pytest.mark.asyncio
async def test_health() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_check_no_file() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/check")
    assert r.status_code == 422 or r.status_code == 400


@pytest.mark.asyncio
async def test_check_wrong_extension() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/check",
            files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_check_doc_extension() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/check",
            files={"file": ("test.doc", io.BytesIO(b"hello"), "application/msword")},
        )
    assert r.status_code == 400
    assert "docx" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_check_annotated_wrong_extension() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/check/annotated",
            files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_check_annotated_returns_docx() -> None:
    """Round-trip: build a synthetic docx, POST it, expect a docx back."""
    from docx import Document as _Document  # local import — keeps top tidy

    buf = io.BytesIO()
    doc = _Document()
    doc.add_paragraph("Title")
    doc.add_paragraph("Abstract")
    doc.add_paragraph("Body text.")
    doc.save(buf)
    buf.seek(0)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/check/annotated",
            files={
                "file": (
                    "synthetic.docx",
                    buf,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "synthetic.annotated.docx" in r.headers["content-disposition"]
    assert r.content[:2] == b"PK"


@pytest.mark.asyncio
async def test_check_template() -> None:
    p = _get_fixture("ets_template.docx")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with open(p, "rb") as f:
            r = await ac.post(
                "/api/check",
                files={"file": ("ets_template.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )
    assert r.status_code == 200
    data = r.json()
    assert "summary" in data
    assert data["summary"]["total_checks"] == 8
