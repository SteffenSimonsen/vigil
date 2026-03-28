"""Tests for vigil restart and vigil remove manager functions."""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import psutil
import pytest

from vigil.config import Config
from vigil.manager import ProcessAlreadyRunning, ProcessNotFound, remove, restart, start
from vigil.state import StateManager


@pytest.fixture
def config(tmp_path: Path) -> Config:
    vigil_dir = tmp_path / ".vigil"
    vigil_dir.mkdir()
    return Config(root=tmp_path)


class TestRestart:
    def test_restart_returns_new_pid(self, config: Config) -> None:
        record = start(config, "web", "python -c 'import time; time.sleep(30)'")
        old_pid = record.pid
        try:
            new_record = restart(config, "web")
            assert new_record.pid != old_pid
        finally:
            with contextlib.suppress(psutil.NoSuchProcess):
                psutil.Process(new_record.pid).kill()

    def test_restart_trims_log_between_stop_and_start(self, config: Config) -> None:
        record = start(config, "web", "python -c 'pass'")
        with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
            psutil.Process(record.pid).wait(timeout=5)
        time.sleep(0.1)

        # Overfill the log
        log_path = config.logs_dir / "web.log"
        log_path.write_text("".join(f"line {i}\n" for i in range(1, 601)))

        new_record = restart(config, "web")
        try:
            lines = log_path.read_text().splitlines()
            assert len(lines) <= config.log_retention_lines
        finally:
            with contextlib.suppress(psutil.NoSuchProcess):
                psutil.Process(new_record.pid).kill()

    def test_restart_unknown_name_raises(self, config: Config) -> None:
        with pytest.raises(ProcessNotFound):
            restart(config, "ghost")


class TestRemove:
    def test_remove_crashed_entry_deletes_from_statefile(self, config: Config) -> None:
        record = start(config, "web", "python -c 'pass'")
        with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
            psutil.Process(record.pid).wait(timeout=5)
        time.sleep(0.1)

        remove(config, "web")

        state = StateManager(config)
        assert not any(r.name == "web" for r in state.read_all())

    def test_remove_alive_process_raises(self, config: Config) -> None:
        record = start(config, "web", "python -c 'import time; time.sleep(30)'")
        try:
            with pytest.raises(ProcessAlreadyRunning):
                remove(config, "web")
        finally:
            with contextlib.suppress(psutil.NoSuchProcess):
                psutil.Process(record.pid).kill()

    def test_remove_force_removes_alive_entry_without_stopping(self, config: Config) -> None:
        record = start(config, "web", "python -c 'import time; time.sleep(30)'")
        pid = record.pid
        try:
            remove(config, "web", force=True)

            state = StateManager(config)
            assert not any(r.name == "web" for r in state.read_all())
            # Process is still running
            assert psutil.pid_exists(pid)
        finally:
            with contextlib.suppress(psutil.NoSuchProcess):
                psutil.Process(pid).kill()

    def test_remove_unknown_name_raises(self, config: Config) -> None:
        with pytest.raises(ProcessNotFound):
            remove(config, "ghost")
