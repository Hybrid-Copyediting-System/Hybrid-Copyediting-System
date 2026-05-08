"""Run pipeline + dump JSON + a long human report to UTF-8 files (for cross-checking)."""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ets_checker.parser.docx_parser import parse
from ets_checker.rules.runner import run_async


async def main(docx_path: str, out_stem: str) -> None:
    parsed = parse(docx_path)
    report = await run_async(parsed, Path(docx_path).name)

    # JSON dump (mode='json' so Pydantic emits jsonable types)
    out_json = Path(out_stem + ".json")
    out_json.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Parsed-doc snapshot (counts + first refs/citations + footnotes preview)
    parsed_snapshot = {
        "paragraphs": len(parsed.paragraphs),
        "tables": len(parsed.tables),
        "references": len(parsed.references),
        "citations": len(parsed.citations),
        "figures": len(parsed.figures),
        "sections": [{"title": s.title, "level": s.level, "p": s.paragraph_index} for s in parsed.sections],
        "footnotes_count": len(parsed.footnotes),
        "footnote_kinds": dict(Counter(f.kind for f in parsed.footnotes)),
    }
    Path(out_stem + ".parsed.json").write_text(
        json.dumps(parsed_snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Human txt report
    lines = []
    lines.append("=" * 100)
    lines.append(f"FILE: {docx_path}")
    lines.append("=" * 100)
    lines.append(f"paragraphs={len(parsed.paragraphs)} tables={len(parsed.tables)} "
                 f"references={len(parsed.references)} citations={len(parsed.citations)} "
                 f"figures={len(parsed.figures)} sections={len(parsed.sections)} "
                 f"footnotes={len(parsed.footnotes)}")
    s = report.summary
    lines.append(f"SUMMARY: total={s.total_checks} passed={s.passed} "
                 f"errors={s.errors} warnings={s.warnings} info={s.info}")
    lines.append("-" * 100)
    failed = [r for r in report.results if r.status == "fail"]
    lines.append(f"FAILED rules ({len(failed)}):")
    for r in failed:
        lines.append(f"  [{r.severity:7s}] {r.rule_id:42s} ({len(r.details)} details)  {r.name}")
    lines.append("-" * 100)
    for r in failed:
        lines.append("")
        lines.append(f"### [{r.rule_id}] {r.name}  sev={r.severity}  ({len(r.details)} details)")
        # Print ALL details so we can verify, not just first 6
        for d in r.details:
            loc = d.location
            msg = (d.message or "").replace("\n", " ")
            lines.append(f"  - {loc}: {msg}")
            if d.expected is not None or d.actual is not None:
                lines.append(f"      expected={d.expected!r}  actual={d.actual!r}")
            if d.excerpt:
                ex = d.excerpt.replace("\n", " ")
                lines.append(f"      excerpt: {ex!r}")

    Path(out_stem + ".txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"WROTE: {out_stem}.txt / .json / .parsed.json", flush=True)


if __name__ == "__main__":
    docx_path = sys.argv[1]
    out_stem = sys.argv[2]
    asyncio.run(main(docx_path, out_stem))
