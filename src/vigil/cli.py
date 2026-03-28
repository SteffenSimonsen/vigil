"""Vigil CLI entry point."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from vigil.config import Config, ConfigError, find_vigil_root
from vigil.init import init_project, parse_process_spec, prompt_for_processes
from vigil.manager import ProcessAlreadyRunning, ProcessCrashed
from vigil.manager import start as manager_start


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


@main.command("start")
@click.argument("name")
@click.argument("command")
@click.option("--force", is_flag=True, help="Stop existing process and start fresh.")
@click.option(
    "--env",
    "env_vars",
    multiple=True,
    metavar="KEY=VAL",
    help="Set environment variable in child process.",
)
@click.option("--cwd", default=None, help="Working directory for the child process.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_start(
    name: str,
    command: str,
    force: bool,
    env_vars: tuple[str, ...],
    cwd: str | None,
    as_json: bool,
) -> None:
    """Start a named process."""
    root = _require_project()
    config = Config(root=root)

    env: dict[str, str] | None = None
    if env_vars:
        env = {}
        for spec in env_vars:
            key, _, val = spec.partition("=")
            env[key] = val

    try:
        record = manager_start(config, name, command, force=force, env=env, cwd=cwd)
    except ProcessAlreadyRunning as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    except ProcessCrashed as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"name": record.name, "pid": record.pid, "status": "started"}))
    else:
        click.echo(f"Started {record.name!r} (pid {record.pid})")


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
