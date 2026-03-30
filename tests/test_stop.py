"""Tests for vigil stop — graceful shutdown, log trim, statefile cleanup."""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import psutil
import pytest

from vigil.config import Config
from vigil.manager import ProcessNotFound, start, stop, stop_all
from vigil.state import StateManager


@pytest.fixture
def config(tmp_path: Path) -> Config:
    vigil_dir = tmp_path / ".vigil"
    vigil_dir.mkdir()
    return Config(root=tmp_path)


class TestStop:
    def test_stop_all_stops_every_managed_process(self, config: Config) -> None:
        r1 = start(config, "web", "python -c 'import time; time.sleep(30)'")
        r2 = start(config, "worker", "python -c 'import time; time.sleep(30)'")
        pid1, pid2 = r1.pid, r2.pid

        stop_all(config)

        assert not psutil.pid_exists(pid1)
        assert not psutil.pid_exists(pid2)
        state = StateManager(config)
        assert state.read_all() == []

    def test_stop_all_returns_per_process_status(self, config: Config) -> None:
        live = start(config, "web", "python -c 'import time; time.sleep(30)'")
        dead = start(config, "worker", "python -c 'pass'")
        with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
            psutil.Process(dead.pid).wait(timeout=5)
        time.sleep(0.1)

        results = stop_all(config)

        by_name = {r["name"]: r["status"] for r in results}
        assert by_name["web"] == "stopped"
        assert by_name["worker"] == "cleaned_up"
        with contextlib.suppress(psutil.NoSuchProcess):
            psutil.Process(live.pid).kill()

    def test_stop_trims_log_after_stopping(self, config: Config) -> None:
        record = start(config, "web", "python -c 'pass'")
        with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
            psutil.Process(record.pid).wait(timeout=5)
        time.sleep(0.1)

        # Write 600 lines to the log file
        log_path = config.logs_dir / "web.log"
        log_path.write_text("".join(f"line {i}\n" for i in range(1, 601)))

        stop(config, "web")

        result = log_path.read_text().splitlines()
        assert len(result) == 500
        assert result[-1] == "line 600"

    def test_stop_unknown_name_raises(self, config: Config) -> None:
        with pytest.raises(ProcessNotFound):
            stop(config, "nonexistent")

    def test_sigkill_sent_when_process_ignores_sigterm(self, tmp_path: Path) -> None:
        # Use grace=0 so TimeoutExpired fires immediately for a live process,
        # forcing the SIGTERM→SIGKILL escalation path.
        cfg = Config(root=tmp_path, stop_grace_period=0)
        (tmp_path / ".vigil").mkdir()
        ignore_sigterm = (
            "python -c 'import signal, time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'"
        )
        record = start(cfg, "web", ignore_sigterm)
        pid = record.pid
        try:
            stop(cfg, "web")
            assert not psutil.pid_exists(pid)
        finally:
            with contextlib.suppress(psutil.NoSuchProcess):
                psutil.Process(pid).kill()

    def test_stop_on_dead_process_is_idempotent_and_cleans_statefile(self, config: Config) -> None:
        record = start(config, "web", "python -c 'pass'")
        with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
            psutil.Process(record.pid).wait(timeout=5)
        time.sleep(0.1)

        stop(config, "web")

        state = StateManager(config)
        assert not any(r.name == "web" for r in state.read_all())

    def test_stop_returns_cleaned_up_for_already_dead_process(self, config: Config) -> None:
        record = start(config, "web", "python -c 'pass'")
        with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
            psutil.Process(record.pid).wait(timeout=5)
        time.sleep(0.1)

        result = stop(config, "web")

        assert result == "cleaned_up"

    def test_stop_returns_stopped_for_live_process(self, config: Config) -> None:
        start(config, "web", "python -c 'import time; time.sleep(30)'")

        result = stop(config, "web")

        assert result == "stopped"

    def test_stop_kills_alive_process_and_removes_statefile_entry(self, config: Config) -> None:
        record = start(config, "web", "python -c 'import time; time.sleep(30)'")
        pid = record.pid
        assert psutil.pid_exists(pid)

        stop(config, "web")

        assert not psutil.pid_exists(pid)
        state = StateManager(config)
        assert not any(r.name == "web" for r in state.read_all())
