"""Integration tests for `vigil restart` and `vigil remove` CLI commands."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import psutil
import pytest
from click.testing import CliRunner

from vigil.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestRestartCLI:
    def test_restart_json_returns_new_pid(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            start_result = runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            old_pid: int = json.loads(start_result.output)["pid"]
            try:
                result = runner.invoke(main, ["restart", "web", "--json"], catch_exceptions=False)
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                assert data["name"] == "web"
                assert data["status"] == "restarted"
                assert "pid" in data
                assert data["pid"] != old_pid
            finally:
                state_data = json.loads(
                    runner.invoke(main, ["status", "--json"], catch_exceptions=False).output
                )
                for entry in state_data.get("managed", []):
                    with contextlib.suppress(Exception):
                        if entry.get("pid"):
                            psutil.Process(entry["pid"]).kill()
                with contextlib.suppress(psutil.NoSuchProcess):
                    psutil.Process(old_pid).kill()

    def test_restart_unknown_name_exits_with_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["restart", "ghost", "--json"])
            assert result.exit_code != 0

    def test_restart_text_output(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            try:
                result = runner.invoke(main, ["restart", "web"], catch_exceptions=False)
                assert result.exit_code == 0, result.output
                assert "web" in result.output
            finally:
                state_data = json.loads(
                    runner.invoke(main, ["status", "--json"], catch_exceptions=False).output
                )
                for entry in state_data.get("managed", []):
                    with contextlib.suppress(Exception):
                        if entry.get("pid"):
                            psutil.Process(entry["pid"]).kill()


class TestRestartOSErrors:
    def test_restart_nonexistent_command_exits_with_json_error(self, runner: CliRunner) -> None:
        """vigil restart exits 1 with JSON error when the recorded command no longer exists."""
        import json as _json

        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            # Write a state record with a command that will trigger FileNotFoundError
            state = {
                "backend": {
                    "name": "backend",
                    "pid": 1,
                    "command": "8080",
                    "started_at": 1000000.0,
                    "port": None,
                    "cwd": None,
                }
            }
            (Path(".vigil") / "state.json").write_text(_json.dumps(state))
            result = runner.invoke(main, ["restart", "backend", "--json"])
            assert result.exit_code == 1
            data = _json.loads(result.output)
            assert "error" in data
            assert isinstance(data["code"], str)


class TestRemoveCLI:
    def test_remove_crashed_entry_json(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            start_result = runner.invoke(
                main,
                ["start", "web", "python -c 'pass'", "--json", "--no-wait"],
                catch_exceptions=False,
            )
            pid: int = json.loads(start_result.output)["pid"]
            with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
                psutil.Process(pid).wait(timeout=5)
            import time

            time.sleep(0.1)

            result = runner.invoke(main, ["remove", "web", "--json"], catch_exceptions=False)
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert data["name"] == "web"
            assert data["status"] == "removed"

    def test_remove_alive_process_exits_with_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            start_result = runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            pid: int = json.loads(start_result.output)["pid"]
            try:
                result = runner.invoke(main, ["remove", "web", "--json"])
                assert result.exit_code != 0
            finally:
                with contextlib.suppress(psutil.NoSuchProcess):
                    psutil.Process(pid).kill()

    def test_remove_force_removes_alive_entry(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            start_result = runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            pid: int = json.loads(start_result.output)["pid"]
            try:
                result = runner.invoke(
                    main, ["remove", "web", "--force", "--json"], catch_exceptions=False
                )
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                assert data["status"] == "removed"
                assert psutil.pid_exists(pid)
            finally:
                with contextlib.suppress(psutil.NoSuchProcess):
                    psutil.Process(pid).kill()

    def test_remove_unknown_name_exits_with_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["remove", "ghost", "--json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "not_found"
