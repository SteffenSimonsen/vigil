"""Tests for manager module — process spawning."""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import psutil
import pytest

from vigil.config import Config
from vigil.manager import ProcessAlreadyRunning, ProcessCrashed, start
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

    def test_stdout_stderr_captured_to_log_file(self, config: Config) -> None:
        record = start(config, "web", "python -c 'print(\"hello vigil\")'")
        # Give the process time to write output and exit
        with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
            psutil.Process(record.pid).wait(timeout=5)
        log_path = config.logs_dir / "web.log"
        assert log_path.exists()
        assert b"hello vigil" in log_path.read_bytes()
