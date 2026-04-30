"""Edge case tests for all 5 new rules."""
from ets_checker.models import (
    CheckDetail, DocumentMetadata, Locator, Paragraph, ParsedDocument, Run, Section,
)
from ets_checker.rules.structure import check_required_sections
from ets_checker.rules.fonts import (
    check_abstract_font, check_heading_font, check_reference_font, check_title_font,
)


def make_doc(**kw):
    defaults = dict(
        metadata=DocumentMetadata(
            paper_size="A4", paper_width_cm=21, paper_height_cm=29.7,
            margin_top_cm=2.5, margin_bottom_cm=2.5, margin_left_cm=2.5, margin_right_cm=2.5,
            default_line_spacing=1.0),
        paragraphs=[], sections=[], citations=[], references=[], figures=[], tables=[])
    defaults.update(kw)
    return ParsedDocument(**defaults)


def R(text, font="Times New Roman", size=10.0, bold=False, italic=False):
    return Run(text=text, font_name=font, font_size_pt=size, bold=bold, italic=italic)


def P(idx, text, runs=None, style=None, in_table=False):
    if runs is None:
        runs = [R(text)]
    return Paragraph(index=idx, text=text, style_name=style, runs=runs,
                     alignment=None, indent_left_cm=None, indent_first_line_cm=None,
                     line_spacing=None, is_in_table=in_table)


def S(title, level, pidx, method="style"):
    return Section(title=title, level=level, paragraph_index=pidx, detection_method=method)


errors = []


def test(name, condition, msg=""):
    if condition:
        print(f"  PASS: {name}")
    else:
        print(f"  FAIL: {name} -- {msg}")
        errors.append(name)


# === 1. structure.required_sections ===
print("=== 1. structure.required_sections ===")

# 1a: Empty doc
r = check_required_sections(make_doc())
test("empty doc -> 3 errors", len(r) == 3, f"got {len(r)}")

# 1b: All present
r = check_required_sections(make_doc(sections=[
    S("Abstract", 1, 0), S("Introduction", 1, 5), S("References", 1, 20)]))
test("all present -> 0 errors", len(r) == 0, f"got {len(r)}")

# 1c: Trailing punctuation
r = check_required_sections(make_doc(sections=[
    S("Abstract:", 1, 0), S("Introduction.", 1, 5), S("References：", 1, 20)]))
test("trailing punct -> 0 errors", len(r) == 0, f"got {len(r)}: {[d.message for d in r]}")

# 1d: Numbered headings
r = check_required_sections(make_doc(sections=[
    S("Abstract", 1, 0), S("1. Introduction", 1, 5), S("References", 1, 20)]))
test('"1. Introduction" matched', len(r) == 0, f"got {len(r)}: {[d.message for d in r]}")

r = check_required_sections(make_doc(sections=[
    S("Abstract", 1, 0), S("1.1 Background", 2, 5), S("References", 1, 20)]))
test('"1.1 Background" matched', len(r) == 0, f"got {len(r)}: {[d.message for d in r]}")

# 1e: Chinese equivalents
r = check_required_sections(make_doc(sections=[
    S("摘要", 1, 0), S("緒論", 1, 5), S("參考文獻", 1, 20)]))
test("Chinese titles -> 0 errors", len(r) == 0, f"got {len(r)}: {[d.message for d in r]}")

# 1f: ALL CAPS
r = check_required_sections(make_doc(sections=[
    S("ABSTRACT", 1, 0), S("INTRODUCTION", 1, 5), S("REFERENCES", 1, 20)]))
test("ALL CAPS -> 0 errors", len(r) == 0, f"got {len(r)}: {[d.message for d in r]}")

# 1g: Only Abstract missing
r = check_required_sections(make_doc(sections=[
    S("Introduction", 1, 5), S("References", 1, 20)]))
test("missing Abstract only", len(r) == 1 and "Abstract" in r[0].message, f"{[d.message for d in r]}")


# === 2. font.abstract ===
print("\n=== 2. font.abstract ===")

# 2a: Correct italic abstract
paras = [
    P(0, "Abstract", [R("Abstract", size=12.0, bold=True)], style="Heading 1"),
    P(1, "This is the abstract.", [R("This is the abstract.", italic=True)]),
    P(2, "Keywords: test, foo", [R("Keywords:", bold=True), R(" test, foo")]),
    P(3, "Introduction", [R("Introduction", size=12.0, bold=True)], style="Heading 1"),
]
secs = [S("Abstract", 1, 0), S("Introduction", 1, 3)]
r = check_abstract_font(make_doc(paragraphs=paras, sections=secs))
test("correct italic -> 0 errors", len(r) == 0, f"got {len(r)}")

# 2b: Non-italic abstract
paras2 = list(paras)
paras2[1] = P(1, "This is the abstract.", [R("This is the abstract.", italic=False)])
r = check_abstract_font(make_doc(paragraphs=paras2, sections=secs))
test("non-italic -> flagged", len(r) > 0, "no errors")
kw_err = [d for d in r if "Keywords" in (d.excerpt or "")]
test("keywords excluded", len(kw_err) == 0, f"{kw_err}")

# 2c: Inline abstract - label should be skipped
paras_inline = [
    P(0, "ABSTRACT: This is the abstract text.", [
        R("ABSTRACT: ", bold=True, italic=False),
        R("This is the abstract text.", italic=True),
    ]),
    P(1, "Introduction", [R("Introduction", size=12.0, bold=True)], style="Heading 1"),
]
secs_inline = [S("Abstract", 1, 0, "heuristic"), S("Introduction", 1, 1)]
r = check_abstract_font(make_doc(paragraphs=paras_inline, sections=secs_inline))
test("inline abstract: label not flagged", len(r) == 0,
     f"got {len(r)}: {[(d.excerpt, d.actual) for d in r]}")

# 2d: Inline abstract with wrong italic on body
paras_inline2 = [
    P(0, "ABSTRACT: This is the abstract text.", [
        R("ABSTRACT: ", bold=True, italic=False),
        R("This is the abstract text.", italic=False),
    ]),
    P(1, "Introduction", [R("Introduction", size=12.0, bold=True)], style="Heading 1"),
]
r = check_abstract_font(make_doc(paragraphs=paras_inline2, sections=secs_inline))
test("inline abstract: body not italic -> flagged", len(r) > 0, "no errors")

# 2e: No abstract section
r = check_abstract_font(make_doc(
    paragraphs=[P(0, "Hello")], sections=[S("Introduction", 1, 0)]))
test("no abstract -> 0 errors (graceful)", len(r) == 0, f"got {len(r)}")

# 2f: italic=None (unresolved) -> should NOT flag
paras_none = [
    P(0, "Abstract", [R("Abstract", size=12.0, bold=True)], style="Heading 1"),
    P(1, "Text here.", [Run(text="Text here.", font_name="Times New Roman",
                            font_size_pt=10.0, bold=False, italic=None)]),
    P(2, "Introduction", [R("Introduction", size=12.0, bold=True)], style="Heading 1"),
]
r = check_abstract_font(make_doc(
    paragraphs=paras_none, sections=[S("Abstract", 1, 0), S("Introduction", 1, 2)]))
test("italic=None -> not flagged", len(r) == 0,
     f"got {len(r)}: {[(d.excerpt, d.actual) for d in r]}")


# === 3. font.heading ===
print("\n=== 3. font.heading ===")

# 3a: Correct H1
r = check_heading_font(make_doc(
    paragraphs=[P(0, "Introduction", [R("Introduction", size=12.0, bold=True)], style="Heading 1")],
    sections=[S("Introduction", 1, 0)]))
test("correct H1 -> 0 errors", len(r) == 0, f"got {len(r)}")

# 3b: Wrong H1 size
r = check_heading_font(make_doc(
    paragraphs=[P(0, "Introduction", [R("Introduction", size=14.0, bold=True)], style="Heading 1")],
    sections=[S("Introduction", 1, 0)]))
test("H1 at 14pt -> flagged", len(r) > 0, "no errors")

# 3c: Title style skipped
paras = [
    P(0, "My Paper", [R("My Paper", size=14.0, bold=True)], style="Title"),
    P(1, "Abstract", [R("Abstract", size=12.0, bold=True)], style="Heading 1"),
]
r = check_heading_font(make_doc(paragraphs=paras,
    sections=[S("My Paper", 1, 0), S("Abstract", 1, 1)]))
title_errs = [d for d in r if "My Paper" in (d.excerpt or "")]
test("Title style skipped", len(title_errs) == 0, f"{title_errs}")

# 3d: Italic heading should be flagged
r = check_heading_font(make_doc(
    paragraphs=[P(0, "Introduction", [R("Introduction", size=12.0, bold=True, italic=True)],
                   style="Heading 1")],
    sections=[S("Introduction", 1, 0)]))
test("italic H1 -> flagged", len(r) > 0 and "italic" in (r[0].actual or ""),
     f"{[(d.actual) for d in r]}")

# 3e: H2 correct (10pt bold)
r = check_heading_font(make_doc(
    paragraphs=[P(0, "Sub", [R("Sub", size=10.0, bold=True)], style="Heading 2")],
    sections=[S("Sub", 2, 0)]))
test("correct H2 -> 0 errors", len(r) == 0, f"got {len(r)}")

# 3f: Level 3 skipped
r = check_heading_font(make_doc(
    paragraphs=[P(0, "L3", [R("L3", size=10.0, bold=True, italic=True)], style="Heading 3")],
    sections=[S("L3", 3, 0)]))
test("level 3 skipped", len(r) == 0, f"got {len(r)}")

# 3g: H1 not bold
r = check_heading_font(make_doc(
    paragraphs=[P(0, "Methods", [R("Methods", size=12.0, bold=False)], style="Heading 1")],
    sections=[S("Methods", 1, 0)]))
test("H1 not bold -> flagged", len(r) > 0, "no errors")


# === 4. font.reference ===
print("\n=== 4. font.reference ===")

# 4a: Correct 9pt references
paras = [
    P(10, "References", [R("References", size=12.0, bold=True)], style="Heading 1"),
    P(11, "Smith (2020). Journal.", [
        R("Smith (2020). ", size=9.0), R("Journal.", size=9.0, italic=True)]),
]
r = check_reference_font(make_doc(paragraphs=paras, sections=[S("References", 1, 10)]))
test("correct 9pt -> 0 errors", len(r) == 0, f"got {len(r)}")

# 4b: Wrong size (10pt)
paras = [
    P(10, "References", [R("References", size=12.0, bold=True)], style="Heading 1"),
    P(11, "Smith (2020).", [R("Smith (2020).", size=10.0)]),
]
r = check_reference_font(make_doc(paragraphs=paras, sections=[S("References", 1, 10)]))
test("10pt refs -> flagged", len(r) > 0, "no errors")

# 4c: Appendix NOT flagged
paras = [
    P(10, "References", [R("References", size=12.0, bold=True)], style="Heading 1"),
    P(11, "Smith.", [R("Smith.", size=9.0)]),
    P(20, "Appendix", [R("Appendix", size=12.0, bold=True)], style="Heading 1"),
    P(21, "Appendix content.", [R("Appendix content.", size=10.0)]),
]
r = check_reference_font(make_doc(paragraphs=paras,
    sections=[S("References", 1, 10), S("Appendix", 1, 20)]))
app_err = [d for d in r if "Appendix" in (d.excerpt or "")]
test("appendix not flagged", len(app_err) == 0, f"{app_err}")

# 4d: No references section
r = check_reference_font(make_doc(
    paragraphs=[P(0, "Hello")], sections=[S("Introduction", 1, 0)]))
test("no refs -> 0 errors", len(r) == 0, f"got {len(r)}")

# 4e: References as last section
paras = [
    P(10, "References", [R("References", size=12.0, bold=True)], style="Heading 1"),
    P(11, "Smith.", [R("Smith.", size=9.0)]),
    P(12, "Jones.", [R("Jones.", size=10.0)]),
]
r = check_reference_font(make_doc(paragraphs=paras, sections=[S("References", 1, 10)]))
test("refs last section, wrong font flagged", len(r) == 1, f"got {len(r)}")

# 4f: Italic journal name not flagged
paras = [
    P(10, "References", [R("References", size=12.0, bold=True)], style="Heading 1"),
    P(11, "Smith. Journal.", [R("Smith. ", size=9.0), R("Journal.", size=9.0, italic=True)]),
]
r = check_reference_font(make_doc(paragraphs=paras, sections=[S("References", 1, 10)]))
test("italic journal not flagged", len(r) == 0, f"got {len(r)}")


# === 5. font.title ===
print("\n=== 5. font.title ===")

# 5a: Title styled, correct font
paras = [
    P(0, "My Paper Title", [R("My Paper Title", size=14.0, bold=True)], style="Title"),
    P(1, "Abstract", [R("Abstract", size=12.0, bold=True)], style="Heading 1"),
]
r = check_title_font(make_doc(paragraphs=paras,
    sections=[S("My Paper Title", 1, 0), S("Abstract", 1, 1)]))
test("correct title -> 0 errors", len(r) == 0, f"got {len(r)}")

# 5b: Title styled, wrong font
paras = [
    P(0, "My Paper Title", [R("My Paper Title", font="Arial", size=14.0, bold=True)], style="Title"),
    P(1, "Abstract", [R("Abstract", size=12.0, bold=True)], style="Heading 1"),
]
r = check_title_font(make_doc(paragraphs=paras,
    sections=[S("My Paper Title", 1, 0), S("Abstract", 1, 1)]))
test("wrong title font -> flagged", len(r) > 0, "no errors")

# 5c: Title styled with None size (style-inherited) -> still checked
paras = [
    P(0, "My Paper", [Run(text="My Paper", font_name="Arial", font_size_pt=None,
                          bold=True, italic=False)], style="Title"),
    P(1, "Abstract", [R("Abstract", size=12.0, bold=True)], style="Heading 1"),
]
r = check_title_font(make_doc(paragraphs=paras,
    sections=[S("My Paper", 1, 0), S("Abstract", 1, 1)]))
test("Title style + None size -> still checked (font wrong)", len(r) > 0, f"got {len(r)}")

# 5d: Title with None size AND correct font -> should pass
paras = [
    P(0, "My Paper", [Run(text="My Paper", font_name="Times New Roman", font_size_pt=None,
                          bold=True, italic=False)], style="Title"),
    P(1, "Abstract", [R("Abstract", size=12.0, bold=True)], style="Heading 1"),
]
r = check_title_font(make_doc(paragraphs=paras,
    sections=[S("My Paper", 1, 0), S("Abstract", 1, 1)]))
test("Title style + None size + correct font -> pass", len(r) == 0, f"got {len(r)}")

# 5e: Front-matter without Title style, looks like title
paras = [
    P(0, "My Paper Title", [R("My Paper Title", size=14.0, bold=True)]),
    P(1, "Author Name", [R("Author Name", size=10.0)]),
    P(2, "Abstract", [R("Abstract", size=12.0, bold=True)], style="Heading 1"),
]
r = check_title_font(make_doc(paragraphs=paras, sections=[S("Abstract", 1, 2)]))
test("front-matter title heuristic works", len(r) == 0, f"got {len(r)}")

# 5f: Author name NOT checked
author_errs = [d for d in r if "Author" in (d.excerpt or "") or "University" in (d.excerpt or "")]
test("author/affiliation not checked", len(author_errs) == 0, f"{author_errs}")

# 5g: Misapplied Title style deep in body NOT checked
paras = [
    P(0, "My Paper", [R("My Paper", size=14.0, bold=True)], style="Title"),
    P(1, "Abstract", [R("Abstract", size=12.0, bold=True)], style="Heading 1"),
    P(2, "Body text.", [R("Body text.", size=10.0)]),
    P(5, "Oops Title", [R("Oops", font="Arial", size=10.0)], style="Title"),
    P(6, "More body.", [R("More body.", size=10.0)]),
]
r = check_title_font(make_doc(paragraphs=paras,
    sections=[S("My Paper", 1, 0), S("Abstract", 1, 1)]))
deep_err = [d for d in r if "Oops" in (d.excerpt or "")]
test("misapplied Title in body NOT checked", len(deep_err) == 0, f"{deep_err}")

# 5h: No sections at all -> no title check
r = check_title_font(make_doc(
    paragraphs=[P(0, "Something", [R("Something", size=14.0, bold=True)])]))
test("no sections -> 0 errors", len(r) == 0, f"got {len(r)}")

# 5i: Multiple front-matter paragraphs, only title-like ones checked
paras = [
    P(0, "My Paper", [R("My Paper", size=14.0, bold=True)]),
    P(1, "Subtitle", [R("Subtitle", size=14.0, bold=True)]),  # also title-like
    P(2, "John Doe", [R("John Doe", font="Arial", size=10.0)]),  # author, wrong font but not title-like
    P(3, "Abstract", [R("Abstract", size=12.0, bold=True)], style="Heading 1"),
]
r = check_title_font(make_doc(paragraphs=paras, sections=[S("Abstract", 1, 3)]))
john_err = [d for d in r if "John" in (d.excerpt or "")]
test("non-title-like front-matter skipped", len(john_err) == 0, f"{john_err}")


print()
if errors:
    print(f"FAILED {len(errors)} test(s): {errors}")
    exit(1)
else:
    print("ALL TESTS PASSED")
