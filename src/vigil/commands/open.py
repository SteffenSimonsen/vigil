"""vigil open command."""

from __future__ import annotations

import json
import sys

import click

from vigil.commands._shared import complete_process_names, json_error, require_project
from vigil.config import Config
from vigil.open import NoPortFound, UnknownProcess, resolve_url
from vigil.state import StateCorruptedError


@click.command("open")
@click.argument("target", shell_complete=complete_process_names)
@click.option("--json", "as_json", is_flag=True, help="Output JSON without opening a browser.")
def cmd_open(target: str, as_json: bool) -> None:
    """Open a service or port in the browser."""
    root = require_project(as_json)
    config = Config(root=root)

    try:
        url = resolve_url(config, target)
    except StateCorruptedError as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)
    except UnknownProcess as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)
    except NoPortFound as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"url": url}))
        return

    import webbrowser

    webbrowser.open(url)
    click.echo(f"Opening {url}")
