# Vigil Maintenance Guide

## Versioning

Vigil uses semantic versioning: `major.minor.patch`

| Change type | Version bump | Example |
|---|---|---|
| Bug fix | patch | `0.1.0` → `0.1.1` |
| New feature (backwards-compatible) | minor | `0.1.0` → `0.2.0` |
| Breaking CLI or API change | major | `0.1.0` → `1.0.0` |

Version is derived from git tags — there is no version field to edit manually.

## Release Process

1. **Quality gate** — all checks must pass before tagging:
   ```bash
   uv run ruff check src tests
   uv run ruff format src tests
   uv run pyright
   uv run pytest
   ```

2. **Tag** — create an annotated tag on the commit to release:
   ```bash
   git tag v0.2.0
   ```

3. **Verify** — confirm the version resolves correctly:
   ```bash
   uv sync --reinstall-package vigil
   uv run python -c "import vigil; print(vigil.__version__)"
   ```

## Issue Workflow

New work enters the project as GitHub issues on `SteffenSimonsen/vigil`.

- **Bugs** get the `bug` label and commit prefix `fix:`
- **Features** get no label and commit prefix `feat:`
- Issues are implemented one at a time using RALPH (`RALPH.md`) — an automated TDD agent that picks the lowest-numbered open issue, implements it, passes the quality gate, commits, and closes the issue.

To run RALPH on the next open issue:
```bash
uv run vigil start ralph "claude --dangerously-skip-permissions -p RALPH.md"
```

## Dependency Updates

```bash
uv sync --upgrade        # update all deps within constraints
uv run pytest            # verify nothing broke
git add uv.lock && git commit -m "chore: update dependencies"
```

Pin a dependency in `pyproject.toml` only if a specific version breaks something.
