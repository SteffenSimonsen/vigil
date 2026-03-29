"""Vigil CLI entry point."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click
from click.shell_completion import CompletionItem

from vigil.config import Config, ConfigError, find_vigil_root
from vigil.docker import enrich as docker_enrich
from vigil.docker import lookup as docker_lookup
from vigil.free import free_port
from vigil.health import check_health
from vigil.init import init_project, parse_process_spec, prompt_for_processes
from vigil.logs import LogNotFound, read_log
from vigil.manager import ProcessAlreadyRunning, ProcessCrashed, ProcessNotFound
from vigil.manager import remove as manager_remove
from vigil.manager import restart as manager_restart
from vigil.manager import start as manager_start
from vigil.manager import stop as manager_stop
from vigil.manager import stop_all as manager_stop_all
from vigil.open import UnknownProcess, resolve_url
from vigil.scanner import next_free_port, ports_for_pid, scan_all, scan_ports
from vigil.state import StateManager
from vigil.vigilfile import ParseError as VigilfileParseError
from vigil.vigilfile import down as vigilfile_down
from vigil.vigilfile import load as vigilfile_load
from vigil.vigilfile import up as vigilfile_up
from vigil.wait import ProcessDied, WaitTimeout, wait_for_ready
from vigil.wait import ProcessNotFound as WaitProcessNotFound


def _complete_process_names(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    """Shell completion callback: return process names from the statefile."""
    try:
        root = find_vigil_root(Path.cwd())
        config = Config(root=root)
        records = StateManager(config).read_all()
        return [CompletionItem(r.name) for r in records if r.name.startswith(incomplete)]
    except ConfigError:
        return []


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


def _json_error(message: str, code: int = 1) -> None:
    """Emit a JSON error to stdout and exit. Used when --json is active."""
    click.echo(json.dumps({"error": message, "code": code}))
    sys.exit(code)


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
        if as_json:
            _json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)
    except ProcessCrashed as e:
        if as_json:
            _json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"name": record.name, "pid": record.pid, "status": "started"}))
    else:
        click.echo(f"Started {record.name!r} (pid {record.pid})")


@main.command("stop")
@click.argument("name", required=False, default=None, shell_complete=_complete_process_names)
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
        if as_json:
            _json_error("Provide a process name or use --all.")
        click.echo("Provide a process name or use --all.", err=True)
        sys.exit(1)

    try:
        manager_stop(config, name)
    except ProcessNotFound as e:
        if as_json:
            _json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"name": name, "status": "stopped"}))
    else:
        click.echo(f"Stopped {name!r}")


@main.command("restart")
@click.argument("name", shell_complete=_complete_process_names)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_restart(name: str, as_json: bool) -> None:
    """Stop and restart a managed process using its recorded command."""
    root = _require_project()
    config = Config(root=root)

    try:
        record = manager_restart(config, name)
    except ProcessNotFound as e:
        if as_json:
            _json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"name": record.name, "pid": record.pid, "status": "restarted"}))
    else:
        click.echo(f"Restarted {record.name!r} (pid {record.pid})")


@main.command("remove")
@click.argument("name")
@click.option("--force", is_flag=True, help="Remove registry entry without stopping the process.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_remove(name: str, force: bool, as_json: bool) -> None:
    """Remove a process entry from the registry."""
    root = _require_project()
    config = Config(root=root)

    try:
        manager_remove(config, name, force=force)
    except ProcessNotFound as e:
        if as_json:
            _json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)
    except ProcessAlreadyRunning as e:
        if as_json:
            _json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"name": name, "status": "removed"}))
    else:
        click.echo(f"Removed {name!r}")


@main.command("logs")
@click.argument("name", shell_complete=_complete_process_names)
@click.option("--tail", default=50, show_default=True, help="Number of lines to show.")
@click.option("--follow", "follow", is_flag=True, help="Stream new output (tail -f style).")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_logs(name: str, tail: int, follow: bool, as_json: bool) -> None:
    """Show log output for a managed process."""
    root = _require_project()
    config = Config(root=root)

    if follow:
        _follow_logs(config, name)
        return

    try:
        lines = read_log(config, name, tail=tail)
    except LogNotFound as e:
        if as_json:
            _json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"lines": lines}))
    else:
        for line in lines:
            click.echo(line)


def _follow_logs(config: Config, name: str) -> None:
    """Stream log file lines until KeyboardInterrupt."""
    import time

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


@main.command("wait")
@click.argument("name", shell_complete=_complete_process_names)
@click.option("--timeout", default=30.0, show_default=True, help="Seconds before giving up.")
@click.option("--port", "port_override", default=None, type=int, help="Wait for a specific port.")
@click.option("--http", "http_flag", is_flag=True, default=False, help="Wait for HTTP on /.")
@click.option(
    "--http-path",
    "http_path_value",
    default=None,
    type=str,
    metavar="PATH",
    help="Wait for HTTP response on PATH (implies --http). E.g. --http-path=/health.",
)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_wait(
    name: str,
    timeout: float,
    port_override: int | None,
    http_flag: bool,
    http_path_value: str | None,
    as_json: bool,
) -> None:
    """Block until a managed process is ready (port open, optional HTTP check).

    Use --http to check for any HTTP response on / (the default path).
    Use --http-path=/health to check on a custom path.
    """
    root = _require_project()
    config = Config(root=root)

    http_path: str | None = http_path_value if http_path_value else ("/" if http_flag else None)

    try:
        wait_for_ready(config, name, timeout=timeout, port=port_override, http_path=http_path)
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


@main.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_status(as_json: bool) -> None:
    """Show status of all managed processes."""
    root = _require_project()
    config = Config(root=root)
    records = StateManager(config).read_all()

    managed: list[dict[str, Any]] = []
    for record in records:
        if record.alive:
            entry_ports = ports_for_pid(record.pid)
            managed.append(
                {
                    "name": record.name,
                    "command": record.command,
                    "pid": record.pid,
                    "alive": True,
                    "ports": entry_ports,
                    "docker": docker_lookup(entry_ports),
                }
            )
        else:
            managed.append(
                {
                    "name": record.name,
                    "command": record.command,
                    "pid": None,
                    "alive": False,
                    "crashed": True,
                    "ports": [],
                    "docker": None,
                }
            )

    if as_json:
        click.echo(json.dumps({"managed": managed}, indent=2))
        return

    if not managed:
        click.echo("No managed processes.")
        return

    for entry in managed:
        if entry["alive"]:
            ports_str = "  ".join(f":{p}" for p in entry["ports"])
            click.echo(
                f"  {entry['name']:<12} \u25cf alive    PID {entry['pid']}  {ports_str}"
                f"  ({entry['command']})"
            )
        else:
            click.echo(f"  {entry['name']:<12} \u2716 crashed  ({entry['command']})")


@main.command("scan")
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
        ports = list(range(int(start_s), int(end_s) + 1))
        listeners = scan_ports(ports)
    else:
        listeners = scan_ports(_DEFAULT_DEV_PORTS)

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


@main.command("health")
@click.option("--endpoint", default="/", show_default=True, help="HTTP path to check.")
@click.option("--timeout", "timeout_sec", default=None, type=float, help="Seconds per check.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_health(endpoint: str, timeout_sec: float | None, as_json: bool) -> None:
    """Check the health of all alive managed processes."""
    root = _require_project()
    config = Config(root=root)

    results = check_health(config, endpoint=endpoint, timeout=timeout_sec)

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


@main.command("free")
@click.argument("port", type=int)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_free(port: int, as_json: bool) -> None:
    """Free a port regardless of what is using it (managed, Docker, or unmanaged)."""
    root = _require_project()
    config = Config(root=root)

    result = free_port(config, port)

    if as_json:
        click.echo(json.dumps(result))
    else:
        was = result["was"]
        if was == "free":
            click.echo(f"Port {port} is already free.")
        else:
            click.echo(f"Freed port {port} ({was}).")


@main.command("open")
@click.argument("target", shell_complete=_complete_process_names)
@click.option("--json", "as_json", is_flag=True, help="Output JSON without opening a browser.")
def cmd_open(target: str, as_json: bool) -> None:
    """Open a service or port in the browser."""
    root = _require_project()
    config = Config(root=root)

    try:
        url = resolve_url(config, target)
    except UnknownProcess as e:
        if as_json:
            _json_error(str(e))
        click.echo(str(e), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"url": url}))
        return

    import webbrowser

    webbrowser.open(url)
    click.echo(f"Opening {url}")


@main.command("next")
@click.argument("start", default=3000, type=int, required=False)
@click.option("--count", default=1, type=int, show_default=True, help="Number of free ports.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_next(start: int, count: int, as_json: bool) -> None:
    """Find the next free port(s) starting from START (default 3000)."""
    result = next_free_port(start, count=count)

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


@main.command("up")
@click.option(
    "--only",
    "only_names",
    default=None,
    metavar="NAME,...",
    help="Comma-separated subset of processes to start.",
)
@click.option("--force", is_flag=True, help="Restart processes even if already running.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_up(only_names: str | None, force: bool, as_json: bool) -> None:
    """Start all Vigilfile processes in order."""
    root = _require_project()
    config = Config(root=root)

    try:
        entries = vigilfile_load(root)
    except VigilfileParseError as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    only: list[str] | None = [n.strip() for n in only_names.split(",")] if only_names else None
    results = vigilfile_up(config, entries, only=only, force=force)

    if as_json:
        click.echo(json.dumps({"processes": results}, indent=2))
        return

    for r in results:
        status = r["status"]
        name = r["name"]
        if status == "started":
            click.echo(f"  {name}: started (pid {r['pid']})")
        elif status == "skipped":
            click.echo(f"  {name}: already running, skipped")
        else:
            click.echo(f"  {name}: failed — {r['error']}")


@main.command("down")
@click.option(
    "--only",
    "only_names",
    default=None,
    metavar="NAME,...",
    help="Comma-separated subset of processes to stop.",
)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def cmd_down(only_names: str | None, as_json: bool) -> None:
    """Stop all Vigilfile processes in reverse order."""
    root = _require_project()
    config = Config(root=root)

    try:
        entries = vigilfile_load(root)
    except VigilfileParseError as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    only: list[str] | None = [n.strip() for n in only_names.split(",")] if only_names else None
    results = vigilfile_down(config, entries, only=only)

    if as_json:
        click.echo(json.dumps({"processes": results}, indent=2))
        return

    for r in results:
        name = r["name"]
        if r["status"] == "stopped":
            click.echo(f"  {name}: stopped")
        else:
            click.echo(f"  {name}: not running")
