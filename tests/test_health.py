"""Tests for vigil health — fleet HTTP and TCP health checks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from vigil.config import Config
from vigil.health import HealthChecker, check_health
from vigil.registry import ProcessRegistry
from vigil.state import ProcessRecord, StateManager

# ── Shared fakes ──────────────────────────────────────────────────────────────


class FakeLivenessChecker:
    def __init__(self, alive_pids: set[int]) -> None:
        self._alive = alive_pids

    def is_alive(self, pid: int, started_at: float | None) -> bool:
        return pid in self._alive


class FakePortProber:
    def __init__(self, pid_to_ports: dict[int, list[int]]) -> None:
        self._map = pid_to_ports
        self.calls: list[int] = []

    def listening_ports(self, pid: int) -> list[int]:
        self.calls.append(pid)
        return self._map.get(pid, [])

    def port_state(self, port: int) -> str:
        return "listen"


class FakeHttpProber:
    def __init__(
        self,
        *,
        status_code: int = 200,
        raises: Exception | None = None,
        responses: list[int | Exception] | None = None,
    ) -> None:
        self._status = status_code
        self._raises = raises
        self._responses = list(responses) if responses else None
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: float) -> int:
        self.calls.append(url)
        if self._responses is not None:
            item = self._responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if self._raises:
            raise self._raises
        return self._status


# ── Fixtures ─────────────────────────────────────────────────────────────────


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
    depends_on: list[str] | None = None,
    circuit_open: bool = False,
    crash_count: int = 0,
) -> ProcessRecord:
    record = ProcessRecord(
        name=name,
        pid=pid,
        command="python -m http.server",
        started_at=started_at,
        port=port,
        depends_on=depends_on or [],
        circuit_open=circuit_open,
        crash_count=crash_count,
    )
    StateManager(cfg).write(record)
    return record


def _reg(
    cfg: Config,
    *,
    alive_pids: set[int] | None = None,
    pid_to_ports: dict[int, list[int]] | None = None,
) -> ProcessRegistry:
    return ProcessRegistry(
        cfg,
        liveness_checker=FakeLivenessChecker(alive_pids or set()),
        port_prober=FakePortProber(pid_to_ports or {}),
    )


# ── TestHealthChecker — boundary-injection tests ──────────────────────────────


class TestHealthChecker:
    # --- Cycle 1: port prober is used (no direct psutil) ---

    def test_check_all_uses_port_prober(self, cfg: Config) -> None:
        """Port discovery routes through injected PortProber — no psutil call needed."""
        _write_record(cfg, pid=12345)
        fake_prober = FakePortProber({12345: [8080]})
        reg = ProcessRegistry(
            cfg,
            liveness_checker=FakeLivenessChecker({12345}),
            port_prober=fake_prober,
        )
        checker = HealthChecker(reg, http_prober=FakeHttpProber(status_code=200))
        checker.check_all()
        assert 12345 in fake_prober.calls

    # --- Cycle 2: single statefile read per check_all() ---

    def test_single_statefile_read(self, cfg: Config) -> None:
        """check_all() reads the statefile exactly once."""
        _write_record(cfg, pid=12345)
        reg = _reg(cfg, alive_pids={12345}, pid_to_ports={12345: []})
        with patch.object(reg, "_read_records", wraps=reg._read_records) as mock_read:
            checker = HealthChecker(reg)
            checker.check_all()
        assert mock_read.call_count == 1

    # --- Cycle 3: HTTP healthy process ---

    def test_healthy_http_process(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        fake_http = FakeHttpProber(status_code=200)
        reg = _reg(cfg, alive_pids={12345}, pid_to_ports={12345: [8080]})
        results = HealthChecker(reg, http_prober=fake_http).check_all()

        assert len(results) == 1
        r = results[0]
        assert r["name"] == "web"
        assert r["healthy"] is True
        assert r["status"] == "200"
        assert r["latency_ms"] is not None
        assert r["error"] is None

    # --- Cycle 4: HTTP connection failure → tcp fallback ---

    def test_unhealthy_when_http_connection_fails(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        fake_http = FakeHttpProber(raises=httpx.ConnectError("refused"))
        reg = _reg(cfg, alive_pids={12345}, pid_to_ports={12345: [8080]})

        with patch("socket.create_connection", side_effect=OSError("refused")):
            results = HealthChecker(reg, http_prober=fake_http).check_all()

        assert results[0]["healthy"] is False
        assert results[0]["error"] is not None

    # --- Cycle 5: HTTP timeout → fallback ---

    def test_unhealthy_when_http_times_out(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        fake_http = FakeHttpProber(raises=httpx.TimeoutException("timeout"))
        reg = _reg(cfg, alive_pids={12345}, pid_to_ports={12345: [8080]})

        with patch("socket.create_connection", side_effect=OSError("refused")):
            results = HealthChecker(reg, http_prober=fake_http).check_all()

        assert results[0]["healthy"] is False
        assert results[0]["error"] is not None

    # --- Cycle 6: any HTTP response (4xx/5xx) counts as healthy ---

    def test_non_2xx_response_counts_as_healthy(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        fake_http = FakeHttpProber(status_code=503)
        reg = _reg(cfg, alive_pids={12345}, pid_to_ports={12345: [8080]})
        results = HealthChecker(reg, http_prober=fake_http).check_all()

        assert results[0]["healthy"] is True
        assert results[0]["status"] == "503"

    # --- Cycle 7: no-port process → no-port status ---

    def test_no_port_process_is_healthy(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        reg = _reg(cfg, alive_pids={12345}, pid_to_ports={12345: []})
        results = HealthChecker(reg).check_all()

        assert len(results) == 1
        assert results[0]["status"] == "no-port"
        assert results[0]["healthy"] is True

    # --- Cycle 8: dead processes skipped ---

    def test_dead_processes_are_skipped(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        reg = _reg(cfg, alive_pids=set(), pid_to_ports={})  # pid 12345 is dead
        results = HealthChecker(reg).check_all()
        assert results == []

    # --- Cycle 9: circuit open → crash_looping, http prober not called ---

    def test_circuit_open_bypasses_http_prober(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345, circuit_open=True, crash_count=5)
        fake_http = FakeHttpProber(status_code=200)
        reg = _reg(cfg, alive_pids={12345}, pid_to_ports={12345: [8080]})
        results = HealthChecker(reg, http_prober=fake_http).check_all()

        assert results[0]["healthy"] is False
        assert results[0]["status"] == "crash_looping"
        assert fake_http.calls == []  # http prober must not be called

    # --- Cycle 10: degraded dependency ---

    def test_degraded_dependency(self, cfg: Config) -> None:
        _write_record(cfg, name="database", pid=9999)
        _write_record(cfg, name="backend", pid=11111, depends_on=["database"])
        reg = _reg(cfg, alive_pids={11111}, pid_to_ports={11111: [8000]})  # database is dead
        results = HealthChecker(reg).check_all()

        backend = next(r for r in results if r["name"] == "backend")
        assert backend["healthy"] is False
        assert backend["status"] == "degraded"

    # --- Cycle 11: custom endpoint ---

    def test_custom_endpoint_is_used(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        fake_http = FakeHttpProber(status_code=200)
        reg = _reg(cfg, alive_pids={12345}, pid_to_ports={12345: [8080]})
        HealthChecker(reg, endpoint="/health", http_prober=fake_http).check_all()

        assert fake_http.calls == ["http://localhost:8080/health"]

    # --- Cycle 12: multiple processes ---

    def test_multiple_processes_all_checked(self, cfg: Config) -> None:
        _write_record(cfg, name="web", pid=11111)
        _write_record(cfg, name="api", pid=22222)
        fake_http = FakeHttpProber(status_code=200)
        reg = _reg(cfg, alive_pids={11111, 22222}, pid_to_ports={11111: [3000], 22222: [4000]})
        results = HealthChecker(reg, http_prober=fake_http).check_all()

        assert len(results) == 2
        assert {r["name"] for r in results} == {"web", "api"}
        assert all(r["healthy"] for r in results)

    # --- Cycle 13: check_one returns result for known name ---

    def test_check_one_returns_result(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        fake_http = FakeHttpProber(status_code=200)
        reg = _reg(cfg, alive_pids={12345}, pid_to_ports={12345: [8080]})
        result = HealthChecker(reg, http_prober=fake_http).check_one("web")

        assert result is not None
        assert result["name"] == "web"
        assert result["healthy"] is True

    # --- Cycle 14: check_one returns None for unknown name ---

    def test_check_one_returns_none_for_unknown(self, cfg: Config) -> None:
        reg = _reg(cfg)
        result = HealthChecker(reg).check_one("nonexistent")
        assert result is None

    # --- Cycle 15: ready flag — port + http → ready=True ---

    def test_check_one_ready_flag_true(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        fake_http = FakeHttpProber(status_code=200)
        reg = _reg(cfg, alive_pids={12345}, pid_to_ports={12345: [8080]})
        result = HealthChecker(reg, http_prober=fake_http).check_one("web")

        assert result is not None
        assert result["ready"] is True

    # --- Cycle 16: ready flag — no port → ready=False ---

    def test_check_one_ready_false_when_no_port(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        reg = _reg(cfg, alive_pids={12345}, pid_to_ports={12345: []})
        result = HealthChecker(reg).check_one("web")

        assert result is not None
        assert result["ready"] is False

    # --- Cycle 17: ready flag — http failure → ready=False ---

    def test_check_one_ready_false_when_http_fails(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        fake_http = FakeHttpProber(raises=httpx.ConnectError("refused"))
        reg = _reg(cfg, alive_pids={12345}, pid_to_ports={12345: [8080]})

        with patch("socket.create_connection", side_effect=OSError("refused")):
            result = HealthChecker(reg, http_prober=fake_http).check_one("web")

        assert result is not None
        assert result["ready"] is False

    # --- Cycle 19: port_mismatch — assigned port but listening elsewhere ---

    def test_port_mismatch_status(self, cfg: Config) -> None:
        """Process with assigned port 8080 but listening on 9999 → port_mismatch."""
        _write_record(cfg, pid=12345, port=8080)  # record.port = 8080
        # PortProber returns 9999, not 8080
        reg = _reg(cfg, alive_pids={12345}, pid_to_ports={12345: [9999]})
        results = HealthChecker(reg).check_all()

        assert len(results) == 1
        r = results[0]
        assert r["healthy"] is False
        assert r["ready"] is False
        assert r["status"] == "port_mismatch"

    # --- Cycle 18: InvalidURL caught and reported ---

    def test_invalid_url_caught_and_reported_as_unhealthy(self, cfg: Config) -> None:
        _write_record(cfg, pid=12345)
        fake_http = FakeHttpProber(raises=httpx.InvalidURL("bad url"))
        reg = _reg(cfg, alive_pids={12345}, pid_to_ports={12345: [8080]})

        with patch("socket.create_connection", side_effect=OSError("conn err")):
            results = HealthChecker(reg, http_prober=fake_http).check_all()

        assert results[0]["healthy"] is False
        assert results[0]["error"] is not None


# ── TestCheckHealth (backward-compat one-liner) ───────────────────────────────


class TestCheckHealth:
    """check_health(config) is a backward-compatible factory — tests use psutil patches
    since they exercise the DefaultPortProber path."""

    def _alive_proc_mock(self, started_at: float = 1000.0) -> MagicMock:
        proc = MagicMock()
        proc.create_time.return_value = started_at
        return proc

    def _listen_conn(self, pid: int, port: int) -> MagicMock:
        conn = MagicMock()
        conn.pid = pid
        conn.status = "LISTEN"
        conn.laddr.port = port
        return conn

    def _write(
        self,
        cfg: Config,
        name: str = "web",
        pid: int = 12345,
        started_at: float = 1000.0,
        depends_on: list[str] | None = None,
    ) -> ProcessRecord:
        record = ProcessRecord(
            name=name,
            pid=pid,
            command="python -m http.server",
            started_at=started_at,
            depends_on=depends_on or [],
        )
        StateManager(cfg).write(record)
        return record

    def test_healthy_http_process_returns_healthy_result(self, cfg: Config) -> None:
        self._write(cfg, pid=12345)
        import respx

        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=self._alive_proc_mock()),
            patch("psutil.net_connections", return_value=[self._listen_conn(12345, 8080)]),
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
        assert r["error"] is None

    def test_unhealthy_when_http_connection_fails(self, cfg: Config) -> None:
        self._write(cfg, pid=12345)
        import respx

        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=self._alive_proc_mock()),
            patch("psutil.net_connections", return_value=[self._listen_conn(12345, 8080)]),
            respx.mock,
        ):
            respx.get("http://localhost:8080/").mock(side_effect=httpx.ConnectError("refused"))
            results = check_health(cfg)

        assert results[0]["healthy"] is False
        assert results[0]["error"] is not None

    def test_dead_processes_are_skipped(self, cfg: Config) -> None:
        self._write(cfg, pid=12345)
        with patch("psutil.pid_exists", return_value=False):
            results = check_health(cfg)
        assert results == []

    def test_degraded_process_is_unhealthy(self, cfg: Config) -> None:
        database_record = ProcessRecord(
            name="database", pid=9999, command="postgres", started_at=1000.0, depends_on=[]
        )
        backend_record = ProcessRecord(
            name="backend",
            pid=11111,
            command="uvicorn main:app",
            started_at=1000.0,
            depends_on=["database"],
        )
        StateManager(cfg).write(database_record)
        StateManager(cfg).write(backend_record)

        def pid_exists(pid: int) -> bool:
            return pid == 11111

        import respx

        with (
            patch("psutil.pid_exists", side_effect=pid_exists),
            patch("psutil.Process", return_value=self._alive_proc_mock()),
            patch("psutil.net_connections", return_value=[self._listen_conn(11111, 8000)]),
            respx.mock,
        ):
            respx.get("http://localhost:8000/").mock(return_value=httpx.Response(200))
            results = check_health(cfg)

        backend_result = next(r for r in results if r["name"] == "backend")
        assert backend_result["healthy"] is False
        assert "degraded" in (backend_result["status"] or "")
