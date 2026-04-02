# Process start/stop/restart logic
"""Manager module — spawn and stop managed processes."""

from __future__ import annotations

import contextlib
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Literal, TypedDict

import psutil

from vigil.config import Config
from vigil.logs import open_log, trim_log
from vigil.scanner import port_socket_state, ports_for_pid
from vigil.state import ProcessRecord, StateManager


class StopResult(TypedDict):
    status: Literal["stopped", "cleaned_up"]
    time_wait_ports: list[int]


class ProcessAlreadyRunning(Exception):
    """Raised when a name is already registered and the process is alive."""


class ProcessCrashed(Exception):
    """Raised when a name is registered but the process has already exited."""


class ProcessNotFound(Exception):
    """Raised when stop is called for a name not in the statefile."""


def start(
    config: Config,
    name: str,
    command: str,
    *,
    force: bool = False,
    env: dict[str, str] | None = None,
    env_file: str | None = None,
    cwd: str | None = None,
) -> ProcessRecord:
    """Spawn *command* as a detached child process named *name*.

    Returns the new ProcessRecord. Raises ProcessAlreadyRunning if *name* is
    registered and alive, ProcessCrashed if registered but dead — unless
    *force* is True, in which case the old process is stopped and a fresh one
    is started.
    """
    state = StateManager(config)
    existing = {r.name: r for r in state.read_all()}

    if name in existing:
        rec = existing[name]
        if rec.alive:
            if not force:
                raise ProcessAlreadyRunning(
                    f"Process {name!r} is already running (pid {rec.pid}). "
                    "Use --force to restart it."
                )
            _stop_process(rec)
        else:
            if not force:
                raise ProcessCrashed(
                    f"Process {name!r} crashed (pid {rec.pid}). Use --force to start a fresh one."
                )

    if not name.strip():
        raise ValueError("Process name cannot be empty.")

    if len(name) > 200:
        raise ValueError(
            f"Process name is too long ({len(name)} characters)."
            " Names must be 200 characters or fewer."
        )

    if "/" in name or "\\" in name or name == "..":
        raise ValueError(
            f"Process name {name!r} is invalid. Names may not contain '/', '\\', or be '..'."
        )

    if not command.strip():
        raise ValueError("Command cannot be empty")

    effective_cwd = Path(cwd) if cwd else config.root
    log_file = open_log(config, name)

    # Load env file vars and merge with explicit env overrides
    file_vars: dict[str, str] = {}
    if env_file:
        from dotenv import dotenv_values

        loaded = dotenv_values(env_file)
        file_vars = {k: v for k, v in loaded.items() if v is not None}

    merged_env: dict[str, str] = {**file_vars, **(env or {})}
    # Record key names only — never values
    recorded_env_keys = sorted(merged_env.keys())

    try:
        import os

        child_env: dict[str, str] | None = None
        if merged_env:
            child_env = os.environ.copy()
            child_env.update(merged_env)

        if sys.platform == "win32":
            # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS — Windows equivalent of setsid()
            _CREATE_NEW_PROCESS_GROUP = 0x00000200
            _DETACHED_PROCESS = 0x00000008
            proc = subprocess.Popen(
                shlex.split(command),
                stdout=log_file,
                stderr=log_file,
                stdin=subprocess.DEVNULL,
                cwd=str(effective_cwd),
                creationflags=_CREATE_NEW_PROCESS_GROUP | _DETACHED_PROCESS,
                env=child_env,
            )
        else:
            proc = subprocess.Popen(
                shlex.split(command),
                stdout=log_file,
                stderr=log_file,
                stdin=subprocess.DEVNULL,
                cwd=str(effective_cwd),
                start_new_session=True,
                env=child_env,
            )
    finally:
        log_file.close()

    started_at: float | None = None
    with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
        started_at = psutil.Process(proc.pid).create_time()

    record = ProcessRecord(
        name=name,
        pid=proc.pid,
        command=command,
        started_at=started_at,
        cwd=str(effective_cwd),
        env_file=env_file,
        env_keys=recorded_env_keys,
    )
    state.write(record)
    return record


def stop(config: Config, name: str) -> StopResult:
    """Stop a managed process by *name*.

    Sends SIGTERM, waits up to the configured grace period, then SIGKILL if
    still alive. Removes the statefile entry and trims the log file.
    Idempotent — succeeds silently if the process is already dead.
    Raises ProcessNotFound if *name* is not in the statefile.

    Returns a StopResult with:
    - ``status``: ``"stopped"`` if the process was alive, ``"cleaned_up"`` if already exited.
    - ``time_wait_ports``: ports that entered TIME_WAIT after the process was killed.
    """
    state = StateManager(config)
    existing = {r.name: r for r in state.read_all()}

    if name not in existing:
        raise ProcessNotFound(f"No managed process named {name!r}.")

    record = existing[name]
    was_alive = record.alive

    held_ports: list[int] = []
    if was_alive:
        held_ports = ports_for_pid(record.pid)
        _stop_process(record, grace=config.stop_grace_period)

    state.delete(name)
    trim_log(config, name, max_lines=config.log_retention_lines)

    tw_ports = [p for p in held_ports if port_socket_state(p) == "time_wait"]
    return StopResult(
        status="stopped" if was_alive else "cleaned_up",
        time_wait_ports=tw_ports,
    )


def restart(config: Config, name: str) -> ProcessRecord:
    """Stop *name* and immediately restart it with its recorded command.

    The log file is trimmed between stop and start. Returns the new ProcessRecord.
    Raises ProcessNotFound if *name* is not in the statefile.
    """
    state = StateManager(config)
    existing = {r.name: r for r in state.read_all()}

    if name not in existing:
        raise ProcessNotFound(f"No managed process named {name!r}.")

    record = existing[name]
    command = record.command
    cwd = record.cwd

    stop(config, name)
    return start(config, name, command, force=True, cwd=cwd)


def remove(config: Config, name: str, *, force: bool = False) -> None:
    """Remove a process entry from the statefile.

    Raises ProcessNotFound if *name* is not registered.
    Raises ProcessAlreadyRunning if the process is alive and *force* is False.
    With *force=True*, removes the entry without stopping the process.
    """
    state = StateManager(config)
    existing = {r.name: r for r in state.read_all()}

    if name not in existing:
        raise ProcessNotFound(f"No managed process named {name!r}.")

    record = existing[name]
    if record.alive and not force:
        raise ProcessAlreadyRunning(
            f"Process {name!r} is still running (pid {record.pid}). "
            "Use --force to remove the registry entry without stopping it."
        )

    state.delete(name)


def stop_all(config: Config) -> list[dict[str, str | list[int]]]:
    """Stop all managed processes.

    Returns a list of dicts with ``name``, ``status``, and ``time_wait_ports``.
    ``status`` is ``"stopped"`` if the process was alive, or ``"cleaned_up"`` if already dead.
    """
    state = StateManager(config)
    names = [r.name for r in state.read_all()]
    results: list[dict[str, str | list[int]]] = []
    for name in names:
        result = stop(config, name)
        results.append(
            {"name": name, "status": result["status"], "time_wait_ports": result["time_wait_ports"]}
        )
    return results


def _stop_process(record: ProcessRecord, grace: int = 5) -> None:
    """Send SIGTERM then SIGKILL to the entire process tree rooted at *record*'s PID.

    On Windows, delegates to ``taskkill /F /T`` which terminates the whole job tree.
    On Unix, children are signalled before the parent so workers cannot be re-adopted.
    Uses psutil.wait_procs() to handle races where children die mid-walk.
    """
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(record.pid)],
            check=False,
        )
        return

    try:
        parent = psutil.Process(record.pid)
        children = parent.children(recursive=True)
        procs = children + [parent]
    except psutil.NoSuchProcess:
        return

    # Graceful pass — children first, then parent
    for p in procs:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            p.terminate()

    _, alive = psutil.wait_procs(procs, timeout=grace)

    # Forceful pass on survivors
    for p in alive:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            p.kill()

    psutil.wait_procs(alive, timeout=5)
