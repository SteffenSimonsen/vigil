"""Integration tests for `vigil start` CLI command."""

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


class TestStartCLI:
    def test_start_json_returns_name_pid_status(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            pid: int | None = None
            try:
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                pid = data["pid"]
                assert data["name"] == "web"
                assert data["status"] == "started"
                assert isinstance(pid, int)
            finally:
                if pid is not None:
                    with contextlib.suppress(Exception):
                        psutil.Process(pid).kill()

    def test_start_text_output(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'"],
                catch_exceptions=False,
            )
            pid: int | None = None
            try:
                assert result.exit_code == 0
                assert "web" in result.output
                # Extract PID from output to clean up
                for word in result.output.split():
                    if word.isdigit():
                        pid = int(word)
                        break
            finally:
                if pid:
                    with contextlib.suppress(Exception):
                        psutil.Process(pid).kill()

    def test_start_error_on_duplicate(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result1 = runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            data = json.loads(result1.output)
            pid: int = data["pid"]
            try:
                result2 = runner.invoke(
                    main,
                    ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                    catch_exceptions=False,
                )
                assert result2.exit_code != 0
            finally:
                with contextlib.suppress(Exception):
                    psutil.Process(pid).kill()

    def test_start_force_replaces_existing(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result1 = runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            data1 = json.loads(result1.output)
            old_pid: int = data1["pid"]
            try:
                result2 = runner.invoke(
                    main,
                    [
                        "start",
                        "web",
                        "python -c 'import time; time.sleep(30)'",
                        "--json",
                        "--force",
                    ],
                    catch_exceptions=False,
                )
                assert result2.exit_code == 0
                data2 = json.loads(result2.output)
                new_pid: int = data2["pid"]
                try:
                    assert new_pid != old_pid
                    assert data2["status"] == "started"
                finally:
                    with contextlib.suppress(Exception):
                        psutil.Process(new_pid).kill()
            finally:
                with contextlib.suppress(Exception):
                    psutil.Process(old_pid).kill()

    def test_start_nonexistent_command_exits_with_json_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(
                main,
                ["start", "backend", "8080", "--json"],
            )
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1

    def test_start_empty_command_exits_with_json_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(
                main,
                ["start", "myproc", "", "--json"],
            )
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1

    def test_start_whitespace_command_exits_with_json_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(
                main,
                ["start", "myproc", "   ", "--json"],
            )
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1

    def test_start_unclosed_quote_exits_with_json_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(
                main,
                ["start", "backend", "python -m http.server 'unclosed", "--json"],
            )
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1

    def test_start_permission_error_exits_with_json_error(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        # Create a file that exists but is not executable
        script = tmp_path / "notexec.sh"
        script.write_text("#!/bin/sh\necho hello")
        script.chmod(0o644)
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(
                main,
                ["start", "backend", str(script), "--json"],
            )
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1

    def test_start_name_with_forward_slash_exits_with_json_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(
                main,
                ["start", "proc/with/slash", "sleep 1", "--json"],
            )
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1

    def test_start_name_with_backslash_exits_with_json_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(
                main,
                ["start", "proc\\evil", "sleep 1", "--json"],
            )
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1

    def test_start_name_with_dotdot_exits_with_json_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(
                main,
                ["start", "../../../tmp/evil", "sleep 1", "--json"],
            )
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1

    def test_start_name_dotdot_alone_exits_with_json_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(
                main,
                ["start", "..", "sleep 1", "--json"],
            )
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1

    def test_start_empty_name_exits_with_json_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(
                main,
                ["start", "", "sleep 300", "--json"],
            )
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1

    def test_start_name_with_single_dot_is_valid(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(
                main,
                ["start", "my.service", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            pid: int | None = None
            try:
                assert result.exit_code == 0
                data = json.loads(result.output)
                pid = data["pid"]
                assert data["name"] == "my.service"
            finally:
                if pid is not None:
                    with contextlib.suppress(Exception):
                        psutil.Process(pid).kill()

    def test_start_env_flag(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(
                main,
                [
                    "start",
                    "web",
                    "python -c 'import os; print(os.environ[\"MY_VAR\"])'",
                    "--json",
                    "--env",
                    "MY_VAR=hello",
                ],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            pid: int = data["pid"]
            with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
                psutil.Process(pid).wait(timeout=5)
            # Check log file
            log_path = Path(".vigil") / "logs" / "web.log"
            assert b"hello" in log_path.read_bytes()
