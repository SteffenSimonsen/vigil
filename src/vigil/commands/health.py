"""vigil health command."""

from __future__ import annotations

import json
import sys

import click

from vigil.commands._shared import json_error, require_project
from vigil.config import Config
from vigil.health import check_health
from vigil.state import StateCorruptedError


@click.command("health")
@click.option("--endpoint", default="/", show_default=True, help="HTTP path to check.")
@click.option("--timeout", "timeout_sec", default=None, type=float, help="Seconds per check.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_health(endpoint: str, timeout_sec: float | None, as_json: bool) -> None:
    """Check the health of all alive managed processes."""
    if not endpoint.startswith("/"):
        if as_json:
            click.echo(json.dumps({"error": "Endpoint must start with /"}))
        else:
            click.echo("Error: Endpoint must start with /")
        sys.exit(1)

    root = require_project(as_json)
    config = Config(root=root)

    try:
        results = check_health(config, endpoint=endpoint, timeout=timeout_sec)
    except StateCorruptedError as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"processes": list(results)}, indent=2))
        return

    if not results:
        click.echo("No alive managed processes.")
        return

    for r in results:
        if r["healthy"]:
            latency = f"  {r['latency_ms']:.0f}ms" if r["latency_ms"] is not None else ""
            click.echo(f"  {r['name']:<12} \u2713 healthy  {r['status'] or ''}{latency}")
        else:
            click.echo(f"  {r['name']:<12} \u2717 unhealthy  {r['error'] or ''}")
