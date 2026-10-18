# Vigil

Vigil is a lightweight process manager for local development. It gives developers and coding
agents one place to start services, inspect ports, wait for readiness, read logs, and clean up.

## Install

Vigil requires Python 3.12 or newer.

```bash
uv tool install git+https://github.com/SteffenSimonsen/vigil
```

## Quick Start

```bash
cd your-project
vigil init
vigil start web "python -m http.server 8000" --port 8000
vigil status
vigil logs web
vigil stop web
```

Add `--json` when using Vigil from scripts or coding agents:

```bash
vigil status --json
vigil start api "uv run uvicorn app:app --port {PORT}" --auto-port --json
```

## Manage a Stack

Define project services in a `Vigilfile`:

```toml
[[process]]
name = "database"
command = "docker compose up postgres"
port = 5432

[[process]]
name = "api"
command = "uv run uvicorn app:app --port 8000"
port = 8000
depends_on = ["database"]
health_endpoint = "/health"
env = { APP_ENV = "development" }
```

Then manage the stack as a unit:

```bash
vigil up
vigil health
vigil down
```

## Commands

| Command | Purpose |
| --- | --- |
| `status [name]` | Show managed processes, ports, and dependency state |
| `start`, `stop`, `restart`, `remove` | Manage one process |
| `up`, `down` | Manage all processes in a `Vigilfile` |
| `wait`, `health`, `logs` | Check readiness, health, and output |
| `scan`, `next`, `free` | Inspect, allocate, and release ports |
| `open` | Open a process or port in the browser |
| `orphans` | Find project processes not managed by Vigil |

Run `vigil <command> --help` for all options.

## Behavior

- Runtime state and logs live in `.vigil/`; project configuration stays in `Vigilfile` and the
  optional root-level `vigil.toml`.
- Lifecycle operations are serialized per project, so concurrent commands cannot create partial
  registry transitions or duplicate managed processes.
- A registered process whose PID is gone is reported as `exited`. Vigil does not run a resident
  supervisor, so it cannot recover the process exit code.
- `status`, `health`, and `wait` only observe state. They never mutate lifecycle history.

## Development

```bash
git clone https://github.com/SteffenSimonsen/vigil
cd vigil
uv sync
uv run pytest
```

See [`CLAUDE.md`](CLAUDE.md) for the development workflow and agent-oriented command reference.
