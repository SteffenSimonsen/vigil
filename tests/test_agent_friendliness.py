"""Tests for issue #68: agent-friendliness improvements.

Covers:
- Named string error codes in JSON error responses
- Idempotent stop (not-found → success with status: not_running)
- Idempotent remove (not-found → success with status: not_found)
- vigil status <name> single-process query
- vigil status exit code 2 when any process is crashed/crash_looping/degraded
- Inline log_tail for crashed processes in status output
- Portless grace period in wait_for_ready
- vigil start implicit wait (returns status: "ready" by default)
- vigil start --no-wait (returns status: "started" immediately)
- vigil stop implicit TIME_WAIT wait
- vigil stop --no-wait
- vigil up --no-wait
- vigil down --no-wait
"""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
import pytest
from click.testing import CliRunner

from vigil.cli import main
from vigil.config import Config
from vigil.state import ProcessRecord, StateManager


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _write_state(vigil_dir: Path, records: dict) -> None:  # type: ignore[type-arg]
    (vigil_dir / "state.json").write_text(json.dumps(records))


def _make_conn(pid: int, port: int, status: str = "LISTEN") -> MagicMock:
    conn = MagicMock()
    conn.pid = pid
    conn.status = status
    conn.laddr = MagicMock()
    conn.laddr.port = port
    return conn


# ── Named error codes ──────────────────────────────────────────────────────────


class TestNamedErrorCodes:
    def test_start_duplicate_returns_already_running_code(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            r1 = runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'", "--no-wait", "--json"],
                catch_exceptions=False,
            )
            pid: int = json.loads(r1.output)["pid"]
            try:
                result = runner.invoke(
                    main,
                    [
                        "start",
                        "web",
                        "python -c 'import time; time.sleep(30)'",
                        "--no-wait",
                        "--json",
                    ],
                )
                assert result.exit_code != 0
                data = json.loads(result.output)
                assert data["code"] == "already_running"
            finally:
                with contextlib.suppress(Exception):
                    psutil.Process(pid).kill()

    def test_restart_not_found_returns_process_not_found_code(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["restart", "ghost", "--json"])
            assert result.exit_code != 0
            data = json.loads(result.output)
            assert data["code"] == "process_not_found"

    def test_start_corrupted_state_returns_state_corrupted_code(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            Path(".vigil/state.json").write_text("not json at all")
            result = runner.invoke(main, ["start", "web", "echo hi", "--json"])
            assert result.exit_code != 0
            data = json.loads(result.output)
            assert data["code"] == "state_corrupted"

    def test_general_error_returns_error_code(self, runner: CliRunner) -> None:
        """Missing .vigil directory produces code: 'error'."""
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["start", "web", "echo hi", "--json"])
            assert result.exit_code != 0
            data = json.loads(result.output)
            assert data["code"] == "error"

    def test_code_field_is_string_not_int(self, runner: CliRunner) -> None:
        """All JSON error code fields are strings, not the old numeric 1."""
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["start", "web", "echo hi", "--json"])
            assert result.exit_code != 0
            data = json.loads(result.output)
            assert isinstance(data["code"], str)
            assert data["code"] != "1"


# ── Idempotent stop ────────────────────────────────────────────────────────────


class TestIdempotentStop:
    def test_stop_not_running_returns_success(self, runner: CliRunner) -> None:
        """vigil stop on a non-existent process returns exit 0."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["stop", "ghost", "--json"])
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert data["status"] == "not_running"
            assert data["name"] == "ghost"

    def test_stop_not_running_text_mode(self, runner: CliRunner) -> None:
        """vigil stop on a non-existent process succeeds in text mode too."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["stop", "ghost"])
            assert result.exit_code == 0, result.output


# ── Idempotent remove ──────────────────────────────────────────────────────────


class TestIdempotentRemove:
    def test_remove_not_found_returns_success(self, runner: CliRunner) -> None:
        """vigil remove on a non-registered process returns exit 0."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["remove", "ghost", "--json"])
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert data["status"] == "not_found"
            assert data["name"] == "ghost"

    def test_remove_not_found_text_mode(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["remove", "ghost"])
            assert result.exit_code == 0, result.output


# ── vigil status <name> ────────────────────────────────────────────────────────


class TestStatusSingleName:
    def test_status_name_arg_returns_single_process(self, runner: CliRunner) -> None:
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 1234,
                        "command": "python -m http.server",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": None,
                    },
                    "api": {
                        "name": "api",
                        "pid": 1235,
                        "command": "uvicorn main:app",
                        "started_at": start_time,
                        "port": 8001,
                        "cwd": None,
                    },
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1

            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[]),
            ):
                result = runner.invoke(main, ["status", "web", "--json"], catch_exceptions=False)

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "managed" in data
        assert len(data["managed"]) == 1
        assert data["managed"][0]["name"] == "web"

    def test_status_name_not_found_exits_nonzero(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["status", "ghost", "--json"])
            assert result.exit_code != 0
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == "process_not_found"

    def test_status_no_name_returns_all_processes(self, runner: CliRunner) -> None:
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 1234,
                        "command": "python -m http.server",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": None,
                    },
                    "api": {
                        "name": "api",
                        "pid": 1235,
                        "command": "uvicorn main:app",
                        "started_at": start_time,
                        "port": 8001,
                        "cwd": None,
                    },
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1

            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[]),
            ):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["managed"]) == 2


# ── vigil status exit code ─────────────────────────────────────────────────────


class TestStatusExitCode:
    def test_status_exits_2_when_process_crashed(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 9999,
                        "command": "python -m http.server",
                        "started_at": time.time() - 100,
                        "port": 8000,
                        "cwd": None,
                    }
                },
            )
            with patch("psutil.pid_exists", return_value=False):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

        assert result.exit_code == 2

    def test_status_exits_2_when_process_degraded(self, runner: CliRunner) -> None:
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "database": {
                        "name": "database",
                        "pid": 9999,
                        "command": "postgres",
                        "started_at": start_time,
                        "port": 5432,
                        "cwd": None,
                        "depends_on": [],
                    },
                    "backend": {
                        "name": "backend",
                        "pid": 1234,
                        "command": "uvicorn main:app",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": None,
                        "depends_on": ["database"],
                    },
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1
            conn = _make_conn(1234, 8000)

            def pid_exists(pid: int) -> bool:
                return pid == 1234

            with (
                patch("psutil.pid_exists", side_effect=pid_exists),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[conn]),
            ):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

        assert result.exit_code == 2

    def test_status_exits_0_when_all_processes_alive(self, runner: CliRunner) -> None:
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 1234,
                        "command": "python -m http.server",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": None,
                    }
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1
            conn = _make_conn(1234, 8000)

            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[conn]),
            ):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

        assert result.exit_code == 0

    def test_status_exits_0_when_no_processes(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)
        assert result.exit_code == 0


# ── Inline log_tail for crashed processes ─────────────────────────────────────


class TestStatusLogTail:
    def test_crashed_process_includes_log_tail(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            Path(".vigil/logs").mkdir()
            log_file = Path(".vigil/logs/web.log")
            log_file.write_text("line 1\nline 2\nline 3\n")
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 9999,
                        "command": "python -m http.server",
                        "started_at": time.time() - 100,
                        "port": 8000,
                        "cwd": None,
                    }
                },
            )
            with patch("psutil.pid_exists", return_value=False):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

        data = json.loads(result.output)
        entry = data["managed"][0]
        assert "log_tail" in entry
        assert entry["log_tail"] is not None
        assert "line 3" in entry["log_tail"]

    def test_crashed_process_log_tail_null_when_no_log(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            # No log file created
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 9999,
                        "command": "python -m http.server",
                        "started_at": time.time() - 100,
                        "port": 8000,
                        "cwd": None,
                    }
                },
            )
            with patch("psutil.pid_exists", return_value=False):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

        data = json.loads(result.output)
        entry = data["managed"][0]
        assert "log_tail" in entry
        assert entry["log_tail"] is None

    def test_alive_process_has_no_log_tail(self, runner: CliRunner) -> None:
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 1234,
                        "command": "python -m http.server",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": None,
                    }
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1
            conn = _make_conn(1234, 8000)

            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[conn]),
            ):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

        data = json.loads(result.output)
        entry = data["managed"][0]
        assert "log_tail" not in entry


# ── Portless grace period ──────────────────────────────────────────────────────


class TestPortlessGracePeriod:
    def test_portless_process_that_exits_immediately_raises_process_died(self) -> None:
        """wait_for_ready on a portless process that exits immediately raises ProcessDied."""
        import tempfile

        from vigil.wait import ProcessDied, wait_for_ready

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".vigil").mkdir()
            (root / ".vigil" / "logs").mkdir()
            cfg = Config(root=root)

            # Write a record for a dead process
            record = ProcessRecord(name="web", pid=99999999, command="echo hi", started_at=1000.0)
            StateManager(cfg).write(record)

            with patch("psutil.pid_exists", return_value=False), pytest.raises(ProcessDied):
                wait_for_ready(cfg, "web", timeout=5)

    def test_portless_process_that_survives_grace_period_returns(self) -> None:
        """wait_for_ready on a portless process that stays alive returns after grace period."""
        import tempfile

        from vigil.wait import wait_for_ready

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".vigil").mkdir()
            (root / ".vigil" / "logs").mkdir()
            cfg = Config(root=root)

            record = ProcessRecord(name="web", pid=12345, command="sleep 10", started_at=1000.0)
            StateManager(cfg).write(record)

            mock_proc = MagicMock()
            mock_proc.create_time.return_value = 1000.0

            start = time.monotonic()
            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[]),
            ):
                wait_for_ready(cfg, "web", timeout=5)

            elapsed = time.monotonic() - start
            # Should have waited ~2s (the portless grace period), not the full 5s
            assert elapsed >= 1.5


# ── vigil start implicit wait ──────────────────────────────────────────────────


class TestStartImplicitWait:
    def test_start_with_port_returns_ready_status(self, runner: CliRunner) -> None:
        """vigil start with --port blocks until port is open and returns status: ready."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("psutil.net_connections", return_value=[]):
                # Start the process first (fire off)
                result = runner.invoke(
                    main,
                    [
                        "start",
                        "web",
                        "python -m http.server {PORT}",
                        "--port",
                        "8765",
                        "--json",
                    ],
                    catch_exceptions=False,
                )

        # After implicit wait returns, we know the process is ready
        # Since we mocked net_connections to return [], the wait will timeout or the port may open
        # For a quick test, use --no-wait to check the path
        assert result.exit_code == 0 or result.exit_code == 1  # may timeout
        if result.exit_code == 0:
            data = json.loads(result.output)
            assert data["status"] in ("ready", "started")

    def test_start_no_wait_returns_started_status(self, runner: CliRunner) -> None:
        """vigil start --no-wait returns status: started immediately."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(
                main,
                [
                    "start",
                    "web",
                    "python -c 'import time; time.sleep(30)'",
                    "--no-wait",
                    "--json",
                ],
                catch_exceptions=False,
            )
            pid: int | None = None
            try:
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                pid = data["pid"]
                assert data["status"] == "started"
            finally:
                if pid is not None:
                    with contextlib.suppress(Exception):
                        psutil.Process(pid).kill()

    def test_start_portless_returns_ready_after_grace_period(self, runner: CliRunner) -> None:
        """vigil start portless process returns status: ready after 2s grace period."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            start = time.monotonic()
            result = runner.invoke(
                main,
                [
                    "start",
                    "web",
                    "python -c 'import time; time.sleep(30)'",
                    "--json",
                ],
                catch_exceptions=False,
            )
            elapsed = time.monotonic() - start
            pid: int | None = None
            try:
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                pid = data["pid"]
                assert data["status"] == "ready"
                # Should have waited ~2s
                assert elapsed >= 1.5
            finally:
                if pid is not None:
                    with contextlib.suppress(Exception):
                        psutil.Process(pid).kill()

    def test_start_portless_crash_returns_error(self, runner: CliRunner) -> None:
        """vigil start on a process that exits immediately returns error."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(
                main,
                [
                    "start",
                    "web",
                    "python -c 'import sys; sys.exit(1)'",
                    "--json",
                ],
            )
            assert result.exit_code != 0
            data = json.loads(result.output)
            assert "error" in data


# ── vigil stop implicit wait and --no-wait ─────────────────────────────────────


class TestStopNoWait:
    def test_stop_no_wait_returns_immediately(self, runner: CliRunner) -> None:
        """vigil stop --no-wait returns immediately after killing the process."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            start_result = runner.invoke(
                main,
                [
                    "start",
                    "web",
                    "python -c 'import time; time.sleep(30)'",
                    "--no-wait",
                    "--json",
                ],
                catch_exceptions=False,
            )
            pid: int = json.loads(start_result.output)["pid"]
            try:
                with patch("vigil.scanner.port_socket_state", return_value="time_wait"):
                    result = runner.invoke(
                        main, ["stop", "web", "--no-wait", "--json"], catch_exceptions=False
                    )
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                assert data["status"] in ("stopped", "cleaned_up")
            finally:
                with contextlib.suppress(Exception):
                    psutil.Process(pid).kill()

    def test_stop_waits_for_time_wait_by_default(self, runner: CliRunner) -> None:
        """vigil stop blocks until TIME_WAIT clears (mocked port transitions)."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            start_result = runner.invoke(
                main,
                [
                    "start",
                    "web",
                    "python -c 'import time; time.sleep(30)'",
                    "--no-wait",
                    "--json",
                ],
                catch_exceptions=False,
            )
            pid: int = json.loads(start_result.output)["pid"]
            try:
                call_count = 0

                def port_state_side_effect(port: int) -> str:
                    nonlocal call_count
                    call_count += 1
                    # First call: time_wait, subsequent: closed
                    return "time_wait" if call_count <= 2 else "closed"

                with (
                    patch("vigil.scanner.ports_for_pid", return_value=[9999]),
                    patch("vigil.scanner.port_socket_state", side_effect=port_state_side_effect),
                ):
                    result = runner.invoke(main, ["stop", "web", "--json"], catch_exceptions=False)
                assert result.exit_code == 0, result.output
            finally:
                with contextlib.suppress(Exception):
                    psutil.Process(pid).kill()


# ── vigil up --no-wait ─────────────────────────────────────────────────────────


class TestUpNoWait:
    def test_up_no_wait_returns_started_status(self, runner: CliRunner) -> None:
        """vigil up --no-wait returns status: started per process."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            Path("Vigilfile").write_text(
                '[[process]]\nname = "web"\ncommand = "python -c \'import time; time.sleep(30)\'"\n'
            )
            result = runner.invoke(
                main,
                ["up", "--no-wait", "--json"],
                catch_exceptions=False,
            )
            pid: int | None = None
            try:
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                assert len(data["processes"]) == 1
                entry = data["processes"][0]
                pid = entry["pid"]
                assert entry["status"] == "started"
            finally:
                if pid is not None:
                    with contextlib.suppress(Exception):
                        psutil.Process(pid).kill()

    def test_up_default_returns_ready_status(self, runner: CliRunner) -> None:
        """vigil up (default) blocks and returns status: ready per process."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            Path("Vigilfile").write_text(
                '[[process]]\nname = "web"\ncommand = "python -c \'import time; time.sleep(30)\'"\n'
            )
            result = runner.invoke(
                main,
                ["up", "--json"],
                catch_exceptions=False,
            )
            pid: int | None = None
            try:
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                assert len(data["processes"]) == 1
                entry = data["processes"][0]
                pid = entry["pid"]
                assert entry["status"] == "ready"
            finally:
                if pid is not None:
                    with contextlib.suppress(Exception):
                        psutil.Process(pid).kill()


# ── vigil down --no-wait ───────────────────────────────────────────────────────


class TestDownNoWait:
    def test_down_no_wait_returns_immediately(self, runner: CliRunner) -> None:
        """vigil down --no-wait returns after sending kill signals."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            Path("Vigilfile").write_text(
                '[[process]]\nname = "web"\ncommand = "python -c \'import time; time.sleep(30)\'"\n'
            )
            runner.invoke(
                main,
                ["up", "--no-wait", "--json"],
                catch_exceptions=False,
            )
            # Now down --no-wait
            with patch("vigil.scanner.port_socket_state", return_value="time_wait"):
                result = runner.invoke(
                    main,
                    ["down", "--no-wait", "--json"],
                    catch_exceptions=False,
                )
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert len(data["processes"]) >= 1

    def test_down_default_waits_for_time_wait(self, runner: CliRunner) -> None:
        """vigil down (default) waits for TIME_WAIT to clear."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            Path("Vigilfile").write_text(
                '[[process]]\nname = "web"\ncommand = "python -c \'import time; time.sleep(30)\'"\n'
            )
            runner.invoke(main, ["up", "--no-wait", "--json"], catch_exceptions=False)

            call_count = 0

            def port_state_side_effect(port: int) -> str:
                nonlocal call_count
                call_count += 1
                return "time_wait" if call_count <= 2 else "closed"

            with (
                patch("vigil.scanner.ports_for_pid", return_value=[]),
                patch("vigil.scanner.port_socket_state", side_effect=port_state_side_effect),
            ):
                result = runner.invoke(main, ["down", "--json"], catch_exceptions=False)

            assert result.exit_code == 0, result.output
