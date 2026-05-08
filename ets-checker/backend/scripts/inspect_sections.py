"""Inspect detected sections."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ets_checker.parser.docx_parser import parse


def main(path: str) -> None:
    parsed = parse(path)
    print(f"sections ({len(parsed.sections)}):")
    for s in parsed.sections:
        print(f"  p{s.paragraph_index:4d}  L{s.level} [{s.detection_method}]  {s.title!r}")

    # Look around p409 for declaration / acknowledgment headings
    print("\nParagraphs 405-420:")
    for p in parsed.paragraphs:
        if 400 <= p.index <= 420:
            r0 = p.runs[0] if p.runs else None
            font_info = (
                f"font={r0.font_name} size={r0.font_size_pt} bold={r0.bold}" if r0 else ""
            )
            print(f"  p{p.index:4d} style={p.style_name!r}  {font_info}  text={p.text[:90]!r}")


if __name__ == "__main__":
    main(sys.argv[1])
