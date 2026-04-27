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
