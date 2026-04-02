"""Tests for manager module — process spawning."""

from __future__ import annotations

import contextlib
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
import pytest

from vigil.config import Config
from vigil.manager import ProcessAlreadyRunning, ProcessCrashed, start, stop
from vigil.state import StateManager


@pytest.fixture
def config(tmp_path: Path) -> Config:
    vigil_dir = tmp_path / ".vigil"
    vigil_dir.mkdir()
    return Config(root=tmp_path)


class TestStart:
    def test_start_returns_record_with_pid(self, config: Config) -> None:
        record = start(config, "web", "python -c 'import time; time.sleep(30)'")
        try:
            assert record.pid > 0
            assert record.name == "web"
        finally:
            psutil.Process(record.pid).kill()

    def test_started_process_is_alive(self, config: Config) -> None:
        record = start(config, "web", "python -c 'import time; time.sleep(30)'")
        try:
            assert psutil.pid_exists(record.pid)
        finally:
            psutil.Process(record.pid).kill()

    def test_record_written_to_statefile(self, config: Config) -> None:
        record = start(config, "web", "python -c 'import time; time.sleep(30)'")
        try:
            state = StateManager(config)
            records = state.read_all()
            assert len(records) == 1
            r = records[0]
            assert r.name == "web"
            assert r.pid == record.pid
            assert r.command == "python -c 'import time; time.sleep(30)'"
            assert r.started_at is not None and r.started_at > 0
            assert r.cwd is not None
        finally:
            psutil.Process(record.pid).kill()

    def test_error_if_already_alive(self, config: Config) -> None:
        record = start(config, "web", "python -c 'import time; time.sleep(30)'")
        try:
            with pytest.raises(ProcessAlreadyRunning):
                start(config, "web", "python -c 'import time; time.sleep(30)'")
        finally:
            psutil.Process(record.pid).kill()

    def test_error_if_crashed(self, config: Config) -> None:
        record = start(config, "web", "python -c 'pass'")
        # Wait for process to exit
        with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
            psutil.Process(record.pid).wait(timeout=5)
        time.sleep(0.1)
        with pytest.raises(ProcessCrashed):
            start(config, "web", "python -c 'pass'")

    def test_force_stops_alive_and_starts_fresh(self, config: Config) -> None:
        first = start(config, "web", "python -c 'import time; time.sleep(30)'")
        second = start(config, "web", "python -c 'import time; time.sleep(30)'", force=True)
        try:
            assert second.pid != first.pid
            assert not psutil.pid_exists(first.pid)
            assert psutil.pid_exists(second.pid)
        finally:
            with contextlib.suppress(psutil.NoSuchProcess):
                psutil.Process(second.pid).kill()

    def test_force_replaces_crashed_entry(self, config: Config) -> None:
        first = start(config, "web", "python -c 'pass'")
        with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
            psutil.Process(first.pid).wait(timeout=5)
        time.sleep(0.1)
        second = start(config, "web", "python -c 'import time; time.sleep(30)'", force=True)
        try:
            assert second.pid != first.pid
            assert psutil.pid_exists(second.pid)
        finally:
            with contextlib.suppress(psutil.NoSuchProcess):
                psutil.Process(second.pid).kill()

    def test_env_vars_injected_into_child(self, config: Config) -> None:
        record = start(
            config,
            "web",
            "python -c 'import os; print(os.environ[\"VIGIL_TEST_VAR\"])'",
            env={"VIGIL_TEST_VAR": "hello_from_vigil"},
        )
        with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
            psutil.Process(record.pid).wait(timeout=5)
        log_path = config.logs_dir / "web.log"
        assert b"hello_from_vigil" in log_path.read_bytes()

    def test_cwd_sets_working_dir_for_child(self, config: Config, tmp_path: Path) -> None:
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        record = start(
            config,
            "web",
            "python -c 'import os; print(os.getcwd())'",
            cwd=str(subdir),
        )
        with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
            psutil.Process(record.pid).wait(timeout=5)
        log_path = config.logs_dir / "web.log"
        assert str(subdir).encode() in log_path.read_bytes()

    def test_start_stores_none_started_at_when_psutil_create_time_unavailable(
        self, config: Config
    ) -> None:
        """When psutil cannot get create_time (race condition), started_at must be None,
        not wall-clock time — so liveness falls back to PID-only check."""
        from unittest.mock import MagicMock, patch

        mock_popen = MagicMock()
        mock_popen.pid = 99999

        mock_psutil_proc = MagicMock()
        mock_psutil_proc.create_time.side_effect = psutil.NoSuchProcess(pid=99999)

        with (
            patch("subprocess.Popen", return_value=mock_popen),
            patch("psutil.Process", return_value=mock_psutil_proc),
        ):
            record = start(config, "web", "python -c 'pass'")

        assert record.started_at is None

    def test_stop_kills_entire_process_tree(self, config: Config) -> None:
        """Stopping a process must kill all descendant processes, not just the top-level PID."""
        # Write a helper script to a temp file to avoid shell-quoting issues
        script_path = config.root / "spawner.py"
        script_path.write_text(
            "import subprocess, time\n"
            "subprocess.Popen(['python', '-c', 'import time; time.sleep(60)'])\n"
            "time.sleep(60)\n"
        )
        record = start(config, "web", f"python {script_path}")
        # Give parent time to spawn child
        deadline = time.monotonic() + 5.0
        children: list[psutil.Process] = []
        while time.monotonic() < deadline:
            with contextlib.suppress(psutil.NoSuchProcess):
                children = psutil.Process(record.pid).children(recursive=True)
            if children:
                break
            time.sleep(0.1)
        assert children, "Expected at least one child process to have been spawned"
        child_pids = [c.pid for c in children]

        stop(config, "web")

        time.sleep(0.3)
        assert not psutil.pid_exists(record.pid), "Parent process should be dead after stop"
        for child_pid in child_pids:
            assert not psutil.pid_exists(child_pid), f"Child {child_pid} should be dead after stop"

    def test_stdout_stderr_captured_to_log_file(self, config: Config) -> None:
        record = start(config, "web", "python -c 'print(\"hello vigil\")'")
        # Give the process time to write output and exit
        with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
            psutil.Process(record.pid).wait(timeout=5)
        log_path = config.logs_dir / "web.log"
        assert log_path.exists()
        assert b"hello vigil" in log_path.read_bytes()


class TestWindowsCompat:
    # Windows-specific constants (not available on non-Windows, so hardcode)
    _CREATE_NEW_PROCESS_GROUP = 0x00000200
    _DETACHED_PROCESS = 0x00000008

    def test_start_uses_windows_creationflags_on_windows(self, config: Config) -> None:
        """On Windows, Popen must use CREATE_NEW_PROCESS_GROUP|DETACHED_PROCESS."""
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_psutil = MagicMock()
        mock_psutil.create_time.return_value = time.time()

        mock_msvcrt = types.ModuleType("msvcrt")
        mock_msvcrt.LK_NBLCK = 2  # type: ignore[attr-defined]
        mock_msvcrt.LK_UNLCK = 0  # type: ignore[attr-defined]
        mock_msvcrt.locking = MagicMock()  # type: ignore[attr-defined]

        with (
            patch("sys.platform", "win32"),
            patch.dict(sys.modules, {"msvcrt": mock_msvcrt}),
            patch("vigil.manager.subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch("vigil.manager.psutil.Process", return_value=mock_psutil),
        ):
            start(config, "web", "python -c 'pass'")

        kwargs = mock_popen.call_args.kwargs
        expected = self._CREATE_NEW_PROCESS_GROUP | self._DETACHED_PROCESS
        assert kwargs.get("creationflags") == expected
        assert "start_new_session" not in kwargs

    def test_start_uses_start_new_session_on_unix(self, config: Config) -> None:
        """On Unix, Popen must use start_new_session=True."""
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_psutil = MagicMock()
        mock_psutil.create_time.return_value = time.time()

        with (
            patch("sys.platform", "linux"),
            patch("vigil.manager.subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch("vigil.manager.psutil.Process", return_value=mock_psutil),
        ):
            start(config, "web", "python -c 'pass'")

        kwargs = mock_popen.call_args.kwargs
        assert kwargs.get("start_new_session") is True
        assert "creationflags" not in kwargs

    def test_stop_uses_taskkill_on_windows(self, config: Config) -> None:
        """On Windows, stop must use taskkill /F /T /PID for process tree kill."""
        record = start(config, "web", "python -c 'import time; time.sleep(30)'")
        pid = record.pid

        mock_msvcrt = types.ModuleType("msvcrt")
        mock_msvcrt.LK_NBLCK = 2  # type: ignore[attr-defined]
        mock_msvcrt.LK_UNLCK = 0  # type: ignore[attr-defined]
        mock_msvcrt.locking = MagicMock()  # type: ignore[attr-defined]

        try:
            with (
                patch("sys.platform", "win32"),
                patch.dict(sys.modules, {"msvcrt": mock_msvcrt}),
                patch("vigil.manager.subprocess.run") as mock_run,
            ):
                stop(config, "web")
            mock_run.assert_called_once_with(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                check=False,
            )
        finally:
            with contextlib.suppress(psutil.NoSuchProcess):
                psutil.Process(pid).kill()
