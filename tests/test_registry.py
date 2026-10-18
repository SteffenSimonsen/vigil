"""Tests for ProcessRegistry — unified process lifecycle and state ownership."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vigil.config import Config
from vigil.registry import PortOccupied, ProcessAlreadyRunning, ProcessRegistry
from vigil.state import ProcessRecord, StateManager


def _listen_conn(pid: int, port: int) -> MagicMock:
    """Return a mock net connection in LISTEN state."""
    conn = MagicMock()
    conn.pid = pid
    conn.status = "LISTEN"
    conn.laddr.port = port
    return conn


@pytest.fixture
def config(tmp_path: Path) -> Config:
    (tmp_path / ".vigil").mkdir()
    return Config(root=tmp_path)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _write_record(
    config: Config,
    *,
    name: str = "web",
    pid: int = 12345,
    command: str = "uvicorn app:app",
    started_at: float = 1000.0,
    port: int | None = None,
    env_file: str | None = None,
    env_keys: list[str] | None = None,
) -> ProcessRecord:
    record = ProcessRecord(
        name=name,
        pid=pid,
        command=command,
        started_at=started_at,
        port=port,
        env_file=env_file,
        env_keys=env_keys or [],
    )
    StateManager(config).write(record)
    return record


class FakeLivenessChecker:
    def __init__(self, alive_pids: set[int] | None = None) -> None:
        self._alive = alive_pids or set()

    def is_alive(self, pid: int, started_at: float | None) -> bool:
        return pid in self._alive


class FakeSpawner:
    def __init__(self, pid: int = 99001, started_at: float = 2000.0) -> None:
        self._pid = pid
        self._started_at = started_at
        self.calls: list[dict[str, object]] = []

    def spawn(
        self,
        command: str,
        *,
        cwd: str,
        env: dict[str, str] | None,
        log_path: str,
    ) -> tuple[int, float | None]:
        self.calls.append({"command": command, "cwd": cwd, "env": env, "log_path": log_path})
        return self._pid, self._started_at


class SequenceSpawner(FakeSpawner):
    def __init__(self) -> None:
        super().__init__()
        self._next_pid = 99001

    def spawn(
        self,
        command: str,
        *,
        cwd: str,
        env: dict[str, str] | None,
        log_path: str,
    ) -> tuple[int, float | None]:
        self.calls.append({"command": command, "cwd": cwd, "env": env, "log_path": log_path})
        pid = self._next_pid
        self._next_pid += 1
        return pid, 2000.0


class FakeKiller:
    def __init__(self) -> None:
        self.killed: list[int] = []
        self._raise_on: set[int] = set()

    def raise_on(self, pid: int) -> None:
        self._raise_on.add(pid)

    def kill(self, pid: int, *, grace: int) -> None:
        if pid in self._raise_on:
            raise RuntimeError(f"kill failed for pid {pid}")
        self.killed.append(pid)


class FakePortProber:
    def __init__(self, listening: dict[int, list[int]] | None = None) -> None:
        # pid -> ports
        self._listening: dict[int, list[int]] = listening or {}

    def listening_ports(self, pid: int) -> list[int]:
        return self._listening.get(pid, [])

    def port_state(self, port: int) -> str:
        return "free"


# ── Cycle 1: set_depends_on persists ─────────────────────────────────────────


class TestSetDependsOn:
    def test_set_depends_on_persists(self, config: Config) -> None:
        _write_record(config, name="web")
        reg = ProcessRegistry(config)
        reg.set_depends_on("web", ["db", "cache"])
        result = reg.get("web")
        assert result is not None
        assert result.depends_on == ["db", "cache"]


class TestLifecycleConcurrency:
    def test_concurrent_start_same_name_spawns_once(self, config: Config) -> None:
        entered_spawn = threading.Event()
        release_spawn = threading.Event()

        class BlockingSpawner(FakeSpawner):
            def spawn(
                self,
                command: str,
                *,
                cwd: str,
                env: dict[str, str] | None,
                log_path: str,
            ) -> tuple[int, float | None]:
                entered_spawn.set()
                assert release_spawn.wait(timeout=2)
                return super().spawn(command, cwd=cwd, env=env, log_path=log_path)

        spawner = BlockingSpawner()
        liveness = FakeLivenessChecker({99001})
        results: list[ProcessRecord] = []
        errors: list[Exception] = []

        def start() -> None:
            try:
                results.append(
                    ProcessRegistry(config, spawner=spawner, liveness_checker=liveness).start(
                        "web", "sleep 60"
                    )
                )
            except Exception as exc:
                errors.append(exc)

        first = threading.Thread(target=start)
        second = threading.Thread(target=start)
        first.start()
        assert entered_spawn.wait(timeout=2)
        second.start()
        release_spawn.set()
        first.join(timeout=2)
        second.join(timeout=2)

        assert len(results) == 1
        assert len(spawner.calls) == 1
        assert len(errors) == 1
        assert isinstance(errors[0], ProcessAlreadyRunning)

    def test_registry_read_waits_for_start_transition(self, config: Config) -> None:
        entered_spawn = threading.Event()
        release_spawn = threading.Event()
        read_finished = threading.Event()

        class BlockingSpawner(FakeSpawner):
            def spawn(
                self,
                command: str,
                *,
                cwd: str,
                env: dict[str, str] | None,
                log_path: str,
            ) -> tuple[int, float | None]:
                entered_spawn.set()
                assert release_spawn.wait(timeout=2)
                return super().spawn(command, cwd=cwd, env=env, log_path=log_path)

        spawner = BlockingSpawner()
        registry = ProcessRegistry(config, spawner=spawner)
        starter = threading.Thread(target=lambda: registry.start("web", "sleep 60"))
        starter.start()
        assert entered_spawn.wait(timeout=2)

        observed: list[ProcessRecord] = []

        def read() -> None:
            observed.extend(registry.all())
            read_finished.set()

        reader = threading.Thread(target=read)
        reader.start()
        assert not read_finished.wait(timeout=0.05)
        release_spawn.set()
        starter.join(timeout=2)
        reader.join(timeout=2)

        assert read_finished.is_set()
        assert [record.name for record in observed] == ["web"]

    def test_auto_ports_exclude_alive_registry_reservations(self, config: Config) -> None:
        spawner = SequenceSpawner()
        liveness = FakeLivenessChecker({99001, 99002})
        registry = ProcessRegistry(config, spawner=spawner, liveness_checker=liveness)

        with patch("psutil.net_connections", return_value=[]):
            first = registry.start("web", "serve", auto_port=True)
            second = registry.start("api", "serve", auto_port=True)

        assert first.port == 3000
        assert second.port == 3001

    def test_failed_state_write_kills_new_child(self, config: Config) -> None:
        spawner = FakeSpawner()
        killer = FakeKiller()
        registry = ProcessRegistry(config, spawner=spawner, killer=killer)

        with (
            patch.object(StateManager, "write", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            registry.start("web", "serve")

        assert killer.killed == [99001]

    def test_failed_restart_retains_old_record(self, config: Config) -> None:
        spawner = MagicMock()
        spawner.spawn.side_effect = [(99001, 1000.0), OSError("spawn failed")]
        killer = FakeKiller()
        liveness = FakeLivenessChecker({99001})
        registry = ProcessRegistry(
            config,
            spawner=spawner,
            killer=killer,
            liveness_checker=liveness,
        )
        registry.start("web", "serve", port=8080, depends_on=["db"])

        with pytest.raises(OSError, match="spawn failed"):
            registry.restart("web")

        records = StateManager(config).read_unannotated()
        assert len(records) == 1
        assert records[0].pid == 99001
        assert records[0].port == 8080
        assert records[0].depends_on == ["db"]

    def test_force_start_validates_before_killing_existing_process(self, config: Config) -> None:
        _write_record(config, pid=99001)
        killer = FakeKiller()
        registry = ProcessRegistry(
            config,
            killer=killer,
            liveness_checker=FakeLivenessChecker({99001}),
        )

        with pytest.raises(ValueError, match="Command cannot be empty"):
            registry.start("web", "", force=True)

        assert killer.killed == []

    def test_stop_if_pid_ignores_reused_pid(self, config: Config) -> None:
        _write_record(config, pid=99001)
        registry = ProcessRegistry(
            config,
            liveness_checker=FakeLivenessChecker(),
        )

        assert registry.stop_if_pid(99001) is None
        assert StateManager(config).read_unannotated()[0].name == "web"


# ── Cycle 2: restart preserves env_file ──────────────────────────────────────


class TestRestartPreservesEnvFile:
    def test_restart_preserves_env_file(self, config: Config, tmp_path: Path) -> None:
        """restart() must pass env vars loaded from env_file to the spawner on re-spawn."""
        env_path = tmp_path / ".env"
        env_path.write_text("MY_VAR=hello\n")

        spawner = FakeSpawner(pid=99001)
        killer = FakeKiller()
        liveness = FakeLivenessChecker(alive_pids={99001})

        reg = ProcessRegistry(
            config,
            spawner=spawner,
            killer=killer,
            liveness_checker=liveness,
        )

        # Start with env_file — spawner is called once (spawn #1)
        reg.start("web", "uvicorn app:app", env_file=str(env_path))
        assert len(spawner.calls) == 1

        # Restart — spawner must be called again with env vars from .env (spawn #2)
        reg.restart("web")
        assert len(spawner.calls) == 2

        restart_env = spawner.calls[1]["env"]
        assert isinstance(restart_env, dict)
        assert restart_env.get("MY_VAR") == "hello"

    def test_restart_is_idempotent_on_env(self, config: Config, tmp_path: Path) -> None:
        """Restarting twice preserves the same env on both restarts."""
        env_path = tmp_path / ".env"
        env_path.write_text("MY_VAR=stable\n")

        spawner = FakeSpawner(pid=99001)
        killer = FakeKiller()
        liveness = FakeLivenessChecker(alive_pids={99001})

        reg = ProcessRegistry(
            config,
            spawner=spawner,
            killer=killer,
            liveness_checker=liveness,
        )

        reg.start("web", "uvicorn app:app", env_file=str(env_path))
        reg.restart("web")
        reg.restart("web")

        assert len(spawner.calls) == 3
        # All three spawns must have received MY_VAR
        for call in spawner.calls:
            env = call["env"]
            assert isinstance(env, dict)
            assert env.get("MY_VAR") == "stable"


# ── Cycle 4: port snapshots are read-only ─────────────────────────────────────


class TestPortsByProcess:
    def test_snapshot_does_not_modify_state(self, config: Config) -> None:
        _write_record(config, name="web", pid=99001, port=8080)
        state_before = config.state_file.read_bytes()
        reg = ProcessRegistry(config, liveness_checker=FakeLivenessChecker({99001}))

        with patch("psutil.net_connections", return_value=[]):
            assert reg.ports_by_process() == {"web": []}

        assert config.state_file.read_bytes() == state_before

    def test_snapshot_reads_net_connections_once(self, config: Config) -> None:
        _write_record(config, name="web", pid=99001, port=8080)
        _write_record(config, name="api", pid=99002, port=9090)

        liveness = FakeLivenessChecker(alive_pids={99001, 99002})
        reg = ProcessRegistry(config, liveness_checker=liveness)

        with patch("psutil.net_connections", return_value=[]) as mock_conns:
            reg.ports_by_process()

        assert mock_conns.call_count == 1

    def test_snapshot_includes_process_ports(self, config: Config) -> None:
        _write_record(config, name="web", pid=99001, port=8080)

        liveness = FakeLivenessChecker(alive_pids={99001})
        reg = ProcessRegistry(config, liveness_checker=liveness)

        conn = _listen_conn(99001, 8080)
        with patch("psutil.net_connections", return_value=[conn]):
            ports = reg.ports_by_process()

        assert ports["web"] == [8080]


# ── Cycle 5: DefaultSpawner / DefaultKiller / DefaultLivenessChecker end-to-end


class TestDefaultSpawnerKillerLiveness:
    def test_start_and_stop_real_process(self, config: Config, tmp_path: Path) -> None:
        """DefaultSpawner starts a real process; DefaultKiller stops it; DefaultLivenessChecker
        detects both states."""
        import contextlib

        import psutil

        from vigil.registry import make_registry

        reg = make_registry(config)
        record = reg.start("web", "sleep 60")
        pid = record.pid

        try:
            # Process is alive immediately after start
            assert psutil.pid_exists(pid)

            entry = reg.get("web")
            assert entry is not None
            assert entry.alive is True

            # Stop it
            result = reg.stop("web")

            # Process is gone
            assert not psutil.pid_exists(pid)
            assert result["status"] == "stopped"
            assert reg.get("web") is None
        finally:
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                psutil.Process(pid).kill()


# ── Cycle 5b: port ownership ─────────────────────────────────────────────────


class FakePortProberWithNext:
    """PortProber that simulates a specific port being free or occupied."""

    def __init__(self, free_port: int = 3500, occupied_ports: set[int] | None = None) -> None:
        self._free_port = free_port
        self._occupied: set[int] = occupied_ports or set()

    def listening_ports(self, pid: int) -> list[int]:
        return []

    def port_state(self, port: int) -> str:
        if port in self._occupied:
            return "listen"
        return "free"


class TestPortOwnership:
    def test_auto_port_picks_port_from_port_range(self, config: Config) -> None:
        """start(auto_port=True) picks a free port within config.port_range."""
        spawner = FakeSpawner(pid=99001)
        liveness = FakeLivenessChecker()

        reg = ProcessRegistry(config, spawner=spawner, liveness_checker=liveness)

        with patch("psutil.net_connections", return_value=[]):
            record = reg.start("web", "uvicorn app:app", auto_port=True)

        start, end = config.port_range
        assert record.port is not None
        assert start <= record.port <= end

    def test_auto_port_injects_PORT_env_var(self, config: Config) -> None:
        """start(auto_port=True) injects PORT=<n> into the child environment."""
        spawner = FakeSpawner(pid=99001)
        liveness = FakeLivenessChecker()

        reg = ProcessRegistry(config, spawner=spawner, liveness_checker=liveness)

        with patch("psutil.net_connections", return_value=[]):
            record = reg.start("web", "uvicorn app:app", auto_port=True)

        assert record.port is not None
        call_env = spawner.calls[0]["env"]
        assert isinstance(call_env, dict)
        assert call_env.get("PORT") == str(record.port)

    def test_auto_port_substitutes_PORT_in_command(self, config: Config) -> None:
        """start(auto_port=True) substitutes {PORT} in the command string."""
        spawner = FakeSpawner(pid=99001)
        liveness = FakeLivenessChecker()

        reg = ProcessRegistry(config, spawner=spawner, liveness_checker=liveness)

        with patch("psutil.net_connections", return_value=[]):
            reg.start("web", "uvicorn app:app --port {PORT}", auto_port=True)

        spawned_command: str = spawner.calls[0]["command"]  # type: ignore[assignment]
        assert "{PORT}" not in spawned_command
        assert spawned_command.startswith("uvicorn app:app --port ")

    def test_auto_port_writes_port_to_record(self, config: Config) -> None:
        """start(auto_port=True) persists record.port to the statefile."""
        spawner = FakeSpawner(pid=99001)
        liveness = FakeLivenessChecker()

        reg = ProcessRegistry(config, spawner=spawner, liveness_checker=liveness)

        with patch("psutil.net_connections", return_value=[]):
            record = reg.start("web", "uvicorn app:app", auto_port=True)

        persisted = reg.get("web")
        assert persisted is not None
        assert persisted.port == record.port

    def test_explicit_port_granted_when_free(self, config: Config) -> None:
        """start(port=3000) succeeds when port 3000 is free."""
        spawner = FakeSpawner(pid=99001)
        liveness = FakeLivenessChecker()

        reg = ProcessRegistry(config, spawner=spawner, liveness_checker=liveness)

        with patch("psutil.net_connections", return_value=[]):
            record = reg.start("web", "uvicorn app:app", port=3000)

        assert record.port == 3000

    def test_explicit_port_raises_when_occupied(self, config: Config) -> None:
        """start(port=3000) raises PortOccupied when port 3000 is already in use."""
        spawner = FakeSpawner(pid=99001)
        liveness = FakeLivenessChecker()

        reg = ProcessRegistry(config, spawner=spawner, liveness_checker=liveness)

        conn = _listen_conn(pid=55555, port=3000)
        with (
            patch("psutil.net_connections", return_value=[conn]),
            pytest.raises(PortOccupied, match="3000"),
        ):
            reg.start("web", "uvicorn app:app", port=3000)

    def test_auto_port_and_explicit_port_are_mutually_exclusive(self, config: Config) -> None:
        """start(auto_port=True, port=3000) raises ValueError."""
        reg = ProcessRegistry(config)
        with pytest.raises(ValueError, match="mutually exclusive"):
            reg.start("web", "uvicorn app:app", auto_port=True, port=3000)


# ── Cycle 6: stop_all collects all results even when one stop fails ───────────


class TestStopAll:
    def test_stop_all_collects_all_results(self, config: Config) -> None:
        """stop_all() continues stopping remaining processes even if one raises."""
        for name, pid in [("web", 99001), ("db", 99002), ("cache", 99003)]:
            _write_record(config, name=name, pid=pid)

        killer = FakeKiller()
        killer.raise_on(99002)  # db will fail to kill
        liveness = FakeLivenessChecker(alive_pids={99001, 99002, 99003})

        reg = ProcessRegistry(
            config,
            killer=killer,
            liveness_checker=liveness,
        )

        results = reg.stop_all()

        assert len(results) == 3
        names = {r["name"] for r in results}
        assert names == {"web", "db", "cache"}

        # web and cache succeeded; db had an error
        by_name = {r["name"]: r for r in results}
        assert by_name["web"]["status"] == "stopped"
        assert by_name["cache"]["status"] == "stopped"
        assert by_name["db"]["status"] == "error"

    def test_stop_all_error_entry_includes_exception_message(self, config: Config) -> None:
        """stop_all() error entry must include the exception message."""
        _write_record(config, name="db", pid=99002)

        killer = FakeKiller()
        killer.raise_on(99002)
        liveness = FakeLivenessChecker(alive_pids={99002})

        reg = ProcessRegistry(config, killer=killer, liveness_checker=liveness)
        results = reg.stop_all()

        assert len(results) == 1
        assert results[0]["status"] == "error"
        assert results[0]["error"] == "kill failed for pid 99002"

    def test_stop_all_success_entry_has_no_error(self, config: Config) -> None:
        """stop_all() successful entry must have error=None."""
        _write_record(config, name="web", pid=99001)

        killer = FakeKiller()
        liveness = FakeLivenessChecker(alive_pids={99001})

        reg = ProcessRegistry(config, killer=killer, liveness_checker=liveness)
        results = reg.stop_all()

        assert len(results) == 1
        assert results[0]["status"] == "stopped"
        assert results[0]["error"] is None
