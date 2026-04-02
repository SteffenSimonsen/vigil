"""Tests for crash-loop detection and circuit breaker."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vigil.config import Config
from vigil.state import ProcessRecord, StateManager


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    (tmp_path / ".vigil").mkdir()
    return Config(root=tmp_path)


def _write_record(
    cfg: Config,
    *,
    name: str = "web",
    pid: int = 12345,
    started_at: float = 1000.0,
    port: int | None = 8080,
    crash_count: int = 0,
    last_crash_at: float | None = None,
    circuit_open: bool = False,
) -> ProcessRecord:
    record = ProcessRecord(
        name=name,
        pid=pid,
        command="uvicorn app:app --reload",
        started_at=started_at,
        port=port,
        crash_count=crash_count,
        last_crash_at=last_crash_at,
        circuit_open=circuit_open,
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


# ── Cycle 1: ProcessRecord round-trips crash-loop fields ──────────────────────


class TestProcessRecordCrashLoopFields:
    def test_crash_loop_fields_default_to_zero(self, cfg: Config) -> None:
        record = ProcessRecord(name="web", pid=1, command="cmd", started_at=None)
        assert record.crash_count == 0
        assert record.last_crash_at is None
        assert record.circuit_open is False

    def test_crash_loop_fields_round_trip_through_json(self, cfg: Config) -> None:
        now = time.time()
        _write_record(cfg, crash_count=3, last_crash_at=now, circuit_open=True)

        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
        ):
            records = StateManager(cfg).read_all()

        r = records[0]
        assert r.crash_count == 3
        assert r.last_crash_at == pytest.approx(now, abs=0.001)
        assert r.circuit_open is True

    def test_crash_loop_fields_default_on_old_state_files(self) -> None:
        """Old state file entries without crash-loop fields deserialise with defaults."""
        data = {"name": "web", "pid": 1234, "command": "cmd"}
        record = ProcessRecord.from_dict(data)
        assert record.crash_count == 0
        assert record.last_crash_at is None
        assert record.circuit_open is False


# ── Cycle 2: observe() increments crash_count when port absent while PID alive ─


class TestObservePortAbsent:
    def test_observe_increments_crash_count_when_port_absent(self, cfg: Config) -> None:
        from vigil.crash_loop import observe

        _write_record(cfg, pid=12345, port=8080)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[]),  # port absent
        ):
            observe(cfg, "web")

        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
        ):
            records = StateManager(cfg).read_all()
        assert records[0].crash_count == 1
        assert records[0].last_crash_at is not None

    def test_observe_does_nothing_for_dead_process(self, cfg: Config) -> None:
        from vigil.crash_loop import observe

        _write_record(cfg, pid=12345, port=8080)
        with (
            patch("psutil.pid_exists", return_value=False),
        ):
            observe(cfg, "web")

        # crash_count stays 0 — dead process is not crash-looping
        with patch("psutil.pid_exists", return_value=False):
            records = StateManager(cfg).read_all()
        assert records[0].crash_count == 0

    def test_observe_does_nothing_for_process_without_port(self, cfg: Config) -> None:
        from vigil.crash_loop import observe

        _write_record(cfg, pid=12345, port=None)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[]),
        ):
            observe(cfg, "web")

        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
        ):
            records = StateManager(cfg).read_all()
        assert records[0].crash_count == 0

    def test_observe_does_nothing_for_unknown_process(self, cfg: Config) -> None:
        from vigil.crash_loop import observe

        # Should not raise
        observe(cfg, "nonexistent")


# ── Cycle 3: circuit opens after threshold observations ───────────────────────


class TestCircuitBreaker:
    def test_circuit_opens_after_threshold_observations(self, cfg: Config) -> None:
        from vigil.crash_loop import observe

        _write_record(cfg, pid=12345, port=8080, crash_count=4)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[]),
        ):
            result = observe(cfg, "web", crash_threshold=5)

        assert result is True  # circuit open

        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
        ):
            records = StateManager(cfg).read_all()
        assert records[0].circuit_open is True
        assert records[0].crash_count == 5

    def test_observe_returns_false_before_threshold(self, cfg: Config) -> None:
        from vigil.crash_loop import observe

        _write_record(cfg, pid=12345, port=8080, crash_count=0)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[]),
        ):
            result = observe(cfg, "web", crash_threshold=5)

        assert result is False
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
        ):
            records = StateManager(cfg).read_all()
        assert records[0].circuit_open is False


# ── Cycle 4: port comes back → state is cleared ────────────────────────────────


class TestCrashStateClearedOnPortReturn:
    def test_state_cleared_when_port_comes_back(self, cfg: Config) -> None:
        from vigil.crash_loop import observe

        _write_record(
            cfg,
            pid=12345,
            port=8080,
            crash_count=7,
            last_crash_at=time.time() - 10,
            circuit_open=True,
        )
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch(
                "psutil.net_connections",
                return_value=[_listen_conn(12345, 8080)],
            ),
        ):
            result = observe(cfg, "web")

        assert result is False

        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
        ):
            records = StateManager(cfg).read_all()
        r = records[0]
        assert r.crash_count == 0
        assert r.last_crash_at is None
        assert r.circuit_open is False


# ── Cycle 5: check_health marks crash-looping processes as unhealthy ──────────


class TestHealthCrashLoop:
    def test_crash_looping_process_is_unhealthy(self, cfg: Config) -> None:
        from vigil.health import check_health

        _write_record(cfg, pid=12345, port=8080, circuit_open=True, crash_count=5)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[]),  # port absent
        ):
            results = check_health(cfg)

        assert len(results) == 1
        r = results[0]
        assert r["healthy"] is False
        assert r["status"] == "crash_looping"
        assert "crash" in r["error"].lower()  # type: ignore[union-attr]

    def test_non_crash_looping_alive_process_is_healthy(self, cfg: Config) -> None:
        """Normal alive process still gets the regular HTTP health check."""
        import httpx
        import respx

        from vigil.health import check_health

        _write_record(cfg, pid=12345, port=8080, circuit_open=False)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[_listen_conn(12345, 8080)]),
            respx.mock,
        ):
            respx.get("http://localhost:8080/").mock(return_value=httpx.Response(200))
            results = check_health(cfg)

        assert results[0]["healthy"] is True


# ── Cycle 6: wait_for_ready fails fast when circuit_open ─────────────────────


class TestWaitCrashLoop:
    def test_wait_raises_crash_looping_when_circuit_open(self, cfg: Config) -> None:
        from vigil.crash_loop import CrashLooping
        from vigil.wait import wait_for_ready

        _write_record(cfg, pid=12345, port=8080, circuit_open=True, crash_count=5)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[]),
            pytest.raises(CrashLooping),
        ):
            wait_for_ready(cfg, "web", timeout=5, interval=0.01)

    def test_wait_does_not_raise_crash_looping_when_port_present(self, cfg: Config) -> None:
        from vigil.wait import wait_for_ready

        _write_record(cfg, pid=12345, port=8080, circuit_open=False)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[_listen_conn(12345, 8080)]),
        ):
            wait_for_ready(cfg, "web", timeout=5, interval=0.01)


# ── Cycle 7: vigil status shows crash_looping ────────────────────────────────


class TestStatusCrashLoop:
    def test_status_json_shows_crash_looping(self) -> None:
        import json

        from click.testing import CliRunner

        from vigil.cli import main

        runner = CliRunner()
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            cfg = Config(root=Path("."))
            _write_record(
                cfg,
                pid=12345,
                port=8080,
                circuit_open=True,
                crash_count=5,
                last_crash_at=time.time() - 5,
            )
            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=_alive_proc_mock()),
                patch("psutil.net_connections", return_value=[]),
            ):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

        assert result.exit_code == 0
        data = json.loads(result.output)
        entry = data["managed"][0]
        assert entry["status"] == "crash_looping"
        assert entry["crash_count"] == 5


# ── Cycle 8: vigil wait CLI exits with error when crash-looping ──────────────


class TestWaitCliCrashLoop:
    def test_wait_cli_exits_nonzero_when_crash_looping(self) -> None:
        import json

        from click.testing import CliRunner

        from vigil.cli import main

        runner = CliRunner()
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            cfg = Config(root=Path("."))
            _write_record(cfg, pid=12345, port=8080, circuit_open=True, crash_count=5)
            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=_alive_proc_mock()),
                patch("psutil.net_connections", return_value=[]),
            ):
                result = runner.invoke(main, ["wait", "web", "--json"], catch_exceptions=False)

        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["status"] == "crash_looping"
