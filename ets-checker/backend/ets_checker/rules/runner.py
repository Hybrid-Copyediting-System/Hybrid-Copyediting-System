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

RuleFunc = Callable[[ParsedDocument], list[CheckDetail]]
AsyncRuleFunc = Callable[[ParsedDocument], Awaitable[list[CheckDetail]]]

_REGISTRY: list[tuple[str, str, str, str, RuleFunc]] = []
_ASYNC_REGISTRY: list[tuple[str, str, str, str, AsyncRuleFunc]] = []


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


async def run_async(doc: ParsedDocument, file_name: str) -> CheckReport:
    results: list[CheckResult] = []

    for rule_id, category, name, severity, fn in _REGISTRY:
        results.append(_make_result(rule_id, category, name, severity, fn(doc)))

    if _ASYNC_REGISTRY:
        details_list = await asyncio.gather(
            *[fn(doc) for _, _, _, _, fn in _ASYNC_REGISTRY]
        )
        for (rule_id, category, name, severity, _), details in zip(
            _ASYNC_REGISTRY, details_list
        ):
            results.append(_make_result(rule_id, category, name, severity, details))

    return _build_report(file_name, results)
