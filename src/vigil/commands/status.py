"""vigil status command."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import click

from vigil.commands._shared import json_error, require_project
from vigil.config import Config
from vigil.docker import lookup as docker_lookup
from vigil.logs import LogNotFound, read_log
from vigil.registry import make_registry
from vigil.state import StateCorruptedError

_BAD_STATUSES = {"exited", "degraded"}


def _format_session(session_id: str | None, current_session: str | None) -> str:
    """Return an abbreviated session label for text output."""
    if session_id is None:
        return ""
    short = session_id[:8]
    if current_session and session_id == current_session:
        return f"{short} (this session)"
    return short


@click.command("status")
@click.argument("name", required=False, default=None)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_status(name: str | None, as_json: bool) -> None:
    """Show status of all managed processes (or a single named process)."""
    root = require_project(as_json)
    config = Config(root=root)

    reg = make_registry(config)

    try:
        records = reg.all()
        ports_by_name = reg.ports_by_process(records=records)
    except StateCorruptedError as e:
        if as_json:
            json_error(str(e), "state_corrupted")
        click.echo(str(e), err=True)
        sys.exit(1)

    # Single-name filter
    if name is not None:
        matched = [r for r in records if r.name == name]
        if not matched:
            if as_json:
                json_error(f"No managed process named {name!r}.", "process_not_found")
            click.echo(f"No managed process named {name!r}.", err=True)
            sys.exit(1)
        records = matched

    alive_names = {r.name for r in records if r.alive}

    managed: list[dict[str, Any]] = []
    for record in records:
        if record.alive:
            entry_ports = ports_by_name.get(record.name, [])
            dead_deps = [d for d in record.depends_on if d not in alive_names]
            status = "degraded" if dead_deps else "alive"
            dep_status = {d: ("alive" if d in alive_names else "dead") for d in record.depends_on}
            managed.append(
                {
                    "name": record.name,
                    "command": record.command,
                    "pid": record.pid,
                    "alive": True,
                    "status": status,
                    "ports": entry_ports,
                    "docker": docker_lookup(entry_ports),
                    "env_file": record.env_file,
                    "env_overrides": {k: "[set]" for k in record.env_keys},
                    "session_id": record.session_id,
                    "depends_on": record.depends_on,
                    "dependency_status": dep_status,
                }
            )
        else:
            # Exited process: include log_tail. Exit status is unavailable without a supervisor.
            try:
                log_lines = read_log(config, record.name, tail=20)
                log_tail: list[str] | None = log_lines
            except LogNotFound:
                log_tail = None

            managed.append(
                {
                    "name": record.name,
                    "command": record.command,
                    "pid": None,
                    "alive": False,
                    "status": "exited",
                    "ports": [],
                    "docker": None,
                    "env_file": record.env_file,
                    "env_overrides": {k: "[set]" for k in record.env_keys},
                    "session_id": record.session_id,
                    "log_tail": log_tail,
                }
            )

    any_bad = any(entry["status"] in _BAD_STATUSES for entry in managed)

    if as_json:
        click.echo(json.dumps({"managed": managed}, indent=2))
        if any_bad:
            sys.exit(2)
        return

    if not managed:
        click.echo("No managed processes.")
        return

    current_session = os.environ.get("VIGIL_SESSION_ID")
    for entry in managed:
        session_str = _format_session(entry.get("session_id"), current_session)
        session_suffix = f"  [{session_str}]" if session_str else ""
        if entry["alive"]:
            ports_str = "  ".join(f":{p}" for p in entry["ports"])
            env_str = f"  env:{entry['env_file']}" if entry.get("env_file") else ""
            click.echo(
                f"  {entry['name']:<12} \u25cf alive    PID {entry['pid']}  {ports_str}"
                f"{env_str}  ({entry['command']}){session_suffix}"
            )
        else:
            click.echo(
                f"  {entry['name']:<12} \u2716 exited   ({entry['command']}){session_suffix}"
            )

    if any_bad:
        sys.exit(2)
