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
from vigil.logs import open_log
from vigil.state import ProcessRecord, StateManager


class ProcessAlreadyRunning(Exception):
    """Raised when a name is already registered and the process is alive."""


class ProcessCrashed(Exception):
    """Raised when a name is registered but the process has already exited."""


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


def _stop_process(record: ProcessRecord) -> None:
    """Send SIGTERM then SIGKILL to *record*'s PID."""
    try:
        proc = psutil.Process(record.pid)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except psutil.TimeoutExpired:
            proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
