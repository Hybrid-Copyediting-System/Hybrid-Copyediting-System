from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable, Literal

from ets_checker.models import (
    CheckDetail,
    CheckReport,
    CheckResult,
    ParsedDocument,
    ReportSummary,
)

Severity = Literal["error", "warning", "info"]
RuleFunc = Callable[[ParsedDocument], list[CheckDetail]]
LinkProgressCallback = Callable[[int, int], Awaitable[None]]
AsyncRuleFunc = Callable[
    [ParsedDocument, LinkProgressCallback | None],
    Awaitable[list[CheckDetail]],
]
ProgressCallback = Callable[[dict], Awaitable[None]]


class RuleRegistry:
    """Explicit registry for sync and async rules.

    Replaces a pair of module-level lists. Iteration order is the order
    in which rules were registered, but the registry exposes ``run`` /
    ``run_async`` so callers don't depend on import order beyond that.
    """

    def __init__(self) -> None:
        self._sync: list[tuple[str, str, str, Severity, RuleFunc]] = []
        self._async: list[tuple[str, str, str, Severity, AsyncRuleFunc]] = []

    def register(
        self,
        rule_id: str,
        category: str,
        name: str,
        severity: Severity,
        fn: RuleFunc,
    ) -> None:
        self._sync.append((rule_id, category, name, severity, fn))

    def register_async(
        self,
        rule_id: str,
        category: str,
        name: str,
        severity: Severity,
        fn: AsyncRuleFunc,
    ) -> None:
        self._async.append((rule_id, category, name, severity, fn))

    @property
    def sync_rules(self) -> list[tuple[str, str, str, Severity, RuleFunc]]:
        return list(self._sync)

    @property
    def async_rules(self) -> list[tuple[str, str, str, Severity, AsyncRuleFunc]]:
        return list(self._async)


# Default registry used by the @register / @register_async decorators below.
# Rules import the decorators; the registry stays a private detail.
_REGISTRY = RuleRegistry()


def register(
    rule_id: str,
    category: str,
    name: str,
    severity: Severity,
) -> Callable[[RuleFunc], RuleFunc]:
    def decorator(fn: RuleFunc) -> RuleFunc:
        _REGISTRY.register(rule_id, category, name, severity, fn)
        return fn
    return decorator


def register_async(
    rule_id: str,
    category: str,
    name: str,
    severity: Severity,
) -> Callable[[AsyncRuleFunc], AsyncRuleFunc]:
    def decorator(fn: AsyncRuleFunc) -> AsyncRuleFunc:
        _REGISTRY.register_async(rule_id, category, name, severity, fn)
        return fn
    return decorator


def _make_result(
    rule_id: str,
    category: str,
    name: str,
    severity: Severity,
    details: list[CheckDetail],
) -> CheckResult:
    status: Literal["pass", "fail"] = "pass" if not details else "fail"
    return CheckResult(
        rule_id=rule_id,
        category=category,
        name=name,
        status=status,
        severity=severity,
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
    for rule_id, category, name, severity, fn in _REGISTRY.sync_rules:
        results.append(_make_result(rule_id, category, name, severity, fn(doc)))
    return _build_report(file_name, results)


async def run_async(
    doc: ParsedDocument,
    file_name: str,
    on_progress: ProgressCallback | None = None,
) -> CheckReport:
    results: list[CheckResult] = []
    sync_rules = _REGISTRY.sync_rules
    async_rules = _REGISTRY.async_rules
    total_steps = len(sync_rules) + len(async_rules)

    async def _emit(event: dict) -> None:
        if on_progress is not None:
            await on_progress(event)

    for i, (rule_id, category, name, severity, fn) in enumerate(sync_rules):
        await _emit({
            "phase": "rule",
            "rule_id": rule_id,
            "name": name,
            "step": i + 1,
            "total_steps": total_steps,
            "message": f"Checking {name}...",
        })
        results.append(_make_result(rule_id, category, name, severity, fn(doc)))

    if async_rules:
        link_step = len(sync_rules) + 1
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

        details_list = await asyncio.gather(
            *[fn(doc, _link_cb) for _, _, _, _, fn in async_rules]
        )

        for (rule_id, category, name, severity, _), details in zip(
            async_rules, details_list
        ):
            results.append(_make_result(rule_id, category, name, severity, details))

    return _build_report(file_name, results)
