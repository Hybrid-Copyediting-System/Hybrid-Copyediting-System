from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Literal

from ets_checker.models import (
    CheckDetail,
    CheckReport,
    CheckResult,
    ParsedDocument,
    ReportSummary,
)

RuleFunc = Callable[[ParsedDocument], list[CheckDetail]]

_REGISTRY: list[tuple[str, str, str, str, RuleFunc]] = []


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


def run(doc: ParsedDocument, file_name: str) -> CheckReport:
    results: list[CheckResult] = []

    for rule_id, category, name, severity, fn in _REGISTRY:
        details = fn(doc)
        status: Literal["pass", "fail"] = "pass" if not details else "fail"
        results.append(CheckResult(
            rule_id=rule_id,
            category=category,
            name=name,
            status=status,
            severity=severity,  # type: ignore[arg-type]
            details=details,
        ))

    passed = sum(1 for r in results if r.status == "pass")
    errors = sum(1 for r in results if r.status == "fail" and r.severity == "error")
    warnings = sum(1 for r in results if r.status == "fail" and r.severity == "warning")
    info_count = sum(1 for r in results if r.severity == "info")

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
