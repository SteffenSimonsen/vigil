"""vigil stop command."""

from __future__ import annotations

import json
import sys

import click

from vigil.commands._shared import complete_process_names, json_error, require_project
from vigil.config import Config
from vigil.manager import ProcessNotFound
from vigil.manager import stop as manager_stop
from vigil.manager import stop_all as manager_stop_all
from vigil.state import StateCorruptedError


@click.command("stop")
@click.argument("name", required=False, default=None, shell_complete=complete_process_names)
@click.option("--all", "stop_all_flag", is_flag=True, help="Stop all managed processes.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_stop(name: str | None, stop_all_flag: bool, as_json: bool) -> None:
    """Stop a managed process (or all processes with --all)."""
    root = require_project(as_json)
    config = Config(root=root)

    if stop_all_flag:
        try:
            results = manager_stop_all(config)
        except StateCorruptedError as e:
            if as_json:
                json_error(str(e))
            click.echo(str(e), err=True)
            sys.exit(1)
        if as_json:
            click.echo(json.dumps({"processes": results}))
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

    try:
        status = manager_stop(config, name)
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
        click.echo(json.dumps({"name": name, "status": status}))
    else:
        if status == "stopped":
            click.echo(f"Stopped {name!r}")
        else:
            click.echo(f"Cleaned up {name!r} (was crashed)")
