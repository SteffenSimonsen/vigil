# HTTP health checks
"""Fleet health checks — HTTP and TCP per managed process."""

from __future__ import annotations

import socket
import time
from collections.abc import Mapping
from typing import Protocol, TypedDict

from vigil.config import Config
from vigil.registry import ProcessRegistry, make_registry
from vigil.state import ProcessRecord


class HealthResult(TypedDict):
    name: str
    healthy: bool
    ready: bool
    status: str | None
    latency_ms: float | None
    error: str | None


class HttpProber(Protocol):
    def get(self, url: str, *, timeout: float) -> int:
        """Perform a GET. Returns HTTP status code. Raises httpx.RequestError on failure."""
        ...


class _DefaultHttpProber:
    def get(self, url: str, *, timeout: float) -> int:
        import httpx

        response = httpx.get(url, timeout=timeout)
        return response.status_code


def _tcp_check(port: int, timeout: float) -> tuple[bool, str | None]:
    """Attempt a TCP connect to localhost:port. Returns (success, error_message)."""
    try:
        with socket.create_connection(("localhost", port), timeout=timeout):
            pass
        return True, None
    except OSError as exc:
        return False, str(exc)


class HealthChecker:
    def __init__(
        self,
        registry: ProcessRegistry,
        *,
        endpoint: str = "/",
        timeout: float | None = None,
        http_prober: HttpProber | None = None,
    ) -> None:
        self._registry = registry
        self._endpoint = endpoint
        self._timeout = timeout
        self._http_prober: HttpProber = http_prober or _DefaultHttpProber()

    def _effective_timeout(self) -> float:
        if self._timeout is not None:
            return self._timeout
        return self._registry.config.health_check_timeout

    def _check_record(
        self,
        record: ProcessRecord,
        alive_names: set[str],
        ports_by_name: Mapping[str, list[int]],
    ) -> HealthResult:
        dead_deps = [d for d in record.depends_on if d not in alive_names]
        if dead_deps:
            return HealthResult(
                name=record.name,
                healthy=False,
                ready=False,
                status="degraded",
                latency_ms=None,
                error=f"dependency down: {', '.join(dead_deps)}",
            )

        ports = ports_by_name.get(record.name, [])

        # PortMismatch: process has an assigned port but is listening elsewhere.
        if record.port is not None and ports and record.port not in ports:
            return HealthResult(
                name=record.name,
                healthy=False,
                ready=False,
                status="port_mismatch",
                latency_ms=None,
                error=(f"Process was assigned port {record.port} but is listening on {ports}."),
            )

        if not ports:
            return HealthResult(
                name=record.name,
                healthy=True,
                ready=False,
                status="port-pending" if record.port is not None else "no-port",
                latency_ms=None,
                error=None,
            )

        port = ports[0]
        url = f"http://localhost:{port}{self._endpoint}"
        effective_timeout = self._effective_timeout()
        t0 = time.monotonic()
        import httpx

        try:
            status_code = self._http_prober.get(url, timeout=effective_timeout)
            latency_ms = (time.monotonic() - t0) * 1000
            return HealthResult(
                name=record.name,
                healthy=True,
                ready=True,
                status=str(status_code),
                latency_ms=latency_ms,
                error=None,
            )
        except (httpx.RequestError, httpx.InvalidURL):
            latency_ms = (time.monotonic() - t0) * 1000
            tcp_ok, tcp_err = _tcp_check(port, timeout=effective_timeout)
            return HealthResult(
                name=record.name,
                healthy=tcp_ok,
                ready=False,
                status="tcp-ok" if tcp_ok else None,
                latency_ms=latency_ms,
                error=None if tcp_ok else tcp_err,
            )

    def check_all(self) -> list[HealthResult]:
        """Check health of all alive managed processes. Single statefile read."""
        records = self._registry.all()
        ports_by_name = self._registry.ports_by_process(records=records)

        alive_names = {r.name for r in records if r.alive}
        alive_records = [r for r in records if r.alive]

        return [self._check_record(r, alive_names, ports_by_name) for r in alive_records]

    def check_one(self, name: str) -> HealthResult | None:
        """Check health of a single process. Returns None if not found or dead."""
        records = self._registry.all()
        ports_by_name = self._registry.ports_by_process(records=records)

        alive_names = {r.name for r in records if r.alive}

        record = next((r for r in records if r.name == name), None)
        if record is None or not record.alive:
            return None

        return self._check_record(record, alive_names, ports_by_name)


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
    reg = make_registry(config)
    return HealthChecker(reg, endpoint=endpoint, timeout=timeout).check_all()
