"""Integration tests for `vigil health` CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx
from click.testing import CliRunner

from vigil.cli import main
from vigil.config import Config
from vigil.state import ProcessRecord, StateManager


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


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


class TestHealthCLI:
    # --- Cycle 1: --json returns PRD schema ---

    def test_json_output_schema(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            cfg = Config(root=Path("."))
            StateManager(cfg).write(
                ProcessRecord(name="web", pid=12345, command="...", started_at=1000.0)
            )
            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=_alive_proc_mock()),
                patch("psutil.net_connections", return_value=[_listen_conn(12345, 8080)]),
                respx.mock,
            ):
                respx.get("http://localhost:8080/").mock(return_value=httpx.Response(200))
                result = runner.invoke(main, ["health", "--json"], catch_exceptions=False)

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "processes" in data
            assert len(data["processes"]) == 1
            proc = data["processes"][0]
            assert proc["name"] == "web"
            assert proc["healthy"] is True
            assert proc["status"] == "200"
            assert proc["latency_ms"] is not None
            assert proc["error"] is None

    # --- Cycle 2: --endpoint custom path ---

    def test_endpoint_option_used(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            cfg = Config(root=Path("."))
            StateManager(cfg).write(
                ProcessRecord(name="api", pid=12345, command="...", started_at=1000.0)
            )
            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=_alive_proc_mock()),
                patch("psutil.net_connections", return_value=[_listen_conn(12345, 4000)]),
                respx.mock,
            ):
                respx.get("http://localhost:4000/health").mock(return_value=httpx.Response(200))
                result = runner.invoke(
                    main, ["health", "--endpoint", "/health", "--json"], catch_exceptions=False
                )

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["processes"][0]["healthy"] is True

    # --- Cycle 3: --timeout option ---

    def test_timeout_option_passed(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            cfg = Config(root=Path("."))
            StateManager(cfg).write(
                ProcessRecord(name="web", pid=12345, command="...", started_at=1000.0)
            )
            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=_alive_proc_mock()),
                patch("psutil.net_connections", return_value=[_listen_conn(12345, 8080)]),
                respx.mock,
            ):
                respx.get("http://localhost:8080/").mock(
                    side_effect=httpx.TimeoutException("timed out")
                )
                result = runner.invoke(
                    main, ["health", "--timeout", "1", "--json"], catch_exceptions=False
                )

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["processes"][0]["healthy"] is False

    # --- Cycle 4: human-readable output flags unhealthy ---

    def test_human_readable_shows_healthy(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            cfg = Config(root=Path("."))
            StateManager(cfg).write(
                ProcessRecord(name="web", pid=12345, command="...", started_at=1000.0)
            )
            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=_alive_proc_mock()),
                patch("psutil.net_connections", return_value=[_listen_conn(12345, 8080)]),
                respx.mock,
            ):
                respx.get("http://localhost:8080/").mock(return_value=httpx.Response(200))
                result = runner.invoke(main, ["health"], catch_exceptions=False)

            assert result.exit_code == 0
            assert "web" in result.output

    def test_human_readable_flags_unhealthy(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            cfg = Config(root=Path("."))
            StateManager(cfg).write(
                ProcessRecord(name="web", pid=12345, command="...", started_at=1000.0)
            )
            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=_alive_proc_mock()),
                patch("psutil.net_connections", return_value=[_listen_conn(12345, 8080)]),
                respx.mock,
            ):
                respx.get("http://localhost:8080/").mock(side_effect=httpx.ConnectError("refused"))
                result = runner.invoke(main, ["health"], catch_exceptions=False)

            assert result.exit_code == 0
            assert "web" in result.output
            # Unhealthy marker must appear
            assert any(s in result.output for s in ["✗", "UNHEALTHY", "unhealthy", "FAIL", "fail"])

    # --- Cycle 5: no managed processes ---

    def test_no_processes_outputs_empty(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["health", "--json"], catch_exceptions=False)
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data == {"processes": []}

    # --- Cycle 6: endpoint missing leading slash ---

    def test_endpoint_without_leading_slash_exits_1(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["health", "--endpoint", "no-slash"])
            assert result.exit_code == 1
            assert "Endpoint must start with /" in (result.output + (result.stderr or ""))

    def test_endpoint_without_leading_slash_json_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["health", "--endpoint", "no-slash", "--json"])
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "error" in data
