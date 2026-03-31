"""vigil init command."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from vigil.commands._shared import json_error
from vigil.init import VigilfileExistsError, init_project, parse_process_spec, prompt_for_processes


@click.command("init")
@click.option(
    "--process",
    "process_specs",
    multiple=True,
    metavar="NAME,CMD[,PORT]",
    help="Non-interactive: define a process as name,command[,port].",
)
@click.option("--force", is_flag=True, help="Overwrite existing Vigilfile.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_init(process_specs: tuple[str, ...], force: bool, as_json: bool) -> None:
    """Initialize a vigil project in the current directory."""
    root = Path.cwd()

    if process_specs:
        try:
            processes = [parse_process_spec(spec) for spec in process_specs]
        except ValueError as e:
            if as_json:
                json_error(str(e))
            click.echo(str(e), err=True)
            sys.exit(1)
    else:
        processes = prompt_for_processes()

    try:
        init_project(root, processes, force=force)
    except VigilfileExistsError as exc:
        click.echo(json.dumps({"error": str(exc), "code": 1}, indent=2))
        sys.exit(1)

    if as_json:
        click.echo(
            json.dumps(
                {"status": "created", "processes": [p.to_dict() for p in processes]},
                indent=2,
            )
        )
    else:
        click.echo(f"Initialized vigil project with {len(processes)} process(es).")
