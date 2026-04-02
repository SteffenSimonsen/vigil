"""vigil status command."""

from __future__ import annotations

import json
import sys
from typing import Any

import click

from vigil.commands._shared import json_error, require_project
from vigil.config import Config
from vigil.crash_loop import observe as _observe_crash_loop
from vigil.docker import lookup as docker_lookup
from vigil.scanner import ports_for_pid
from vigil.state import StateCorruptedError, StateManager


@click.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_status(as_json: bool) -> None:
    """Show status of all managed processes."""
    root = require_project(as_json)
    config = Config(root=root)
    try:
        records = StateManager(config).read_all()
    except StateCorruptedError as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)

    # Update crash-loop observations before building status output
    for record in records:
        if record.alive:
            _observe_crash_loop(config, record.name)

    # Re-read with updated crash-loop state
    try:
        records = StateManager(config).read_all()
    except StateCorruptedError as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)

    managed: list[dict[str, Any]] = []
    for record in records:
        if record.alive:
            if record.circuit_open:
                managed.append(
                    {
                        "name": record.name,
                        "command": record.command,
                        "pid": record.pid,
                        "alive": True,
                        "status": "crash_looping",
                        "crash_count": record.crash_count,
                        "last_crash_at": record.last_crash_at,
                        "ports": [],
                        "docker": None,
                        "message": f"Process exited {record.crash_count} times. "
                        f"Use 'vigil logs {record.name}' to investigate.",
                    }
                )
            else:
                entry_ports = ports_for_pid(record.pid)
                managed.append(
                    {
                        "name": record.name,
                        "command": record.command,
                        "pid": record.pid,
                        "alive": True,
                        "status": "alive",
                        "ports": entry_ports,
                        "docker": docker_lookup(entry_ports),
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
                }
            )

    if as_json:
        click.echo(json.dumps({"managed": managed}, indent=2))
        return

    if not managed:
        click.echo("No managed processes.")
        return

    for entry in managed:
        if entry["status"] == "crash_looping":
            click.echo(
                f"  {entry['name']:<12} \u26a0 crash_looping  PID {entry['pid']}  "
                f"(crashes={entry['crash_count']})  ({entry['command']})"
            )
        elif entry["alive"]:
            ports_str = "  ".join(f":{p}" for p in entry["ports"])
            click.echo(
                f"  {entry['name']:<12} \u25cf alive    PID {entry['pid']}  {ports_str}"
                f"  ({entry['command']})"
            )
        else:
            click.echo(f"  {entry['name']:<12} \u2716 crashed  ({entry['command']})")
