"""vigil logs command."""

from __future__ import annotations

import json
import sys
import time

import click

from vigil.commands._shared import complete_process_names, json_error, require_project
from vigil.config import Config
from vigil.logs import LogNotFound, read_log


@click.command("logs")
@click.argument("name", shell_complete=complete_process_names)
@click.option("--tail", default=50, show_default=True, help="Number of lines to show.")
@click.option("--follow", "follow", is_flag=True, help="Stream new output (tail -f style).")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_logs(name: str, tail: int, follow: bool, as_json: bool) -> None:
    """Show log output for a managed process."""
    root = require_project(as_json)
    config = Config(root=root)

    if follow:
        _follow_logs(config, name)
        return

    try:
        lines = read_log(config, name, tail=tail)
    except LogNotFound as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"lines": lines}))
    else:
        for line in lines:
            click.echo(line)


def _follow_logs(config: Config, name: str) -> None:
    """Stream log file lines until KeyboardInterrupt."""
    log_path = config.logs_dir / f"{name}.log"
    if not log_path.exists():
        click.echo(f"No log file found for process {name!r}", err=True)
        sys.exit(1)

    with log_path.open("r", encoding="utf-8", errors="replace") as f:
        f.seek(0, 2)  # seek to end
        try:
            while True:
                line = f.readline()
                if line:
                    click.echo(line, nl=False)
                else:
                    time.sleep(0.1)
        except KeyboardInterrupt:
            pass
