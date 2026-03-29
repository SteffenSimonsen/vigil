# Wait-for-ready polling
"""Readiness polling — block until a process's port is open."""

from __future__ import annotations

import time

import httpx

from vigil.config import Config
from vigil.scanner import ports_for_pid
from vigil.state import StateManager


class WaitTimeout(Exception):
    """Raised when the timeout elapses before the process becomes ready."""


class ProcessDied(Exception):
    """Raised when the process dies while waiting for readiness."""


def wait_for_ready(
    config: Config,
    name: str,
    *,
    timeout: float = 30,
    port: int | None = None,
    http_path: str | None = None,
    interval: float = 0.5,
) -> None:
    """Block until a named process is ready.

    Polls at *interval* seconds. On each tick:
    1. Check PID liveness — raises ProcessDied immediately if dead.
    2. Check for a listening port. If *port* is set, wait for that specific
       port; otherwise wait for any port the process is listening on.
    3. If *http_path* is set, also require a successful HTTP response.

    Raises WaitTimeout if *timeout* seconds elapse without readiness.
    Raises ProcessDied if the process dies while polling.
    """
    state = StateManager(config)
    deadline = time.monotonic() + timeout

    while True:
        records = {r.name: r for r in state.read_all()}
        if name not in records or not records[name].alive:
            raise ProcessDied(f"Process {name!r} died while waiting for readiness.")

        pid = records[name].pid

        # Determine which port to check
        if port is not None:
            pid_ports = ports_for_pid(pid)
            ready_port: int | None = port if port in pid_ports else None
        else:
            pid_ports = ports_for_pid(pid)
            ready_port = pid_ports[0] if pid_ports else None

        if ready_port is not None:
            if http_path is None:
                return  # Port open, no HTTP check required
            # HTTP check — any response (including 4xx/5xx) counts as ready
            url = f"http://localhost:{ready_port}{http_path}"
            try:
                httpx.get(url, timeout=2.0)
                return
            except (httpx.RequestError, httpx.HTTPStatusError):
                pass

        if time.monotonic() >= deadline:
            raise WaitTimeout(f"Process {name!r} did not become ready within {timeout:.0f}s.")

        time.sleep(interval)
