# Vigil

A lightweight CLI process manager for local development. Gives Claude Code and humans a single source of truth for what's running, on which port, and why.

## Install

```bash
uv tool install git+https://github.com/SteffenSimonsen/vigil
```

## Dev setup

```bash
git clone https://github.com/SteffenSimonsen/vigil
cd vigil
uv sync
```

See `CLAUDE.md` for development workflow and CLI reference.

## Lifecycle semantics

- Lifecycle operations and registry reads are serialized per project, so concurrent Vigil
  commands observe a complete before-or-after state.
- A registered process whose PID is no longer alive is reported as `exited`. Vigil cannot know
  its exit code because it does not run a resident supervisor.
- Status, health, and wait commands are read-only. An alive process waiting to bind its assigned
  port remains alive; `health` reports it as `port-pending` and `wait` applies its timeout.
