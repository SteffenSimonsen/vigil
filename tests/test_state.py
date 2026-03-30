"""Tests for state module."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vigil.config import Config
from vigil.state import ProcessRecord, StateManager


@pytest.fixture
def config(tmp_path: Path) -> Config:
    vigil_dir = tmp_path / ".vigil"
    vigil_dir.mkdir()
    return Config(root=tmp_path)


@pytest.fixture
def state(config: Config) -> StateManager:
    return StateManager(config)


def make_record(
    name: str = "web",
    pid: int = 1234,
    command: str = "python -m http.server",
    started_at: float | None = None,
    port: int | None = 8000,
) -> ProcessRecord:
    return ProcessRecord(
        name=name,
        pid=pid,
        command=command,
        started_at=started_at if started_at is not None else time.time(),
        port=port,
    )


class TestStateReadWrite:
    def test_write_and_read_record(self, state: StateManager) -> None:
        record = make_record()
        state.write(record)
        records = state.read_all()
        assert len(records) == 1
        assert records[0].name == "web"
        assert records[0].pid == 1234

    def test_write_multiple_records(self, state: StateManager) -> None:
        state.write(make_record(name="web", pid=1))
        state.write(make_record(name="api", pid=2))
        records = state.read_all()
        names = {r.name for r in records}
        assert names == {"web", "api"}

    def test_overwrite_existing_record_by_name(self, state: StateManager) -> None:
        state.write(make_record(name="web", pid=100))
        state.write(make_record(name="web", pid=200))
        records = state.read_all()
        assert len(records) == 1
        assert records[0].pid == 200

    def test_read_all_returns_empty_when_no_statefile(self, state: StateManager) -> None:
        records = state.read_all()
        assert records == []

    def test_port_can_be_none(self, state: StateManager) -> None:
        record = make_record(port=None)
        state.write(record)
        records = state.read_all()
        assert records[0].port is None


class TestStateDelete:
    def test_delete_removes_record(self, state: StateManager) -> None:
        state.write(make_record(name="web"))
        state.delete("web")
        records = state.read_all()
        assert records == []

    def test_delete_nonexistent_is_noop(self, state: StateManager) -> None:
        state.delete("nonexistent")  # should not raise

    def test_delete_only_removes_named_record(self, state: StateManager) -> None:
        state.write(make_record(name="web"))
        state.write(make_record(name="api"))
        state.delete("web")
        records = state.read_all()
        assert len(records) == 1
        assert records[0].name == "api"


class TestStateUpdate:
    def test_update_modifies_existing_record(self, state: StateManager) -> None:
        state.write(make_record(name="web", pid=100))
        state.update("web", pid=999)
        records = state.read_all()
        assert records[0].pid == 999

    def test_update_preserves_unmodified_fields(self, state: StateManager) -> None:
        record = make_record(name="web", pid=100, port=8000)
        state.write(record)
        state.update("web", pid=999)
        records = state.read_all()
        assert records[0].port == 8000

    def test_update_nonexistent_raises(self, state: StateManager) -> None:
        with pytest.raises(KeyError):
            state.update("nonexistent", pid=1)


class TestAtomicWrite:
    def test_failed_rename_leaves_original_intact(self, state: StateManager) -> None:
        record = make_record(name="web", pid=100)
        state.write(record)

        original_content = state.config.state_file.read_text()

        with patch("os.rename", side_effect=OSError("disk full")), pytest.raises(OSError):
            state.write(make_record(name="api", pid=200))

        assert state.config.state_file.read_text() == original_content


class TestPIDVerification:
    def test_alive_pid_with_matching_start_time_is_alive(self, state: StateManager) -> None:
        start_time = time.time() - 10
        record = make_record(pid=1234, started_at=start_time)
        state.write(record)

        mock_proc = MagicMock()
        mock_proc.create_time.return_value = start_time + 0.1  # within tolerance

        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=mock_proc),
        ):
            records = state.read_all()

        assert records[0].alive is True

    def test_pid_dead_returns_alive_false(self, state: StateManager) -> None:
        record = make_record(pid=9999)
        state.write(record)

        with patch("psutil.pid_exists", return_value=False):
            records = state.read_all()

        assert records[0].alive is False

    def test_alive_pid_with_mismatched_start_time_is_dead(self, state: StateManager) -> None:
        start_time = time.time() - 100
        record = make_record(pid=1234, started_at=start_time)
        state.write(record)

        # Process started much later — PID was reused
        mock_proc = MagicMock()
        mock_proc.create_time.return_value = time.time()

        with (
            patch("psutil.pid_exists", return_value=True),
            patch("psutil.Process", return_value=mock_proc),
        ):
            records = state.read_all()

        assert records[0].alive is False


class TestConcurrentModification:
    def test_concurrent_deletes_leave_no_stale_entries(self, state: StateManager) -> None:
        """Concurrent deletes on different names must not overwrite each other."""
        n = 10
        for i in range(n):
            state.write(make_record(name=f"proc-{i}", pid=1000 + i))

        errors: list[Exception] = []

        def delete_one(name: str) -> None:
            try:
                state.delete(name)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=delete_one, args=(f"proc-{i}",)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Threads raised errors: {errors}"
        records = state.read_all()
        assert records == [], f"Expected empty state, got {[r.name for r in records]}"
