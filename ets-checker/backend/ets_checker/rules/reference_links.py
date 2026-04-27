from __future__ import annotations

import asyncio

import httpx

from ets_checker.models import CheckDetail, Locator, ParsedDocument, Reference
from ets_checker.rules.runner import register_async

TIMEOUT = 10.0
CONCURRENCY = 5
MAX_REPORTED = 20


async def _check_url(
    url: str,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
) -> tuple[str, str | None]:
    """Return (url, error_message). error_message is None when the link is OK."""
    async with sem:
        try:
            resp = await client.head(url)
            if resp.status_code == 405:
                resp = await client.get(url)
            code = resp.status_code
            if code in (404, 410):
                return url, f"HTTP {code} - page not found"
            # 403/429/5xx: access restricted or server-side blocking (common for
            # publisher sites that block automated requests). Cannot confirm broken.
            return url, None
        except httpx.TimeoutException:
            return url, "request timed out"
        except httpx.ConnectError:
            return url, "could not connect"
        except Exception as exc:
            msg = str(exc)
            # Decompression failures (Zstandard, gzip truncation, etc.) mean the
            # server responded — it's reachable, just using an encoding httpx
            # couldn't fully decode (common with CDN-served academic sites).
            if any(k in msg for k in ("Zstandard", "zstd", "decompress", "Decompress")):
                return url, None
            return url, f"error: {msg[:60]}"


@register_async("reference.links", "Reference", "Reference link check", "warning")
async def check_reference_links(doc: ParsedDocument) -> list[CheckDetail]:
    # Build (ref, canonical_url, label) for every link found in references
    tasks: list[tuple[Reference, str, str]] = []
    for ref in doc.references:
        if ref.doi:
            tasks.append((ref, f"https://doi.org/{ref.doi}", "DOI"))
        for u in ref.urls:
            tasks.append((ref, u, "URL"))

    if not tasks:
        return []

    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (compatible) ETS-Checker/1.0"},
    ) as client:
        outcomes = await asyncio.gather(
            *[_check_url(url, client, sem) for _, url, _ in tasks]
        )

    details: list[CheckDetail] = []
    broken = 0
    for (ref, url, label), (_, error) in zip(tasks, outcomes):
        if not error:
            continue
        broken += 1
        if broken <= MAX_REPORTED:
            details.append(CheckDetail(
                location=f"Reference #{ref.index}",
                locator=Locator(kind="paragraph", paragraph_index=ref.paragraph_index),
                message=f"{label} link unreachable: {error}",
                expected="accessible link",
                actual=url,
                excerpt=ref.raw_text[:120],
            ))

    if broken > MAX_REPORTED:
        details.append(CheckDetail(
            location="document",
            locator=Locator(kind="document"),
            message=f"... and {broken - MAX_REPORTED} more broken links",
        ))

    return details
