"""vigil restart command."""

from __future__ import annotations

import json
import sys

import click

from vigil.commands._shared import complete_process_names, json_error, require_project
from vigil.config import Config
from vigil.manager import ProcessNotFound
from vigil.manager import restart as manager_restart
from vigil.state import StateCorruptedError


@click.command("restart")
@click.argument("name", shell_complete=complete_process_names)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_restart(name: str, as_json: bool) -> None:
    """Stop and restart a managed process using its recorded command."""
    root = require_project(as_json)
    config = Config(root=root)

    try:
        record = manager_restart(config, name)
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
    except (FileNotFoundError, PermissionError, ValueError) as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"name": record.name, "pid": record.pid, "status": "restarted"}))
    else:
        click.echo(f"Restarted {record.name!r} (pid {record.pid})")
