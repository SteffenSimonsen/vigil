"""Integration tests for `vigil wait` CLI command."""

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


class TestWaitCLI:
    def test_exits_0_when_port_opens(self, runner: CliRunner) -> None:
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
            ):
                result = runner.invoke(
                    main, ["wait", "web", "--timeout", "5", "--json"], catch_exceptions=False
                )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "ready"
            assert data["name"] == "web"

    def test_exits_1_on_timeout(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            cfg = Config(root=Path("."))
            StateManager(cfg).write(
                ProcessRecord(name="web", pid=12345, command="...", started_at=1000.0)
            )
            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=_alive_proc_mock()),
                patch("psutil.net_connections", return_value=[]),  # no port ever
            ):
                result = runner.invoke(main, ["wait", "web", "--timeout", "0.05", "--json"])
            assert result.exit_code == 1

    def test_exits_2_when_process_dies(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            cfg = Config(root=Path("."))
            StateManager(cfg).write(
                ProcessRecord(name="web", pid=12345, command="...", started_at=1000.0)
            )
            with patch("psutil.pid_exists", return_value=False):
                result = runner.invoke(main, ["wait", "web", "--timeout", "5", "--json"])
            assert result.exit_code == 2

    def test_http_flag_default_path(self, runner: CliRunner) -> None:
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
                result = runner.invoke(
                    main, ["wait", "web", "--http", "--timeout", "5"], catch_exceptions=False
                )
            assert result.exit_code == 0

    def test_http_flag_with_custom_path(self, runner: CliRunner) -> None:
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
                respx.get("http://localhost:8080/health").mock(return_value=httpx.Response(200))
                result = runner.invoke(
                    main,
                    ["wait", "web", "--http=/health", "--timeout", "5"],
                    catch_exceptions=False,
                )
            assert result.exit_code == 0

    def test_http_inline_path_syntax(self, runner: CliRunner) -> None:
        """--http=/health should check /health (spec syntax, was broken)."""
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
                respx.get("http://localhost:8080/health").mock(return_value=httpx.Response(200))
                result = runner.invoke(
                    main,
                    ["wait", "web", "--http=/health", "--timeout", "5"],
                    catch_exceptions=False,
                )
            assert result.exit_code == 0

    def test_exits_1_when_name_not_in_statefile(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["wait", "doesnotexist", "--timeout", "5", "--json"])
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert data["error"] == "No managed process named 'doesnotexist'"
            assert data["code"] == 1

    # --- http path missing leading slash ---

    def test_http_path_without_leading_slash_exits_1(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            cfg = Config(root=Path("."))
            StateManager(cfg).write(
                ProcessRecord(name="web", pid=12345, command="...", started_at=1000.0)
            )
            result = runner.invoke(main, ["wait", "web", "--http=no-slash"])
            assert result.exit_code == 1
            assert "Endpoint must start with /" in (result.output + (result.stderr or ""))

    def test_http_path_without_leading_slash_json_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            cfg = Config(root=Path("."))
            StateManager(cfg).write(
                ProcessRecord(name="web", pid=12345, command="...", started_at=1000.0)
            )
            result = runner.invoke(main, ["wait", "web", "--http=no-slash", "--json"])
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "error" in data

    def test_log_match_exits_0_when_line_matches(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            cfg = Config(root=Path("."))
            StateManager(cfg).write(
                ProcessRecord(name="web", pid=12345, command="...", started_at=1000.0)
            )
            log_dir = Path(".vigil") / "logs"
            log_dir.mkdir()
            (log_dir / "web.log").write_text("worker ready\n")
            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=_alive_proc_mock()),
                patch("psutil.net_connections", return_value=[]),
            ):
                result = runner.invoke(
                    main,
                    ["wait", "web", "--log-match", "worker ready", "--timeout", "5", "--json"],
                    catch_exceptions=False,
                )
            assert result.exit_code == 0

    def test_ready_cmd_exits_0_when_command_succeeds(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            cfg = Config(root=Path("."))
            StateManager(cfg).write(
                ProcessRecord(name="web", pid=12345, command="...", started_at=1000.0)
            )
            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=_alive_proc_mock()),
                patch("psutil.net_connections", return_value=[]),
                patch("subprocess.run", return_value=MagicMock(returncode=0)),
            ):
                result = runner.invoke(
                    main,
                    ["wait", "web", "--ready-cmd", "true", "--timeout", "5", "--json"],
                    catch_exceptions=False,
                )
            assert result.exit_code == 0

    def test_port_mismatch_exits_2(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            cfg = Config(root=Path("."))
            StateManager(cfg).write(
                ProcessRecord(name="web", pid=12345, command="...", started_at=1000.0, port=8080)
            )
            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=_alive_proc_mock()),
                # Process listening on 9999 instead of assigned 8080
                patch("psutil.net_connections", return_value=[_listen_conn(12345, 9999)]),
            ):
                result = runner.invoke(
                    main,
                    ["wait", "web", "--timeout", "5", "--json"],
                    catch_exceptions=False,
                )
            assert result.exit_code == 2
            data = json.loads(result.output)
            assert data["status"] == "port_mismatch"

    def test_port_override(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            cfg = Config(root=Path("."))
            StateManager(cfg).write(
                ProcessRecord(name="web", pid=12345, command="...", started_at=1000.0)
            )
            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=_alive_proc_mock()),
                patch("psutil.net_connections", return_value=[_listen_conn(12345, 9000)]),
            ):
                result = runner.invoke(
                    main,
                    ["wait", "web", "--port", "9000", "--timeout", "5", "--json"],
                    catch_exceptions=False,
                )
            assert result.exit_code == 0
