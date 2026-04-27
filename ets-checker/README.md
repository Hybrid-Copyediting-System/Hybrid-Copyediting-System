# ET&S Format Checker — MVP

Web-based tool that checks `.docx` manuscripts against ET&S (Educational Technology & Society) APA 7th format requirements.

## Quick Start

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e ".[dev]"
uvicorn ets_checker.server:app --reload --port 8080
```

### Frontend

```bash
cd frontend
npm install
npm run dev                   # → http://localhost:5173
```

Open http://localhost:5173 — Vite proxies `/api/*` to the backend.

## 8 Rules Checked

| Rule | Category | Severity |
|------|----------|----------|
| `layout.margins` | Layout | error |
| `layout.line_spacing` | Layout | error |
| `font.body` | Fonts | warning |
| `structure.abstract_length` | Structure | warning |
| `structure.keywords_count` | Structure | warning |
| `citation.cross_reference` | Citation | error |
| `reference.no_et_al` | Reference | error |
| `figures_tables.referenced_in_text` | Figures & Tables | warning |

## Production Build

```bash
cd frontend && npm run build
cp -r dist/* ../backend/ets_checker/frontend_dist/
cd ../backend
uvicorn ets_checker.server:app --port 8080
# → http://localhost:8080
```

## Tests

```bash
cd backend
pytest tests/ -v
```
