# Vigil — Design Specification v1

> A CLI process manager that gives Claude Code (and humans) full visibility and control over local development processes and ports.

## Problem

Claude Code runs local dev commands (`uv run`, `npm run dev`, `docker compose up`) but loses track of them. Processes become orphaned in the background, CC doesn't know what's running on which port, and there's no reliable way to check status, restart, or tear things down. The result: port conflicts, mystery processes, and constant manual detective work.

## Solution

**Vigil** is a lightweight CLI tool that acts as a single source of truth for local dev processes. It can start, stop, and monitor named processes, scan ports for anything listening, capture logs, and report status in both human-readable and JSON formats.

Vigil has **no daemon**. Each CLI call inspects live system state (PIDs, ports) and reconciles it with a statefile of managed processes. This means zero setup, no background process to babysit, and results that always reflect reality.

---

## Core Concepts

### Managed vs Unmanaged Processes

- **Managed**: Processes started via `vigil start`. Vigil tracks their name, command, PID, and captures their logs.
- **Unmanaged**: Processes vigil didn't start but that are listening on ports. Detected by `vigil scan`. Shown separately so CC has full situational awareness.

### Statefile

A JSON file that records managed processes. On every CLI call, vigil reads the statefile and validates entries against live system state (is the PID still alive? does the start time match? what ports is it using?).

Written atomically: write to a temp file, then `os.rename()` to the real path. This prevents corruption if vigil is interrupted mid-write.

### PID Verification

PIDs can be reused by the OS. Before trusting a recorded PID, vigil checks two things:

1. Is the PID still alive?
2. Was it started at or after the recorded `started_at` timestamp?

If the PID is alive but started before the recorded time, vigil treats the managed process as dead and cleans up. No command string matching — launchers like `uv run` exec into child processes that would never match the original command string anyway.

### Process Lifecycle

- **Alive**: PID is running and start time matches.
- **Crashed**: PID is gone but vigil did not stop it — entry remains in statefile, visible in `vigil status` as a warning.
- **Stopped**: Vigil stopped it intentionally via `vigil stop` — entry is removed from statefile entirely, never shown in status.

### Log Capture

Each managed process has its stdout/stderr redirected to `.vigil/logs/<name>.log` at spawn time. Logs grow freely while the process runs. When a process is stopped or restarted, the log file is trimmed to the last N lines (configurable, default 500). This prevents unbounded growth at a natural moment in the process lifecycle.

### Docker Enrichment

Vigil automatically enriches port and process data with Docker container metadata wherever it is relevant. This is handled by a dedicated `docker` module that sits below all commands as a cross-cutting concern — it is not a feature of any single command.

When any command needs process or port data, the `docker` module checks if the underlying process is a Docker-managed container and, if so, adds:
- `container_name` — the Docker container name
- `image` — the image name and tag
- `compose_service` — the Docker Compose service name (from container labels)
- `compose_project` — the Docker Compose project name (from container labels)

This data surfaces as a nested `docker` object in JSON output — `null` for non-container processes.

**Implementation:** Vigil shells out to `docker ps --format json` once per invocation when enrichment is needed. The result is computed once and reused within that invocation — no repeated calls. If `docker` is not in PATH or the daemon is unreachable, enrichment is silently skipped. Non-Docker workflows are unaffected.

### Per-Project State

Vigil requires explicit initialization via `vigil init`. All commands walk up the directory tree (git-style) to find `.vigil/`. If no `.vigil/` directory is found, vigil exits with a clear error: `"No vigil project found. Run vigil init first."`

There is no global mode. Vigil is a project tool.

---

## Commands

### `vigil init`

Initialize a vigil project in the current directory. Creates `.vigil/` and writes a `Vigilfile`.

**Human mode (interactive):**
```
$ vigil init
? Process name: backend
? Command: uv run uvicorn main:app --port 8000
? Expected port: 8000
? Add another process? (y/n): y
? Process name: frontend
? Command: npm run dev
? Expected port: 3000
? Add another process? (y/n): n

✓ .vigil/ created
✓ Vigilfile written
Run vigil up to start all processes.
```

**CC mode (explicit flags):**
```bash
vigil init \
  --process backend,"uv run uvicorn main:app --port 8000",8000 \
  --process frontend,"npm run dev",3000 \
  --process db,"docker compose up postgres",5432 \
  --json
```

```json
{"status": "created", "processes": [{"name": "backend", "command": "uv run uvicorn main:app --port 8000", "port": 8000}, {"name": "frontend", "command": "npm run dev", "port": 3000}, {"name": "db", "command": "docker compose up postgres", "port": 5432}]}
```

**Flags:**
- `--process name,"command",port` — define a process (repeatable)
- `--json` — machine-readable output

---

### `vigil status`

The primary dashboard command. Shows all managed processes — alive and crashed. Intentionally stopped processes are not shown.

```
$ vigil status
  backend   ● alive    PID 12345  :8000  (uv run uvicorn main:app --port 8000)
  frontend  ● alive    PID 12346  :3000  (npm run dev)
  db        ✖ crashed             :5432  (docker compose up postgres)
```

```
$ vigil status --json
{
  "managed": [
    {
      "name": "backend",
      "command": "uv run uvicorn main:app --port 8000",
      "pid": 12345,
      "alive": true,
      "ports": [8000]
    },
    {
      "name": "frontend",
      "command": "npm run dev",
      "pid": 12346,
      "alive": true,
      "ports": [3000]
    },
    {
      "name": "db",
      "command": "docker compose up postgres",
      "pid": null,
      "alive": false,
      "crashed": true,
      "ports": []
    }
  ]
}
```

**Flags:**
- `--json` — machine-readable JSON output

---

### `vigil scan`

Full OS port landscape snapshot. The escape hatch for when CC needs to reorient — shows everything listening on dev-range ports, enriched with Docker container metadata where applicable. Independent of the statefile. Reads the OS socket table directly (one syscall, instant).

Use `vigil status` for managed process state. Use `vigil scan` when the picture is unclear and a full landscape view is needed.

```
$ vigil scan
  PID 12345  :8000   uv run uvicorn main:app --port 8000
  PID 12346  :3000   npm run dev
  PID 9921   :5432   [docker] myapp-postgres-1  postgres:16  (compose: myapp/postgres)
```

```
$ vigil scan --json
{
  "listeners": [
    {
      "pid": 12345,
      "ports": [8000],
      "command": "uvicorn main:app --port 8000",
      "docker": null
    },
    {
      "pid": 12346,
      "ports": [3000],
      "command": "npm run dev",
      "docker": null
    },
    {
      "pid": 9921,
      "ports": [5432],
      "command": "docker-proxy",
      "docker": {
        "container_name": "myapp-postgres-1",
        "image": "postgres:16",
        "compose_service": "postgres",
        "compose_project": "myapp"
      }
    }
  ]
}
```

**Default scan scope** — in priority order:
1. Ports defined in the Vigilfile
2. Ranges configured in `vigil.toml`
3. Built-in dev defaults: 3000–3999, 4000–4999, 5000–5999, 8000–8999, 9000–9999, plus 5432, 6379, 27017

**Flags:**
- `--json` — machine-readable output
- `--port 3000` — check a specific port
- `--range 3000-4000` — scan a specific range
- `--all` — show everything in the OS socket table (full visibility, use with caution — output can be large)

---

### `vigil next`

Find the next free port from a given start. The fast path for CC when it needs to pick a port for a new service without reasoning about the landscape.

```
$ vigil next
3001

$ vigil next 8000
8002

$ vigil next 8000 --count 3
8002
8003
8004
```

```
$ vigil next --json
{"port": 3001}

$ vigil next 8000 --count 3 --json
{"ports": [8002, 8003, 8004]}
```

**Behavior:**
- Reads the OS socket table once (same call as `vigil scan`).
- Walks upward from `start` until it finds a port (or N consecutive ports) with nothing listening.
- Returns the result immediately.

**Flags:**
- `start` — positional, optional. Port to start searching from (default: 3000).
- `--count N` — find N consecutive free ports (default: 1)
- `--json`

---

### `vigil open`

Open a managed process or port in the default browser.

```
$ vigil open backend
Opening http://localhost:8000...

$ vigil open 3000
Opening http://localhost:3000...
```

**Behavior:**
- `vigil open <name>` — resolves the port from the statefile, opens `http://localhost:<port>`. If the Vigilfile defines a `url` for this process, that URL is used instead.
- `vigil open <port>` — opens `http://localhost:<port>` directly. Useful for unmanaged processes discovered via `vigil scan`.
- If the process is not alive, opens the URL anyway — the browser will handle the error.

**Flags:**
- `--json` — outputs `{"url": "http://localhost:8000"}` instead of opening a browser (useful for CC to know the URL without side effects)

---

### `vigil free <port>`

Clear whatever is on a port so it can be used. Idempotent — succeeds silently if the port is already free.

```
$ vigil free 8000
✓ Freed port 8000 (stopped backend)

$ vigil free 5432
✓ Freed port 5432 (killed PID 9921)

$ vigil free 9999
✓ Port 9999 is already free
```

**Behavior:**
- If the port belongs to a **managed process**: performs a proper `vigil stop` (SIGTERM → wait → SIGKILL, statefile cleanup, log trim).
- If the port belongs to an **unmanaged process**: sends SIGTERM, waits up to the configured grace period, then SIGKILL. No statefile involvement.
- If the port belongs to a **Docker container**: runs `docker stop <container>`.
- If nothing is on the port: succeeds immediately.

**Flags:**
- `--json` — outputs `{"port": 8000, "freed": true, "was": "managed|unmanaged|docker|free"}`

---

### `vigil start <name> "<command>"`

Start a process under vigil's management.

```
$ vigil start backend "uv run uvicorn main:app --port 8000"
✓ backend started (PID 12345)
```

**Behavior:**
- Spawns the command as a detached child process (`start_new_session=True`) so it survives vigil exiting.
- Redirects stdout/stderr to `.vigil/logs/<name>.log`.
- Records `{name, command, pid, started_at, cwd}` in the statefile.
- Returns immediately — use `vigil wait` to block until the process is actually ready.

**Error cases:**
- Name already exists and is alive → error: `"backend" is already running (PID 12345). Use --force to replace.`
- Name already exists but crashed → error: `"backend" crashed. Use --force to replace, or vigil remove backend first.`
- `--force` flag → stops existing process (if alive) and starts fresh.

**Flags:**
- `--force` — replace existing process with same name
- `--json` — output `{"name": "backend", "pid": 12345, "status": "started"}`
- `--env KEY=VAL` — set environment variables (repeatable)
- `--cwd /path` — override working directory

---

### `vigil stop <name>`

Stop a managed process and remove it from the statefile.

```
$ vigil stop backend
✓ backend stopped
```

**Behavior:**
1. Send `SIGTERM` to the process.
2. Wait up to 5 seconds for graceful shutdown.
3. If still alive, send `SIGKILL`.
4. Remove the entry from the statefile entirely.
5. Trim `.vigil/logs/<name>.log` to the last 500 lines (configurable).

**Edge cases:**
- Process already dead (crashed) → clean up statefile entry. Idempotent.
- Unknown name → error: `No managed process named "backend".`

**Flags:**
- `--json`

### `vigil stop --all`

Stop all managed processes.

```
$ vigil stop --all
✓ backend stopped
✓ frontend stopped
✓ db cleaned up (was crashed)
```

---

### `vigil restart <name>`

Stop then start a process using its recorded command.

```
$ vigil restart backend
✓ backend stopped
✓ backend started (PID 12400)
```

Trims the log file between stop and start.

---

### `vigil remove <name>`

Remove a crashed process entry from the statefile. If the process is alive, error unless `--force`.

```
$ vigil remove db
✓ Removed "db" from registry
```

**Flags:**
- `--force` — remove even if the process is alive (does not stop it)
- `--json`

---

### `vigil logs <name>`

View captured output from a managed process.

```
$ vigil logs backend
[2025-03-27 10:15:01] INFO:     Uvicorn running on http://0.0.0.0:8000
[2025-03-27 10:15:01] INFO:     Started reloader process [12345]
...
```

**Flags:**
- `--tail N` — last N lines (default: 50)
- `--follow` — live tail, like `tail -f`
- `--json` — output as `{"lines": ["...", "..."]}`

**Log storage:**
- Each managed process logs to `.vigil/logs/<name>.log`.
- Files grow freely while the process runs.
- Trimmed to the last 500 lines (configurable) when the process is stopped or restarted.

---

### `vigil health`

HTTP health check on all managed processes. Checks every alive process that has a known port.

```
$ vigil health
  backend   :8000  ● healthy  HTTP 200 (45ms)
  frontend  :3000  ● healthy  HTTP 200 (12ms)
  db        :5432  ✖ unhealthy  connection refused
```

```
$ vigil health --json
{
  "processes": [
    {"name": "backend", "port": 8000, "healthy": true, "status": 200, "latency_ms": 45},
    {"name": "frontend", "port": 3000, "healthy": true, "status": 200, "latency_ms": 12},
    {"name": "db", "port": 5432, "healthy": false, "error": "connection refused"}
  ]
}
```

**Behavior:**
- Finds each process's port(s) from live inspection.
- Sends `GET /` (or configured health endpoint) and reports any HTTP response as healthy.
- If the HTTP request fails (connection refused, non-HTTP protocol), falls back to a TCP connect check. This makes postgres, redis, and similar non-HTTP processes report correctly.

**Flags:**
- `--json`
- `--endpoint /health` — custom health check path
- `--timeout 5` — seconds to wait for response

---

### `vigil wait <name>`

Block until a managed process is listening on a port. Critical for CC workflows where `vigil start` returns immediately but the server needs time to boot.

```
$ vigil start backend "uv run uvicorn main:app --port 8000"
✓ backend started (PID 12345)

$ vigil wait backend --timeout 15
✓ backend is listening on :8000 (took 2.3s)

$ vigil wait backend --http=/health --timeout 15
✓ backend is responding on :8000/health (took 3.1s)
```

**Behavior:**
- Polls every 0.5s checking if the process's PID has any listening ports.
- On each poll: check PID alive first (exit code 2 if dead), then check port.
- If `--port` is specified, waits for that specific port.
- If `--http` or `--http=<path>` is specified, also waits for any HTTP response before returning ready. Path defaults to `/` when `--http` is given without a value.

**Exit codes:**
- 0 — process is ready
- 1 — timeout reached, process never became ready
- 2 — process died while waiting

**Flags:**
- `--timeout N` — max seconds to wait (default: 30)
- `--port N` — wait for a specific port
- `--http[=/path]` — also require any HTTP response before returning ready; path defaults to `/`
- `--json`

---

### `vigil up`

Start all processes defined in the Vigilfile. Best-effort — continues even if individual processes fail.

```
$ vigil up
✓ db started (PID 9000)
  Waiting for :5432... ready (1.2s)
✓ backend started (PID 9001)
  Waiting for :8000... ready (2.1s)
✗ frontend failed to start
  Run vigil logs frontend to diagnose.

2 running, 1 failed.
```

**Behavior:**
- Reads the Vigilfile, starts processes in `order` sequence.
- For each process: start it, then if `port` is defined, wait for it before proceeding to the next.
- If a process fails or times out, logs the failure and continues with remaining processes.
- Skips processes that are already alive (idempotent).

**Flags:**
- `--json`
- `--force` — restart everything even if already running
- `--only name1,name2` — start only specific processes

---

### `vigil down`

Stop all processes defined in the Vigilfile in reverse startup order, sequentially.

```
$ vigil down
✓ frontend stopped
✓ backend stopped
✓ db stopped

All processes stopped.
```

**Flags:**
- `--json`
- `--only name1,name2` — stop only specific processes

---

## Vigilfile

A TOML file that declaratively defines all processes for a project. Lives in the project root.

```toml
# Vigilfile

[[process]]
name = "db"
command = "docker compose up postgres"
port = 5432
wait_timeout = 30
order = 1

[[process]]
name = "backend"
command = "uv run uvicorn main:app --port 8000"
port = 8000
wait_timeout = 15
order = 2
env = { DATABASE_URL = "postgresql://localhost:5432/mydb" }

[[process]]
name = "frontend"
command = "npm run dev"
port = 3000
wait_timeout = 10
order = 3
cwd = "./frontend"

[[process]]
name = "docs"
command = "mkdocs serve --dev-addr 0.0.0.0:4000"
port = 4000
url = "http://localhost:4000/my-project/"   # overrides vigil open default
order = 4
```

**Fields:**
- `command` (required) — the shell command to run
- `port` (optional) — expected port; used by `vigil up` for wait-for-ready logic
- `wait_timeout` (optional) — override default wait timeout for this process (seconds)
- `order` (optional) — startup order; lower numbers start first; unordered processes start after ordered ones
- `env` (optional) — environment variables as key-value pairs
- `cwd` (optional) — working directory relative to Vigilfile location
- `url` (optional) — override the URL used by `vigil open` (default: `http://localhost:<port>`)
- `health_endpoint` (optional) — path for HTTP health checks (default: `/`)

---

## Configuration

`vigil.toml` — optional config file. Located at `.vigil/vigil.toml` in the project.

```toml
[defaults]
log_retention_lines = 500   # lines to keep when trimming on stop/restart
health_check_timeout = 5    # HTTP/TCP health check timeout (seconds)
stop_grace_period = 5       # seconds between SIGTERM and SIGKILL
```

All values have sensible defaults. The config file is entirely optional.

---

## Exit Codes

Consistent across all commands:

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (process not found, command failed, timeout, etc.) |
| 2 | Partial success (`vigil up` with some failures; `vigil wait` process died) |

In `--json` mode, errors are returned as JSON objects on stdout, never as stderr text:
```json
{"error": "No managed process named \"backend\"", "code": 1}
```

---

## Cross-Platform Support

Vigil supports both Linux and macOS. The `psutil` library handles OS-specific differences for:
- Listing listening ports per PID
- Finding which PID owns a port
- Reading process command lines
- Checking if a PID is alive
- Reading process start times
- Sending signals to processes

No platform-specific code paths needed in the main logic.

---

## Project Structure

```
vigil/
├── pyproject.toml           # Package config, entry point, dependencies
├── src/
│   └── vigil/
│       ├── __init__.py      # Version
│       ├── cli.py           # Click CLI entry point and command definitions
│       ├── manager.py       # Process start/stop/restart logic
│       ├── scanner.py       # Port scanning and process discovery
│       ├── docker.py        # Docker enrichment (cross-cutting, lazy)
│       ├── state.py         # Statefile read/write (atomic)
│       ├── logs.py          # Log capture and trimming
│       ├── health.py        # HTTP health checks
│       ├── wait.py          # Wait-for-ready polling
│       ├── vigilfile.py     # Vigilfile parsing and up/down orchestration
│       └── config.py        # Configuration loading and defaults
├── tests/
│   ├── test_manager.py
│   ├── test_scanner.py
│   ├── test_docker.py
│   ├── test_state.py
│   └── ...
├── CLAUDE.md                # CC integration instructions
├── README.md
└── LICENSE
```

**Shell completions** are provided via `click`'s built-in completion mechanism. Process names are completed from the statefile for commands that accept a `<name>` argument (`stop`, `restart`, `logs`, `open`, `wait`, `health`).

## Dependencies

- **click** — CLI framework
- **psutil** — cross-platform process and port inspection
- **httpx** — HTTP health checks
- **tomli** — TOML parsing (Python <3.11 compat; stdlib tomllib in 3.11+)

## Installation

```bash
# From PyPI (once published)
uv tool install vigil

# From git
uv tool install git+https://github.com/<user>/vigil

# For development
git clone https://github.com/<user>/vigil
cd vigil
uv sync
```

The `pyproject.toml` defines a `[project.scripts]` entry point:
```toml
[project.scripts]
vigil = "vigil.cli:main"
```

---

## Claude Code Integration

### CLAUDE.md Snippet

Drop this into any project's `CLAUDE.md` to teach CC how to use vigil:

```markdown
## Local Dev Process Management — Vigil

Use `vigil` to manage local dev processes. ALWAYS use vigil instead of raw
shell commands for starting, stopping, or inspecting services.

### Quick Reference

- Check what's running: `vigil status --json`
- Start a service: `vigil start <name> "<command>" --json`
- Stop a service: `vigil stop <name> --json`
- Stop everything: `vigil stop --all --json`
- Restart a service: `vigil restart <name> --json`
- Full OS landscape: `vigil scan --json`
- Find a free port: `vigil next [start] --json`
- Free a blocked port: `vigil free <port> --json`
- Open a service in browser: `vigil open <name|port>`
- View logs: `vigil logs <name> --tail 100`
- Wait for ready: `vigil wait <name> --timeout 15 --json`
- Health check: `vigil health --json`
- Start full stack: `vigil up --json`
- Stop full stack: `vigil down --json`

### Rules

1. ALWAYS use `--json` flag so you can parse the output.
2. ALWAYS run `vigil status --json` before starting services to avoid conflicts.
3. ALWAYS use `vigil wait <name>` after `vigil start` before making requests.
4. If a Vigilfile exists, prefer `vigil up` / `vigil down` over individual commands.
5. Check `vigil logs <name> --tail 50` when a process fails or behaves unexpectedly.
6. Use `vigil next --json` to pick a port for a new service — never guess or hardcode.
7. If a port is blocked, use `vigil free <port> --json` to clear it before starting.
8. Use `vigil scan --json` only when the situation is unclear and a full landscape view is needed.
9. Run `vigil health --json` as a pulse check before running tests or making requests.
```

### CC Workflow Examples

**Starting the full stack with Vigilfile:**
```bash
vigil up --json
```

**Starting services individually:**
```bash
vigil start db "docker compose up postgres" --json
vigil wait db --port 5432 --timeout 30
vigil start backend "uv run uvicorn main:app --port 8000" --json
vigil wait backend --port 8000 --timeout 15
vigil start frontend "npm run dev" --json
vigil wait frontend --port 3000 --timeout 10
```

**Picking a port for a new service:**
```bash
vigil next 8000 --json
# {"port": 8002}
vigil start myservice "..." --json
vigil wait myservice --port 8002 --timeout 15
```

**Clearing a blocked port before starting:**
```bash
vigil free 8000 --json
vigil start backend "uv run uvicorn main:app --port 8000" --json
vigil wait backend --timeout 15
```

**Checking before running tests:**
```bash
vigil health --json
# Parse JSON to verify all required services are healthy
```

**Debugging a failure:**
```bash
vigil status --json          # See what crashed
vigil logs backend --tail 100  # Check what happened
vigil restart backend --json   # Try again
vigil wait backend --timeout 15
```

**Reorienting after confusion:**
```bash
vigil scan --json            # Full OS landscape — what is actually running?
# Docker containers, native processes, ports — all in one view
```

**Setting up a new project:**
```bash
vigil init \
  --process backend,"uv run uvicorn main:app --port 8000",8000 \
  --process frontend,"npm run dev",3000 \
  --json
vigil up --json
```

---

## .gitignore

Projects using vigil should add:

```gitignore
# Vigil process manager
.vigil/state.json
.vigil/logs/
```

The `Vigilfile` and `vigil.toml` should be committed.
