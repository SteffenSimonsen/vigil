"""vigil start command."""

from __future__ import annotations

import json
import sys

import click

from vigil.commands._shared import json_error, require_project
from vigil.config import Config
from vigil.registry import PortOccupied, ProcessAlreadyRunning, ProcessCrashed, make_registry
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
@click.option("--auto-port", "auto_port", is_flag=True, help="Assign a free port automatically.")
@click.option("--port", "explicit_port", default=None, type=int, help="Request a specific port.")
@click.option(
    "--no-wait",
    "no_wait",
    is_flag=True,
    help="Return immediately without waiting for readiness.",
)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_start(
    name: str,
    command: str,
    force: bool,
    env_vars: tuple[str, ...],
    cwd: str | None,
    env_file: str | None,
    auto_port: bool,
    explicit_port: int | None,
    no_wait: bool,
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
            name,
            command,
            force=force,
            env=env,
            env_file=env_file,
            cwd=cwd,
            auto_port=auto_port,
            port=explicit_port,
        )
    except StateCorruptedError as e:
        if as_json:
            json_error(str(e), "state_corrupted")
        click.echo(str(e), err=True)
        sys.exit(1)
    except ProcessAlreadyRunning as e:
        if as_json:
            json_error(str(e), "already_running")
        click.echo(str(e), err=True)
        sys.exit(1)
    except ProcessCrashed as e:
        if as_json:
            json_error(str(e), "process_crashed")
        click.echo(str(e), err=True)
        sys.exit(1)
    except PortOccupied as e:
        if as_json:
            json_error(str(e), "port_occupied")
        click.echo(str(e), err=True)
        sys.exit(1)
    except (FileNotFoundError, PermissionError, ValueError) as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)

    if no_wait:
        status = "started"
    else:
        from vigil.wait import CrashLooping, ProcessDied, WaitTimeout, wait_for_ready

        try:
            wait_for_ready(config, name, timeout=30, port=record.port)
            status = "ready"
        except (ProcessDied, CrashLooping) as e:
            if as_json:
                json_error(str(e), "process_crashed")
            click.echo(str(e), err=True)
            sys.exit(1)
        except WaitTimeout as e:
            if as_json:
                json_error(str(e))
            click.echo(str(e), err=True)
            sys.exit(1)

    out: dict[str, object] = {"name": record.name, "pid": record.pid, "status": status}
    if record.port is not None:
        out["port"] = record.port

    if as_json:
        click.echo(json.dumps(out))
    else:
        if status == "ready":
            click.echo(f"Started {record.name!r} (pid {record.pid}) — ready")
        else:
            click.echo(f"Started {record.name!r} (pid {record.pid})")
