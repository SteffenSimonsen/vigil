"""vigil next command."""

from __future__ import annotations

import json

import click

from vigil.scanner import next_free_port


@click.command("next")
@click.argument("start", default=3000, type=int, required=False)
@click.option("--count", default=1, type=int, show_default=True, help="Number of free ports.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_next(start: int, count: int, as_json: bool) -> None:
    """Find the next free port(s) starting from START (default 3000)."""
    try:
        result = next_free_port(start, count=count)
    except ValueError as exc:
        if as_json:
            click.echo(json.dumps({"error": str(exc), "code": 1}))
        else:
            click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if as_json:
        if count == 1:
            click.echo(json.dumps({"port": result}))
        else:
            click.echo(json.dumps({"ports": result}))
    else:
        if count == 1:
            click.echo(str(result))
        else:
            assert isinstance(result, list)
            for p in result:
                click.echo(str(p))
