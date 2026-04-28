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

## Rules (9)

The `ets_profile.py` module hard-codes ET&S APA 7th expectations
(A4, 2.5 cm margins, single line spacing, Times New Roman 10 pt body, etc.).
Each rule is registered via a decorator in `backend/ets_checker/rules/`.

| Rule ID                              | Category         | Severity | Notes |
|--------------------------------------|------------------|----------|-------|
| `layout.margins`                     | Layout           | error    | All four margins vs. ET&S profile |
| `layout.line_spacing`                | Layout           | error    | Document default line spacing |
| `font.body`                          | Fonts            | warning  | Body runs vs. Times New Roman 10 pt |
| `structure.abstract_length`          | Structure        | warning  | ≤ 250 words (CJK + Latin word count) |
| `structure.keywords_count`           | Structure        | warning  | ≤ 5 keywords |
| `citation.cross_reference`           | Citation         | error    | Orphans, year mismatches, surname inconsistencies, uncited refs |
| `reference.no_et_al`                 | Reference        | error    | The reference list must spell out all authors |
| `reference.links`                    | Reference        | warning  | Async DOI / URL liveness check (HEAD, then GET on 405) |
| `figures_tables.referenced_in_text`  | Figures & Tables | warning  | Defined-but-uncited and cited-but-undefined figures and tables |

`reference.links` is the only async rule; it runs concurrently (5-way semaphore,
10 s timeout) via `httpx`. Soft failures (403/429/5xx, decompression errors) are
ignored on purpose — only 404/410, timeouts, and connect errors are reported.

## API

| Method | Path                     | Body                  | Returns |
|--------|--------------------------|-----------------------|---------|
| GET    | `/api/health`            | —                     | `{"status": "ok"}` |
| POST   | `/api/check`             | multipart `file=.docx`| `CheckReport` JSON (see `backend/ets_checker/models.py`) |
| POST   | `/api/check/annotated`   | multipart `file=.docx`| Annotated `.docx` (`<original-stem>.annotated.docx`) |

Upload limit: 50 MB. `.doc` is rejected with a "Save As .docx" hint.

### Annotated `.docx` export

`/api/check/annotated` runs the same pipeline as `/api/check`, then injects one
native Word comment per failed `CheckDetail` and returns the new bytes. The
original file is never modified. Anchoring is paragraph-level: document-level
findings (margins, line spacing) attach to a synthetic anchor at the top.
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
