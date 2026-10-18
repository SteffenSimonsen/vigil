"""vigil scan command."""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import click

from vigil.commands._shared import json_error
from vigil.config import Config, ConfigError, find_vigil_root
from vigil.docker import enrich as docker_enrich
from vigil.registry import make_registry
from vigil.scanner import ports_for_pid, scan_all, scan_ports

_DEFAULT_DEV_PORTS: list[int] = [
    *range(3000, 4000),
    *range(4000, 5000),
    *range(5000, 6000),
    *range(8000, 9000),
    *range(9000, 10000),
    5432,
    6379,
    27017,
]


@click.command("scan")
@click.option("--port", "port_filter", default=None, type=int, help="Check a single port.")
@click.option("--range", "range_filter", default=None, metavar="START-END", help="Check a range.")
@click.option("--all", "scan_all_flag", is_flag=True, help="Full OS socket table.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_scan(
    port_filter: int | None,
    range_filter: str | None,
    scan_all_flag: bool,
    as_json: bool,
) -> None:
    """Show the port landscape (default: dev ranges)."""
    if scan_all_flag:
        listeners = scan_all()
    elif port_filter is not None:
        listeners = scan_ports([port_filter])
    elif range_filter is not None:
        start_s, _, end_s = range_filter.partition("-")
        try:
            ports = list(range(int(start_s), int(end_s) + 1))
        except ValueError:
            msg = (
                f"Invalid --range {range_filter!r}: expected START-END with integers"
                " (e.g. 3000-4000)."
            )
            if as_json:
                json_error(msg)
            click.echo(msg, err=True)
            sys.exit(1)
        listeners = scan_ports(ports)
    else:
        managed_ports: list[int] = []
        with contextlib.suppress(ConfigError, Exception):
            root = find_vigil_root(Path.cwd())
            config = Config(root=root)
            records = make_registry(config).all()
            dev_port_set = set(_DEFAULT_DEV_PORTS)
            for record in records:
                if record.alive:
                    for port in ports_for_pid(record.pid):
                        if port not in dev_port_set:
                            managed_ports.append(port)
        listeners = scan_ports(_DEFAULT_DEV_PORTS + managed_ports)

    docker_enrich(listeners)

    if as_json:
        click.echo(json.dumps({"listeners": list(listeners)}, indent=2))
    else:
        if not listeners:
            click.echo("No listeners found.")
            return
        for entry in listeners:
            proc = entry["process"] or "?"
            docker = entry["docker"]
            if docker:
                docker_suffix = (
                    f"  [{docker['container_name']}  {docker['image']}"
                    + (f"  {docker['compose_service']}" if docker["compose_service"] else "")
                    + "]"
                )
            else:
                docker_suffix = ""
            click.echo(f"  :{entry['port']:<6} pid {entry['pid']}  {proc}{docker_suffix}")
