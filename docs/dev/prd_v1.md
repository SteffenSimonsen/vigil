# PRD: Vigil v1 — CLI Process Manager for Local Development

## Problem Statement

When Claude Code (CC) runs local development commands (`uv run`, `npm run dev`, `docker compose up`), it loses track of them. Processes become orphaned in the background, CC has no reliable way to know what is running on which port, and there is no structured way to check status, restart services, or tear things down. The result is port conflicts, mystery background processes, and constant manual detective work — both for CC and for the human developer. There is no single source of truth for local dev process state.

When CC needs to start a new service, it has no fast way to find a free port without reasoning through a scan manually. When a port is blocked by something unexpected, there is no single command to clear it. When CC loses its mental model of what is running, there is no escape hatch that gives it the full picture in one call.

---

## Solution

**Vigil** is a lightweight CLI tool that acts as a single source of truth for local development processes. It starts, stops, and monitors named processes, captures their logs, scans ports, and reports status in both human-readable and machine-readable (JSON) formats.

Vigil has no daemon. Each CLI call inspects live system state (PIDs, ports) and reconciles it against a statefile of managed processes. This means zero setup, no background process to babysit, and output that always reflects reality.

Vigil automatically enriches all port and process data with Docker container metadata — container name, image, and Compose service/project — wherever it is available. This enrichment is a cross-cutting capability available to all commands, not a feature of any single one.

Vigil is designed for two consumers equally: **humans** who want visibility into their dev stack, and **Claude Code** which needs structured, parseable output to reason about and manage services autonomously.

---

## User Stories

### Setup

1. As a developer, I want to run `vigil init` so that I can set up vigil for my project interactively without reading documentation.
2. As a developer, I want `vigil init` to prompt me for each process name, command, and port so that I can define my stack conversationally.
3. As Claude Code, I want to run `vigil init --process name,"command",port` so that I can set up a project non-interactively using flags.
4. As Claude Code, I want `vigil init` to output `--json` so that I can confirm the project was initialized successfully.
5. As a developer, I want vigil to find `.vigil/` by walking up the directory tree so that I can run vigil commands from any subdirectory of my project.
6. As a developer, I want a clear error message when running vigil outside an initialized project so that I know to run `vigil init` first.
7. As a developer, I want the `Vigilfile` and `vigil.toml` to be committed to git and `.vigil/state.json` and `.vigil/logs/` to be gitignored so that project configuration is shared but runtime state is not.

### Starting Processes

8. As a developer, I want to run `vigil start backend "uv run uvicorn main:app"` so that vigil manages the process and captures its logs.
9. As Claude Code, I want `vigil start` to return `--json` with the PID so that I can confirm the process started and record its identity.
10. As a developer, I want started processes to be detached so that they survive vigil exiting.
11. As a developer, I want `vigil start` to error if a process with that name is already alive so that I don't accidentally launch duplicates.
12. As a developer, I want `vigil start --force` to stop an existing process and start a fresh one so that I can replace it in one command.
13. As Claude Code, I want to pass `--env KEY=VAL` to `vigil start` so that I can inject environment variables without modifying shell state.
14. As a developer, I want to pass `--cwd /path` to `vigil start` so that I can run a process from a specific directory.

### Checking Status

15. As a developer, I want to run `vigil status` so that I can see at a glance which managed processes are alive and which have crashed.
16. As Claude Code, I want `vigil status --json` so that I can parse the state of all managed processes programmatically.
17. As a developer, I want crashed processes to appear in `vigil status` as a warning so that I know something died unexpectedly.
18. As a developer, I want intentionally stopped processes to disappear from `vigil status` so that the output is not cluttered with stale entries.
19. As a developer, I want `vigil status` to show the PID, port, and command for each alive process so that I have full context at a glance.

### Stopping Processes

20. As a developer, I want to run `vigil stop backend` so that the process is gracefully terminated and removed from the statefile.
21. As Claude Code, I want `vigil stop --json` so that I can confirm the process was stopped.
22. As a developer, I want vigil to send SIGTERM first and wait up to 5 seconds before sending SIGKILL so that processes have a chance to clean up.
23. As a developer, I want `vigil stop` on an already-dead process to succeed silently so that the command is idempotent.
24. As a developer, I want `vigil stop --all` to stop all managed processes so that I can tear down my entire stack in one command.
25. As a developer, I want stopped processes to have their logs trimmed to the last 500 lines so that log files don't grow unbounded over time.

### Restarting Processes

26. As a developer, I want to run `vigil restart backend` so that the process is stopped and restarted with its original recorded command.
27. As Claude Code, I want `vigil restart --json` so that I can confirm the new PID after restart.

### Waiting for Readiness

28. As Claude Code, I want to run `vigil wait backend` after `vigil start` so that I can block until the process is listening on a port before making requests.
29. As Claude Code, I want `vigil wait` to exit with code 2 if the process dies while waiting so that I can detect startup failures immediately.
30. As Claude Code, I want `vigil wait` to exit with code 1 if the timeout is reached so that I don't wait forever.
31. As a developer, I want to pass `--timeout N` to `vigil wait` so that I can control how long to wait for slow-booting servers.
32. As Claude Code, I want `vigil wait --http` so that I can wait until the process is actually responding to HTTP requests, not just holding a port open.
33. As Claude Code, I want `vigil wait --http=/health` so that I can wait until the process responds on a specific health endpoint rather than the root path.
34. As Claude Code, I want `vigil wait --port N` so that I can wait for a specific port when a process uses multiple ports.

### Viewing Logs

35. As Claude Code, I want to run `vigil logs backend --tail 100` so that I can read recent output and diagnose failures.
36. As a developer, I want `vigil logs --follow` so that I can stream live output from a running process.
37. As Claude Code, I want `vigil logs --json` so that I can receive log lines as a structured array.
38. As a developer, I want log files to be trimmed to the last 500 lines when a process is stopped or restarted so that disk usage stays reasonable.
39. As a developer, I want each process to have its own log file so that output is not mixed together.

### Health Checks

40. As Claude Code, I want to run `vigil health --json` so that I can get a pulse check on all managed processes in one command.
41. As Claude Code, I want health output to include HTTP status and latency so that I can detect degraded services, not just dead ones.
42. As Claude Code, I want unhealthy processes in `vigil health` output to be clearly flagged so that I know to investigate with `vigil logs`.
43. As a developer, I want `vigil health --endpoint /health` so that I can specify a custom health check path per invocation.
44. As a developer, I want `vigil health --timeout N` so that I can control how long to wait for a response.

### Scanning Ports

45. As Claude Code, I want to run `vigil scan --json` so that I can get a full OS landscape snapshot when I need to reorient and understand what is actually running on the machine.
46. As a developer, I want `vigil scan` to default to common dev port ranges so that the output is focused and relevant.
47. As a developer, I want `vigil scan --port 3000` so that I can check what is using a specific port.
48. As a developer, I want `vigil scan --range 3000-4000` so that I can inspect a specific port range.
49. As a developer, I want `vigil scan --all` so that I can see the full OS socket table when I need complete visibility.
50. As Claude Code, I want `vigil scan --json` to include Docker container metadata for container-backed ports so that I can immediately identify what a port belongs to without additional lookups.
51. As a developer, I want Docker container name, image, and Compose service to appear in `vigil scan` output so that containerized ports are as identifiable as native ones.
52. As a developer, I want Docker enrichment in `vigil scan` to be silently skipped when Docker is not available so that native-only workflows are unaffected.

### Finding Free Ports

53. As Claude Code, I want to run `vigil next` so that I can get the next free port from 3000 without scanning and reasoning manually.
54. As Claude Code, I want `vigil next 8000` so that I can find the next free port starting from a specific number when allocating ports in a particular range.
55. As Claude Code, I want `vigil next --count 3` so that I can allocate multiple consecutive free ports at once for services that need them.
56. As Claude Code, I want `vigil next --json` to return the port as structured data so that I can use it directly in scripted start workflows.

### Freeing Ports

57. As Claude Code, I want to run `vigil free 8000` so that I can clear whatever is blocking a port before starting a new service there, without investigating the blocker manually.
58. As Claude Code, I want `vigil free` to handle managed processes, unmanaged native processes, and Docker containers uniformly so that I use one command regardless of what is on the port.
59. As Claude Code, I want `vigil free` on an already-free port to succeed silently so that the command is safe to use as a precaution.
60. As a developer, I want `vigil free` to use SIGTERM → wait → SIGKILL for unmanaged processes so that services have a chance to clean up even when vigil did not start them.
61. As Claude Code, I want `vigil free --json` to return what was freed so that I can confirm the port is now available before proceeding.

### Opening Services

62. As a developer, I want to run `vigil open backend` so that the service opens in my browser without me remembering the port number.
63. As a developer, I want `vigil open 3000` so that I can open any port in my browser including ports belonging to unmanaged processes.
64. As a developer, I want to define a `url` field in the Vigilfile so that services with custom paths or HTTPS open correctly when I run `vigil open`.
65. As Claude Code, I want `vigil open --json` to return the URL without opening a browser so that I can use the URL in subsequent requests without side effects.

### Vigilfile Orchestration

66. As a developer, I want to define all my processes in a `Vigilfile` so that my dev stack is declarative and reproducible.
67. As a developer, I want `vigil up` to start all Vigilfile processes in order so that dependencies start before the services that need them.
68. As a developer, I want `vigil up` to wait for each process's port before starting the next so that services don't start before their dependencies are ready.
69. As a developer, I want `vigil up` to skip already-running processes so that the command is idempotent.
70. As a developer, I want `vigil up` to continue if one process fails so that I get the rest of my stack running and can fix the failure independently.
71. As a developer, I want `vigil up` to clearly report which processes failed so that I know what to investigate.
72. As a developer, I want `vigil down` to stop all Vigilfile processes in reverse startup order so that dependencies are shut down cleanly.
73. As a developer, I want `vigil down` to stop processes sequentially so that each process shuts down completely before the next.
74. As a developer, I want `vigil up --only name1,name2` so that I can start a subset of my stack.
75. As a developer, I want `vigil down --only name1,name2` so that I can stop a subset of my stack.
76. As a developer, I want `vigil up --force` so that I can restart everything even if it is already running.

### Removing Entries

77. As a developer, I want to run `vigil remove db` so that I can clean up a crashed process entry from the statefile.
78. As a developer, I want `vigil remove` to error if the process is alive so that I don't accidentally orphan a running process.
79. As a developer, I want `vigil remove --force` so that I can remove a running process from the registry without stopping it.

### Shell Completions

80. As a developer, I want process names to tab-complete in `vigil stop`, `vigil restart`, `vigil logs`, `vigil open`, and `vigil wait` so that I can work faster without memorizing names.

### Configuration

81. As a developer, I want to configure log retention, scan ranges, health check timeouts, and stop grace periods in `vigil.toml` so that I can tune vigil's behavior per project.
82. As a developer, I want all `vigil.toml` values to have sensible defaults so that the config file is entirely optional.

### JSON and Exit Codes

83. As Claude Code, I want every vigil command to support `--json` so that I can parse all output programmatically.
84. As Claude Code, I want errors in `--json` mode to be returned as JSON on stdout so that I never need to parse stderr.
85. As Claude Code, I want consistent exit codes across all commands (0 success, 1 error, 2 partial) so that I can branch on outcomes reliably.

---

## Implementation Decisions

### Architecture

- **No daemon.** Vigil is a pure CLI tool. Each invocation reads live system state and reconciles with the statefile. No background process is ever required.
- **Project-scoped only.** There is no global mode. A `.vigil/` directory must exist (created by `vigil init`). Vigil walks up the directory tree to find it, git-style. Commands run outside an initialized project exit with a clear error.
- **Atomic statefile writes.** The statefile is written by writing to a temp file then renaming it, preventing corruption on interrupted writes.

### Modules

**`state`** — Statefile read/write. Owns all serialization and deserialization of process records. Validates PID liveness and start time on every read. Interface: read all records, write a record, delete a record, update a record. All other modules go through `state` to access managed process data.

**`scanner`** — Port and process inspection. Wraps `psutil` to answer: "what ports does this PID own?" and "what processes are listening on these ports?" Stateless, no statefile involvement. Reads the OS socket table in one syscall — not port-by-port scanning.

**`docker`** — Docker enrichment. Cross-cutting module that sits below all commands. Given a list of port/PID records from `scanner`, enriches any entry whose PID belongs to a Docker container with: `container_name`, `image`, `compose_service`, `compose_project`. Shells out to `docker ps --format json` once per invocation. Silently no-ops if Docker is not available. Enrichment is exposed as a nested `docker` object on port records — `null` for non-container processes. No other module is responsible for Docker awareness.

**`manager`** — Process lifecycle. Handles spawning (detached, log-redirected), stopping (SIGTERM → wait → SIGKILL), and restarting. Delegates statefile updates to `state` and log trimming to `logs`. Used by `vigil free` for managed-process teardown.

**`logs`** — Log file management. Handles writing (via file descriptor set at spawn), reading with tail/follow, and trimming to the last N lines. Trim is triggered by `manager` on stop/restart.

**`wait`** — Readiness polling. Polls at a configurable interval. On each tick: check PID alive (exit 2 if dead), check port open, optionally check HTTP response on a configurable path. The `--http[=/path]` flag collapses port-open and HTTP-response checks into a single flag — path defaults to `/` when no path is given. Clean exit codes.

**`health`** — Fleet health checks. Iterates all alive managed processes, delegates port lookup to `scanner` and HTTP requests to `httpx`. Returns structured results.

**`vigilfile`** — Vigilfile parsing and orchestration. Parses TOML, drives `vigil up` (ordered start + wait per process) and `vigil down` (reverse sequential stop). Best-effort — collects failures and reports them without aborting.

**`config`** — Configuration loading. Loads `vigil.toml` with hardcoded defaults. Injected into all modules that need configurable values.

**`init`** — Project initialization. Interactive TUI flow (human) and flag-driven flow (CC). Writes `.vigil/` directory and `Vigilfile`.

**`cli`** — Click entry point. Thin command definitions only. No business logic — delegates entirely to the modules above. Shell completions are registered via `click`'s built-in completion mechanism; process names are completed from the statefile for all commands that accept a `<name>` argument.

### New Commands

**`vigil next [start] [--count N]`** — Implemented in `cli` using a single `scanner` call. Walks upward from `start` (default 3000) until it finds a free port or N consecutive free ports. Returns immediately.

**`vigil open <name|port>`** — Implemented in `cli`. Resolves port from statefile (by name) or uses the argument directly (by port number). Opens `http://localhost:<port>` unless the Vigilfile defines a `url` override for the process. `--json` returns the URL without opening a browser.

**`vigil free <port>`** — Implemented in `cli` and `manager`. Looks up what is on the port using `scanner` + `docker`. Dispatches to: `manager.stop()` if managed, `docker stop <container>` if Docker, direct SIGTERM → SIGKILL if unmanaged. Idempotent — succeeds silently if port is already free.

### PID Verification

Vigil verifies a recorded PID by checking two things:
1. Is the PID still alive?
2. Was the process started at or after the recorded `started_at` timestamp?

Command string matching is explicitly avoided — launchers like `uv run` exec into child processes whose command line will not match the original command.

### Process Lifecycle in Statefile

- **Alive:** PID running, start time matches.
- **Crashed:** PID gone, but vigil did not stop it — entry remains in statefile, shown in `vigil status` as crashed.
- **Stopped:** Vigil stopped it intentionally — entry removed from statefile, never shown in status again.

### Docker Enrichment Schema

All commands that return port or process data expose enrichment as a nested `docker` object:

```
{
  "port": 5432,
  "pid": 9921,
  "command": "docker-proxy",
  "docker": {
    "container_name": "myapp-postgres-1",
    "image": "postgres:16",
    "compose_service": "postgres",
    "compose_project": "myapp"
  }
}
```

Non-container processes carry `"docker": null`. This schema is designed to remain stable through v2, including when `vigil graph` is added.

### `vigil scan` Purpose

`vigil scan` is the CC escape hatch — a full OS landscape snapshot for reorienting when the mental model is lost. It is not a dashboard (that is `vigil status`) and not a port picker (that is `vigil next`). Its default scope is dev-range ports; `--all` exposes the full OS socket table.

### Log Trimming

Log files grow freely while a process runs. On `vigil stop` or `vigil restart`, the log file is trimmed to the last N lines (default 500, configurable in `vigil.toml`). `vigil logs --tail N` reads the last N lines without loading the entire file.

### `vigil health`

Checks all managed alive processes. Any HTTP response (not strictly 2xx) counts as healthy — the server is up and responding. Non-HTTP processes report TCP connection success/failure.

### `vigil wait` Readiness

Default: waits for port open. `--http` flag (no path): waits for any HTTP response on `/`. `--http=/path`: waits for any HTTP response on the given path. Polls every 0.5s (configurable). Checks PID liveness on every poll tick.

### `vigil up` Failure Behavior

Best-effort. If a process fails to start or times out, vigil logs the failure, leaves already-started processes running, and continues with remaining processes. Reports a summary at the end.

### `vigil down` Order

Sequential, in reverse Vigilfile startup order. Each process receives SIGTERM, waits up to the configured grace period, then SIGKILL if needed — before moving to the next.

### Vigilfile `url` Field

Each process in the Vigilfile may optionally declare a `url` field. This overrides the default `http://localhost:<port>` used by `vigil open`. Intended for services with HTTPS, non-root base paths, or other non-standard URL shapes.

### Output

All commands support `--json`. In JSON mode, errors are returned as `{"error": "...", "code": N}` on stdout — never on stderr. Exit codes are consistent: 0 success, 1 error, 2 partial/timeout.

### Dependencies

- `click` — CLI framework and shell completion
- `psutil` — cross-platform process and port inspection
- `httpx` — HTTP health checks
- `tomli` — TOML parsing (stdlib `tomllib` on Python 3.11+)

---

## Testing Decisions

### What makes a good test

Tests should verify external behavior — what a module returns or what side effects it produces — not how it is implemented internally. Tests should not mock the modules being tested; they should mock only at system boundaries (OS calls, file system, network). A test that passes when the implementation is broken is worse than no test.

### Modules to test

**`state`** — Test read/write/delete/update of statefile entries. Test atomic write behavior. Test PID validation logic (alive + start time check) with mocked psutil responses. Test that a PID with a mismatched start time is correctly identified as dead.

**`scanner`** — Test port-to-PID mapping and PID-to-port mapping with mocked psutil responses. Test filtering behavior (Vigilfile ports, dev ranges, --all). Test that the OS socket table is read once, not per-port.

**`docker`** — Test enrichment of port records when `docker ps` returns container data. Test that the correct container is matched to the correct PID. Test silent no-op when `docker` is not in PATH. Test that `compose_service` and `compose_project` are read from container labels. Test that enrichment runs once per invocation, not once per port record.

**`manager`** — Test the full start/stop/restart lifecycle against real processes (spawn a simple sleep or echo process). Test SIGTERM → wait → SIGKILL escalation. Test that a stopped process is removed from the statefile. Test that a crashed process remains in the statefile as crashed.

**`wait`** — Test exit code 0 when port opens within timeout. Test exit code 1 when timeout is reached. Test exit code 2 when PID dies while polling. Test `--http` mode with a mock HTTP server. Test `--http=/path` with a mock HTTP server that responds on the specified path.

**`vigilfile`** — Test parsing of valid and invalid Vigilfile TOML. Test `vigil up` ordering. Test `vigil up` best-effort behavior (one process fails, others continue). Test `vigil down` reverse order.

### Prior art

No existing tests in the repository yet — this is a greenfield project. Tests should be written using `pytest`. Integration tests for `manager` should spawn real subprocesses (e.g. `python -m http.server`) rather than mocking process creation.

---

## Out of Scope

The following are explicitly out of scope for v1:

- **Global mode** (`~/.vigil/`) — vigil is a project tool, init is required
- **Auto-detection of project stack** in `vigil init` — reserved for v2
- **Cryptographic PID verification** (`VIGIL_ID` env token) — reserved for v2
- **Vigilfile `ready` field** (custom readiness strategies per process) — reserved for v2
- **`vigil graph`** — runtime TCP dependency topology — reserved for v2
- **Process stats** (CPU, memory, threads, uptime) — reserved for v2
- **`vigil attach`** — interactive stdio attachment
- **`vigil groups`** — named process groups
- **File watching** — auto-restart on file changes
- **Crash notifications** — incompatible with no-daemon design
- **MCP server** — native tool server for Claude Code
- **Web UI** — browser dashboard
- **Windows support** — Linux and macOS only
- **Remote scanning** — inspecting ports on a remote host over SSH

---

## Further Notes

- The `Vigilfile` and `vigil.toml` should be committed to git. `.vigil/state.json` and `.vigil/logs/` should be gitignored.
- The CLAUDE.md snippet in the spec defines the rules CC should follow when using vigil. This should ship as part of the repo so any project can drop it in.
- The primary design constraint throughout is **CC token budget** — vigil's JSON output should be tight and relevant by default. `--all` flags exist for when full visibility is needed but should never be the default.
- The `docker` module is a cross-cutting concern, not a feature of `vigil scan` specifically. Any command that surfaces process or port data benefits from Docker enrichment automatically.
- `vigil scan`, `vigil status`, and `vigil next` serve three distinct and non-overlapping purposes: full landscape (scan), managed process dashboard (status), and fast free-port allocation (next). These boundaries should be preserved.
- v2 decisions (cryptographic PID verification, stack auto-detection, Vigilfile `ready` field, `vigil graph`, process stats) are fully designed and documented in `spec_v2.md`. The v1 JSON output schemas for `vigil scan` and `vigil status` are intentionally designed to remain stable when these v2 features are added.
