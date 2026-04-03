"""Statefile read/write (atomic, with file-lock for concurrent safety)."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

from vigil.config import Config


class StateCorruptedError(Exception):
    """Raised when state.json is corrupted or unreadable."""


# How many seconds of tolerance to allow between recorded started_at and
# the process's actual create_time (clocks differ slightly between APIs).
_START_TIME_TOLERANCE = 30.0


@dataclass
class ProcessRecord:
    """A single managed process entry."""

    name: str
    pid: int
    command: str
    started_at: float | None
    port: int | None = None
    cwd: str | None = None
    alive: bool = False  # populated on read, not persisted
    crash_count: int = 0
    last_crash_at: float | None = None
    circuit_open: bool = False
    env_file: str | None = None
    env_keys: list[str] = field(default_factory=lambda: [])
    session_id: str | None = None
    depends_on: list[str] = field(default_factory=lambda: [])

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "pid": self.pid,
            "command": self.command,
            "started_at": self.started_at,
            "port": self.port,
            "cwd": self.cwd,
            "crash_count": self.crash_count,
            "last_crash_at": self.last_crash_at,
            "circuit_open": self.circuit_open,
            "env_file": self.env_file,
            "env_keys": self.env_keys,
            "session_id": self.session_id,
            "depends_on": self.depends_on,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProcessRecord:
        return cls(
            name=data["name"],
            pid=data["pid"],
            command=data["command"],
            started_at=data.get("started_at"),
            port=data.get("port"),
            cwd=data.get("cwd"),
            crash_count=data.get("crash_count", 0),
            last_crash_at=data.get("last_crash_at"),
            circuit_open=bool(data.get("circuit_open", False)),
            env_file=data.get("env_file"),
            env_keys=data.get("env_keys", []),
            session_id=data.get("session_id"),
            depends_on=data.get("depends_on", []),
        )


def _is_pid_alive(pid: int, started_at: float | None) -> bool:
    """Return True if the PID is running and its start time matches.

    When *started_at* is None the check falls back to PID existence only —
    used when psutil create_time was unavailable at spawn time.
    """
    import psutil  # lazy: only needed when liveness is checked

    if not psutil.pid_exists(pid):
        return False
    if started_at is None:
        return True
    try:
        proc = psutil.Process(pid)
        create_time = proc.create_time()
        return abs(create_time - started_at) <= _START_TIME_TOLERANCE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


class StateManager:
    """Read/write process records in `.vigil/state.json` with atomic writes."""

    def __init__(self, config: Config) -> None:
        self.config = config

    @contextlib.contextmanager
    def _exclusive_lock(self) -> Generator[None, None, None]:
        """Acquire an exclusive file lock for the duration of a read-modify-write.

        Uses fcntl.flock on Unix and msvcrt.locking on Windows.
        """
        lock_path = self.config.state_file.parent / "state.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            import msvcrt

            with open(lock_path, "w") as lf:
                msvcrt.locking(lf.fileno(), msvcrt.LK_NBLCK, 1)
                try:
                    yield
                finally:
                    msvcrt.locking(lf.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            with open(lock_path, "w") as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lf, fcntl.LOCK_UN)

    def _load_raw(self) -> dict[str, Any]:
        if not self.config.state_file.exists():
            return {}
        try:
            with self.config.state_file.open() as f:
                data = json.load(f)
        except PermissionError as e:
            raise StateCorruptedError("State file is corrupted or unreadable") from e
        except json.JSONDecodeError as e:
            raise StateCorruptedError("State file is corrupted or unreadable") from e
        if not isinstance(data, dict):
            raise StateCorruptedError("State file is corrupted or unreadable")
        return data  # type: ignore[no-any-return]

    def _save_raw(self, data: dict[str, Any]) -> None:
        """Write atomically via a temp file and os.rename."""
        state_file = self.config.state_file
        state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=state_file.parent, prefix=".state_", suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.rename(tmp_path, state_file)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    def read_all(self) -> list[ProcessRecord]:
        """Return all records, each annotated with live PID status."""
        raw = self._load_raw()
        records: list[ProcessRecord] = []
        try:
            for item in raw.values():
                record = ProcessRecord.from_dict(item)
                record.alive = _is_pid_alive(record.pid, record.started_at)
                records.append(record)
        except (KeyError, TypeError) as e:
            raise StateCorruptedError("State file is corrupted or unreadable") from e
        return records

    def write(self, record: ProcessRecord) -> None:
        """Write or overwrite a record by name."""
        with self._exclusive_lock():
            raw = self._load_raw()
            raw[record.name] = record.to_dict()
            self._save_raw(raw)

    def delete(self, name: str) -> None:
        """Remove a record by name. No-op if not found."""
        with self._exclusive_lock():
            raw = self._load_raw()
            if name in raw:
                del raw[name]
                self._save_raw(raw)

    def update(self, name: str, **fields: int | str | float | bool | list[str] | None) -> None:
        """Update specific fields of an existing record."""
        with self._exclusive_lock():
            raw = self._load_raw()
            if name not in raw:
                raise KeyError(f"No process named {name!r}")
            raw[name].update(fields)
            self._save_raw(raw)
