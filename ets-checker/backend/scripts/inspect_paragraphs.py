"""Inspect specific paragraphs and citations in detail."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ets_checker.parser.docx_parser import parse


def main(path: str) -> None:
    parsed = parse(path)
    targets = [377, 386, 409]
    for idx in targets:
        if 0 <= idx < len(parsed.paragraphs):
            p = parsed.paragraphs[idx]
            print(f"=== paragraph[{idx}] style={p.style_name!r}")
            print("FULL TEXT:")
            print(repr(p.text))
            print()

    print("\n=== ALL Crotty / Goffman / Fwu / Hood related references ===")
    for r in parsed.references:
        if r.first_author_surname and r.first_author_surname.lower() in {
            "crotty", "goffman", "fwu", "hood", "hochschild"
        }:
            print(f"  idx={r.index} surname={r.first_author_surname} year={r.year} count={r.author_count}")
            print(f"    raw: {r.raw_text!r}")

    print("\n=== References that lack DOI and URL (potential book/journal misclass) ===")
    for r in parsed.references:
        if not r.doi and not r.urls:
            print(f"  idx={r.index} surname={r.first_author_surname} year={r.year}")
            print(f"    raw: {r.raw_text!r}")
            print()


if __name__ == "__main__":
    main(sys.argv[1])
