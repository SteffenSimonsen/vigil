"""vigil stop command."""

from __future__ import annotations

import json
import os
import sys
import time

import click

from vigil.commands._shared import complete_process_names, json_error, require_project
from vigil.config import Config
from vigil.registry import ProcessNotFound, make_registry
from vigil.state import StateCorruptedError, StateManager

_TIME_WAIT_POLL_INTERVAL = 0.5
_TIME_WAIT_TIMEOUT = 65.0


def wait_for_time_wait_clear(ports: list[int]) -> None:
    """Poll until all given ports leave TIME_WAIT state (or timeout)."""
    from vigil.scanner import port_socket_state

    deadline = time.monotonic() + _TIME_WAIT_TIMEOUT
    remaining: list[int] = list(ports)
    while remaining and time.monotonic() < deadline:
        remaining = [p for p in remaining if port_socket_state(p) == "time_wait"]
        if remaining:
            time.sleep(_TIME_WAIT_POLL_INTERVAL)


@click.command("stop")
@click.argument("name", required=False, default=None, shell_complete=complete_process_names)
@click.option("--all", "stop_all_flag", is_flag=True, help="Stop all managed processes.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
@click.option("--force", is_flag=True, help="Suppress cross-session ownership warning.")
@click.option(
    "--no-wait",
    "no_wait",
    is_flag=True,
    help="Return immediately without waiting for TIME_WAIT to clear.",
)
def cmd_stop(
    name: str | None, stop_all_flag: bool, as_json: bool, force: bool, no_wait: bool
) -> None:
    """Stop a managed process (or all processes with --all)."""
    root = require_project(as_json)
    config = Config(root=root)

    if stop_all_flag:
        try:
            results = make_registry(config).stop_all()
        except StateCorruptedError as e:
            if as_json:
                json_error(str(e), "state_corrupted")
            click.echo(str(e), err=True)
            sys.exit(1)

        if not no_wait:
            all_tw_ports = [p for r in results for p in r["time_wait_ports"]]
            if all_tw_ports:
                wait_for_time_wait_clear(all_tw_ports)

        if as_json:
            click.echo(json.dumps({"processes": list(results)}))
        else:
            if results:
                for r in results:
                    if r["status"] == "stopped":
                        click.echo(f"  \u2713 {r['name']} stopped")
                    elif r["status"] == "error":
                        msg = r.get("error") or "unknown error"
                        click.echo(f"  \u2717 {r['name']} error: {msg}")
                    else:
                        click.echo(f"  \u2713 {r['name']} cleaned up (was crashed)")
            else:
                click.echo("No managed processes to stop.")
        return

    if not name:
        if as_json:
            json_error("Provide a process name or use --all.")
        click.echo("Provide a process name or use --all.", err=True)
        sys.exit(1)

    # Cross-session ownership warning
    if not force and not as_json:
        current_session = os.environ.get("VIGIL_SESSION_ID")
        if current_session:
            try:
                records = {r.name: r for r in StateManager(config).read_all()}
                record = records.get(name)
                if record and record.session_id and record.session_id != current_session:
                    click.echo(
                        f"Warning: {name!r} was started by a different vigil session "
                        f"({record.session_id[:8]}).\n"
                        "Stopping anyway. Use --force to suppress this warning."
                    )
            except StateCorruptedError:
                pass

    try:
        result = make_registry(config).stop(name)
    except StateCorruptedError as e:
        if as_json:
            json_error(str(e), "state_corrupted")
        click.echo(str(e), err=True)
        sys.exit(1)
    except ProcessNotFound:
        # Idempotent: not running is a success
        if as_json:
            click.echo(json.dumps({"name": name, "status": "not_running"}))
        else:
            click.echo(f"{name!r} is not running")
        return

    if not no_wait and result["time_wait_ports"]:
        wait_for_time_wait_clear(result["time_wait_ports"])

    if as_json:
        click.echo(
            json.dumps(
                {
                    "name": name,
                    "status": result["status"],
                    "time_wait_ports": result["time_wait_ports"],
                }
            )
        )
    else:
        if result["status"] == "stopped":
            click.echo(f"Stopped {name!r}")
        else:
            click.echo(f"Cleaned up {name!r} (was crashed)")
        if result["time_wait_ports"]:
            ports_str = ", ".join(str(p) for p in result["time_wait_ports"])
            click.echo(
                f"  Warning: port(s) {ports_str} entered TIME_WAIT — "
                "they may be unavailable for ~60s."
            )
