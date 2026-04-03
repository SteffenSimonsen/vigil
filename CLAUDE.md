# Vigil — Claude Code Guide

## Development Workflow

Before every commit, run the full quality check:

```bash
uv run ruff check src tests      # lint
uv run ruff format src tests     # format
uv run pyright                   # type check
uv run pytest                    # tests
```

Fix all ruff and pyright errors before committing. Do not suppress errors with `# type: ignore` or `# noqa` unless there is a documented reason.

## Project Structure

```
src/vigil/       # package source
tests/           # pytest tests
docs/dev/        # specs, PRDs, design documents
pyproject.toml   # package config, tool config
CLAUDE.md        # this file
```

## Adding a Module

Each module in `src/vigil/` is a deep module: a small, stable public interface over a large private implementation. When adding a new module:
- Define the public interface first (functions/classes that other modules call)
- Keep all implementation details private (prefix with `_`)
- Add a corresponding `tests/test_<module>.py`

## Running Commands

```bash
uv run vigil <command>    # run the CLI
uv run pytest             # run all tests
uv run pytest tests/test_state.py   # run a single test file
uv run ruff check src     # lint
uv run pyright            # type check
```

---

## Vigil CLI Reference (for using vigil in this project)

When using vigil to manage this project's own dev processes, follow the rules below.

### Quick Reference

- Check what's running: `vigil status --json`
- Start a service: `vigil start <name> "<command>" --json`
- Stop a service: `vigil stop <name> --json`
- Stop everything: `vigil stop --all --json`
- Restart a service: `vigil restart <name> --json`
- Full OS landscape: `vigil scan --json`
- Find a free port: `vigil next [start] --json`
- Free a blocked port: `vigil free <port> --json`
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
