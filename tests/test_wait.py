"""Tests for vigil wait — readiness polling with port, HTTP, and exit codes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from vigil.config import Config
from vigil.state import ProcessRecord, StateManager
from vigil.wait import ProcessDied, WaitTimeout, wait_for_ready


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    (tmp_path / ".vigil").mkdir()
    return Config(root=tmp_path)


def _write_record(cfg: Config, pid: int = 12345, started_at: float = 1000.0) -> ProcessRecord:
    record = ProcessRecord(
        name="web", pid=pid, command="python -m http.server", started_at=started_at
    )
    StateManager(cfg).write(record)
    return record


def _alive_proc_mock(pid: int = 12345, started_at: float = 1000.0) -> MagicMock:
    """Return a psutil.Process mock whose create_time matches started_at."""
    proc = MagicMock()
    proc.create_time.return_value = started_at
    return proc


def _listen_conn(pid: int, port: int) -> MagicMock:
    """Return a mock net connection in LISTEN state."""
    conn = MagicMock()
    conn.pid = pid
    conn.status = "LISTEN"
    conn.laddr.port = port
    return conn


class TestWaitForReady:
    # --- Cycle 1: port opens → returns (exit 0) ---

    def test_returns_when_port_opens(self, cfg: Config) -> None:
        _write_record(cfg)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[_listen_conn(12345, 8080)]),
        ):
            wait_for_ready(cfg, "web", timeout=5, interval=0.01)

    # --- Cycle 2: timeout → WaitTimeout raised (exit 1) ---

    def test_raises_wait_timeout_when_no_port_opens(self, cfg: Config) -> None:
        _write_record(cfg)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[]),  # no ports ever open
            pytest.raises(WaitTimeout),
        ):
            wait_for_ready(cfg, "web", timeout=0.05, interval=0.01)

    # --- Cycle 3: process dies → ProcessDied raised (exit 2) ---

    def test_raises_process_died_immediately_when_pid_gone(self, cfg: Config) -> None:
        _write_record(cfg)
        with (
            patch("psutil.pid_exists", return_value=False),  # process already dead
            pytest.raises(ProcessDied),
        ):
            wait_for_ready(cfg, "web", timeout=5, interval=0.01)

    # --- Cycle 4: --http waits for HTTP response on / ---

    def test_http_returns_when_root_responds(self, cfg: Config) -> None:
        _write_record(cfg)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[_listen_conn(12345, 8080)]),
            respx.mock,
        ):
            respx.get("http://localhost:8080/").mock(return_value=httpx.Response(200))
            wait_for_ready(cfg, "web", timeout=5, interval=0.01, http_path="/")

    # --- Cycle 5: --http=/health waits for HTTP response on /health ---

    def test_http_path_uses_specified_path(self, cfg: Config) -> None:
        _write_record(cfg)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[_listen_conn(12345, 8080)]),
            respx.mock,
        ):
            respx.get("http://localhost:8080/health").mock(return_value=httpx.Response(200))
            wait_for_ready(cfg, "web", timeout=5, interval=0.01, http_path="/health")

    def test_http_stays_polling_until_http_responds(self, cfg: Config) -> None:
        _write_record(cfg)
        call_count = 0

        def _conn_side_effect(*_: object, **__: object) -> list[MagicMock]:
            nonlocal call_count
            call_count += 1
            return [_listen_conn(12345, 8080)]

        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", side_effect=_conn_side_effect),
            respx.mock,
        ):
            # First call fails, second succeeds
            respx.get("http://localhost:8080/").mock(
                side_effect=[httpx.ConnectError("refused"), httpx.Response(200)]
            )
            wait_for_ready(cfg, "web", timeout=5, interval=0.01, http_path="/")
            assert call_count >= 2

    # --- Cycle 6: --port N waits for specific port ---

    def test_port_override_waits_for_specific_port(self, cfg: Config) -> None:
        """--port N checks that N is in the process's listening ports."""
        _write_record(cfg)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            # Process listens on 8081, not 8080 — but we ask for 8081
            patch("psutil.net_connections", return_value=[_listen_conn(12345, 8081)]),
        ):
            wait_for_ready(cfg, "web", timeout=5, interval=0.01, port=8081)

    # --- Cycle 7: httpx.InvalidURL is caught (not propagated) ---

    def test_invalid_url_does_not_crash_wait(self, cfg: Config) -> None:
        """httpx.InvalidURL in HTTP check path is caught; wait times out rather than crashing."""
        _write_record(cfg)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", return_value=[_listen_conn(12345, 8080)]),
            patch("httpx.get", side_effect=httpx.InvalidURL("bad url")),
            pytest.raises(WaitTimeout),
        ):
            wait_for_ready(cfg, "web", timeout=0.05, interval=0.01, http_path="/")

    def test_port_override_keeps_polling_when_wrong_port_listening(self, cfg: Config) -> None:
        """--port N does not satisfy readiness when a different port opens."""
        _write_record(cfg)
        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            # Process only ever opens 8081, but we wait for 9000
            patch("psutil.net_connections", return_value=[_listen_conn(12345, 8081)]),
            pytest.raises(WaitTimeout),
        ):
            wait_for_ready(cfg, "web", timeout=0.05, interval=0.01, port=9000)

    def test_net_connections_called_once_per_tick(self, cfg: Config) -> None:
        """wait_for_ready calls net_connections exactly once per polling tick.

        Records with a port field trigger observe_all's crash-loop check AND the
        readiness port check. Before the fix, each ran a separate net_connections()
        call; after the fix there is exactly one call per tick.
        """
        # Write a record with port=8080 so observe_all's snapshot path is exercised
        record = ProcessRecord(
            name="web", pid=12345, command="python -m http.server", started_at=1000.0, port=8080
        )
        from vigil.state import StateManager

        StateManager(cfg).write(record)

        call_counter = 0

        def _counting_net_connections(*_: object, **__: object) -> list[MagicMock]:
            nonlocal call_counter
            call_counter += 1
            return [_listen_conn(12345, 8080)]

        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=_alive_proc_mock()),
            patch("psutil.net_connections", side_effect=_counting_net_connections),
        ):
            wait_for_ready(cfg, "web", timeout=5, interval=0.01)

        # Port opened immediately → exactly 1 tick → exactly 1 net_connections call
        assert call_counter == 1
