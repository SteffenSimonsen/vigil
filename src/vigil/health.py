# HTTP health checks
"""Fleet health checks — HTTP and TCP per managed process."""

from __future__ import annotations

import socket
import time
from typing import TypedDict

import httpx

from vigil.config import Config
from vigil.scanner import ports_for_pid
from vigil.state import StateManager


class HealthResult(TypedDict):
    name: str
    healthy: bool
    status: str | None
    latency_ms: float | None
    error: str | None


def _tcp_check(port: int, timeout: float) -> tuple[bool, str | None]:
    """Attempt a TCP connect to localhost:port. Returns (success, error_message)."""
    try:
        with socket.create_connection(("localhost", port), timeout=timeout):
            pass
        return True, None
    except OSError as exc:
        return False, str(exc)


def check_health(
    config: Config,
    *,
    endpoint: str = "/",
    timeout: float | None = None,
) -> list[HealthResult]:
    """Check the health of all alive managed processes.

    For each alive process:
    - If it has listening ports, sends a GET request to the first port at *endpoint*.
      Any HTTP response (including 4xx/5xx) counts as healthy.
    - If HTTP fails, falls back to a TCP connect check.
    - If it has no listening ports, reports status "no-port" (treated as healthy).

    Returns a list of HealthResult dicts, one per alive process.
    """
    effective_timeout = timeout if timeout is not None else config.health_check_timeout
    state = StateManager(config)
    records = [r for r in state.read_all() if r.alive]

    results: list[HealthResult] = []
    for record in records:
        ports = ports_for_pid(record.pid)
        if not ports:
            results.append(
                HealthResult(
                    name=record.name,
                    healthy=True,
                    status="no-port",
                    latency_ms=None,
                    error=None,
                )
            )
            continue

        port = ports[0]
        url = f"http://localhost:{port}{endpoint}"
        t0 = time.monotonic()
        try:
            response = httpx.get(url, timeout=effective_timeout)
            latency_ms = (time.monotonic() - t0) * 1000
            results.append(
                HealthResult(
                    name=record.name,
                    healthy=True,
                    status=str(response.status_code),
                    latency_ms=latency_ms,
                    error=None,
                )
            )
        except (httpx.RequestError, httpx.HTTPStatusError, httpx.InvalidURL):
            # HTTP failed — fall back to TCP connect
            latency_ms = (time.monotonic() - t0) * 1000
            tcp_ok, tcp_err = _tcp_check(port, timeout=effective_timeout)
            results.append(
                HealthResult(
                    name=record.name,
                    healthy=tcp_ok,
                    status="tcp-ok" if tcp_ok else None,
                    latency_ms=latency_ms,
                    error=None if tcp_ok else tcp_err,
                )
            )

    return results
