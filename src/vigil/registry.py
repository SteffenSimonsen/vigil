"""Process registry — unified process lifecycle and state ownership."""

from __future__ import annotations

import contextlib
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Protocol, TypedDict, runtime_checkable

from vigil.config import Config
from vigil.logs import trim_log
from vigil.state import ProcessRecord, StateManager

# ── Exceptions ────────────────────────────────────────────────────────────────


class ProcessNotFound(Exception):
    """Raised when a name is not in the statefile."""


class ProcessAlreadyRunning(Exception):
    """Raised when a process is alive and force=False."""


class ProcessExited(Exception):
    """Raised when a process is registered but no longer alive and force=False."""


class PortOccupied(Exception):
    """Raised when a requested port is already in use."""


# ── Result types ─────────────────────────────────────────────────────────────


class StopResult(TypedDict):
    status: str
    time_wait_ports: list[int]


class StopAllEntry(TypedDict):
    name: str
    status: str
    error: str | None
    time_wait_ports: list[int]


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


@runtime_checkable
class BatchPortProber(Protocol):
    def listening_ports_by_pid(self, pids: set[int]) -> dict[int, list[int]]: ...


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

    def listening_ports_by_pid(self, pids: set[int]) -> dict[int, list[int]]:
        from vigil.scanner import ports_by_pid

        return ports_by_pid(pids)


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
            if proc.status() == psutil.STATUS_ZOMBIE:
                return False
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
    ) -> None:
        self._config = config
        self._spawner: ProcessSpawner = spawner or DefaultSpawner()
        self._killer: ProcessKiller = killer or DefaultKiller()
        self._port_prober: PortProber = port_prober or DefaultPortProber()
        self._liveness_checker: LivenessChecker = liveness_checker or DefaultLivenessChecker()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _read_records_locked(self) -> list[ProcessRecord]:
        """Read all records, annotating alive via the injected liveness checker."""
        state = StateManager(self._config)
        raw_records = state.read_unannotated()
        for r in raw_records:
            r.alive = self._liveness_checker.is_alive(r.pid, r.started_at)
        return raw_records

    def _get_or_raise_locked(self, name: str) -> ProcessRecord:
        records = {r.name: r for r in self._read_records_locked()}
        if name not in records:
            raise ProcessNotFound(f"No managed process named {name!r}.")
        return records[name]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _resolve_port(
        self,
        auto_port: bool,
        port: int | None,
        records: list[ProcessRecord],
        *,
        replacing: str | None = None,
    ) -> int | None:
        """Pick or validate a port. Returns the resolved port, or None if neither requested."""
        if auto_port and port is not None:
            raise ValueError("--auto-port and --port are mutually exclusive")
        if not auto_port and port is None:
            return None
        from vigil.scanner import next_free_port, port_socket_state

        reserved_ports = {
            record.port
            for record in records
            if record.alive and record.port is not None and record.name != replacing
        }

        if auto_port:
            start, end = self._config.port_range
            return next_free_port(start, end=end, excluded=reserved_ports)  # type: ignore[return-value]
        # explicit port requested
        assert port is not None
        if port in reserved_ports:
            holder = next(record for record in records if record.alive and record.port == port)
            raise PortOccupied(
                f"Port {port} is reserved by managed process {holder.name!r} (pid {holder.pid})."
            )
        state = port_socket_state(port)
        if state == "listen":
            import contextlib

            import psutil

            from vigil.scanner import pid_for_port

            holder_pid = pid_for_port(port)
            holder_name: str | None = None
            if holder_pid is not None:
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    holder_name = psutil.Process(holder_pid).name()
            suffix = ""
            if holder_pid is not None:
                suffix = f" (pid {holder_pid}"
                if holder_name:
                    suffix += f", {holder_name}"
                suffix += ")"
            raise PortOccupied(f"Port {port} is already in use{suffix}.")
        return port

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
        auto_port: bool = False,
        port: int | None = None,
    ) -> ProcessRecord:
        state = StateManager(self._config)
        with state.lifecycle_lock():
            return self._start_locked(
                name,
                command,
                force=force,
                env=env,
                env_file=env_file,
                cwd=cwd,
                depends_on=depends_on,
                auto_port=auto_port,
                port=port,
            )

    def _start_locked(
        self,
        name: str,
        command: str,
        *,
        force: bool = False,
        env: dict[str, str] | None = None,
        env_file: str | None = None,
        cwd: str | None = None,
        depends_on: list[str] | None = None,
        auto_port: bool = False,
        port: int | None = None,
    ) -> ProcessRecord:
        state = StateManager(self._config)
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
        if auto_port and port is not None:
            raise ValueError("--auto-port and --port are mutually exclusive")

        records = self._read_records_locked()
        existing = {r.name: r for r in records}

        if name in existing:
            rec = existing[name]
            if rec.alive:
                if not force:
                    raise ProcessAlreadyRunning(
                        f"Process {name!r} is already running (pid {rec.pid}). "
                        "Use --force to restart it."
                    )
                self._killer.kill(rec.pid, grace=self._config.stop_grace_period)
            else:
                if not force:
                    raise ProcessExited(
                        f"Process {name!r} exited (pid {rec.pid}). "
                        "Use --force to start a fresh one."
                    )

        resolved_port = self._resolve_port(auto_port, port, records, replacing=name)

        effective_cwd = str(Path(cwd) if cwd else self._config.root)
        log_path = str(self._config.logs_dir / f"{name}.log")
        self._config.logs_dir.mkdir(parents=True, exist_ok=True)

        file_vars: dict[str, str] = {}
        if env_file:
            from dotenv import dotenv_values

            loaded = dotenv_values(env_file)
            file_vars = {k: v for k, v in loaded.items() if v is not None}

        merged_env: dict[str, str] = {**file_vars, **(env or {})}
        # Inject PORT env var if a port was assigned (explicit env takes precedence)
        if resolved_port is not None and "PORT" not in merged_env:
            merged_env["PORT"] = str(resolved_port)
        recorded_env_keys = sorted(merged_env.keys())

        child_env: dict[str, str] | None = None
        if merged_env:
            child_env = os.environ.copy()
            child_env.update(merged_env)

        # Substitute {PORT} in command string
        spawn_command = command
        if resolved_port is not None:
            spawn_command = command.replace("{PORT}", str(resolved_port))

        pid, started_at = self._spawner.spawn(
            spawn_command,
            cwd=effective_cwd,
            env=child_env,
            log_path=log_path,
        )

        record = ProcessRecord(
            name=name,
            pid=pid,
            command=command,
            started_at=started_at,
            port=resolved_port,
            cwd=effective_cwd,
            env_file=env_file,
            env_keys=recorded_env_keys,
            session_id=os.environ.get("VIGIL_SESSION_ID"),
            depends_on=depends_on or [],
        )
        try:
            state.write(record)
        except Exception:
            with contextlib.suppress(Exception):
                self._killer.kill(pid, grace=self._config.stop_grace_period)
            raise
        return record

    def stop(self, name: str) -> StopResult:
        state = StateManager(self._config)
        with state.lifecycle_lock():
            return self._stop_locked(name)

    def stop_if_pid(self, pid: int) -> StopResult | None:
        """Atomically stop the managed process still associated with *pid*."""
        state = StateManager(self._config)
        with state.lifecycle_lock():
            record = next(
                (
                    candidate
                    for candidate in self._read_records_locked()
                    if candidate.alive and candidate.pid == pid
                ),
                None,
            )
            if record is None:
                return None
            return self._stop_locked(record.name)

    def _stop_locked(self, name: str) -> StopResult:
        state = StateManager(self._config)
        record = self._get_or_raise_locked(name)
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
        state = StateManager(self._config)
        with state.lifecycle_lock():
            record = self._get_or_raise_locked(name)
            if record.alive:
                self._killer.kill(record.pid, grace=self._config.stop_grace_period)
            trim_log(self._config, name, max_lines=self._config.log_retention_lines)
            return self._start_locked(
                name,
                record.command,
                force=True,
                cwd=record.cwd,
                env_file=record.env_file,
                depends_on=record.depends_on,
                port=record.port,
            )

    def remove(self, name: str, *, force: bool = False) -> None:
        state = StateManager(self._config)
        with state.lifecycle_lock():
            record = self._get_or_raise_locked(name)
            if record.alive and not force:
                raise ProcessAlreadyRunning(
                    f"Process {name!r} is still running (pid {record.pid}). "
                    "Use --force to remove the registry entry without stopping it."
                )
            state.delete(name)

    def stop_all(self) -> list[StopAllEntry]:
        state = StateManager(self._config)
        with state.lifecycle_lock():
            records = self._read_records_locked()
            results: list[StopAllEntry] = []
            for record in records:
                try:
                    result = self._stop_locked(record.name)
                    results.append(
                        StopAllEntry(
                            name=record.name,
                            status=result["status"],
                            error=None,
                            time_wait_ports=result["time_wait_ports"],
                        )
                    )
                except Exception as exc:
                    results.append(
                        StopAllEntry(
                            name=record.name,
                            status="error",
                            error=str(exc),
                            time_wait_ports=[],
                        )
                    )
            return results

    def set_depends_on(self, name: str, depends_on: list[str]) -> None:
        state = StateManager(self._config)
        with state.lifecycle_lock():
            state.update(name, depends_on=depends_on)

    # ── Observation ───────────────────────────────────────────────────────────

    def ports_by_process(self, records: list[ProcessRecord] | None = None) -> dict[str, list[int]]:
        """Return a read-only listening-port snapshot keyed by process name."""
        if records is None:
            records = self.all()

        alive_pids = {r.pid for r in records if r.alive}
        if not alive_pids:
            pid_ports_map: dict[int, list[int]] = {}
        elif isinstance(self._port_prober, BatchPortProber):
            pid_ports_map = self._port_prober.listening_ports_by_pid(alive_pids)
        else:
            pid_ports_map = {pid: self._port_prober.listening_ports(pid) for pid in alive_pids}
        return {
            record.name: pid_ports_map.get(record.pid, []) if record.alive else []
            for record in records
        }

    # ── Read ─────────────────────────────────────────────────────────────────

    def all(self) -> list[ProcessRecord]:
        state = StateManager(self._config)
        with state.lifecycle_lock():
            return self._read_records_locked()

    def get(self, name: str) -> ProcessRecord | None:
        state = StateManager(self._config)
        with state.lifecycle_lock():
            for record in self._read_records_locked():
                if record.name == name:
                    return record
            return None

    def alive_names(self) -> set[str]:
        state = StateManager(self._config)
        with state.lifecycle_lock():
            return {r.name for r in self._read_records_locked() if r.alive}

    def registry_pids(self) -> set[int]:
        state = StateManager(self._config)
        with state.lifecycle_lock():
            return {r.pid for r in self._read_records_locked()}

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
