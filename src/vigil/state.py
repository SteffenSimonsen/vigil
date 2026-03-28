"""Statefile read/write (atomic)."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass
from typing import Any

import psutil

from vigil.config import Config

# How many seconds of tolerance to allow between recorded started_at and
# the process's actual create_time (clocks differ slightly between APIs).
_START_TIME_TOLERANCE = 2.0


@dataclass
class ProcessRecord:
    """A single managed process entry."""

    name: str
    pid: int
    command: str
    started_at: float
    port: int | None = None
    cwd: str | None = None
    alive: bool = False  # populated on read, not persisted

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "pid": self.pid,
            "command": self.command,
            "started_at": self.started_at,
            "port": self.port,
            "cwd": self.cwd,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProcessRecord:
        return cls(
            name=data["name"],
            pid=data["pid"],
            command=data["command"],
            started_at=data["started_at"],
            port=data.get("port"),
            cwd=data.get("cwd"),
        )


def _is_pid_alive(pid: int, started_at: float) -> bool:
    """Return True if the PID is running and its start time matches."""
    if not psutil.pid_exists(pid):
        return False
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

    def _load_raw(self) -> dict[str, Any]:
        if not self.config.state_file.exists():
            return {}
        with self.config.state_file.open() as f:
            return json.load(f)  # type: ignore[no-any-return]

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
        for item in raw.values():
            record = ProcessRecord.from_dict(item)
            record.alive = _is_pid_alive(record.pid, record.started_at)
            records.append(record)
        return records

    def write(self, record: ProcessRecord) -> None:
        """Write or overwrite a record by name."""
        raw = self._load_raw()
        raw[record.name] = record.to_dict()
        self._save_raw(raw)

    def delete(self, name: str) -> None:
        """Remove a record by name. No-op if not found."""
        raw = self._load_raw()
        if name in raw:
            del raw[name]
            self._save_raw(raw)

    def update(self, name: str, **fields: int | str | float | None) -> None:
        """Update specific fields of an existing record."""
        raw = self._load_raw()
        if name not in raw:
            raise KeyError(f"No process named {name!r}")
        raw[name].update(fields)
        self._save_raw(raw)
