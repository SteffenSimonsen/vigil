# Wait-for-ready polling
"""Readiness polling — block until a process's port is open."""

from __future__ import annotations

import time

from vigil.config import Config
from vigil.registry import make_registry

__all__ = ["CrashLooping", "ProcessDied", "ProcessNotFound", "WaitTimeout", "wait_for_ready"]


class CrashLooping(Exception):
    """Raised when a managed process is detected as crash-looping (circuit open)."""


class WaitTimeout(Exception):
    """Raised when the timeout elapses before the process becomes ready."""


class ProcessDied(Exception):
    """Raised when the process dies while waiting for readiness."""


class ProcessNotFound(Exception):
    """Raised when the name is not in the statefile at all."""


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
    deadline = time.monotonic() + timeout
    reg = make_registry(config)

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
