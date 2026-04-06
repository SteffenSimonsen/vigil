"""vigil down command."""

from __future__ import annotations

import json
import sys

import click

from vigil.commands._shared import json_error, require_project
from vigil.commands.stop import wait_for_time_wait_clear
from vigil.config import Config
from vigil.state import StateCorruptedError
from vigil.vigilfile import ParseError as VigilfileParseError
from vigil.vigilfile import down as vigilfile_down
from vigil.vigilfile import load as vigilfile_load


@click.command("down")
@click.option(
    "--only",
    "only_names",
    default=None,
    metavar="NAME,...",
    help="Comma-separated subset of processes to stop.",
)
@click.option(
    "--no-wait",
    "no_wait",
    is_flag=True,
    help="Return immediately after sending kill signals.",
)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_down(only_names: str | None, no_wait: bool, as_json: bool) -> None:
    """Stop all Vigilfile processes in reverse order."""
    root = require_project(as_json)
    config = Config(root=root)

    try:
        entries = vigilfile_load(root)
    except VigilfileParseError as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)

    only: list[str] | None = [n.strip() for n in only_names.split(",")] if only_names else None
    try:
        results = vigilfile_down(config, entries, only=only)
    except StateCorruptedError as e:
        if as_json:
            json_error(str(e), "state_corrupted")
        click.echo(str(e), err=True)
        sys.exit(1)

    if not no_wait:
        all_tw_ports = [p for r in results for p in r.get("time_wait_ports", [])]
        if all_tw_ports:
            wait_for_time_wait_clear(all_tw_ports)

    if as_json:
        click.echo(json.dumps({"processes": results}, indent=2))
        return

    for r in results:
        name = r["name"]
        if r["status"] == "stopped":
            click.echo(f"  {name}: stopped")
        else:
            click.echo(f"  {name}: not running")
