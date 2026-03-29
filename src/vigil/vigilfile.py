# Vigilfile parsing and up/down orchestration
"""Vigilfile — parse Vigilfile TOML and orchestrate vigil up / vigil down."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from vigil.config import Config
from vigil.manager import ProcessAlreadyRunning, ProcessNotFound
from vigil.manager import start as manager_start
from vigil.manager import stop as manager_stop
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
            )
        )

    return entries


def _sorted_entries(entries: list[VigilEntry], only: list[str] | None) -> list[VigilEntry]:
    """Return entries filtered by *only* and sorted: ordered (asc) then unordered (def order)."""
    filtered = [e for e in entries if only is None or e.name in only]
    ordered_entries = [e for e in filtered if e.order is not None]
    ordered_entries.sort(key=lambda e: cast(int, e.order))
    unordered = [e for e in filtered if e.order is None]
    return ordered_entries + unordered


# Internal wrappers — thin delegates to manager/wait, patched in tests
def _start(
    config: Config,
    name: str,
    command: str,
    *,
    force: bool = False,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> ProcessRecord:
    return manager_start(config, name, command, force=force, env=env, cwd=cwd)


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
    manager_stop(config, name)


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

    for entry in _sorted_entries(entries, only):
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
            continue

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
