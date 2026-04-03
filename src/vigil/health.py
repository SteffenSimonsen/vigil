# HTTP health checks
"""Fleet health checks — HTTP and TCP per managed process."""

from __future__ import annotations

import socket
import time
from typing import TypedDict

from vigil.config import Config
from vigil.crash_loop import observe as _observe_crash_loop
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
    import psutil  # lazy: only loaded when vigil health is invoked

    effective_timeout = timeout if timeout is not None else config.health_check_timeout
    state = StateManager(config)
    all_records = state.read_all()
    alive_names = {r.name for r in all_records if r.alive}
    records = [r for r in all_records if r.alive]

    # Snapshot the socket table once for all PID→port lookups in this invocation.
    conns = psutil.net_connections(kind="inet")

    results: list[HealthResult] = []
    for record in records:
        # Update crash-loop state and check circuit
        _observe_crash_loop(config, record.name)
        # Re-read updated record
        updated = {r.name: r for r in StateManager(config).read_all()}
        if record.name in updated and updated[record.name].circuit_open:
            count = updated[record.name].crash_count
            results.append(
                HealthResult(
                    name=record.name,
                    healthy=False,
                    status="crash_looping",
                    latency_ms=None,
                    error=f"Process is crash-looping (crash_count={count}). "
                    f"Use 'vigil logs {record.name}' to investigate.",
                )
            )
            continue

        # Degraded: alive but a dependency is down
        dead_deps = [d for d in record.depends_on if d not in alive_names]
        if dead_deps:
            results.append(
                HealthResult(
                    name=record.name,
                    healthy=False,
                    status="degraded",
                    latency_ms=None,
                    error=f"dependency down: {', '.join(dead_deps)}",
                )
            )
            continue

        ports: list[int] = []
        for c in conns:
            if c.pid == record.pid and c.status == "LISTEN":
                p = getattr(c.laddr, "port", None)
                if isinstance(p, int):
                    ports.append(p)
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

        import httpx  # lazy: only loaded when vigil health is invoked

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
