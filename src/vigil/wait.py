# Wait-for-ready polling
"""Readiness polling — block until a process's port is open."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from vigil.config import Config
from vigil.registry import make_registry

__all__ = [
    "CrashLooping",
    "PortMismatch",
    "ProcessDied",
    "ProcessNotFound",
    "WaitTimeout",
    "wait_for_ready",
]


class CrashLooping(Exception):
    """Raised when a managed process is detected as crash-looping (circuit open)."""


class WaitTimeout(Exception):
    """Raised when the timeout elapses before the process becomes ready."""


class ProcessDied(Exception):
    """Raised when the process dies while waiting for readiness."""


class ProcessNotFound(Exception):
    """Raised when the name is not in the statefile at all."""


class PortMismatch(Exception):
    """Raised when a process is alive but listening on a different port than assigned."""


_PORTLESS_GRACE_PERIOD = 2.0
"""Default seconds to confirm liveness for portless processes (no readiness strategy)."""


def wait_for_ready(
    config: Config,
    name: str,
    *,
    timeout: float = 30,
    port: int | None = None,
    http_path: str | None = None,
    log_match: str | None = None,
    ready_cmd: str | None = None,
    interval: float = 0.5,
) -> None:
    """Block until a named process is ready.

    Polls at *interval* seconds. On each tick:
    1. Check PID liveness — raises ProcessDied immediately if dead.
    2. Check for a listening port. If *port* is set, wait for that specific
       port; otherwise wait for any port the process is listening on.
    3. If *http_path* is set, also require a successful HTTP response.

    For portless processes (no port, http_path, log_match, or ready_cmd),
    applies a grace period of _PORTLESS_GRACE_PERIOD seconds: if the process
    stays alive for the full grace period, it is considered ready.

    Raises WaitTimeout if *timeout* seconds elapse without readiness.
    Raises ProcessDied if the process dies while polling.
    """
    start = time.monotonic()
    deadline = start + timeout
    portless = port is None and http_path is None and log_match is None and ready_cmd is None
    grace_deadline = start + min(timeout, _PORTLESS_GRACE_PERIOD) if portless else None
    reg = make_registry(config)

    # For log_match: open log file once, seek to EOF so pre-existing lines are skipped.
    log_file = None
    log_pattern = re.compile(log_match) if log_match else None
    if log_match:
        log_path = Path(config.logs_dir) / f"{name}.log"
        if log_path.exists():
            log_file = log_path.open("r")
            log_file.seek(0, 2)  # seek to end: only match lines written after wait starts

    try:
        while True:
            records = reg.all()
            record = next((r for r in records if r.name == name), None)
            if record is None:
                raise ProcessNotFound(f"No managed process named {name!r}")
            if not record.alive:
                raise ProcessDied(f"Process {name!r} died while waiting for readiness.")

            # Update crash-loop observation; fail fast if circuit is open.
            # Pass records= to avoid a second statefile read; observe_all snapshots
            # net_connections once internally and exposes per-process ports in obs["ports"].
            observations = reg.observe_all(records=records)
            obs = observations.get(name)
            if obs and obs["circuit_open"]:
                count = obs["crash_count"]
                raise CrashLooping(
                    f"Process {name!r} is crash-looping (crash_count={count}). "
                    f"Use 'vigil logs {name}' to investigate."
                )

            pid_ports = obs["ports"] if obs is not None else []

            # PortMismatch: process alive, has assigned port, but listening on wrong port.
            if record.port is not None and pid_ports and record.port not in pid_ports:
                raise PortMismatch(
                    f"Process {name!r} was assigned port {record.port} but is listening "
                    f"on {pid_ports}."
                )

            # Non-port readiness: log_match strategy
            if log_match is not None:
                assert log_pattern is not None
                if log_file is None:
                    log_path = Path(config.logs_dir) / f"{name}.log"
                    if log_path.exists():
                        log_file = log_path.open("r")
                if log_file is not None:
                    for line in log_file:
                        if log_pattern.search(line):
                            return

                if time.monotonic() >= deadline:
                    raise WaitTimeout(
                        f"Process {name!r} did not become ready within {timeout:.0f}s."
                    )
                time.sleep(interval)
                continue

            # Non-port readiness: ready_cmd strategy
            if ready_cmd is not None:
                result = subprocess.run(
                    ready_cmd,
                    shell=True,  # noqa: S602 — user-supplied command, intentional
                    capture_output=True,
                )
                if result.returncode == 0:
                    return

                if time.monotonic() >= deadline:
                    raise WaitTimeout(
                        f"Process {name!r} did not become ready within {timeout:.0f}s."
                    )
                time.sleep(interval)
                continue

            # Portless grace period: no readiness strategy configured.
            # Consider ready once the process has survived the grace period.
            if portless:
                assert grace_deadline is not None
                if time.monotonic() >= grace_deadline:
                    return  # process survived the grace period
                time.sleep(min(interval, grace_deadline - time.monotonic()))
                continue

            # Determine which port to check
            if port is not None:
                ready_port: int | None = port if port in pid_ports else None
            else:
                ready_port = pid_ports[0] if pid_ports else None

            if ready_port is not None:
                if http_path is None:
                    return  # Port open, no HTTP check required
                # HTTP check — any response (including 4xx/5xx) counts as ready
                import httpx  # lazy: only loaded when --http is used

                url = f"http://localhost:{ready_port}{http_path}"
                try:
                    httpx.get(url, timeout=2.0)
                    return
                except (httpx.RequestError, httpx.HTTPStatusError, httpx.InvalidURL):
                    pass

            if time.monotonic() >= deadline:
                raise WaitTimeout(f"Process {name!r} did not become ready within {timeout:.0f}s.")

            time.sleep(interval)
    finally:
        if log_file is not None:
            log_file.close()
