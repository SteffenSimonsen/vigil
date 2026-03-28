"""Vigil CLI entry point."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from vigil.config import ConfigError, find_vigil_root
from vigil.init import init_project, parse_process_spec, prompt_for_processes


def _require_project() -> Path:
    """Return project root or exit with a clear error message."""
    try:
        return find_vigil_root(Path.cwd())
    except ConfigError as e:
        click.echo(str(e))
        sys.exit(1)


@click.group()
def main() -> None:
    """Vigil — local dev process manager."""


@main.command("init")
@click.option(
    "--process",
    "process_specs",
    multiple=True,
    metavar="NAME,CMD[,PORT]",
    help="Non-interactive: define a process as name,command[,port].",
)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_init(process_specs: tuple[str, ...], as_json: bool) -> None:
    """Initialize a vigil project in the current directory."""
    root = Path.cwd()

    if process_specs:
        processes = [parse_process_spec(spec) for spec in process_specs]
    else:
        processes = prompt_for_processes()

    init_project(root, processes)

    if as_json:
        click.echo(
            json.dumps(
                {"status": "created", "processes": [p.to_dict() for p in processes]},
                indent=2,
            )
        )
    else:
        click.echo(f"Initialized vigil project with {len(processes)} process(es).")


@main.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_status(as_json: bool) -> None:
    """Show status of all managed processes."""
    _require_project()
    # Full implementation comes in a later issue.
    if as_json:
        click.echo(json.dumps({"processes": []}))
    else:
        click.echo("No managed processes.")
