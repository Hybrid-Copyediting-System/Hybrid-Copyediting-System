"""Run the full pipeline on a single .docx and dump a structured report."""
from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ets_checker.parser.docx_parser import parse
from ets_checker.rules.runner import run_async


async def main(path: str) -> None:
    parsed = parse(path)

    print("=" * 80)
    print(f"FILE: {path}")
    print("=" * 80)
    print(f"paragraphs   : {len(parsed.paragraphs)}")
    print(f"tables       : {len(parsed.tables)}")
    print(f"references   : {len(parsed.references)}")
    print(f"citations    : {len(parsed.citations)}")
    print(f"figures      : {len(parsed.figures)}")
    print(f"sections     : {len(parsed.sections)}")
    print(f"footnotes    : {len(parsed.footnotes)}")
    if parsed.footnotes:
        kinds = Counter(f.kind for f in parsed.footnotes)
        print(f"  by kind    : {dict(kinds)}")
        for f in parsed.footnotes[:8]:
            preview = f.text[:80].replace("\n", " ")
            print(f"  - id={f.footnote_id} kind={f.kind} p={f.paragraph_index} text={preview!r}")

    report = await run_async(parsed, Path(path).name)

    print("-" * 80)
    print(f"SUMMARY: total={report.summary.total_checks} passed={report.summary.passed} "
          f"errors={report.summary.errors} warnings={report.summary.warnings} info={report.summary.info}")
    print("-" * 80)

    failed = [r for r in report.results if r.status == "fail"]
    print(f"FAILED rules ({len(failed)}):")
    for r in failed:
        print(f"  [{r.severity:7s}] {r.rule_id:40s}  {r.name}  ({len(r.details)} details)")

    print("-" * 80)
    print("DETAILS (up to 6 per rule):")
    for r in failed:
        print(f"\n### [{r.rule_id}] {r.name}  sev={r.severity}  ({len(r.details)} details)")
        for d in r.details[:6]:
            loc = d.location
            msg = (d.message or "").replace("\n", " ")[:240]
            print(f"  - {loc}: {msg}")
            if d.expected is not None or d.actual is not None:
                print(f"      expected={d.expected!r}  actual={d.actual!r}")
            if d.excerpt:
                ex = d.excerpt.replace("\n", " ")[:240]
                print(f"      excerpt: {ex!r}")
        if len(r.details) > 6:
            print(f"  ... ({len(r.details) - 6} more)")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
