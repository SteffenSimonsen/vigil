# Vigilfile parsing and up/down orchestration
"""Vigilfile — parse Vigilfile TOML and orchestrate vigil up / vigil down."""

from __future__ import annotations

import contextlib
import tomllib
from dataclasses import dataclass, field
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Any, cast

from vigil.config import Config
from vigil.registry import ProcessAlreadyRunning, ProcessNotFound, make_registry
from vigil.state import ProcessRecord
from vigil.wait import WaitTimeout, wait_for_ready


class ParseError(Exception):
    """Raised when the Vigilfile cannot be parsed or is structurally invalid."""


@dataclass
class VigilEntry:
    """A single process definition from the Vigilfile."""

    name: str
    command: str
    port: int | None = None
    wait_timeout: float = 30.0
    order: int | None = None
    env: dict[str, str] = field(default_factory=lambda: {})
    cwd: str | None = None
    url: str | None = None
    health_endpoint: str | None = None
    depends_on: list[str] = field(default_factory=lambda: [])


def load(root: Path) -> list[VigilEntry]:
    """Parse the Vigilfile at *root*/Vigilfile and return a list of VigilEntry objects.

    Raises ParseError if the file is missing, malformed, or contains invalid entries.
    """
    vigilfile = root / "Vigilfile"
    if not vigilfile.exists():
        raise ParseError(f"Vigilfile not found in {root}")

    try:
        with vigilfile.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ParseError(f"Vigilfile contains invalid TOML: {exc}") from exc

    raw_processes: list[dict[str, Any]] = data.get("process", [])

    entries: list[VigilEntry] = []
    for i, raw in enumerate(raw_processes):
        if "name" not in raw:
            raise ParseError(f"Process entry {i} is missing required field 'name'")
        if "command" not in raw:
            raise ParseError(
                f"Process entry {i} ({raw.get('name', '?')!r}) is missing required field 'command'"
            )

        env: dict[str, str] = {}
        raw_env = raw.get("env", {})
        if isinstance(raw_env, dict):
            for k, v in cast(dict[str, object], raw_env).items():
                env[k] = str(v)

        raw_depends_on = raw.get("depends_on", [])
        depends_on: list[str] = (
            [str(d) for d in cast(list[object], raw_depends_on)]
            if isinstance(raw_depends_on, list)
            else []
        )

        entries.append(
            VigilEntry(
                name=str(raw["name"]),
                command=str(raw["command"]),
                port=int(raw["port"]) if "port" in raw else None,
                wait_timeout=float(raw.get("wait_timeout", 30.0)),
                order=int(raw["order"]) if "order" in raw else None,
                env=env,
                cwd=str(raw["cwd"]) if "cwd" in raw else None,
                url=str(raw["url"]) if "url" in raw else None,
                health_endpoint=str(raw["health_endpoint"]) if "health_endpoint" in raw else None,
                depends_on=depends_on,
            )
        )

    _validate_dependencies(entries)
    return entries


def _validate_dependencies(entries: list[VigilEntry]) -> None:
    """Validate that depends_on names exist and contain no cycles."""
    known = {e.name for e in entries}
    for entry in entries:
        for dep in entry.depends_on:
            if dep not in known:
                raise ParseError(f"Process {entry.name!r} depends_on unknown process {dep!r}")
    # Check for cycles
    graph: dict[str, set[str]] = {e.name: set(e.depends_on) for e in entries}
    try:
        list(TopologicalSorter(graph).static_order())
    except CycleError as exc:
        raise ParseError(f"Circular dependency detected: {exc}") from exc


def _sorted_entries(entries: list[VigilEntry], only: list[str] | None) -> list[VigilEntry]:
    """Return entries filtered by *only* and sorted.

    If any entry has depends_on, uses topological sort (dependency-first).
    Otherwise uses legacy order: ordered (asc) then unordered (definition order).
    """
    filtered = [e for e in entries if only is None or e.name in only]
    if any(e.depends_on for e in filtered):
        return _topo_sorted(filtered)
    ordered_entries = [e for e in filtered if e.order is not None]
    ordered_entries.sort(key=lambda e: cast(int, e.order))
    unordered = [e for e in filtered if e.order is None]
    return ordered_entries + unordered


def _topo_sorted(entries: list[VigilEntry]) -> list[VigilEntry]:
    """Return entries in topological dependency order (dependencies first)."""
    by_name = {e.name: e for e in entries}
    graph: dict[str, set[str]] = {
        e.name: {d for d in e.depends_on if d in by_name} for e in entries
    }
    order = list(TopologicalSorter(graph).static_order())
    return [by_name[name] for name in order if name in by_name]


# Internal wrappers — thin delegates to registry/wait, patched in tests
def _start(
    config: Config,
    name: str,
    command: str,
    *,
    force: bool = False,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> ProcessRecord:
    return make_registry(config).start(name, command, force=force, env=env, cwd=cwd)


def _wait(
    config: Config,
    name: str,
    *,
    timeout: float = 30.0,
    port: int | None = None,
    http_path: str | None = None,
) -> None:
    wait_for_ready(config, name, timeout=timeout, port=port, http_path=http_path)


def _stop(config: Config, name: str) -> None:
    make_registry(config).stop(name)


def up(
    config: Config,
    entries: list[VigilEntry],
    *,
    only: list[str] | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Start Vigilfile processes in order.

    Skips already-running processes (unless *force* is True).  Best-effort:
    records failures and continues.  Returns a result list in startup order.
    """
    results: list[dict[str, Any]] = []
    failed: set[str] = set()  # names of processes that failed or were blocked

    for entry in _sorted_entries(entries, only):
        # Block if any dependency failed
        blocking_deps = [d for d in entry.depends_on if d in failed]
        if blocking_deps:
            results.append(
                {
                    "name": entry.name,
                    "status": "blocked",
                    "pid": None,
                    "error": f"dependency failed: {', '.join(blocking_deps)}",
                }
            )
            failed.add(entry.name)
            continue

        try:
            rec = _start(
                config,
                entry.name,
                entry.command,
                force=force,
                env=entry.env or None,
                cwd=entry.cwd,
            )
        except ProcessAlreadyRunning:
            results.append({"name": entry.name, "status": "skipped", "pid": None, "error": None})
            continue
        except Exception as exc:
            results.append({"name": entry.name, "status": "failed", "pid": None, "error": str(exc)})
            failed.add(entry.name)
            continue

        # Wait for readiness
        try:
            _wait(
                config,
                entry.name,
                timeout=entry.wait_timeout,
                port=entry.port,
                http_path=entry.health_endpoint,
            )
        except (WaitTimeout, Exception) as exc:
            results.append(
                {"name": entry.name, "status": "failed", "pid": rec.pid, "error": str(exc)}
            )
            failed.add(entry.name)
            continue

        # Persist depends_on so status can compute degraded state
        if entry.depends_on:
            with contextlib.suppress(KeyError):
                make_registry(config).set_depends_on(entry.name, entry.depends_on)

        results.append({"name": entry.name, "status": "started", "pid": rec.pid, "error": None})

    return results


def down(
    config: Config,
    entries: list[VigilEntry],
    *,
    only: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Stop Vigilfile processes in reverse startup order, sequentially.

    Each process is fully stopped before the next begins.
    """
    results: list[dict[str, Any]] = []
    ordered = _sorted_entries(entries, only)

    for entry in reversed(ordered):
        try:
            _stop(config, entry.name)
            results.append({"name": entry.name, "status": "stopped", "error": None})
        except ProcessNotFound:
            results.append({"name": entry.name, "status": "not_running", "error": None})

    return results
