"""vigil free command."""

from __future__ import annotations

import json
import sys

import click

from vigil.commands._shared import json_error, require_project
from vigil.config import Config
from vigil.free import free_port
from vigil.state import StateCorruptedError


@click.command("free")
@click.argument("port", type=int)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_free(port: int, as_json: bool) -> None:
    """Free a port regardless of what is using it (managed, Docker, or unmanaged)."""
    root = require_project(as_json)
    config = Config(root=root)

    try:
        result = free_port(config, port)
    except StateCorruptedError as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(result))
    else:
        was = result["was"]
        if was == "free":
            click.echo(f"Port {port} is already free.")
        elif was == "time_wait":
            retry = result.get("retry_after_seconds", 60)
            click.echo(
                f"Port {port} is in TIME_WAIT — the kernel is holding it after process death.\n"
                f"It will become free in ~{retry}s. Pick another port or wait."
            )
        else:
            click.echo(f"Freed port {port} ({was}).")
