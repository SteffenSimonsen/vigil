"""vigil remove command."""

from __future__ import annotations

import json
import sys

import click

from vigil.commands._shared import json_error, require_project
from vigil.config import Config
from vigil.registry import ProcessAlreadyRunning, ProcessNotFound, make_registry
from vigil.state import StateCorruptedError


@click.command("remove")
@click.argument("name")
@click.option("--force", is_flag=True, help="Remove registry entry without stopping the process.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_remove(name: str, force: bool, as_json: bool) -> None:
    """Remove a process entry from the registry."""
    root = require_project(as_json)
    config = Config(root=root)

    try:
        make_registry(config).remove(name, force=force)
    except StateCorruptedError as e:
        if as_json:
            json_error(str(e), "state_corrupted")
        click.echo(str(e), err=True)
        sys.exit(1)
    except ProcessNotFound:
        # Idempotent: not in registry is a success
        if as_json:
            click.echo(json.dumps({"name": name, "status": "not_found"}))
        else:
            click.echo(f"{name!r} not found in registry")
        return
    except ProcessAlreadyRunning as e:
        if as_json:
            json_error(str(e), "already_running")
        click.echo(str(e), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"name": name, "status": "removed"}))
    else:
        click.echo(f"Removed {name!r}")
