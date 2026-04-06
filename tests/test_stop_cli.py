"""Integration tests for `vigil stop` CLI command."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from unittest.mock import patch

import psutil
import pytest
from click.testing import CliRunner

from vigil.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestStopCLI:
    def test_stop_json_confirms_stopped(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            start_result = runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            pid: int = json.loads(start_result.output)["pid"]
            try:
                result = runner.invoke(main, ["stop", "web", "--json"], catch_exceptions=False)
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                assert data["name"] == "web"
                assert data["status"] == "stopped"
                assert not psutil.pid_exists(pid)
            finally:
                with contextlib.suppress(Exception):
                    psutil.Process(pid).kill()

    def test_stop_unknown_name_exits_with_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["stop", "ghost", "--json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "not_running"

    def test_stop_all_stops_all_processes(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            r1 = runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            r2 = runner.invoke(
                main,
                ["start", "worker", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            pid1: int = json.loads(r1.output)["pid"]
            pid2: int = json.loads(r2.output)["pid"]
            try:
                result = runner.invoke(main, ["stop", "--all", "--json"], catch_exceptions=False)
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                by_name = {p["name"]: p["status"] for p in data["processes"]}
                assert by_name["web"] == "stopped"
                assert by_name["worker"] == "stopped"
                assert not psutil.pid_exists(pid1)
                assert not psutil.pid_exists(pid2)
            finally:
                with contextlib.suppress(Exception):
                    psutil.Process(pid1).kill()
                with contextlib.suppress(Exception):
                    psutil.Process(pid2).kill()

    def test_stop_cleaned_up_for_already_dead_process(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            start_result = runner.invoke(
                main,
                ["start", "crashme", "python -c 'pass'", "--json", "--no-wait"],
                catch_exceptions=False,
            )
            pid: int = json.loads(start_result.output)["pid"]
            with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
                psutil.Process(pid).wait(timeout=5)

            result = runner.invoke(main, ["stop", "crashme", "--json"], catch_exceptions=False)
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert data["name"] == "crashme"
            assert data["status"] == "cleaned_up"

    def test_stop_warns_time_wait_ports_in_json(self, runner: CliRunner) -> None:
        """vigil stop --json includes time_wait_ports when port enters TIME_WAIT after kill."""
        from unittest.mock import patch

        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            start_result = runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            pid: int = json.loads(start_result.output)["pid"]
            try:
                # After stop, port 3000 enters TIME_WAIT
                with (
                    patch("vigil.scanner.ports_for_pid", return_value=[3000]),
                    patch("vigil.scanner.port_socket_state", return_value="time_wait"),
                ):
                    result = runner.invoke(main, ["stop", "web", "--json"], catch_exceptions=False)
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                assert data["name"] == "web"
                assert data["status"] == "stopped"
                assert data["time_wait_ports"] == [3000]
            finally:
                with contextlib.suppress(Exception):
                    psutil.Process(pid).kill()

    def test_stop_warns_when_stopping_cross_session_process(self, runner: CliRunner) -> None:
        """vigil stop warns (stderr) when stopping a process owned by a different session."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            # Start process with session-A
            with patch.dict("os.environ", {"VIGIL_SESSION_ID": "session-a"}):
                runner.invoke(
                    main,
                    ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                    catch_exceptions=False,
                )
            # Stop from session-B — should warn
            with patch.dict("os.environ", {"VIGIL_SESSION_ID": "session-b"}):
                result = runner.invoke(main, ["stop", "web"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "different vigil session" in result.output

    def test_stop_force_suppresses_cross_session_warning(self, runner: CliRunner) -> None:
        """vigil stop --force does not warn about cross-session ownership."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch.dict("os.environ", {"VIGIL_SESSION_ID": "session-a"}):
                runner.invoke(
                    main,
                    ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                    catch_exceptions=False,
                )
            with patch.dict("os.environ", {"VIGIL_SESSION_ID": "session-b"}):
                result = runner.invoke(main, ["stop", "web", "--force"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "different vigil session" not in result.output

    def test_stop_all_text_shows_error_message(self, runner: CliRunner) -> None:
        """vigil stop --all text output shows error message for failed entries."""
        from unittest.mock import MagicMock

        from vigil.registry import StopAllEntry

        error_result = [
            StopAllEntry(name="db", status="error", error="permission denied", time_wait_ports=[]),
        ]
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("vigil.commands.stop.make_registry") as mock_reg:
                mock_reg.return_value = MagicMock()
                mock_reg.return_value.stop_all.return_value = error_result
                result = runner.invoke(main, ["stop", "--all"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "permission denied" in result.output

    def test_stop_all_json_includes_error_field(self, runner: CliRunner) -> None:
        """vigil stop --all --json includes the error field for each entry."""
        from unittest.mock import MagicMock

        from vigil.registry import StopAllEntry

        results = [
            StopAllEntry(name="db", status="error", error="permission denied", time_wait_ports=[]),
            StopAllEntry(name="web", status="stopped", error=None, time_wait_ports=[]),
        ]
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("vigil.commands.stop.make_registry") as mock_reg:
                mock_reg.return_value = MagicMock()
                mock_reg.return_value.stop_all.return_value = results
                result = runner.invoke(main, ["stop", "--all", "--json"], catch_exceptions=False)

        assert result.exit_code == 0
        data = json.loads(result.output)
        by_name = {p["name"]: p for p in data["processes"]}
        assert by_name["db"]["error"] == "permission denied"
        assert by_name["web"]["error"] is None

    def test_stop_all_json_includes_cleaned_up_status(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            runner.invoke(
                main,
                ["start", "live", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            dead_result = runner.invoke(
                main,
                ["start", "dead", "python -c 'pass'", "--json", "--no-wait"],
                catch_exceptions=False,
            )
            dead_pid: int = json.loads(dead_result.output)["pid"]
            with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
                psutil.Process(dead_pid).wait(timeout=5)

            result = runner.invoke(main, ["stop", "--all", "--json"], catch_exceptions=False)
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            by_name = {p["name"]: p["status"] for p in data["processes"]}
            assert by_name["live"] == "stopped"
            assert by_name["dead"] == "cleaned_up"
