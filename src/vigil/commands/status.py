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
from vigil.registry import make_registry
from vigil.state import StateCorruptedError


def _format_session(session_id: str | None, current_session: str | None) -> str:
    """Return an abbreviated session label for text output."""
    if session_id is None:
        return ""
    short = session_id[:8]
    if current_session and session_id == current_session:
        return f"{short} (this session)"
    return short


@click.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_status(as_json: bool) -> None:
    """Show status of all managed processes."""
    root = require_project(as_json)
    config = Config(root=root)

    reg = make_registry(config)

    try:
        records = reg.all()
        observations = reg.observe_all(records=records)
    except StateCorruptedError as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)

    alive_names = {r.name for r in records if r.alive}

    managed: list[dict[str, Any]] = []
    for record in records:
        obs = observations.get(record.name)
        circuit_open = obs["circuit_open"] if obs else record.circuit_open
        crash_count = obs["crash_count"] if obs else record.crash_count
        last_crash_at = obs["last_crash_at"] if obs else record.last_crash_at

        if record.alive:
            if circuit_open:
                managed.append(
                    {
                        "name": record.name,
                        "command": record.command,
                        "pid": record.pid,
                        "alive": True,
                        "status": "crash_looping",
                        "crash_count": crash_count,
                        "last_crash_at": last_crash_at,
                        "ports": [],
                        "docker": None,
                        "message": f"Process exited {crash_count} times. "
                        f"Use 'vigil logs {record.name}' to investigate.",
                    }
                )
            else:
                entry_ports = obs["ports"] if obs else []
                dead_deps = [d for d in record.depends_on if d not in alive_names]
                status = "degraded" if dead_deps else "alive"
                dep_status = {
                    d: ("alive" if d in alive_names else "dead") for d in record.depends_on
                }
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
            managed.append(
                {
                    "name": record.name,
                    "command": record.command,
                    "pid": None,
                    "alive": False,
                    "status": "crashed",
                    "crashed": True,
                    "ports": [],
                    "docker": None,
                    "env_file": record.env_file,
                    "env_overrides": {k: "[set]" for k in record.env_keys},
                    "session_id": record.session_id,
                }
            )

    if as_json:
        click.echo(json.dumps({"managed": managed}, indent=2))
        return

    if not managed:
        click.echo("No managed processes.")
        return

    current_session = os.environ.get("VIGIL_SESSION_ID")
    for entry in managed:
        session_str = _format_session(entry.get("session_id"), current_session)
        session_suffix = f"  [{session_str}]" if session_str else ""
        if entry["status"] == "crash_looping":
            click.echo(
                f"  {entry['name']:<12} \u26a0 crash_looping  PID {entry['pid']}  "
                f"(crashes={entry['crash_count']})  ({entry['command']}){session_suffix}"
            )
        elif entry["alive"]:
            ports_str = "  ".join(f":{p}" for p in entry["ports"])
            env_str = f"  env:{entry['env_file']}" if entry.get("env_file") else ""
            click.echo(
                f"  {entry['name']:<12} \u25cf alive    PID {entry['pid']}  {ports_str}"
                f"{env_str}  ({entry['command']}){session_suffix}"
            )
        else:
            click.echo(
                f"  {entry['name']:<12} \u2716 crashed  ({entry['command']}){session_suffix}"
            )
