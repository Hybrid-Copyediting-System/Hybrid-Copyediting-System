from __future__ import annotations

import asyncio
import contextvars
from datetime import datetime, timezone
from typing import Awaitable, Callable, Literal

from ets_checker.models import (
    CheckDetail,
    CheckReport,
    CheckResult,
    ParsedDocument,
    ReportSummary,
)

RuleFunc = Callable[[ParsedDocument], list[CheckDetail]]
AsyncRuleFunc = Callable[[ParsedDocument], Awaitable[list[CheckDetail]]]
ProgressCallback = Callable[[dict], Awaitable[None]]

_REGISTRY: list[tuple[str, str, str, str, RuleFunc]] = []
_ASYNC_REGISTRY: list[tuple[str, str, str, str, AsyncRuleFunc]] = []

# Threads a per-link progress callback into async rules without changing their signatures.
_link_progress_var: contextvars.ContextVar[
    Callable[[int, int], Awaitable[None]] | None
] = contextvars.ContextVar("_link_progress", default=None)


def get_link_progress() -> Callable[[int, int], Awaitable[None]] | None:
    return _link_progress_var.get()


def register(
    rule_id: str,
    category: str,
    name: str,
    severity: str,
) -> Callable[[RuleFunc], RuleFunc]:
    def decorator(fn: RuleFunc) -> RuleFunc:
        _REGISTRY.append((rule_id, category, name, severity, fn))
        return fn
    return decorator


def register_async(
    rule_id: str,
    category: str,
    name: str,
    severity: str,
) -> Callable[[AsyncRuleFunc], AsyncRuleFunc]:
    def decorator(fn: AsyncRuleFunc) -> AsyncRuleFunc:
        _ASYNC_REGISTRY.append((rule_id, category, name, severity, fn))
        return fn
    return decorator


def _make_result(
    rule_id: str,
    category: str,
    name: str,
    severity: str,
    details: list[CheckDetail],
) -> CheckResult:
    status: Literal["pass", "fail"] = "pass" if not details else "fail"
    return CheckResult(
        rule_id=rule_id,
        category=category,
        name=name,
        status=status,
        severity=severity,  # type: ignore[arg-type]
        details=details,
    )


def _build_report(file_name: str, results: list[CheckResult]) -> CheckReport:
    passed = sum(1 for r in results if r.status == "pass")
    errors = sum(1 for r in results if r.status == "fail" and r.severity == "error")
    warnings = sum(1 for r in results if r.status == "fail" and r.severity == "warning")
    info_count = sum(1 for r in results if r.status == "fail" and r.severity == "info")

    return CheckReport(
        file_name=file_name,
        timestamp=datetime.now(timezone.utc),
        summary=ReportSummary(
            total_checks=len(results),
            passed=passed,
            errors=errors,
            warnings=warnings,
            info=info_count,
        ),
        results=results,
    )


def run(doc: ParsedDocument, file_name: str) -> CheckReport:
    results: list[CheckResult] = []
    for rule_id, category, name, severity, fn in _REGISTRY:
        results.append(_make_result(rule_id, category, name, severity, fn(doc)))
    return _build_report(file_name, results)


async def run_async(
    doc: ParsedDocument,
    file_name: str,
    on_progress: ProgressCallback | None = None,
) -> CheckReport:
    results: list[CheckResult] = []
    total_steps = len(_REGISTRY) + len(_ASYNC_REGISTRY)

    async def _emit(event: dict) -> None:
        if on_progress is not None:
            await on_progress(event)

    for i, (rule_id, category, name, severity, fn) in enumerate(_REGISTRY):
        await _emit({
            "phase": "rule",
            "rule_id": rule_id,
            "name": name,
            "step": i + 1,
            "total_steps": total_steps,
            "message": f"Checking {name}...",
        })
        results.append(_make_result(rule_id, category, name, severity, fn(doc)))

    if _ASYNC_REGISTRY:
        link_step = len(_REGISTRY) + 1
        await _emit({
            "phase": "links_start",
            "step": link_step,
            "total_steps": total_steps,
            "message": "Checking reference links...",
        })

        async def _link_cb(done: int, total: int) -> None:
            await _emit({
                "phase": "links",
                "done": done,
                "total": total,
                "step": link_step,
                "total_steps": total_steps,
                "message": f"Checking links ({done}/{total})...",
            })

        token = _link_progress_var.set(_link_cb)
        try:
            details_list = await asyncio.gather(
                *[fn(doc) for _, _, _, _, fn in _ASYNC_REGISTRY]
            )
        finally:
            _link_progress_var.reset(token)

        for (rule_id, category, name, severity, _), details in zip(
            _ASYNC_REGISTRY, details_list
        ):
            results.append(_make_result(rule_id, category, name, severity, details))

    return _build_report(file_name, results)
