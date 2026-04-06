"""vigil up command."""

from __future__ import annotations

import json
import sys

import click

from vigil.commands._shared import json_error, require_project
from vigil.config import Config
from vigil.state import StateCorruptedError
from vigil.vigilfile import ParseError as VigilfileParseError
from vigil.vigilfile import load as vigilfile_load
from vigil.vigilfile import up as vigilfile_up


@click.command("up")
@click.option(
    "--only",
    "only_names",
    default=None,
    metavar="NAME,...",
    help="Comma-separated subset of processes to start.",
)
@click.option("--force", is_flag=True, help="Restart processes even if already running.")
@click.option(
    "--no-wait",
    "no_wait",
    is_flag=True,
    help="Return immediately after spawning without waiting for readiness.",
)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_up(only_names: str | None, force: bool, no_wait: bool, as_json: bool) -> None:
    """Start all Vigilfile processes in order."""
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
        results = vigilfile_up(config, entries, only=only, force=force, no_wait=no_wait)
    except StateCorruptedError as e:
        if as_json:
            json_error(str(e), "state_corrupted")
        click.echo(str(e), err=True)
        sys.exit(1)

    any_failed = any(r["status"] == "failed" for r in results)

    if as_json:
        click.echo(json.dumps({"processes": results}, indent=2))
        if any_failed:
            sys.exit(2)
        return

    for r in results:
        status = r["status"]
        name = r["name"]
        if status in ("started", "ready"):
            click.echo(f"  {name}: {status} (pid {r['pid']})")
        elif status == "skipped":
            click.echo(f"  {name}: already running, skipped")
        else:
            click.echo(f"  {name}: failed — {r['error']}")

    if any_failed:
        sys.exit(2)
