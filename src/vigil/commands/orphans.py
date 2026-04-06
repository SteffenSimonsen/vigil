"""vigil orphans command."""

from __future__ import annotations

import json

import click

from vigil.commands._shared import json_error, require_project
from vigil.config import Config
from vigil.orphans import find_orphans
from vigil.state import StateCorruptedError, StateManager


@click.command("orphans")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_orphans(as_json: bool) -> None:
    """List processes in the project directory not managed by vigil."""
    root = require_project(as_json)
    config = Config(root=root)

    try:
        records = StateManager(config).read_all()
    except StateCorruptedError as e:
        if as_json:
            json_error(str(e), "state_corrupted")
        click.echo(str(e), err=True)
        raise SystemExit(1) from None

    registry_pids = {r.pid for r in records if r.alive}
    orphans = find_orphans(root, registry_pids)

    if as_json:
        click.echo(json.dumps({"orphans": list(orphans)}, indent=2))
        return

    if not orphans:
        click.echo("No orphaned processes found.")
        return

    click.echo("ORPHANED PROCESSES (not in vigil registry)")
    click.echo(f"  {'PID':<8} {'PORT':<6} {'COMMAND'}")
    for o in orphans:
        port_str = str(o["ports"][0]) if o["ports"] else "-"
        click.echo(f"  {o['pid']:<8} {port_str:<6} {o['command']}   cwd={o['cwd']}")
    click.echo()
    click.echo("These processes are running in your project directory but not managed by vigil.")
    click.echo("Use `vigil free <port>` to kill them.")
