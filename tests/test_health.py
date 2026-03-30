"""Tests for vigil health — fleet HTTP and TCP health checks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from vigil.config import Config
from vigil.health import check_health
from vigil.state import ProcessRecord, StateManager


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    (tmp_path / ".vigil").mkdir()
    return Config(root=tmp_path)


def _write_record(
    cfg: Config,
    name: str = "web",
    pid: int = 12345,
    started_at: float = 1000.0,
    port: int | None = None,
) -> ProcessRecord:
    record = ProcessRecord(
        name=name,
        pid=pid,
        command="python -m http.server",
        started_at=started_at,
        port=port,
    )
    StateManager(cfg).write(record)
    return record


def _alive_proc_mock(started_at: float = 1000.0) -> MagicMock:
    proc = MagicMock()
    proc.create_time.return_value = started_at
    return proc


def _listen_conn(pid: int, port: int) -> MagicMock:
    conn = MagicMock()
    conn.pid = pid
    conn.status = "LISTEN"
    conn.laddr.port = port
    return conn


class TestCheckHealth:
    # --- Cycle 1: HTTP healthy ---

    def test_healthy_http_process_returns_healthy_result(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[_listen_conn(12345, 8080)]),
            respx.mock,
        ):
            respx.get("http://localhost:8080/").mock(return_value=httpx.Response(200))
            results = check_health(cfg)

        assert len(results) == 1
        r = results[0]
        assert r["name"] == "web"
        assert r["healthy"] is True
        assert r["status"] == "200"
        assert r["latency_ms"] is not None
        assert r["latency_ms"] >= 0
        assert r["error"] is None

    # --- Cycle 2: HTTP unhealthy (connection refused) ---

    def test_unhealthy_when_http_connection_fails(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[_listen_conn(12345, 8080)]),
            respx.mock,
        ):
            respx.get("http://localhost:8080/").mock(side_effect=httpx.ConnectError("refused"))
            results = check_health(cfg)

        assert len(results) == 1
        r = results[0]
        assert r["healthy"] is False
        assert r["status"] is None
        assert r["error"] is not None

    # --- Cycle 3: HTTP timeout ---

    def test_unhealthy_when_http_times_out(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[_listen_conn(12345, 8080)]),
            respx.mock,
        ):
            respx.get("http://localhost:8080/").mock(side_effect=httpx.TimeoutException("timeout"))
            results = check_health(cfg)

        assert len(results) == 1
        r = results[0]
        assert r["healthy"] is False
        assert r["error"] is not None

    # --- Cycle 4: any HTTP response (4xx/5xx) counts as healthy ---

    def test_non_2xx_response_counts_as_healthy(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[_listen_conn(12345, 8080)]),
            respx.mock,
        ):
            respx.get("http://localhost:8080/").mock(return_value=httpx.Response(503))
            results = check_health(cfg)

        assert results[0]["healthy"] is True
        assert results[0]["status"] == "503"

    # --- Cycle 5: no-port process → TCP check ---

    def test_tcp_only_process_healthy_when_port_open(self, cfg: Config) -> None:
        """Process with no HTTP (no ports from scanner) reports TCP success."""
        _write_record(cfg, pid=12345)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[]),  # no ports listening
        ):
            results = check_health(cfg)

        assert len(results) == 1
        r = results[0]
        # No port = no TCP check possible → reported as no-port
        assert r["name"] == "web"
        assert r["status"] == "no-port"
        # A process with no port is considered healthy (we can't check it)
        assert r["healthy"] is True

    # --- Cycle 6: dead processes are skipped ---

    def test_dead_processes_are_skipped(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        with (
            patch("psutil.pid_exists", return_value=False),  # dead
        ):
            results = check_health(cfg)

        assert results == []

    # --- Cycle 7: custom endpoint ---

    def test_custom_endpoint_is_used(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[_listen_conn(12345, 8080)]),
            respx.mock,
        ):
            respx.get("http://localhost:8080/health").mock(return_value=httpx.Response(200))
            results = check_health(cfg, endpoint="/health")

        assert results[0]["healthy"] is True

    # --- Cycle 8: timeout option ---

    def test_timeout_is_passed_to_http_request(self, cfg: Config) -> None:
        """Timeout is forwarded — when it fires the process is unhealthy."""
        _write_record(cfg, pid=12345)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[_listen_conn(12345, 8080)]),
            respx.mock,
        ):
            respx.get("http://localhost:8080/").mock(side_effect=httpx.TimeoutException("t/o"))
            results = check_health(cfg, timeout=0.001)

        assert results[0]["healthy"] is False

    # --- Cycle 9: httpx.InvalidURL is caught and reported ---

    def test_invalid_url_caught_and_reported_as_unhealthy(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[_listen_conn(12345, 8080)]),
            patch("httpx.get", side_effect=httpx.InvalidURL("bad url")),
        ):
            results = check_health(cfg)

        assert len(results) == 1
        r = results[0]
        assert r["healthy"] is False
        assert r["error"] is not None

    # --- Cycle 11: multiple processes ---

    def test_multiple_processes_all_checked(self, cfg: Config) -> None:
        _write_record(cfg, name="web", pid=11111)
        _write_record(cfg, name="api", pid=22222)

        def _net_conns(*_: object, **__: object) -> list[MagicMock]:
            return [_listen_conn(11111, 3000), _listen_conn(22222, 4000)]

        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", side_effect=_net_conns),
            respx.mock,
        ):
            respx.get("http://localhost:3000/").mock(return_value=httpx.Response(200))
            respx.get("http://localhost:4000/").mock(return_value=httpx.Response(200))
            results = check_health(cfg)

        assert len(results) == 2
        names = {r["name"] for r in results}
        assert names == {"web", "api"}
        assert all(r["healthy"] for r in results)
