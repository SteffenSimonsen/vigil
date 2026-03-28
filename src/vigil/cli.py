"""Vigil CLI entry point."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from vigil.config import Config, ConfigError, find_vigil_root
from vigil.init import init_project, parse_process_spec, prompt_for_processes
from vigil.manager import ProcessAlreadyRunning, ProcessCrashed, ProcessNotFound
from vigil.manager import start as manager_start
from vigil.manager import stop as manager_stop
from vigil.manager import stop_all as manager_stop_all


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


@main.command("stop")
@click.argument("name", required=False, default=None)
@click.option("--all", "stop_all_flag", is_flag=True, help="Stop all managed processes.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_stop(name: str | None, stop_all_flag: bool, as_json: bool) -> None:
    """Stop a managed process (or all processes with --all)."""
    root = _require_project()
    config = Config(root=root)

    if stop_all_flag:
        names = manager_stop_all(config)
        if as_json:
            click.echo(json.dumps({"status": "stopped", "names": names}))
        else:
            if names:
                click.echo(f"Stopped {len(names)} process(es): {', '.join(names)}")
            else:
                click.echo("No managed processes to stop.")
        return

    if not name:
        click.echo("Provide a process name or use --all.", err=True)
        sys.exit(1)

    try:
        manager_stop(config, name)
    except ProcessNotFound as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"name": name, "status": "stopped"}))
    else:
        click.echo(f"Stopped {name!r}")


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
