from __future__ import annotations

import asyncio
import random

import httpx

from ets_checker.models import CheckDetail, Locator, ParsedDocument, Reference
from ets_checker.rules.runner import get_link_progress, register_async

TIMEOUT = 10.0
CONCURRENCY = 5
MAX_REPORTED = 20
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds; doubled on each subsequent attempt


async def _check_url(
    url: str,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
) -> tuple[str, str | None]:
    """Return (url, error_message). Retries transient failures with exponential backoff.

    The semaphore is acquired per-attempt so the slot is free during sleep between retries.
    """
    last_error: str | None = None
    for attempt in range(MAX_RETRIES):
        async with sem:
            try:
                resp = await client.head(url)
                if resp.status_code == 405:
                    resp = await client.get(url)
                code = resp.status_code
                if code in (404, 410):
                    return url, f"HTTP {code} - page not found"
                if code >= 500:
                    last_error = f"HTTP {code} - server error"
                    # Retry on 5xx — may be transient
                else:
                    # 403/429/2xx/3xx: either accessible or bot-blocked
                    return url, None
            except httpx.TimeoutException:
                last_error = "request timed out"
            except httpx.ConnectError:
                last_error = "could not connect"
            except Exception as exc:
                msg = str(exc)
                # Decompression failures mean the server responded — reachable.
                if any(k in msg for k in ("Zstandard", "zstd", "decompress", "Decompress")):
                    return url, None
                return url, f"error: {msg[:60]}"  # unknown error; don't retry

        if attempt < MAX_RETRIES - 1:
            delay = RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0.0, 0.5)
            await asyncio.sleep(delay)

    return url, last_error


@register_async("reference.links", "Reference", "Reference link check", "warning")
async def check_reference_links(doc: ParsedDocument) -> list[CheckDetail]:
    tasks: list[tuple[Reference, str, str]] = []
    for ref in doc.references:
        if ref.doi:
            tasks.append((ref, f"https://doi.org/{ref.doi}", "DOI"))
        for u in ref.urls:
            tasks.append((ref, u, "URL"))

    if not tasks:
        return []

    total = len(tasks)
    completed = [0]  # single-element list avoids nonlocal in nested async def
    on_link_progress = get_link_progress()
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (compatible) ETS-Checker/1.0"},
    ) as client:

        async def _check_and_count(url: str) -> tuple[str, str | None]:
            result = await _check_url(url, client, sem)
            completed[0] += 1
            if on_link_progress is not None:
                await on_link_progress(completed[0], total)
            return result

        outcomes = await asyncio.gather(
            *[_check_and_count(url) for _, url, _ in tasks]
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
