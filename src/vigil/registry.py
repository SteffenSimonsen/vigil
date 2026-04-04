"""Process registry — unified process lifecycle and state ownership."""

from __future__ import annotations

import contextlib
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, TypedDict

from vigil.config import Config
from vigil.logs import trim_log
from vigil.state import ProcessRecord, StateManager

# ── Exceptions ────────────────────────────────────────────────────────────────


class ProcessNotFound(Exception):
    """Raised when a name is not in the statefile."""


class ProcessAlreadyRunning(Exception):
    """Raised when a process is alive and force=False."""


class ProcessCrashed(Exception):
    """Raised when a process is registered but dead and force=False."""


# ── Result types ─────────────────────────────────────────────────────────────


class StopResult(TypedDict):
    status: str
    time_wait_ports: list[int]


class StopAllEntry(TypedDict):
    name: str
    status: str
    time_wait_ports: list[int]


class CrashObservation(TypedDict):
    circuit_open: bool
    crash_count: int
    last_crash_at: float | None
    ports: list[int]


# ── OS-boundary protocols ─────────────────────────────────────────────────────


class ProcessSpawner(Protocol):
    def spawn(
        self,
        command: str,
        *,
        cwd: str,
        env: dict[str, str] | None,
        log_path: str,
    ) -> tuple[int, float | None]: ...


class ProcessKiller(Protocol):
    def kill(self, pid: int, *, grace: int) -> None: ...


class PortProber(Protocol):
    def listening_ports(self, pid: int) -> list[int]: ...

    def port_state(self, port: int) -> str: ...


class LivenessChecker(Protocol):
    def is_alive(self, pid: int, started_at: float | None) -> bool: ...


# ── Default OS implementations ────────────────────────────────────────────────


class DefaultSpawner:
    def spawn(
        self,
        command: str,
        *,
        cwd: str,
        env: dict[str, str] | None,
        log_path: str,
    ) -> tuple[int, float | None]:
        import psutil

        log_file = open(log_path, "ab")  # noqa: SIM115 — intentionally kept open for subprocess
        try:
            if sys.platform == "win32":
                _CREATE_NEW_PROCESS_GROUP = 0x00000200
                _DETACHED_PROCESS = 0x00000008
                proc = subprocess.Popen(
                    shlex.split(command),
                    stdout=log_file,
                    stderr=log_file,
                    stdin=subprocess.DEVNULL,
                    cwd=cwd,
                    creationflags=_CREATE_NEW_PROCESS_GROUP | _DETACHED_PROCESS,
                    env=env,
                )
            else:
                proc = subprocess.Popen(
                    shlex.split(command),
                    stdout=log_file,
                    stderr=log_file,
                    stdin=subprocess.DEVNULL,
                    cwd=cwd,
                    start_new_session=True,
                    env=env,
                )
        finally:
            log_file.close()

        started_at: float | None = None
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            started_at = psutil.Process(proc.pid).create_time()

        return proc.pid, started_at


class DefaultKiller:
    def kill(self, pid: int, *, grace: int) -> None:
        import psutil

        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                check=False,
            )
            return

        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            procs = children + [parent]
        except psutil.NoSuchProcess:
            return

        for p in procs:
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                p.terminate()

        _, alive = psutil.wait_procs(procs, timeout=grace)

        for p in alive:
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                p.kill()

        psutil.wait_procs(alive, timeout=5)


class DefaultPortProber:
    def listening_ports(self, pid: int) -> list[int]:
        from vigil.scanner import ports_for_pid

        return ports_for_pid(pid)

    def port_state(self, port: int) -> str:
        from vigil.scanner import port_socket_state

        return port_socket_state(port)


_START_TIME_TOLERANCE = 30.0


class DefaultLivenessChecker:
    def is_alive(self, pid: int, started_at: float | None) -> bool:
        import psutil

        if not psutil.pid_exists(pid):
            return False
        if started_at is None:
            return True
        try:
            proc = psutil.Process(pid)
            return abs(proc.create_time() - started_at) <= _START_TIME_TOLERANCE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False


# ── ProcessRegistry ───────────────────────────────────────────────────────────


class ProcessRegistry:
    def __init__(
        self,
        config: Config,
        *,
        spawner: ProcessSpawner | None = None,
        killer: ProcessKiller | None = None,
        port_prober: PortProber | None = None,
        liveness_checker: LivenessChecker | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        self._spawner: ProcessSpawner = spawner or DefaultSpawner()
        self._killer: ProcessKiller = killer or DefaultKiller()
        self._port_prober: PortProber = port_prober or DefaultPortProber()
        self._liveness_checker: LivenessChecker = liveness_checker or DefaultLivenessChecker()
        self._clock = clock

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _read_records(self) -> list[ProcessRecord]:
        """Read all records, annotating alive via the injected liveness checker."""
        state = StateManager(self._config)
        raw_records = state.read_unannotated()
        for r in raw_records:
            r.alive = self._liveness_checker.is_alive(r.pid, r.started_at)
        return raw_records

    def _get_or_raise(self, name: str) -> ProcessRecord:
        records = {r.name: r for r in self._read_records()}
        if name not in records:
            raise ProcessNotFound(f"No managed process named {name!r}.")
        return records[name]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(
        self,
        name: str,
        command: str,
        *,
        force: bool = False,
        env: dict[str, str] | None = None,
        env_file: str | None = None,
        cwd: str | None = None,
        depends_on: list[str] | None = None,
    ) -> ProcessRecord:
        state = StateManager(self._config)
        existing = {r.name: r for r in self._read_records()}

        if name in existing:
            rec = existing[name]
            if rec.alive:
                if not force:
                    raise ProcessAlreadyRunning(
                        f"Process {name!r} is already running (pid {rec.pid}). "
                        "Use --force to restart it."
                    )
                self._killer.kill(rec.pid, grace=self._config.stop_grace_period)
                state.delete(name)
            else:
                if not force:
                    raise ProcessCrashed(
                        f"Process {name!r} crashed (pid {rec.pid}). "
                        "Use --force to start a fresh one."
                    )

        if not name.strip():
            raise ValueError("Process name cannot be empty.")
        if len(name) > 200:
            raise ValueError(
                f"Process name is too long ({len(name)} characters)."
                " Names must be 200 characters or fewer."
            )
        if "/" in name or "\\" in name or name == "..":
            raise ValueError(
                f"Process name {name!r} is invalid. Names may not contain '/', '\\', or be '..'."
            )
        if not command.strip():
            raise ValueError("Command cannot be empty")

        effective_cwd = str(Path(cwd) if cwd else self._config.root)
        log_path = str(self._config.logs_dir / f"{name}.log")
        self._config.logs_dir.mkdir(parents=True, exist_ok=True)

        file_vars: dict[str, str] = {}
        if env_file:
            from dotenv import dotenv_values

            loaded = dotenv_values(env_file)
            file_vars = {k: v for k, v in loaded.items() if v is not None}

        merged_env: dict[str, str] = {**file_vars, **(env or {})}
        recorded_env_keys = sorted(merged_env.keys())

        child_env: dict[str, str] | None = None
        if merged_env:
            child_env = os.environ.copy()
            child_env.update(merged_env)

        pid, started_at = self._spawner.spawn(
            command,
            cwd=effective_cwd,
            env=child_env,
            log_path=log_path,
        )

        record = ProcessRecord(
            name=name,
            pid=pid,
            command=command,
            started_at=started_at,
            cwd=effective_cwd,
            env_file=env_file,
            env_keys=recorded_env_keys,
            session_id=os.environ.get("VIGIL_SESSION_ID"),
            depends_on=depends_on or [],
        )
        state.write(record)
        return record

    def stop(self, name: str) -> StopResult:
        state = StateManager(self._config)
        record = self._get_or_raise(name)
        was_alive = record.alive

        held_ports: list[int] = []
        if was_alive:
            held_ports = self._port_prober.listening_ports(record.pid)
            self._killer.kill(record.pid, grace=self._config.stop_grace_period)

        state.delete(name)
        trim_log(self._config, name, max_lines=self._config.log_retention_lines)

        tw_ports = [p for p in held_ports if self._port_prober.port_state(p) == "time_wait"]
        return StopResult(
            status="stopped" if was_alive else "cleaned_up",
            time_wait_ports=tw_ports,
        )

    def restart(self, name: str) -> ProcessRecord:
        record = self._get_or_raise(name)
        self.stop(name)
        return self.start(
            name,
            record.command,
            force=True,
            cwd=record.cwd,
            env_file=record.env_file,  # preserved — fixes the silent data-loss bug
        )

    def remove(self, name: str, *, force: bool = False) -> None:
        record = self._get_or_raise(name)
        if record.alive and not force:
            raise ProcessAlreadyRunning(
                f"Process {name!r} is still running (pid {record.pid}). "
                "Use --force to remove the registry entry without stopping it."
            )
        StateManager(self._config).delete(name)

    def stop_all(self) -> list[StopAllEntry]:
        records = self._read_records()
        results: list[StopAllEntry] = []
        for record in records:
            try:
                result = self.stop(record.name)
                results.append(
                    StopAllEntry(
                        name=record.name,
                        status=result["status"],
                        time_wait_ports=result["time_wait_ports"],
                    )
                )
            except Exception:
                results.append(
                    StopAllEntry(
                        name=record.name,
                        status="error",
                        time_wait_ports=[],
                    )
                )
        return results

    def set_depends_on(self, name: str, depends_on: list[str]) -> None:
        StateManager(self._config).update(name, depends_on=depends_on)

    # ── Observation ───────────────────────────────────────────────────────────

    def observe_all(
        self,
        records: list[ProcessRecord] | None = None,
        *,
        crash_threshold: int = 5,
    ) -> dict[str, CrashObservation]:
        """Update crash-loop state for all processes and return observations.

        If *records* is provided, use it directly (avoids a second statefile read).
        Returns results directly — callers do not need to re-read state.
        """
        from vigil.scanner import ports_by_pid

        state = StateManager(self._config)
        if records is None:
            records = self._read_records()

        # Snapshot the socket table once for all alive processes.
        alive_pids = {r.pid for r in records if r.alive}
        pid_ports_map = ports_by_pid(alive_pids) if alive_pids else {}

        results: dict[str, CrashObservation] = {}

        for record in records:
            name = record.name
            if not record.alive or record.port is None:
                results[name] = CrashObservation(
                    circuit_open=record.circuit_open,
                    crash_count=record.crash_count,
                    last_crash_at=record.last_crash_at,
                    ports=pid_ports_map.get(record.pid, []) if record.alive else [],
                )
                continue

            listening = pid_ports_map.get(record.pid, [])
            if record.port in listening:
                if record.circuit_open or record.crash_count > 0:
                    state.update(name, crash_count=0, last_crash_at=None, circuit_open=False)
                    results[name] = CrashObservation(
                        circuit_open=False, crash_count=0, last_crash_at=None, ports=listening
                    )
                else:
                    results[name] = CrashObservation(
                        circuit_open=False,
                        crash_count=record.crash_count,
                        last_crash_at=record.last_crash_at,
                        ports=listening,
                    )
                continue

            # Port absent while alive
            if record.circuit_open:
                results[name] = CrashObservation(
                    circuit_open=True,
                    crash_count=record.crash_count,
                    last_crash_at=record.last_crash_at,
                    ports=listening,
                )
                continue

            new_count = record.crash_count + 1
            circuit_open = new_count >= crash_threshold
            last_crash_at = self._clock()
            state.update(
                name,
                crash_count=new_count,
                last_crash_at=last_crash_at,
                circuit_open=circuit_open,
            )
            results[name] = CrashObservation(
                circuit_open=circuit_open,
                crash_count=new_count,
                last_crash_at=last_crash_at,
                ports=listening,
            )

        return results

    # ── Read ─────────────────────────────────────────────────────────────────

    def all(self) -> list[ProcessRecord]:
        return self._read_records()

    def get(self, name: str) -> ProcessRecord | None:
        for r in self._read_records():
            if r.name == name:
                return r
        return None

    def alive_names(self) -> set[str]:
        return {r.name for r in self._read_records() if r.alive}

    def registry_pids(self) -> set[int]:
        return {r.pid for r in self._read_records()}

    @property
    def config(self) -> Config:
        return self._config

    def ports_for_pid(self, pid: int) -> list[int]:
        """Return TCP ports this PID is listening on, via the injected PortProber."""
        return self._port_prober.listening_ports(pid)


# ── Factory ───────────────────────────────────────────────────────────────────


def make_registry(config: Config) -> ProcessRegistry:
    """One-liner for CLI commands. Wires real OS implementations."""
    return ProcessRegistry(config)
