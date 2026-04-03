# Vigil — Design Specification v2

> Decisions already made for v2, to be built after v1 ships.

---

## PID Verification — Cryptographic Token

**Decision:** Inject a cryptographic token at spawn time and verify it to achieve near-certain process identity.

**Implementation:**
- At spawn time, generate a token using `os.urandom()` (cryptographically secure system randomness)
- Store the token in the statefile alongside the PID
- Inject it into the child process environment as `VIGIL_ID=<token>`
- To verify: read `/proc/<pid>/environ`, check that `VIGIL_ID` matches the stored token

A recycled PID will almost certainly not carry the same token, making false positives astronomically unlikely.

**Edge case:** Some processes scrub their environment variables (certain setuid binaries, hardened containers). If `VIGIL_ID` is missing or unreadable, do not treat this as proof of the wrong process — treat it as inconclusive and fall back to start-time verification only.

**V1 fallback (already in use):** PID alive + start time check.

---

## `vigil init` — Auto-Detection of Project Stack

**Decision:** `vigil init` should inspect the project directory and propose a Vigilfile based on what it finds.

**Detection targets (non-exhaustive):**
- `package.json` → Node/npm process
- `pyproject.toml` / `uv.lock` → Python/uv process
- `docker-compose.yml` / `compose.yaml` → Docker Compose services
- `Cargo.toml` → Rust/cargo process
- `go.mod` → Go process

**Modes:**
```bash
vigil init                 # Human: auto-detect + interactive review of proposals
vigil init --json          # CC: auto-detect, output proposals as JSON (dry run, no writes)
vigil init --accept        # CC: auto-detect + accept all proposals, write Vigilfile
```

**CC dry-run output example:**
```json
{
  "proposed": [
    {"name": "backend", "command": "uv run uvicorn main:app --port 8000", "port": 8000},
    {"name": "frontend", "command": "npm run dev", "port": 3000}
  ]
}
```

CC can inspect the proposals, adjust if needed, then call `vigil init --accept` or write the Vigilfile directly.

---

## Process Readiness — `ready` Field in Vigilfile

**Decision:** Each process in the Vigilfile can declare how it signals readiness, replacing the one-size-fits-all port-open check used in v1.

**Supported strategies:**

**HTTP check:**
```toml
[processes.backend]
command = "uv run uvicorn main:app --port 8000"
port = 8000
ready = "http"   # wait for any HTTP response on the port
```

**Custom shell command:**
```toml
[processes.db]
command = "docker compose up postgres"
port = 5432
ready = "pg_isready -p 5432"   # exits 0 when ready
```

**Log pattern match:**
```toml
[processes.frontend]
command = "npm run dev"
port = 3000
ready = "log:Ready on"   # wait until this string appears in the log
```

**Motivation:** Web servers (Next.js, uvicorn) bind the port before they finish compiling or loading. Waiting for a port to open is not a reliable signal for slow-booting servers. Each process type knows best how to signal its own readiness.

**V1 fallback (already in use):** Port open by default, `--http[=/path]` flag for opt-in HTTP check on `vigil wait`.

---

## `vigil graph` — Runtime Dependency Topology

**Decision:** Inspect live TCP connections between processes to show which services are actually talking to each other at runtime.

**Implementation:**
- Read established TCP connections from the OS (`/proc/net/tcp` on Linux, `netstat`/`lsof` on macOS)
- Cross-reference both endpoints against the port→PID map from `vigil scan`
- Cross-reference PIDs against the statefile to resolve named managed processes
- Build a directed graph: source process → destination process

**Output formats:**
```bash
vigil graph              # human-readable ASCII
vigil graph --json       # structured edge list
vigil graph --dot        # Graphviz DOT format for rendering
```

**ASCII example:**
```
$ vigil graph
  backend  ──→  db       :5432
  backend  ──→  redis    :6379
  frontend ──→  backend  :8000
```

**JSON example:**
```json
{
  "edges": [
    {"from": "backend", "from_port": null, "to": "db", "to_port": 5432},
    {"from": "backend", "from_port": null, "to": "redis", "to_port": 6379},
    {"from": "frontend", "from_port": null, "to": "backend", "to_port": 8000}
  ]
}
```

**Named vs unnamed nodes:** Managed processes (in statefile) are shown by name. Unmanaged processes are shown as `pid:<N>` or, if Docker-enriched, by container name.

**Schema forward-compatibility note:** `vigil graph` is designed to work against v1's existing `vigil scan` and `vigil status` JSON output schemas. No changes to those commands are required in v2 to support graph.

---

## Process Stats — `vigil status --stats`

**Decision:** Add a `--stats` flag to `vigil status` that enriches managed process output with live resource usage.

**Additional fields per process:**
- `cpu_percent` — CPU usage over the last interval
- `mem_mb` — resident memory in megabytes
- `threads` — thread count
- `uptime_s` — seconds since the process started

**Implementation:** `psutil` already provides all of these at zero additional dependency cost. Stats are only fetched when `--stats` is requested — normal `vigil status` calls are unaffected.

**Human output:**
```
$ vigil status --stats
  backend   ● alive  PID 12345  :8000   CPU 1.2%  MEM 142MB  threads 4  uptime 3h12m
  frontend  ● alive  PID 12346  :3000   CPU 0.3%  MEM  88MB  threads 2  uptime 3h11m
```

**JSON:**
```json
{
  "managed": [
    {
      "name": "backend",
      "pid": 12345,
      "alive": true,
      "ports": [8000],
      "stats": {"cpu_percent": 1.2, "mem_mb": 142, "threads": 4, "uptime_s": 11520}
    }
  ]
}
```

When `--stats` is not passed, the `stats` key is absent from JSON output entirely.

---

## Future Considerations

These are not yet decided — open for a future design session:

- **`vigil attach <name>`** — attach to a running process's stdio (interactive)
- **`vigil groups`** — named groups of processes to start/stop together
- **File watching** — auto-restart on file changes (overlaps with tools that already do this)
- **MCP server** — expose vigil as an MCP tool server so CC can call it natively without shell commands
- **Web UI** — browser dashboard showing all processes and logs
- **Remote scanning** — inspect ports on a remote host over SSH
