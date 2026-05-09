# Paper Format — ET&S Format Checker workspace

Web tool that validates `.docx` manuscripts against the
*Educational Technology & Society* (ET&S) APA 7th formatting rules and can
return an annotated copy of the document with one native Word comment per
finding.

The application itself lives in [`ets-checker/`](./ets-checker/). For the
rule list, API reference, and developer setup, see
[`ets-checker/README.md`](./ets-checker/README.md).

## Layout

| Path                   | Tracked? | Purpose |
|------------------------|----------|---------|
| `ets-checker/`         | yes      | Full application (FastAPI backend, Vue 3 SPA, Dockerfile, design docs) |
| `local document/`      | no (`.gitignore`) | Local working copies of source manuscripts |
| `local To be Tested/`  | no (`.gitignore`) | Local fixtures for manual testing |
| `.claude/`, `.sixth/`  | no       | Editor/agent state, not part of the project |

The two `local …/` folders are intentionally untracked — they hold large
binary `.docx` files used while iterating on rules. Drop new fixtures there
without worrying about repo size.

---

## Running the project locally (Windows, recommended path)

The fastest way to run the checker on a personal machine is **Docker
Desktop with the WSL2 backend**. The container ships the built SPA and the
FastAPI server together on a single port, so you do not need to install
Python or Node.js yourself.

### 1. System requirements

- **OS:** Windows 10 (version 2004 / build 19041 or later) or Windows 11
- **Free disk space:** ~3 GB (Docker Desktop + image + dependencies)
- **RAM:** 4 GB minimum, 8 GB+ recommended
- **Admin rights** are needed once during Docker Desktop installation
- A working internet connection (the first build pulls base images and
  installs dependencies)

### 2. Install Docker Desktop with the WSL2 backend

1. Download Docker Desktop for Windows from
   <https://www.docker.com/products/docker-desktop/> and run the installer.
2. During install, leave **"Use WSL 2 instead of Hyper-V"** checked. If
   Windows prompts you to install the WSL2 kernel update, accept.
3. After install, launch **Docker Desktop**. The whale icon in the system
   tray should turn solid (not animated) — that means the engine is ready.
4. Open **Settings → General** in Docker Desktop and confirm
   **"Use the WSL 2 based engine"** is checked.
5. Verify from a terminal (PowerShell is fine):
   ```powershell
   docker --version
   docker compose version
   ```
   Both commands should print a version string. If `docker` is not found,
   Docker Desktop is not running — start it from the Start menu and wait
   for the whale icon to settle.

If WSL2 itself has not been enabled before, run this once in an elevated
PowerShell and reboot:

```powershell
wsl --install
```

For a full walkthrough, Microsoft's WSL install guide is the canonical
reference: <https://learn.microsoft.com/windows/wsl/install>.

### 3. Get the project

Pick one:

- **Using git** (preferred — makes future updates a one-liner):
  ```powershell
  git clone <repository-url>
  cd 論文格式
  ```
- **Without git:** download the repository as a ZIP from the host
  (GitHub/GitLab/etc.) and extract it. Open a PowerShell window in the
  extracted folder.

### 4. Start the container

From the repository root:

```powershell
cd ets-checker
docker compose up --build
```

The first run will:

1. Pull `node:20-alpine` and `python:3.12-slim` base images (~few minutes)
2. Install npm dependencies and build the SPA
3. Install Python dependencies and start `uvicorn`

When you see a line ending with
`Uvicorn running on http://0.0.0.0:48000`, the service is ready.

The port is read from `ets-checker/.env` (default `ETS_PORT=48000`). To
override:

```powershell
$env:ETS_PORT=51234; docker compose up --build
```

### 5. Use the checker

1. Open <http://localhost:48000> in any browser.
2. Drag a `.docx` file onto the upload area (or click to pick one).
   `.doc` files are rejected — open them in Word and **Save As** `.docx`
   first. Upload limit is 50 MB.
3. The page streams progress as each rule runs. When it finishes, you see
   a categorised report (errors / warnings / info) with paragraph-level
   anchors.
4. Click **Download annotated `.docx`** to get a copy of your file with
   one native Word comment per finding. The original file is never
   modified.

### 6. Stop / restart / update

- **Stop:** press `Ctrl+C` in the terminal that is running `docker compose
  up`. To remove the stopped container as well, run `docker compose down`
  in `ets-checker/`.
- **Start again later:** `docker compose up` (no `--build` needed unless
  the source changed).
- **Update to the latest code:**
  ```powershell
  git pull
  cd ets-checker
  docker compose up --build
  ```

---

## Troubleshooting

- **`docker: command not found` / `error during connect`** — Docker
  Desktop is not running. Start it from the Start menu and wait for the
  whale icon in the system tray to stop animating.
- **`Bind for 0.0.0.0:48000 failed: port is already allocated`** —
  another process holds that port. Pick a free one and re-run with
  `$env:ETS_PORT=51234; docker compose up`.
- **The first build hangs at `npm ci` or `pip install`** — usually
  network throttling. Cancel with `Ctrl+C` and retry; npm and pip both
  resume from cache on the next attempt.
- **Browser shows "This site can't be reached"** — confirm the container
  is still running (`docker ps` should list `ets-checker`) and that the
  port in the URL matches the one printed in the terminal.
- **Antivirus quarantines the build** — some Windows AV products flag
  the temporary node\_modules tree. Add the repository folder to the AV
  exclusions or pause real-time scanning during the first build.
- **Upload returns "unsupported file type"** — only `.docx` is
  accepted. `.doc`, `.pdf`, and Google Docs exports must be saved as
  `.docx` first.

---

## Want to develop, not just run?

See [`ets-checker/README.md`](./ets-checker/README.md) for the rule list,
API reference, test commands, and instructions for running the backend
and frontend dev servers separately.
