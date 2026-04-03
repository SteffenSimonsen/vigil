"""vigil wait command."""

from __future__ import annotations

import json
import sys

import click

from vigil.commands._shared import complete_process_names, json_error, require_project
from vigil.config import Config
from vigil.state import StateCorruptedError
from vigil.wait import CrashLooping, ProcessDied, WaitTimeout, wait_for_ready
from vigil.wait import ProcessNotFound as WaitProcessNotFound


class _HttpOptionCommand(click.Command):
    """Command subclass that normalises ``--http`` → ``--http=/`` before parsing.

    Click does not support options with optional values (``--flag[=VALUE]``).
    This class preprocesses the argument list so that a bare ``--http``
    argument is rewritten to ``--http=/``, making ``--http`` an option that
    always receives a string value.
    """

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        args = ["--http=/" if a == "--http" else a for a in args]
        return super().parse_args(ctx, args)


@click.command("wait", cls=_HttpOptionCommand)
@click.argument("name", shell_complete=complete_process_names)
@click.option("--timeout", default=30.0, show_default=True, help="Seconds before giving up.")
@click.option("--port", "port_override", default=None, type=int, help="Wait for a specific port.")
@click.option(
    "--http",
    "http_path",
    default=None,
    type=str,
    metavar="PATH",
    help="Wait for HTTP response on PATH. Use --http for / or --http=/health for a custom path.",
)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_wait(
    name: str,
    timeout: float,
    port_override: int | None,
    http_path: str | None,
    as_json: bool,
) -> None:
    """Block until a managed process is ready (port open, optional HTTP check).

    Use --http to check for any HTTP response on / (the default path).
    Use --http=/health to check on a custom path.
    """
    if http_path is not None and not http_path.startswith("/"):
        if as_json:
            click.echo(json.dumps({"error": "Endpoint must start with /"}))
        else:
            click.echo("Error: Endpoint must start with /")
        sys.exit(1)

    root = require_project(as_json)
    config = Config(root=root)

    try:
        wait_for_ready(config, name, timeout=timeout, port=port_override, http_path=http_path)
    except CrashLooping as e:
        if as_json:
            click.echo(json.dumps({"name": name, "status": "crash_looping", "error": str(e)}))
        else:
            click.echo(str(e), err=True)
        sys.exit(2)
    except StateCorruptedError as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)
    except WaitProcessNotFound as e:
        if as_json:
            click.echo(json.dumps({"error": str(e), "code": 1}))
        else:
            click.echo(str(e), err=True)
        sys.exit(1)
    except ProcessDied as e:
        if as_json:
            click.echo(json.dumps({"name": name, "status": "died", "error": str(e)}))
        else:
            click.echo(str(e), err=True)
        sys.exit(2)
    except WaitTimeout as e:
        if as_json:
            click.echo(json.dumps({"name": name, "status": "timeout", "error": str(e)}))
        else:
            click.echo(str(e), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"name": name, "status": "ready"}))
    else:
        click.echo(f"{name!r} is ready.")
