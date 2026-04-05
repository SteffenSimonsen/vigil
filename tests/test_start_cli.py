"""Integration tests for `vigil start` CLI command."""

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

    def test_start_name_longer_than_200_chars_exits_with_json_error(
        self, runner: CliRunner
    ) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            long_name = "a" * 201
            result = runner.invoke(
                main,
                ["start", long_name, "sleep 300", "--json"],
            )
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1

    def test_start_name_exactly_200_chars_is_valid(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            name = "a" * 200
            result = runner.invoke(
                main,
                ["start", name, "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            pid: int | None = None
            try:
                assert result.exit_code == 0
                data = json.loads(result.output)
                pid = data["pid"]
                assert data["name"] == name
            finally:
                if pid is not None:
                    with contextlib.suppress(Exception):
                        psutil.Process(pid).kill()

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

    def test_start_env_file_flag_loads_vars_into_child(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            Path(".env.test").write_text("MY_SECRET=hunter2\nOTHER_VAR=hello\n")
            result = runner.invoke(
                main,
                [
                    "start",
                    "web",
                    "python -c 'import os; print(os.environ[\"MY_SECRET\"])'",
                    "--json",
                    "--env-file",
                    ".env.test",
                ],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            pid: int = data["pid"]
            with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
                psutil.Process(pid).wait(timeout=5)
            log_path = Path(".vigil") / "logs" / "web.log"
            assert b"hunter2" in log_path.read_bytes()

    def test_start_env_file_records_env_file_and_keys_in_state(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            Path(".env.staging").write_text(
                "DATABASE_URL=postgres://localhost/db\nAPI_KEY=secret\n"
            )
            result = runner.invoke(
                main,
                [
                    "start",
                    "web",
                    "python -c 'import time; time.sleep(30)'",
                    "--json",
                    "--env-file",
                    ".env.staging",
                ],
                catch_exceptions=False,
            )
            pid: int | None = None
            try:
                assert result.exit_code == 0
                data = json.loads(result.output)
                pid = data["pid"]
                state_raw = json.loads(Path(".vigil/state.json").read_text())
                entry = state_raw["web"]
                assert entry["env_file"] == ".env.staging"
                assert set(entry["env_keys"]) == {"DATABASE_URL", "API_KEY"}
                # Values must never appear in state.json
                assert "postgres://localhost/db" not in Path(".vigil/state.json").read_text()
                assert "secret" not in Path(".vigil/state.json").read_text()
            finally:
                if pid is not None:
                    with contextlib.suppress(Exception):
                        psutil.Process(pid).kill()

    def test_start_auto_port_json_includes_port(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("psutil.net_connections", return_value=[]):
                result = runner.invoke(
                    main,
                    [
                        "start",
                        "web",
                        "python -c 'import time; time.sleep(30)'",
                        "--auto-port",
                        "--json",
                    ],
                    catch_exceptions=False,
                )
            pid: int | None = None
            try:
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                pid = data["pid"]
                assert "port" in data
                assert isinstance(data["port"], int)
            finally:
                if pid is not None:
                    with contextlib.suppress(Exception):
                        psutil.Process(pid).kill()

    def test_start_explicit_port_json_includes_port(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("psutil.net_connections", return_value=[]):
                result = runner.invoke(
                    main,
                    [
                        "start",
                        "web",
                        "python -c 'import time; time.sleep(30)'",
                        "--port",
                        "7777",
                        "--json",
                    ],
                    catch_exceptions=False,
                )
            pid: int | None = None
            try:
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                pid = data["pid"]
                assert data["port"] == 7777
            finally:
                if pid is not None:
                    with contextlib.suppress(Exception):
                        psutil.Process(pid).kill()

    def test_start_explicit_port_occupied_returns_error_with_pid(self, runner: CliRunner) -> None:
        """When the requested port is already in use, exit non-zero with an error that
        includes the occupying PID (and optionally process name)."""
        from unittest.mock import MagicMock

        occupied_conn = MagicMock()
        occupied_conn.status = "LISTEN"
        occupied_conn.laddr.port = 5432
        occupied_conn.pid = 9999

        proc_mock = MagicMock()
        proc_mock.name.return_value = "postgres"

        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with (
                patch("psutil.net_connections", return_value=[occupied_conn]),
                patch("psutil.Process", return_value=proc_mock),
            ):
                result = runner.invoke(
                    main,
                    ["start", "web", "sleep 1", "--port", "5432", "--json"],
                )
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert "error" in data
        assert "5432" in data["error"]
        assert "9999" in data["error"]
        assert "postgres" in data["error"]

    def test_start_explicit_port_outside_range_is_accepted(self, runner: CliRunner) -> None:
        """--port accepts ports outside port_range (range only constrains --auto-port)."""
        # Default port_range is (3000, 9999); port 80 is outside that range.
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("psutil.net_connections", return_value=[]):
                result = runner.invoke(
                    main,
                    [
                        "start",
                        "web",
                        "python -c 'import time; time.sleep(30)'",
                        "--port",
                        "80",
                        "--json",
                    ],
                    catch_exceptions=False,
                )
            pid: int | None = None
            try:
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                pid = data["pid"]
                assert data["port"] == 80
            finally:
                if pid is not None:
                    with contextlib.suppress(Exception):
                        psutil.Process(pid).kill()

    def test_start_explicit_port_injects_port_env_var(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("psutil.net_connections", return_value=[]):
                result = runner.invoke(
                    main,
                    [
                        "start",
                        "web",
                        "python -c 'import os; print(os.environ[\"PORT\"])'",
                        "--port",
                        "7654",
                        "--json",
                    ],
                    catch_exceptions=False,
                )
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            pid: int = data["pid"]
            with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
                psutil.Process(pid).wait(timeout=5)
            log_path = Path(".vigil") / "logs" / "web.log"
            assert b"7654" in log_path.read_bytes()

    def test_start_explicit_port_substitutes_port_in_command(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("psutil.net_connections", return_value=[]):
                result = runner.invoke(
                    main,
                    [
                        "start",
                        "web",
                        "python -c 'import sys; print(sys.argv[1])' {PORT}",
                        "--port",
                        "7654",
                        "--json",
                    ],
                    catch_exceptions=False,
                )
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            pid = data["pid"]
            with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
                psutil.Process(pid).wait(timeout=5)
            log_path = Path(".vigil") / "logs" / "web.log"
            assert b"7654" in log_path.read_bytes()

    def test_start_explicit_port_writes_port_to_statefile(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("psutil.net_connections", return_value=[]):
                result = runner.invoke(
                    main,
                    [
                        "start",
                        "web",
                        "python -c 'import time; time.sleep(30)'",
                        "--port",
                        "7654",
                        "--json",
                    ],
                    catch_exceptions=False,
                )
            pid: int | None = None
            try:
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                pid = data["pid"]
                state_raw = json.loads(Path(".vigil/state.json").read_text())
                assert state_raw["web"]["port"] == 7654
            finally:
                if pid is not None:
                    with contextlib.suppress(Exception):
                        psutil.Process(pid).kill()

    def test_start_auto_port_and_explicit_port_mutually_exclusive(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(
                main,
                [
                    "start",
                    "web",
                    "sleep 1",
                    "--auto-port",
                    "--port",
                    "3000",
                    "--json",
                ],
            )
            assert result.exit_code != 0

    def test_start_auto_port_within_configured_range(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("psutil.net_connections", return_value=[]):
                result = runner.invoke(
                    main,
                    [
                        "start",
                        "web",
                        "python -c 'import time; time.sleep(30)'",
                        "--auto-port",
                        "--json",
                    ],
                    catch_exceptions=False,
                )
            pid: int | None = None
            try:
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                pid = data["pid"]
                port = data["port"]
                # Default port_range is (3000, 9999)
                assert 3000 <= port <= 9999
            finally:
                if pid is not None:
                    with contextlib.suppress(Exception):
                        psutil.Process(pid).kill()

    def test_start_auto_port_injects_port_env_var(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("psutil.net_connections", return_value=[]):
                result = runner.invoke(
                    main,
                    [
                        "start",
                        "web",
                        "python -c 'import os; print(os.environ[\"PORT\"])'",
                        "--auto-port",
                        "--json",
                    ],
                    catch_exceptions=False,
                )
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            pid: int = data["pid"]
            port: int = data["port"]
            with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
                psutil.Process(pid).wait(timeout=5)
            log_path = Path(".vigil") / "logs" / "web.log"
            assert str(port).encode() in log_path.read_bytes()

    def test_start_auto_port_substitutes_port_in_command(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("psutil.net_connections", return_value=[]):
                result = runner.invoke(
                    main,
                    [
                        "start",
                        "web",
                        "python -c 'import sys; print(sys.argv[1])' {PORT}",
                        "--auto-port",
                        "--json",
                    ],
                    catch_exceptions=False,
                )
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            pid: int = data["pid"]
            port: int = data["port"]
            with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
                psutil.Process(pid).wait(timeout=5)
            log_path = Path(".vigil") / "logs" / "web.log"
            assert str(port).encode() in log_path.read_bytes()

    def test_start_auto_port_writes_port_to_statefile(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("psutil.net_connections", return_value=[]):
                result = runner.invoke(
                    main,
                    [
                        "start",
                        "web",
                        "python -c 'import time; time.sleep(30)'",
                        "--auto-port",
                        "--json",
                    ],
                    catch_exceptions=False,
                )
            pid: int | None = None
            try:
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                pid = data["pid"]
                port: int = data["port"]
                state_raw = json.loads(Path(".vigil/state.json").read_text())
                assert state_raw["web"]["port"] == port
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
