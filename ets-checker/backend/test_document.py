"""
Quick CLI test: parse a .docx and run all ETS rules.
Usage:  python test_document.py <path-to-docx>
"""
from __future__ import annotations

import asyncio
import sys
import os
import io

# Force UTF-8 output on Windows so Unicode characters don't crash
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Make sure the ets_checker package is importable
sys.path.insert(0, os.path.dirname(__file__))

from ets_checker.parser.docx_parser import parse
from ets_checker.rules import runner  # ensures @register decorators fire

# Import all rule modules so decorators run
import ets_checker.rules.layout
import ets_checker.rules.fonts
import ets_checker.rules.structure
import ets_checker.rules.citation
import ets_checker.rules.reference
import ets_checker.rules.figures_tables
import ets_checker.rules.reference_links


async def main(path: str) -> None:
    print(f"\n{'='*70}")
    print(f"  ETS Checker – test run")
    print(f"  File: {os.path.basename(path)}")
    print(f"{'='*70}\n")

    print("[1/2] Parsing document...")
    doc = parse(path)
    print(f"  paragraphs : {len(doc.paragraphs)}")
    print(f"  sections   : {len(doc.sections)}")
    print(f"  citations  : {len(doc.citations)}")
    print(f"  references : {len(doc.references)}")
    print(f"  figures    : {len(doc.figures)}")
    print(f"  tables     : {len(doc.tables)}")
    print()

    print("[2/2] Running checks...")
    steps: list[str] = []

    async def on_progress(event: dict) -> None:
        phase = event.get("phase", "")
        if phase == "rule":
            steps.append(event.get("name", ""))
        elif phase == "links":
            done = event.get("done", 0)
            total = event.get("total", 0)
            # Print link progress every 5 links to avoid flooding
            if done % 5 == 0 or done == total:
                print(f"    links: {done}/{total}", end="\r", flush=True)

    report = await runner.run_async(doc, os.path.basename(path), on_progress=on_progress)
    print()  # newline after link progress

    # Summary
    s = report.summary
    print(f"\n{'─'*70}")
    print(f"  Summary:  total={s.total_checks}  passed={s.passed}  errors={s.errors}  warnings={s.warnings}  info={s.info}")
    print(f"{'─'*70}\n")

    # Results
    for result in report.results:
        icon = "✓" if result.status == "pass" else ("✗" if result.severity == "error" else "⚠" if result.severity == "warning" else "ℹ")
        status_str = f"[{result.severity.upper()}]" if result.status == "fail" else "[PASS]"
        print(f"  {icon} {result.rule_id:<30}  {status_str:<12}  {result.name}")
        if result.details:
            for d in result.details[:5]:
                loc = d.location or ""
                msg = d.message or ""
                exc = f' → "{d.excerpt[:60]}"' if d.excerpt else ""
                exp = f"  expected: {d.expected}" if d.expected else ""
                act = f"  actual: {d.actual}" if d.actual else ""
                print(f"       @ {loc}: {msg}{exc}")
                if exp or act:
                    print(f"         {exp}{act}")
            if len(result.details) > 5:
                print(f"       ... and {len(result.details)-5} more details")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_document.py <path-to-docx>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
