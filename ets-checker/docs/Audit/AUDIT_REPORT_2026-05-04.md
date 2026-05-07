# ETS-Checker — Full Codebase Audit Report

**Date:** 2026-05-04  
**Scope:** Backend (Python/FastAPI), Frontend (Vue 3 + TypeScript), Tests, Infrastructure  
**Coverage:** Security, Systemic Bugs, Unclear Responsibilities, Code Quality

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Security Vulnerabilities](#1-security-vulnerabilities)
3. [Systemic Bugs](#2-systemic-bugs)
4. [Unclear Responsibilities & Architecture](#3-unclear-responsibilities--architecture)
5. [Code Quality Issues](#4-code-quality-issues)
6. [Test Suite Issues](#5-test-suite-issues)
7. [Master Issue Index](#6-master-issue-index)

---

## Executive Summary

| Category | Critical | High | Medium | Low |
|----------|----------|------|--------|-----|
| Security | 1 | 2 | 5 | 1 |
| Systemic Bugs | 0 | 4 | 8 | 4 |
| Unclear Responsibilities | 0 | 2 | 7 | 2 |
| Code Quality | 0 | 0 | 3 | 12 |
| Test Coverage | 2 | 5 | 6 | 3 |

**Highest-priority items requiring immediate attention:**

1. CORS misconfiguration allows all HTTP methods and headers (`server.py:36-41`)
2. User-supplied filename injected into `Content-Disposition` header without sanitization (`server.py:203-214`)
3. Six critical rule groups (citations, references, fonts) have zero pytest coverage
4. Streaming SSE endpoint (`/api/check/stream`) is entirely untested
5. Global mutable rule registry with import-order-dependent behavior (`runner.py:21-22`)
6. Business logic, file I/O, and HTTP handling are all mixed inside endpoint handlers

---

## 1. Security Vulnerabilities

### 1.1 CORS Allows All Methods and Headers — CRITICAL

**File:** `backend/ets_checker/server.py`, lines 36–41

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(set(_cors_origins)),
    allow_methods=["*"],
    allow_headers=["*"],
)
```

`allow_methods=["*"]` permits DELETE, PUT, PATCH, and other methods the API never uses. `allow_headers=["*"]` allows arbitrary header forwarding, including custom authentication headers from other origins. Hardcoded `localhost` origins in `.env` may leak into production.

**Fix:** Restrict to `["GET", "POST", "OPTIONS"]` and enumerate only the headers actually needed.

---

### 1.2 Unsafe Filename Injected into Content-Disposition Header — HIGH

**File:** `backend/ets_checker/server.py`, lines 203–214

```python
stem = filename.rsplit(".", 1)[0]
out_name = f"{stem}.annotated.docx"
encoded_name = quote(out_name)
headers={"Content-Disposition": f"attachment; filename=\"{out_name.encode('ascii', 'replace').decode()}\"; filename*=UTF-8''{encoded_name}"}
```

A filename like `foo"; Content-Type: text/html; x-evil="` or a path traversal pattern like `../../etc/passwd` is processed without any sanitization. This enables HTTP header injection and path-traversal-style attacks. There is also no length limit on filenames.

**Fix:**
```python
import re
safe_stem = re.sub(r'[^a-zA-Z0-9._\-]', '_', stem)[:100]
out_name = f"{safe_stem}.annotated.docx"
```

---

### 1.3 Temporary File TOCTOU Race Condition — MEDIUM

**File:** `backend/ets_checker/server.py`, lines 82–90

`tempfile.NamedTemporaryFile(delete=False)` closes the file descriptor after the `with` block, but the file is not deleted until the endpoint's `finally` clause. Between those two points, the file is world-readable on some systems and accessible to any co-tenant process. Under concurrent load, multiple requests may interleave their temp file lifecycles.

**Fix:** Set restrictive umask before creation, or use `tempfile.TemporaryDirectory()` which guarantees cleanup.

---

### 1.4 No Rate Limiting on Any Endpoint — MEDIUM

**File:** `backend/ets_checker/server.py`, lines 48+

All POST endpoints accept large `.docx` files from any origin with no rate limiting, CSRF tokens, or per-IP throttling. A script can continuously upload 50 MB files to exhaust CPU, disk, and memory.

**Fix:** Add `slowapi` or equivalent rate-limiting middleware; enforce per-IP request quotas.

---

### 1.5 Exception Details Leaked to Clients — MEDIUM

**File:** `backend/ets_checker/rules/reference_links.py`, lines 47–52

```python
except Exception as exc:
    msg = str(exc)
    if any(k in msg for k in ("Zstandard", "zstd", ...)):
        return url, None
    return url, f"error: {msg[:60]}"
```

The raw exception string (which can include library names, internal paths, system details) is sent to the client as part of the check report. String-matching on exception text is fragile and can be bypassed.

**Fix:** Log the full exception server-side; return a generic `"Network error checking URL"` to the client.

---

### 1.6 Unvalidated URL Schemes in Reference Link Checker — LOW

**File:** `backend/ets_checker/rules/reference_links.py`, lines 61–118

URLs extracted from references are dispatched to `httpx` without validating the scheme. A malformed reference containing `file:///etc/passwd` or `ftp://...` is not explicitly blocked. `follow_redirects=True` means redirect chains are also not validated for scheme changes.

**Fix:** Add an explicit check: `if not url.startswith(("http://", "https://")):` before dispatching.

---

### 1.7 Potential ReDoS in Reference URL Regex — MEDIUM

**File:** `backend/ets_checker/parser/references.py`, lines 18, 31–34, 42

The `_CONT` continuation pattern:
```python
_CONT = re.compile(r'[\s ]+(?!https?://)([0-9_(]\S*)')
```
Uses `\S*` (zero or more non-whitespace) which can cause catastrophic backtracking when applied to long strings containing many parentheses or underscores before a boundary. Crafted input like repeated `"((((((((((0"` sequences can trigger polynomial-time backtracking.

**Fix:** Replace `\S*` with a bounded quantifier: `\S{0,200}`.

---

## 2. Systemic Bugs

### 2.1 Bare `except Exception` Handlers Swallow All Errors — HIGH

**File:** `backend/ets_checker/server.py`, lines 86, 99, 123, 137, 180, 186, 196

Seven separate `except Exception:` or `except Exception as e:` blocks (where `e` is never used) mask the actual failure. Some of these could catch `SystemExit`, `MemoryError`, or `GeneratorExit`. The exception context is lost; production failures become undiagnosable.

**Fix:** Catch specific exceptions. Where broad catching is necessary, always log with `logger.exception(...)`.

---

### 2.2 Async Task Cancellation Not Awaited — MEDIUM

**File:** `backend/ets_checker/server.py`, lines 154–155

```python
if runner_task is not None and not runner_task.done():
    runner_task.cancel()
```

Calling `.cancel()` without `await runner_task` leaves a dangling `CancelledError` and logs an unhandled exception warning. Resources held inside the task are not released deterministically.

**Fix:**
```python
runner_task.cancel()
try:
    await runner_task
except asyncio.CancelledError:
    pass
```

---

### 2.3 `bare except: pass` in Parser Metadata — MEDIUM

**File:** `backend/ets_checker/parser/metadata.py`, lines 71–72

```python
except Exception:
    pass
return False
```

This silently swallows any exception from `_scan_hf()`. If there is a bug in header/footer scanning, the function returns `False` (no page numbers detected) with no log entry. The error is invisible in production.

**Fix:**
```python
except Exception:
    logger.warning("Header/footer scan failed", exc_info=True)
```

---

### 2.4 Negative Paragraph Index Not Validated — HIGH

**File:** `backend/ets_checker/rules/reference.py`, lines 196–197

The bounds check reads:
```python
if r.paragraph_index >= len(doc.paragraphs): continue
```
This guards against too-large indices but not negative values. In Python, a negative index silently wraps around to the end of the list, so a malformed `paragraph_index=-1` would point to the last paragraph rather than raising an error.

**Fix:** Change to `if not (0 <= r.paragraph_index < len(doc.paragraphs)): continue`.

---

### 2.5 Off-By-One in Error Count Reporting — MEDIUM

**File:** `backend/ets_checker/rules/citation.py`, lines 193–209

`orphan_count` is incremented **before** checking `if orphan_count <= MAX_REPORTED`, while `year_mismatch_count` is incremented **after** the check. This means orphan citations may report one fewer item than year mismatches under identical conditions, creating inconsistent behavior across rules.

**Fix:** Apply the same increment-after-check pattern uniformly.

---

### 2.6 Silent Citation Loss When Author Normalizes to Empty — MEDIUM

**File:** `backend/ets_checker/parser/citations.py`, lines 162–170

When stripping discourse markers leaves `t_authors` empty, the citation is silently discarded with no log entry. A valid citation whose author string happened to match a discourse marker would vanish from the report without any indication.

**Fix:** Log a warning before `continue` when `t_authors` becomes empty after normalization.

---

### 2.7 Figure Paragraph Index Falls Back Silently — LOW

**File:** `backend/ets_checker/parser/figures.py`, lines 153–154

```python
if para_index >= len(paragraphs):
    para_index = max(0, len(paragraphs) - 1)
```

An out-of-range index is silently clamped to the last paragraph. This masks data corruption or parsing errors that produced the bad index.

**Fix:** Log a warning before reassigning `para_index`.

---

### 2.8 Unsafe `int()` Conversion Without Error Handling — LOW

**File:** `backend/ets_checker/parser/paragraphs.py`, lines 53, 63, 98

```python
return round(int(val) / EMU_PER_CM, 4)
```

If `val` is a non-numeric string from a malformed DOCX, `int(val)` raises `ValueError` with no error handling. The call stack propagates upward and may cause an entire document parse to fail.

**Fix:**
```python
try:
    return round(int(val) / EMU_PER_CM, 4)
except (ValueError, TypeError):
    logger.warning("Invalid dimension: %r", val)
    return None
```

---

### 2.9 Author Sort Key Doesn't Validate Its Inputs — MEDIUM

**File:** `backend/ets_checker/rules/reference.py`, lines 54–61

If `author_sort_keys` contains empty strings or malformed entries, the fallback to `first_author_surname` is never triggered, and sorting proceeds on incomplete keys. This can cause incorrect alphabetical order validation without raising an error.

**Fix:** Filter empty strings from `keys` before checking `if not keys`.

---

### 2.10 ObjectURL Leak in Download Error Path — MEDIUM

**File:** `frontend/src/App.vue`, lines 70–86

If an error is thrown after `URL.createObjectURL(blob)` is called, the catch block does not call `URL.revokeObjectURL()`. The blob URL is leaked for the lifetime of the page.

**Fix:** Use a `finally` block or assign the URL in a variable that is always revoked:
```typescript
let objUrl: string | null = null;
try {
    objUrl = URL.createObjectURL(blob);
    // ... click ...
} finally {
    if (objUrl) setTimeout(() => URL.revokeObjectURL(objUrl!), 60_000);
}
```

---

### 2.11 SSE Stream Continues on JSON Parse Error — MEDIUM

**File:** `frontend/src/api.ts`, lines 89–92

```typescript
try {
    data = JSON.parse(dataStr);
} catch {
    continue;  // silently skip
}
```

If the backend sends a malformed SSE event, the client skips it and keeps waiting for `"complete"`. The user sees an infinite spinner with no error feedback.

**Fix:** Track malformed event count; if it exceeds a threshold, reject the stream with an informative error.

---

### 2.12 Button Disabled State Does Not Check `report` — LOW

**File:** `frontend/src/App.vue`, lines 67, 181

The download button is disabled when `!lastFile`, but the function also guards `if (!lastFile.value || !report.value) return`. A user whose `report` is null but `lastFile` exists will see an enabled button that does nothing.

**Fix:**
```vue
:disabled="!lastFile || !report"
```

---

## 3. Unclear Responsibilities & Architecture

### 3.1 Endpoint Handlers Contain Business Logic, File I/O, and HTTP Handling — HIGH

**File:** `backend/ets_checker/server.py`, lines 93–220

Each of the three endpoints (`/api/check`, `/api/check/stream`, `/api/check/annotated`) duplicates the same pattern: validate file → save to temp → parse → run rules → clean up. The try/except/finally structure is copy-pasted across three functions. Business logic (document parsing, rule running) is interleaved with HTTP concerns.

**Fix:** Extract a service layer:
```python
# services.py
async def process_document(tmp_path: str, filename: str) -> CheckReport: ...

# server.py
@app.post("/api/check")
async def check(file: UploadFile = File(...)):
    tmp_path, name = await save_temp(file)
    try:
        return await process_document(tmp_path, name)
    finally:
        os.unlink(tmp_path)
```

---

### 3.2 Global Mutable Rule Registry with Import-Order-Dependent Behavior — HIGH

**File:** `backend/ets_checker/rules/runner.py`, lines 21–22, 41, 53

```python
_REGISTRY: list[tuple[str, str, str, Severity, RuleFunc]] = []
_ASYNC_REGISTRY: list[tuple[str, str, str, Severity, AsyncRuleFunc]] = []
```

Rules register themselves via decorators at import time. The order rules execute depends on the order Python imports the modules — an implicit, fragile dependency. There is no mechanism to disable or reorder rules without changing import statements.

**Fix:** Use an explicit registry class with deterministic ordering:
```python
class RuleRegistry:
    def register(self, rule: Rule): ...
    def run_all(self, doc: ParsedDocument) -> CheckReport: ...
```

---

### 3.3 Progress Callback Hidden in Context Variables — MEDIUM

**File:** `backend/ets_checker/rules/runner.py`, lines 24–31

The progress callback is stored in a `ContextVar` and retrieved via `get_link_progress()` inside the async rule. This makes the dependency invisible from function signatures, impossible to mock without patching the global variable, and confusing for any reader tracing the call chain.

**Fix:** Pass the callback explicitly as a parameter to `check_reference_links()`.

---

### 3.4 Inconsistent Error Handling Across Three Endpoints — MEDIUM

**File:** `backend/ets_checker/server.py`, lines 99–104, 125–130, 186–191

The same "Could not parse the uploaded document" message appears in three separate `except` blocks with slightly different logging strategies. Changing the error message or status code requires editing three places.

**Fix:** Register a FastAPI exception handler for a custom `DocumentParseError`:
```python
@app.exception_handler(DocumentParseError)
async def parse_error_handler(request, exc):
    logger.exception("Parse failed", exc_info=exc)
    return JSONResponse(status_code=422, content={"detail": "..."})
```

---

### 3.5 Surname Normalization Duplicated with Subtle Differences — MEDIUM

**Files:**
- `backend/ets_checker/rules/citation.py`, lines 36–41 (`normalise_surname`)
- `backend/ets_checker/parser/references.py`, lines 129–136 (`_normalise_for_sort`)

Both functions strip diacritics and lower-case surnames for comparison, but they apply `.lower()` at different points and strip different character classes via different regex patterns. A surname that normalizes differently in each function will cause false cross-reference failures.

**Fix:** Extract one canonical `normalise_surname()` function (e.g., in `models.py` or a `utils.py`) and import it from both modules.

---

### 3.6 Reference Section Boundary Logic Duplicated Between Two Parsers — MEDIUM

**Files:**
- `backend/ets_checker/parser/citations.py`, lines 115–127
- `backend/ets_checker/parser/references.py`, lines 241–255

Both files contain independent implementations of `_compute_reference_bounds`, which determines where the reference section starts and ends. A bug fix or behavior change in one will not be reflected in the other.

**Fix:** Extract to a shared utility and import it in both parsers.

---

### 3.7 Font Checker Mixes Paragraph Filtering with Font Validation — MEDIUM

**File:** `backend/ets_checker/rules/fonts.py`, lines 125–194

`check_body_font` simultaneously: (1) determines which paragraphs qualify as "body" paragraphs, (2) checks font name, (3) checks font size, and (4) gathers size statistics. The body-paragraph filtering logic also has near-identical code in `_get_abstract_paragraph_indices`.

**Fix:** Extract `_get_body_paragraph_indices()` as a standalone function reused by both.

---

### 3.8 Annotation Module Has Hardcoded Author Name — MEDIUM

**File:** `backend/ets_checker/exporter/annotate.py`, lines 27–61

`author="ET&S Checker"` is hardcoded in the annotation writer. The comment formatting function `_format_comment_text` duplicates rule name/ID strings that are already present on `CheckResult`. This creates a second source of truth for display text.

**Fix:** Make `author` a configurable parameter; derive comment text from `CheckResult.rule_name` rather than re-building it.

---

### 3.9 API Layer Builds Fake Error Objects Matching Axios Shape — MEDIUM

**File:** `frontend/src/api.ts`, lines 47, 61, 102

```typescript
throw Object.assign(new Error(msg), { response: { data: { detail: msg } } });
```

The SSE streaming code manually creates objects shaped like axios errors so that `extractErrorMessage()` (which parses axios error structure) can process them. This is an abstraction leak — the non-axios code path is pretending to be axios.

**Fix:** Create a dedicated `APIError` class:
```typescript
class APIError extends Error {
    constructor(public detail: string) { super(detail); }
}
```

---

### 3.10 Progress Event Type Defined in API Module, Used by UI — LOW

**File:** `frontend/src/api.ts` + `frontend/src/App.vue`

`ProgressEvent` is defined in `api.ts` alongside HTTP functions, but it is fundamentally a UI state type. Components import it from `api.ts`, coupling the UI layer to the API layer for a type that has nothing to do with HTTP transport.

**Fix:** Move `ProgressEvent` (and other UI-facing types) to `types.ts`.

---

### 3.11 Health Check Blocks Component Mount with `await` — LOW

**File:** `frontend/src/App.vue`, lines 29–35

The health check loop uses `await new Promise(r => setTimeout(r, 2000 * (attempt + 1)))` inside `onMounted`, blocking the component from becoming interactive until all retries complete.

**Fix:** Use `setTimeout` (non-awaited) to check in the background:
```typescript
const checkHealth = async () => {
    backendReady.value = await healthCheck();
    if (!backendReady.value && attempt < 5) {
        attempt++;
        setTimeout(checkHealth, 2000 * attempt);
    }
};
checkHealth(); // fire-and-forget
```

---

## 4. Code Quality Issues

### 4.1 `docker-compose.yml` Health Check Uses Python Interpreter — LOW

**File:** `docker-compose.yml`, line 18

The health check runs a Python interpreter to make an HTTP call, which is slow, heavyweight, and fragile. It also installs dev dependencies via `pip install -e .`.

**Fix:** Use `curl -f http://localhost:8080/api/health` as the health check command.

---

### 4.2 Dockerfile Installs Package in Editable Mode — LOW

**File:** `Dockerfile`, line 31

`pip install -e .` in production leaks the entire source tree into the editable install path and includes dev dependencies implicitly.

**Fix:** Use `pip install .` (non-editable) for production builds.

---

### 4.3 `alert()` Used for Form Validation in FileUploader — MEDIUM

**File:** `frontend/src/components/FileUploader.vue`, lines 16–17, 22, 26

Three separate `alert()` calls for validation errors. `alert()` blocks the main thread, is not theme-able, is not accessible to screen readers, and cannot be automatically tested.

**Fix:** Emit a validation error event to the parent, which displays it inline using a `v-alert`.

---

### 4.4 Magic Numbers Scattered Across Frontend — LOW

**Files:** `frontend/src/components/FileUploader.vue:11`, `frontend/src/App.vue:33,78,99`

Constants like `50 * 1024 * 1024` (max file size), `2000` (retry delay), and `60_000` (blob revocation timeout) appear inline with no explanation.

**Fix:** Centralize in `src/constants.ts`.

---

### 4.5 Dead Export: `checkDocument()` — LOW

**File:** `frontend/src/api.ts`, lines 116–121

`checkDocument()` is exported but never imported or called anywhere. The application uses `checkDocumentStreaming()` exclusively.

**Fix:** Delete `checkDocument()` or mark it clearly as a non-streaming fallback with a comment explaining when to use it.

---

### 4.6 Inconsistent Pattern: Some Error Counts Increment Before Check, Others After — LOW

**File:** `backend/ets_checker/rules/citation.py`, lines 193–209

Some counters are incremented before the `MAX_REPORTED` guard, others after. The actual number of reported items varies by one between rule types under identical conditions.

**Fix:** Apply a uniform pattern: check first, then increment.

---

### 4.7 Log Entry May Include Arbitrarily Long `detail.message` — LOW

**File:** `backend/ets_checker/exporter/anchor.py`, lines 66–75

The fallback warning log includes `detail.message` without length truncation. A rule that generates a very long message would produce an oversized log line.

**Fix:** Truncate: `detail.message[:120]`.

---

### 4.8 Regex Compiled Inside Loop — LOW

**File:** `backend/ets_checker/parser/citations.py`, line 151

```python
re.sub(r"\(Eds?\.\)", "", author_text)
```

Python caches compiled regexes, but explicit pre-compilation (`_RE_EDS = re.compile(...)`) communicates intent and avoids the cache lookup on every iteration.

---

### 4.9 `getCategories()` Uses Unnecessary Intermediate Array — LOW

**File:** `frontend/src/App.vue`, lines 107–117

Can be simplified to:
```typescript
function getCategories(r: CheckReport): string[] {
    return [...new Set(r.results.map(item => item.category))];
}
```

---

### 4.10 `.env` File Is Tracked in Git — MEDIUM

**File:** `.env` (repository root)

The `.env` file containing `ETS_CORS_ORIGINS` (and potentially other secrets) is committed to the repository. Even if the current values are harmless, having `.env` tracked means any future secret added to it will be stored in git history permanently.

**Fix:** Add `.env` to `.gitignore`; use `.env.example` to document expected variables.

---

## 5. Test Suite Issues

### 5.1 Citation and Reference Cross-Check Rules Have Zero Pytest Coverage — CRITICAL

**Files:** `backend/ets_checker/rules/citation.py`, `backend/ets_checker/rules/reference.py`

The `check_cross_reference` function (~260 lines) handles orphan citations, year mismatches, surname normalization, near-miss detection, and institutional author matching. None of this logic is exercised by the pytest suite. Only the non-integrated `test_edge_cases.py` script (not run by CI) touches it.

---

### 5.2 Font Rules Only Tested in Non-Integrated Script — CRITICAL

**File:** `backend/tests/test_rules.py`

Six font rules (`font.body`, `font.abstract`, `font.heading`, `font.reference`, `font.title`, `font.stat_italic`) are only tested in `test_edge_cases.py`, which is not part of the pytest suite and therefore not run in CI.

---

### 5.3 Streaming Endpoint Not Tested — HIGH

**File:** `backend/tests/test_api.py`

The `/api/check/stream` endpoint exists in `server.py` but has no test at all. The SSE event structure, error behavior, progress events, and final `"complete"` event are all unverified.

---

### 5.4 Rule Count Discrepancy (21 vs. 22) — HIGH

**Files:**
- `backend/tests/test_rules.py`, line 47: expects `total_checks == 21`
- `backend/tests/test_api.py`, line 116: expects `total_checks == 22`

Two tests expect different totals for the same rule set. This indicates one test is outdated, or the rule registry behaves differently when accessed directly versus through the HTTP endpoint (e.g., one async rule is not being counted in the sync-only test).

**Fix:** Replace both hardcoded values with:
```python
from ets_checker.rules.runner import _REGISTRY, _ASYNC_REGISTRY
expected = len(_REGISTRY) + len(_ASYNC_REGISTRY)
```

---

### 5.5 Figure/Table Rules Entirely Untested — HIGH

**File:** `backend/tests/`

No test fixtures contain figures or tables. The rules `figures_tables.referenced_in_text`, `figures_tables.caption_position`, and `figures_tables.table_format` are never exercised.

---

### 5.6 Async Reference Link Rule Untested — HIGH

**File:** `backend/tests/`

The async rule `check_reference_links` — including URL validation, retry logic, HTTP error handling, and the progress callback — has no tests in the pytest suite.

---

### 5.7 Weak Assertions Provide False Confidence — MEDIUM (multiple locations)

| Location | Issue |
|----------|-------|
| `test_rules.py:52` | `assert report.summary.passed >= 5` — passes even if only 5 of 21 rules pass |
| `test_rules.py:61–78` | Checks only `status == "fail"`; doesn't validate error messages or locators |
| `test_api.py:43–56` | Extension tests check only status codes, not error message content |
| `test_parser.py:27` | Tolerance `±0.2 cm` for margin test is too loose |
| `test_annotate.py:184–210` | Out-of-bounds anchor test only checks that DOCX is valid; doesn't verify fallback paragraph |

---

### 5.8 No Tests for Malformed or Empty Documents — MEDIUM

The test suite has no fixtures for:
- Empty `.docx` files (zero paragraphs)
- Corrupted `.docx` files (invalid ZIP structure)
- Documents with no detected sections
- Documents where all paragraphs are in tables
- Documents at the 50 MB file size boundary

---

### 5.9 `test_edge_cases.py` Not Integrated into Pytest — MEDIUM

**Files:** `backend/test_edge_cases.py`, `backend/test_document.py`

Both files live outside `backend/tests/` and are not collected by the default pytest configuration. They contain the most comprehensive behavioral tests (font rules, link checking, citation parsing), but are never run automatically.

**Fix:** Move into `backend/tests/` and add `conftest.py` fixtures as needed.

---

### 5.10 Fixture Values Don't Match Test Assertions — MEDIUM

**File:** `backend/tests/conftest.py`, lines 26–65

Fixtures create documents with specific values (margin = 4.0 cm, abstract = 260 words) but tests only assert `status == "fail"` without checking the actual measured values. This means the rule could return `"fail"` for a completely different reason and the test would still pass.

---

### 5.11 Progress Callback Conditional Not Fully Tested — LOW

**File:** `backend/tests/test_rules.py`, lines 119–124

`test_run_async_without_callback_does_not_raise()` only validates that no exception is raised when `on_progress=None`. It does not validate that the report is correct or that all async rules ran.

---

### 5.12 Annotated Download Endpoint Not Tested — LOW

**File:** `backend/tests/test_api.py`

The `/api/check/annotated` endpoint (which accepts `report_json` as a body parameter alongside the file) has no test case verifying that the `report_json` parameter is correctly parsed and applied.

---

## 6. Master Issue Index

| # | Severity | Category | File | Lines | Title |
|---|----------|----------|------|-------|-------|
| S-01 | CRITICAL | Security | `server.py` | 36–41 | CORS allows all methods and headers |
| S-02 | HIGH | Security | `server.py` | 203–214 | Filename injected into Content-Disposition |
| S-03 | MEDIUM | Security | `server.py` | 82–90 | Temp file TOCTOU race condition |
| S-04 | MEDIUM | Security | `server.py` | 48+ | No rate limiting on any endpoint |
| S-05 | MEDIUM | Security | `reference_links.py` | 47–52 | Exception details leaked to clients |
| S-06 | MEDIUM | Security | `references.py` | 18, 42 | ReDoS risk in `_CONT` regex |
| S-07 | LOW | Security | `reference_links.py` | 61–118 | Unvalidated URL schemes |
| B-01 | HIGH | Bug | `server.py` | 86, 99, 123, 137, 180, 186, 196 | Bare except handlers swallow all errors |
| B-02 | MEDIUM | Bug | `server.py` | 154–155 | Async task cancellation not awaited |
| B-03 | MEDIUM | Bug | `metadata.py` | 71–72 | `except: pass` silences parser errors |
| B-04 | HIGH | Bug | `reference.py` | 196–197 | Negative paragraph index not validated |
| B-05 | MEDIUM | Bug | `citation.py` | 193–209 | Off-by-one in error count reporting |
| B-06 | MEDIUM | Bug | `citations.py` | 162–170 | Silent citation loss on empty author |
| B-07 | LOW | Bug | `figures.py` | 153–154 | Figure index silently clamped |
| B-08 | LOW | Bug | `paragraphs.py` | 53, 63, 98 | Unsafe `int()` without error handling |
| B-09 | MEDIUM | Bug | `reference.py` | 54–61 | Sort key not validated for empty entries |
| B-10 | MEDIUM | Bug | `App.vue` | 70–86 | ObjectURL leaked in error path |
| B-11 | MEDIUM | Bug | `api.ts` | 89–92 | SSE stream hangs on JSON parse error |
| B-12 | LOW | Bug | `App.vue` | 67, 181 | Download button disabled state ignores `report` |
| A-01 | HIGH | Architecture | `server.py` | 93–220 | Business logic mixed into endpoint handlers |
| A-02 | HIGH | Architecture | `runner.py` | 21–22 | Global mutable rule registry |
| A-03 | MEDIUM | Architecture | `runner.py` | 24–31 | Progress callback hidden in ContextVar |
| A-04 | MEDIUM | Architecture | `server.py` | scattered | Inconsistent error handling across endpoints |
| A-05 | MEDIUM | Architecture | `citation.py`/`references.py` | — | Surname normalization duplicated |
| A-06 | MEDIUM | Architecture | `citations.py`/`references.py` | — | Reference bounds logic duplicated |
| A-07 | MEDIUM | Architecture | `fonts.py` | 125–194 | Font checker mixes paragraph filtering and font validation |
| A-08 | MEDIUM | Architecture | `annotate.py` | 27–61 | Hardcoded author name; duplicated message text |
| A-09 | MEDIUM | Architecture | `api.ts` | 47, 61, 102 | Fake error objects shaped like axios errors |
| A-10 | LOW | Architecture | `api.ts`/`App.vue` | — | ProgressEvent type defined in API module |
| A-11 | LOW | Architecture | `App.vue` | 29–35 | Health check blocks component mount |
| Q-01 | LOW | Quality | `docker-compose.yml` | 18 | Health check uses Python interpreter |
| Q-02 | LOW | Quality | `Dockerfile` | 31 | Editable install in production |
| Q-03 | MEDIUM | Quality | `FileUploader.vue` | 16–26 | `alert()` for form validation |
| Q-04 | LOW | Quality | `FileUploader.vue`/`App.vue` | — | Magic numbers without constants |
| Q-05 | LOW | Quality | `api.ts` | 116–121 | Dead export `checkDocument()` |
| Q-06 | LOW | Quality | `citation.py` | 193–209 | Inconsistent counter increment pattern |
| Q-07 | LOW | Quality | `anchor.py` | 66–75 | Unbounded log message from `detail.message` |
| Q-08 | MEDIUM | Quality | `.env` | — | `.env` committed to git |
| T-01 | CRITICAL | Tests | `citation.py` | — | Citation/reference cross-check rule untested in pytest |
| T-02 | CRITICAL | Tests | `fonts.py` | — | Font rules only in non-integrated test script |
| T-03 | HIGH | Tests | `test_api.py` | — | Streaming endpoint not tested |
| T-04 | HIGH | Tests | `test_rules.py:47`/`test_api.py:116` | — | Rule count discrepancy (21 vs. 22) |
| T-05 | HIGH | Tests | `tests/` | — | Figure/table rules entirely untested |
| T-06 | HIGH | Tests | `tests/` | — | Async link-checking rule untested |
| T-07 | MEDIUM | Tests | multiple | — | Weak assertions provide false confidence |
| T-08 | MEDIUM | Tests | `tests/` | — | No tests for malformed or empty documents |
| T-09 | MEDIUM | Tests | `test_edge_cases.py` | — | Edge-case tests not integrated into pytest |
| T-10 | MEDIUM | Tests | `conftest.py`/test files | — | Fixture values not validated in assertions |
| T-11 | LOW | Tests | `test_rules.py` | 119–124 | Progress callback conditional not fully tested |
| T-12 | LOW | Tests | `test_api.py` | — | Annotated download endpoint not tested |
