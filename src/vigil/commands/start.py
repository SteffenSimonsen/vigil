"""vigil start command."""

from __future__ import annotations

import json
import sys

import click

from vigil.commands._shared import json_error, require_project
from vigil.config import Config
from vigil.registry import ProcessAlreadyRunning, ProcessCrashed, make_registry
from vigil.state import StateCorruptedError


@click.command("start")
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
@click.option("--env-file", "env_file", default=None, help="Load env vars from a .env file.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_start(
    name: str,
    command: str,
    force: bool,
    env_vars: tuple[str, ...],
    cwd: str | None,
    env_file: str | None,
    as_json: bool,
) -> None:
    """Start a named process."""
    root = require_project(as_json)
    config = Config(root=root)

    env: dict[str, str] | None = None
    if env_vars:
        env = {}
        for spec in env_vars:
            key, _, val = spec.partition("=")
            env[key] = val

    try:
        record = make_registry(config).start(
            name, command, force=force, env=env, env_file=env_file, cwd=cwd
        )
    except StateCorruptedError as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)
    except ProcessAlreadyRunning as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)
    except ProcessCrashed as e:
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
        click.echo(json.dumps({"name": record.name, "pid": record.pid, "status": "started"}))
    else:
        click.echo(f"Started {record.name!r} (pid {record.pid})")
