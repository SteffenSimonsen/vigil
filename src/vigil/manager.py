# Process start/stop/restart logic
"""Manager module — spawn and stop managed processes."""

from __future__ import annotations

import contextlib
import shlex
import subprocess
import time
from pathlib import Path

import psutil

from vigil.config import Config
from vigil.logs import open_log, trim_log
from vigil.state import ProcessRecord, StateManager


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

    effective_cwd = Path(cwd) if cwd else config.root
    log_file = open_log(config, name)
    try:
        import os

        child_env: dict[str, str] | None = None
        if env:
            child_env = os.environ.copy()
            child_env.update(env)

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

    started_at = time.time()
    # Prefer the actual process create_time from psutil for accuracy
    with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
        started_at = psutil.Process(proc.pid).create_time()

    record = ProcessRecord(
        name=name,
        pid=proc.pid,
        command=command,
        started_at=started_at,
        cwd=str(effective_cwd),
    )
    state.write(record)
    return record


def stop(config: Config, name: str) -> None:
    """Stop a managed process by *name*.

    Sends SIGTERM, waits up to the configured grace period, then SIGKILL if
    still alive. Removes the statefile entry and trims the log file.
    Idempotent — succeeds silently if the process is already dead.
    Raises ProcessNotFound if *name* is not in the statefile.
    """
    state = StateManager(config)
    existing = {r.name: r for r in state.read_all()}

    if name not in existing:
        raise ProcessNotFound(f"No managed process named {name!r}.")

    record = existing[name]
    if record.alive:
        _stop_process(record, grace=config.stop_grace_period)

    state.delete(name)
    trim_log(config, name, max_lines=config.log_retention_lines)


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


def stop_all(config: Config) -> list[str]:
    """Stop all managed processes.

    Returns the list of names that were stopped.
    """
    state = StateManager(config)
    names = [r.name for r in state.read_all()]
    for name in names:
        stop(config, name)
    return names


def _stop_process(record: ProcessRecord, grace: int = 5) -> None:
    """Send SIGTERM then SIGKILL to *record*'s PID."""
    try:
        proc = psutil.Process(record.pid)
        proc.terminate()
        try:
            proc.wait(timeout=grace)
        except psutil.TimeoutExpired:
            proc.kill()
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                proc.wait(timeout=5)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
