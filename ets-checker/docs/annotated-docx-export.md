# Annotated `.docx` Export — Build Specification

## 1. Goal

Add a feature that, given an uploaded `.docx`, produces an **annotated copy of the same `.docx`** in which every rule finding is attached to the relevant location as a native Word **comment** (the kind that appears in Word's review pane). The original file is never modified; the annotated file is a new artifact returned to the user.

Out of scope for v1: tracked changes, automatic fixes, highlighting/coloring runs, PDF export.

## 2. Current State Assessment

> **Review note (post-walkthrough):** the original draft of this spec under-specified five things that surfaced when the actual code was inspected. They are now folded into the relevant sections below and explicitly called out in §8. Read §8 before starting work.

> **Implementation status:** the annotated-export feature described in this spec is **fully implemented**. §2–§4 reflect the state at spec-time; §8 lists corrections applied during implementation (all resolved).

### 2.1 What exists today *(pre-implementation snapshot)*
- `POST /api/check` (`backend/ets_checker/server.py`) accepts a `.docx`, parses it, runs all registered rules, and returns a JSON `CheckReport`. The original docx is written to a tempfile and deleted after the response — it is never returned to the client.
- The rule engine (`rules/runner.py`) iterates a registry of rules, each producing a list of `CheckDetail`.
- ~~The frontend renders the JSON report; there is no "download annotated copy" affordance.~~ **Implemented:** `POST /api/check/annotated` now exists; the frontend exposes a "Download annotated .docx" button that posts the same file and triggers a browser download.

### 2.2 Gap analysis — locator information
Word comments must anchor to a specific range of text inside a paragraph. The current data model does not carry enough locator information to do this reliably:

| Object | Has paragraph index? | Has run/offset? | Notes |
|---|---|---|---|
| `Paragraph` (`models.py:19`) | yes (`index`) | n/a | OK |
| `Citation` (`models.py:39`) | yes (`paragraph_index`) | **no** | We know which paragraph, not the character span |
| `Reference` (`models.py:49`) | **yes** (`paragraph_index`) | no | Fixed: `paragraph_index` is now captured in `parser/references.py` |
| `Figure` / `Table` (`models.py:60`) | yes (`paragraph_index`) | n/a | Anchor at caption paragraph |
| `CheckDetail.location` (`models.py`) | free-form string (kept) | n/a | `"document"`, `"paragraph 42"`, `"Reference #3"`, `"Figure 2"` — kept for human readability; `locator: Locator \| None` now carries the machine-addressable anchor |

Findings fall into three classes for anchoring purposes:

1. **Document-level** (no paragraph anchor) — `layout.margins`, `layout.line_spacing`, `font.body` (when reported as a global default), summary lines such as `"... and N more orphan citations"`. These cannot be attached to a range; they go on a synthetic anchor at the top of the document.
2. **Paragraph-level** — `structure.abstract_length`, `structure.keywords_count`, `figures_tables.referenced_in_text`, citation findings. Anchor: the whole paragraph.
3. **Span-level** (nice-to-have) — a specific citation token like `(Smith, 2020)` inside a paragraph. Requires the parser to record the character offset of each citation. **Not required for v1**; v1 anchors at paragraph granularity.

### 2.3 Library choice
`python-docx` is already a dependency (used by the parser). It does **not** expose a public API for inserting Word comments. The accepted approach is to:
- write the comment metadata into a new `word/comments.xml` part,
- register that part in `[Content_Types].xml` and the document `.rels`,
- inject `<w:commentRangeStart>`, `<w:commentRangeEnd>`, and `<w:commentReference>` elements directly via `lxml` on the existing `python-docx` document object.

No new third-party dependency is required beyond `lxml` (already a transitive dep of `python-docx`).

### 2.4 Effort estimate
| Item | Estimate |
|---|---|
| Locator model + parser changes (paragraph_index on `Reference`, structured locator on `CheckDetail`) | 0.5 day |
| Comment-injection helper (lxml + parts wiring) | 1 day |
| Mapping layer: `CheckResult` → comment anchors | 0.5 day |
| New endpoint + temp-file lifecycle | 0.25 day |
| Frontend "Download annotated copy" button | 0.25 day |
| Tests (unit + golden-file) | 0.5 day |
| **Total** | **~3 dev-days** |

## 3. Design

### 3.1 Data model changes

Add a structured locator to `CheckDetail` (keep `location: str` for backward compatibility, fill it from the structured field):

```python
# models.py
class Locator(BaseModel):
    kind: Literal["document", "paragraph", "reference", "figure", "table"]
    paragraph_index: int | None = None  # for paragraph/reference/figure/table
    char_start: int | None = None       # optional, for v2 span anchors
    char_end: int | None = None

class CheckDetail(BaseModel):
    location: str                       # existing, human-readable
    locator: Locator | None = None      # new, machine-addressable
    message: str
    expected: Any | None = None
    actual: Any | None = None
    excerpt: str | None = None
```

`Reference` gains `paragraph_index: int` so reference-list findings can be anchored. Update `parser/references.py` to record `p.index` when iterating `ref_paragraphs`.

### 3.2 Rule-side changes

Every existing rule populates `Locator` alongside the human-readable `location` string. Examples:

- `layout.margins` → `Locator(kind="document")`
- `figures_tables.referenced_in_text` for a defined-but-not-cited figure → `Locator(kind="figure", paragraph_index=fig.paragraph_index)`
- `citation.cross_reference` orphan citation → `Locator(kind="paragraph", paragraph_index=c.paragraph_index)`
- `reference.no_et_al` → `Locator(kind="reference", paragraph_index=ref.paragraph_index)`

Rules that aggregate ("... and N more ...") use `kind="document"`.

### 3.3 Comment injection module

New module `backend/ets_checker/exporter/annotate.py`:

```python
def annotate(
    src_path: str,
    report: CheckReport,
    author: str = "ET&S Checker",
) -> bytes:
    """Open src_path, inject one Word comment per CheckDetail, return the
    bytes of the resulting .docx. The source file is not modified."""
```

Internals:
1. Open the source with `docx.Document(src_path)`.
2. Ensure a `word/comments.xml` part exists; create one if absent. Helper: `_ensure_comments_part(doc)`.
3. For each `CheckResult` whose `status == "fail"`:
   - For each `CheckDetail`:
     - Resolve `locator` to a target `<w:p>` element using the helper from §8.1 (`build_paragraph_element_index(document)[locator.paragraph_index]`). **Do not** use `document.paragraphs[i]` directly — it skips table-cell paragraphs and will index-shift any in-table anchor.
       - `document` → first body paragraph (synthetic top-of-doc anchor).
     - Allocate a fresh comment id (monotonic across the run).
     - Append a `<w:comment>` child to `comments.xml` with `w:id`, `w:author`, `w:date`, and a single `<w:p><w:r><w:t>` carrying the formatted message:
       `[{severity}] {rule_id} — {message}` plus optional `expected`/`actual` lines.
     - In the target paragraph, wrap its existing runs with `<w:commentRangeStart w:id="N"/>` before the first run and `<w:commentRangeEnd w:id="N"/>` after the last run, then append `<w:r><w:commentReference w:id="N"/></w:r>`.
4. Save to an in-memory `BytesIO` and return the bytes.

Document-level findings all attach to the same first-paragraph anchor — Word will show them stacked in the review pane, which is acceptable for v1.

### 3.4 New endpoint

```
POST /api/check/annotated
  multipart: file=<docx>
  → 200 application/vnd.openxmlformats-officedocument.wordprocessingml.document
       Content-Disposition: attachment; filename="<original>.annotated.docx"
```

Implementation notes:
- Reuse the existing parse/run pipeline; only the response shape differs.
- Stream the bytes via `fastapi.responses.Response(content=bytes, media_type=...)`.
- Re-validate file size and extension exactly as `/api/check` does; share the validation helper.
- Keep `/api/check` unchanged for clients that only want JSON.
- **Do not** return the `CheckReport` via a response header — see §8.3. Clients that need both the report and the annotated file call `/api/check` and `/api/check/annotated` in sequence with the same `File`.

### 3.5 Frontend

In `frontend/src/components/` (wherever the upload result is rendered), add a secondary action:

- A **"Download annotated .docx"** button next to the existing report view.
- The component must already cache the uploaded `File` in state from the `/api/check` call. Clicking the new button POSTs that same `File` to `/api/check/annotated`.
- On 200: trigger a download of the response body using `URL.createObjectURL` + a hidden `<a download>` carrying `<original>.annotated.docx`.
- On 4xx/5xx: surface the error message exactly like the existing flow.
- The button is only enabled after `/api/check` has returned successfully (same `File` is known to be parseable).

## 4. Implementation Plan (ordered tasks)

1. **Model + parser** — add `Locator`, add `paragraph_index` to `Reference`, update `parser/references.py`.
2. **Rules** — populate `locator` in every `CheckDetail` across the six rule modules. Keep `location` strings unchanged.
3. **Exporter module** — `exporter/__init__.py`, `exporter/annotate.py`, `exporter/_comments_xml.py` (helpers for the `w:comments` part). No FastAPI imports here — pure function over `(path, report) → bytes`.
4. **Endpoint** — `POST /api/check/annotated` in `server.py`, sharing validation with `/api/check`.
5. **Frontend** — add download button + handler; reuse types in `types.ts` (extend `CheckDetail` to include optional `locator`).
6. **Tests**:
   - `tests/test_annotate.py`: feed a known docx + synthetic `CheckReport`, assert that the resulting bytes open as a valid docx, contain a `comments.xml` part, and contain the expected number of `w:commentReference` elements.
   - `tests/test_api.py`: hit `/api/check/annotated`, assert content-type, content-disposition, and that `X-ETS-Report` decodes to a valid `CheckReport`.
   - One golden-file fixture: `fixtures/sample.docx` → `fixtures/sample.annotated.expected.docx` (compare structurally, not byte-for-byte; docx zips are not deterministic).
7. **Docs** — update `README.md` with the new endpoint and a screenshot of the annotated output.

## 5. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Source docx already contains comments → id collisions | Read max existing `w:id` from `comments.xml` and start allocation above it |
| Paragraph found inside a table / nested structure | `python-docx` exposes table-cell paragraphs; resolve via `doc.paragraphs[i]` only for body paragraphs. For table-cell anchors, fall back to document-level anchor in v1 |
| Locator points to a non-existent paragraph (parser drift) | Validate `0 <= paragraph_index < len(doc.paragraphs)`; on miss, attach to the document-level anchor and prefix the message with the original `location` string |
| Word rejects the modified file | Validate output by reopening with `docx.Document(BytesIO(out))` inside the exporter as a self-check before returning |
| Large reports → very long review pane | Cap comments per rule (existing `MAX_REPORTED = 20` in `rules/citation.py` already handles this); document the cap |
| Tracked-changes mode in source | Comments coexist with tracked changes; no special handling needed |

## 6. Acceptance Criteria

- [ ] Uploading a sample docx with at least one violation per rule and calling `/api/check/annotated` returns a `.docx` that opens cleanly in Microsoft Word and Google Docs. *(requires manual verification)*
- [x] Each failed `CheckDetail` produces exactly one Word comment whose text starts with `[error]` or `[warning]` and contains the rule id. (`exporter/annotate.py:_format_comment_text`)
- [x] Document-level findings appear as comments anchored to the first body paragraph. (`exporter/anchor.py:resolve_anchor` — `kind="document"` falls back to first element)
- [x] Paragraph/reference/figure/table findings are anchored to their target paragraph. (`Locator(kind="paragraph", paragraph_index=…)` populated in all rule modules)
- [x] The original uploaded file on disk is unchanged (temp file written by `_validate_and_save`, never modified, deleted in `finally` block of `/api/check/annotated`).
- [ ] `pytest tests/ -v` passes, including the new `test_annotate.py`. *(run to confirm)*
- [x] Frontend exposes a "Download annotated .docx" button that triggers a browser download with the correct filename. (`frontend/src/App.vue:downloadAnnotatedDocx`)

## 8. Issues Found in Detailed Code Review *(all resolved)*

These were the concrete defects in the original spec, with corrected guidance. All items below have been addressed in the implementation.

### 8.1 `paragraph_index` does **not** equal `python-docx` paragraph index for in-table paragraphs ✓ resolved

`parser/paragraphs.py:63` (`iter_all`) builds a single combined list: first every body paragraph from `document.paragraphs`, then every paragraph found by walking `document.tables[*].rows[*].cells[*].paragraphs`. The parser then assigns `index` by enumeration order across that combined list.

Consequence:
- For a paragraph with `is_in_table == False`, `parsed.paragraphs[i].index` **does** equal the index into `python-docx`'s `document.paragraphs`. Anchoring via `document.paragraphs[locator.paragraph_index]._p` works.
- For a paragraph with `is_in_table == True`, that mapping is **wrong**. `document.paragraphs` does not include cell paragraphs at all; the parser-side index is offset past the body count.

**Required fix:** the exporter must not use `document.paragraphs[i]` as a generic lookup. Instead, build the same combined list the parser builds (body paragraphs first, then `tables[*].rows[*].cells[*].paragraphs` in walk order) and index into **that** list to get the underlying lxml `<w:p>` element. Add a single helper:

```python
# exporter/anchor.py
def build_paragraph_element_index(document: DocxDocument) -> list[CT_P]:
    out = [p._p for p in document.paragraphs]
    for t in document.tables:
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    out.append(p._p)
    return out
```

This mirrors `parser/paragraphs.iter_all` exactly. Any future change to that walk order **must** be mirrored here — add a comment in both files cross-referencing the other, and a test that asserts equal length and order between parser output and this index.

### 8.2 `Reference.paragraph_index` does not exist yet ✓ resolved

`parser/references.py:68` constructs `Reference` objects with only `index` (a 0-based position within the reference list). The originating paragraph index is discarded.

**Required fix:** add `paragraph_index: int` to the `Reference` model and capture `p.index` in the loop at `references.py:44`. The `Locator.kind="reference"` case then resolves identically to `kind="paragraph"` — in fact, drop `"reference"` from the `kind` enum and use `"paragraph"` once the index is available. Same for `"figure"` and `"table"`: they all collapse to `"paragraph"` plus the integer.

Revised `Locator`:

```python
class Locator(BaseModel):
    kind: Literal["document", "paragraph"]
    paragraph_index: int | None = None
    char_start: int | None = None  # reserved for v2
    char_end: int | None = None
```

### 8.3 `X-ETS-Report` header is the wrong place for the JSON report ✓ resolved

HTTP headers are practically capped around 8 KB by most servers and proxies. A `CheckReport` for a real manuscript can easily exceed this — `citation.cross_reference` alone can emit up to 40 details (20 orphan citations + 20 uncited references), plus the `font.body` rule that emits up to 20 more, plus structural details. Base64-encoded, this blows past the limit fast. Even when it fits, browsers will not let JS read a custom response header without `Access-Control-Expose-Headers: X-ETS-Report` on the CORS layer.

**Required fix:** make the client issue **two requests**: the existing `POST /api/check` for the JSON report, and a new `POST /api/check/annotated` that returns only the binary docx. The frontend already has the `File` in component state from the upload step, so the second call adds one round-trip and zero UX friction. Drop the `X-ETS-Report` header entirely.

If a single-call API is ever wanted, use `multipart/mixed` with a JSON part and a binary part — not headers.

### 8.4 Severity lives on `CheckResult`, not `CheckDetail` ✓ resolved

The original spec wrote `[{severity}] {rule_id} — {message}` "for each `CheckDetail`", which implied severity was on the detail. It is not — `CheckResult.severity` is the source of truth (`models.py:107`). The exporter must thread `(result, detail)` pairs, not just details, into the comment text. Trivial but worth pinning.

### 8.5 Comment-reference XML must be well-formed ✓ resolved

Word's `w:commentReference` must sit inside a `w:r` that has an `rPr` with an `rStyle w:val="CommentReference"` (otherwise some Word versions render fine but Word for Mac / older builds drop the marker). Add the `CommentReference` style to `word/styles.xml` if absent, or inline `rPr` on each reference run. The exporter's golden test (§4 step 6) must open the result in `python-docx` **and** assert that `w:commentRangeStart`, `w:commentRangeEnd`, and `w:commentReference` all carry matching `w:id` values for each comment.

### 8.6 Other smaller issues confirmed during review ✓ resolved

- **Aggregate "... and N more ..." details** carry no useful anchor — emit them as `kind="document"`. The MAX_REPORTED cap (currently 20 in `rules/citation.py` and `rules/fonts.py`) is sufficient to keep the comment count bounded; document the cap in the README so reviewers know not all violations are necessarily annotated.
- **`structure.abstract_length`** currently uses `location="Abstract"` — the rule has the abstract section's `paragraph_index` available (`rules/structure.py:21`); update it to record that index in the locator.
- **`figures_tables` rule** emits findings keyed by figure/table number, not paragraph. The exporter must look up the `Figure`/`Table` whose number matches and use its `paragraph_index`. For "referenced in text but not found in document" findings, no anchor exists — fall back to `kind="document"`.
- **CORS** — even after removing the response header, adding the new endpoint does not require any CORS change beyond what `/api/check` already has, since the request is the same `multipart/form-data` POST.

## 9. Future Work (explicitly deferred)

- Span-level anchoring (highlight just the offending citation token). Requires citation parser to record `(char_start, char_end)` per citation.
- Inline highlight/color marks in addition to comments.
- Auto-fix mode that applies safe corrections (e.g., normalize line spacing) and emits tracked changes.
- PDF export of the annotated document.
