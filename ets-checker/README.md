# ET&S Format Checker — MVP

Web-based tool that checks `.docx` manuscripts against the ET&S (Educational
Technology & Society) APA 7th formatting requirements and returns a structured
report. Optionally re-emits the same `.docx` with one native Word comment per
finding, attached to the relevant paragraph.

- **Backend:** FastAPI + `python-docx` + `lxml` (Python ≥ 3.11)
- **Frontend:** Vue 3 + Vuetify 3 + Vite (TypeScript)
- **Deployment:** single Docker container serves the SPA and the API on one port

## Quick Start (development)

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -e ".[dev]"
uvicorn ets_checker.server:app --reload --port 8080
```

### Frontend

```bash
cd frontend
npm install
npm run dev                        # → http://localhost:5173
```

Open <http://localhost:5173>. Vite proxies `/api/*` to `http://localhost:8080`.

## Rules (47)

The `ets_profile.py` module hard-codes ET&S APA 7th expectations
(A4, 2.5 cm margins, single line spacing, Times New Roman 10 pt body, etc.).
Each rule is registered via a decorator in `backend/ets_checker/rules/`.

| Rule ID                                   | Category         | Severity | Notes |
|-------------------------------------------|------------------|----------|-------|
| `layout.paper_size`                       | Layout           | error    | Paper size must be A4 (21 × 29.7 cm) |
| `layout.margins`                          | Layout           | error    | All four margins vs. ET&S profile (2.5 cm) |
| `layout.line_spacing`                     | Layout           | error    | Document default line spacing must be 1.0 |
| `layout.page_numbers`                     | Layout           | info     | Page numbers presence check |
| `layout.first_line_indent`                | Layout           | info     | Body first-line indent ≈ 1.27 cm (APA 7 §2.24) |
| `layout.body_alignment`                   | Layout           | info     | Body paragraphs must be left or justified |
| `font.body`                               | Fonts            | warning  | Body runs vs. Times New Roman 10 pt |
| `font.stat_italic`                        | Fonts            | warning  | Statistical symbols (p, F, t, etc.) must be italic |
| `font.abstract`                           | Fonts            | warning  | Abstract runs vs. Times New Roman 10 pt italic (ET&S) |
| `font.heading`                            | Fonts            | warning  | Heading fonts vs. ET&S profile |
| `font.reference`                          | Fonts            | warning  | Reference list runs vs. Times New Roman 9 pt |
| `font.title`                              | Fonts            | warning  | Title run vs. Times New Roman 14 pt bold |
| `structure.abstract_length`               | Structure        | warning  | ≤ 250 words (CJK + Latin word count) |
| `structure.keywords_count`                | Structure        | warning  | ≤ 5 keywords |
| `structure.required_sections`             | Structure        | error    | Abstract, Introduction, and References must all be present |
| `structure.placeholder`                   | Structure        | error    | No `[insert ...]`, `TODO`, `???`, etc. left in the manuscript (AQF Item 4) |
| `structure.abstract_single_paragraph`     | Structure        | warning  | Abstract must be a single paragraph (APA 7 §2.27) |
| `structure.abstract_no_indent`            | Structure        | warning  | Abstract first line must be flush left (APA 7 §2.27) |
| `structure.title_length`                  | Structure        | info     | Paper title ≤ 12 words (APA 7 §2.4) |
| `structure.no_introduction_heading`       | Structure        | info     | APA 7 §2.27: don't label first body section "Introduction" |
| `structure.section_order`                 | Structure        | warning  | Abstract → Body → References → Appendices order |
| `structure.no_footnotes`                  | Structure        | error    | ET&S forbids footnotes (AQF Item 4) |
| `headings.no_numbering`                   | Structure        | info     | Headings must not carry "1." / "Chapter N" prefixes |
| `headings.level_order`                    | Structure        | warning  | Heading levels must not skip (no H1 → H3) |
| `citation.cross_reference`                | Citation         | error    | Orphans, year mismatches, surname inconsistencies, uncited refs |
| `citation.et_al_usage`                    | Citation         | warning  | "et al." used only when ≥ 3 authors (APA 7th) |
| `citation.amp_vs_and`                     | Citation         | warning  | "&" inside parens, "and" in narrative (APA 7 §8.17) |
| `citation.disambiguate`                   | Citation         | error    | Same-surname-same-year reference entries need a/b suffixes (AQF Item 5) |
| `reference.no_et_al`                      | Reference        | error    | The reference list must spell out all authors |
| `reference.alphabetical_order`            | Reference        | warning  | Reference entries must be in alphabetical order |
| `reference.hanging_indent`                | Reference        | warning  | Each reference entry must use a hanging indent (1.27 cm) |
| `reference.page_number_complete`          | Reference        | warning  | Detect abbreviated page ranges like `129–65` (AQF Item 6) |
| `reference.doi_or_url`                    | Reference        | warning  | Journal articles need either Volume(Issue), pages or a DOI/URL (AQF Item 6) |
| `reference.apa_format`                    | Reference        | warning  | Structural sanity: period after year, non-empty title, terminal punct |
| `reference.italics_journal_volume`        | Reference        | warning  | Journal name + volume italic; issue number roman (APA 7 §10.1) |
| `reference.url_terminal_punctuation`      | Reference        | warning  | DOI / URL must not end with a period (APA 7 §9.36) |
| `reference.author_count_rule`             | Reference        | warning  | ≤20 authors list all; 21+ uses ellipsis + last (APA 7 §9.8) |
| `reference.links`                         | Reference        | warning  | Async DOI / URL liveness check (HEAD, then GET on 405) |
| `statistics.operator_spacing`             | Statistics       | warning  | Spaces around `=`, `<`, `>`, `≤`, `≥` (APA 7 §6.45) |
| `statistics.p_value_format`               | Statistics       | warning  | p without leading zero; "p < .001" not "p = .000" (APA 7 §6.44) |
| `quotation.pagination`                    | Quotation        | warning  | Direct quotes need a page locator on the citation (AQF Item 4) |
| `quotation.block_format`                  | Quotation        | warning  | ≥ 40-word quotes use block format; short quotes stay inline (APA 7 §8.27) |
| `figures_tables.referenced_in_text`       | Figures & Tables | warning  | Defined-but-uncited and cited-but-undefined figures and tables |
| `figures_tables.caption_position`         | Figures & Tables | info     | Captions must appear above figures and tables (ET&S) |
| `figures_tables.table_format`             | Figures & Tables | warning  | Tables must not use vertical borders |
| `figures_tables.numbering_sequence`       | Figures & Tables | warning  | Figure / table numbering must be 1, 2, 3, … (no gaps, no duplicates) |
| `figures_tables.caption_format`           | Figures & Tables | info     | Caption number bold; caption title italic (APA 7 §7.10/§7.24) |

`reference.links` is the only async rule; it runs concurrently (5-way semaphore,
10 s timeout) via `httpx`. Soft failures (403/429/5xx, decompression errors) are
ignored on purpose — only 404/410, timeouts, and connect errors are reported.

## API

| Method | Path                     | Body                  | Returns |
|--------|--------------------------|-----------------------|---------|
| GET    | `/api/health`            | —                     | `{"status": "ok"}` |
| POST   | `/api/check`             | multipart `file=.docx`| `CheckReport` JSON (see `backend/ets_checker/models.py`) |
| POST   | `/api/check/stream`      | multipart `file=.docx`| `text/event-stream` — SSE progress events (`progress`, `complete`, `error`) |
| POST   | `/api/check/annotated`   | multipart `file=.docx`; optional `report_json=<CheckReport JSON>`| Annotated `.docx` (`<original-stem>.annotated.docx`) |

Upload limit: 50 MB. `.doc` is rejected with a "Save As .docx" hint.

`/api/check/stream` sends named SSE events: `progress` events carry rule-by-rule
status during processing (including per-link progress for `reference.links`); the
final `complete` event carries the full `CheckReport` JSON; an `error` event is
sent on failure.

### Annotated `.docx` export

`/api/check/annotated` runs the same pipeline as `/api/check`, then injects one
native Word comment per failed `CheckDetail` and returns the new bytes. The
original file is never modified. Anchoring is paragraph-level: document-level
findings (margins, line spacing) attach to a synthetic anchor at the top.

If a previously-obtained `CheckReport` JSON is passed as the `report_json` form
field, the endpoint skips re-running the checks and injects comments directly from
that report (saves a second parsing + rule-running pass when the frontend already
has a report).

Implementation lives in `backend/ets_checker/exporter/` — see
`docs/annotated-docx-export.md` for the design rationale.

## Production build

### Option A — Docker (recommended)

The container runs the FastAPI app and serves the built SPA from the same port.

```bash
docker compose up --build              # → http://localhost:48000  (ETS_PORT set in .env)
ETS_PORT=51234 docker compose up       # override the port
```

The `.env` file in `ets-checker/` sets `ETS_PORT=48000`; the docker-compose default
without that file is 47823. Override on the command line as shown above.
A healthcheck against `/api/health` is wired into `docker-compose.yml`.

### Option B — local Python serving the built SPA

```bash
cd frontend
npm run build                          # writes ./dist
# Copy the bundle into the location server.py auto-mounts:
#   backend/ets_checker/frontend_dist/
# Windows (PowerShell):
#   Copy-Item -Recurse -Force dist\* ..\backend\ets_checker\frontend_dist\
# Bash:
#   cp -r dist/* ../backend/ets_checker/frontend_dist/

cd ../backend
uvicorn ets_checker.server:app --port 8080   # → http://localhost:8080
```

`server.py` mounts `frontend_dist/` only when it exists and is non-empty, so
you can switch back to dev mode just by clearing that folder.

## Tests & quality gates

```bash
cd backend
pytest tests/ -v          # unit + ASGI integration tests
ruff check .              # lint (line-length 100, target py311)
mypy .                    # strict mode (see [tool.mypy] in pyproject.toml)
```

Some tests need `tests/fixtures/ets_template.docx` and skip cleanly if it is
absent. The annotated-export round-trip test (`test_check_annotated_returns_docx`)
builds its docx fixture in-process and always runs.

## Repository layout

```
ets-checker/
├── backend/
│   └── ets_checker/
│       ├── server.py            # FastAPI app + routes + SPA mount
│       ├── ets_profile.py       # Hard-coded ET&S APA 7 expectations
│       ├── models.py            # Pydantic models (Parsed*, CheckReport, …)
│       ├── parser/              # docx → ParsedDocument
│       ├── rules/               # Registered rule functions + runner
│       └── exporter/            # Word-comment injection (annotated docx)
├── frontend/                    # Vue 3 + Vuetify SPA
├── docs/
│   └── annotated-docx-export.md # Design spec for the annotated-export feature
├── Dockerfile                   # Multi-stage: build SPA, then Python runtime
└── docker-compose.yml           # Single-service deployment, ETS_PORT override
```
