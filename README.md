# 論文格式 — ET&S Format Checker workspace

This repository hosts the **ET&S Format Checker**, a web tool that validates
`.docx` manuscripts against the *Educational Technology & Society* (ET&S)
APA 7th formatting rules and can return an annotated copy of the document
with one native Word comment per finding.

The actual application lives in [`ets-checker/`](./ets-checker/) — see
[`ets-checker/README.md`](./ets-checker/README.md) for setup, the rule list,
the API, and Docker deployment instructions.

## Layout

| Path                   | Tracked? | Purpose |
|------------------------|----------|---------|
| `ets-checker/`         | yes      | The full application (FastAPI backend, Vue 3 SPA, Dockerfile, design docs) |
| `local document/`      | no (`.gitignore`) | Local working copies of source manuscripts |
| `local To be Tested/`  | no (`.gitignore`) | Local fixtures used during manual testing |
| `.claude/`, `.sixth/`  | no       | Editor/agent state, not part of the project |

The two `local …/` folders are intentionally untracked — they hold large
binary `.docx` files used while iterating on rules. Drop new fixtures there
without worrying about repo size.

## Quick start

```bash
# Containerised (single port, includes built SPA):
cd ets-checker
docker compose up --build           # → http://localhost:48000  (ETS_PORT in .env)

# Or run backend + frontend dev servers separately:
#   ets-checker/README.md → "Quick Start (development)"
```
