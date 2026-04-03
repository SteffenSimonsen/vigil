"""vigil stop command."""

from __future__ import annotations

import json
import os
import sys

import click

from vigil.commands._shared import complete_process_names, json_error, require_project
from vigil.config import Config
from vigil.registry import ProcessNotFound, make_registry
from vigil.state import StateCorruptedError, StateManager


@click.command("stop")
@click.argument("name", required=False, default=None, shell_complete=complete_process_names)
@click.option("--all", "stop_all_flag", is_flag=True, help="Stop all managed processes.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
@click.option("--force", is_flag=True, help="Suppress cross-session ownership warning.")
def cmd_stop(name: str | None, stop_all_flag: bool, as_json: bool, force: bool) -> None:
    """Stop a managed process (or all processes with --all)."""
    root = require_project(as_json)
    config = Config(root=root)

    if stop_all_flag:
        try:
            results = make_registry(config).stop_all()
        except StateCorruptedError as e:
            if as_json:
                json_error(str(e))
            click.echo(str(e), err=True)
            sys.exit(1)
        if as_json:
            click.echo(json.dumps({"processes": list(results)}))
        else:
            if results:
                for r in results:
                    if r["status"] == "stopped":
                        click.echo(f"  \u2713 {r['name']} stopped")
                    else:
                        click.echo(f"  \u2713 {r['name']} cleaned up (was crashed)")
            else:
                click.echo("No managed processes to stop.")
        return

    if not name:
        if as_json:
            json_error("Provide a process name or use --all.")
        click.echo("Provide a process name or use --all.", err=True)
        sys.exit(1)

    # Cross-session ownership warning
    if not force and not as_json:
        current_session = os.environ.get("VIGIL_SESSION_ID")
        if current_session:
            try:
                records = {r.name: r for r in StateManager(config).read_all()}
                record = records.get(name)
                if record and record.session_id and record.session_id != current_session:
                    click.echo(
                        f"Warning: {name!r} was started by a different vigil session "
                        f"({record.session_id[:8]}).\n"
                        "Stopping anyway. Use --force to suppress this warning."
                    )
            except StateCorruptedError:
                pass

    try:
        result = make_registry(config).stop(name)
    except StateCorruptedError as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)
    except ProcessNotFound as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)

    if as_json:
        click.echo(
            json.dumps(
                {
                    "name": name,
                    "status": result["status"],
                    "time_wait_ports": result["time_wait_ports"],
                }
            )
        )
    else:
        if result["status"] == "stopped":
            click.echo(f"Stopped {name!r}")
        else:
            click.echo(f"Cleaned up {name!r} (was crashed)")
        if result["time_wait_ports"]:
            ports_str = ", ".join(str(p) for p in result["time_wait_ports"])
            click.echo(
                f"  Warning: port(s) {ports_str} entered TIME_WAIT — "
                "they may be unavailable for ~60s."
            )
