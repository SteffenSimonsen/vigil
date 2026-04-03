"""Tests for ProcessRegistry — unified process lifecycle and state ownership."""

from __future__ import annotations

from pathlib import Path

import pytest

from vigil.config import Config
from vigil.registry import ProcessRegistry
from vigil.state import ProcessRecord, StateManager


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
    crash_count: int = 0,
    circuit_open: bool = False,
    last_crash_at: float | None = None,
) -> ProcessRecord:
    record = ProcessRecord(
        name=name,
        pid=pid,
        command=command,
        started_at=started_at,
        port=port,
        env_file=env_file,
        env_keys=env_keys or [],
        crash_count=crash_count,
        circuit_open=circuit_open,
        last_crash_at=last_crash_at,
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


# ── Cycle 4: observe_all returns results without re-reading ───────────────────


class TestObserveAll:
    def test_observe_all_returns_results_without_rereading(self, config: Config) -> None:
        """observe_all() result matches what a subsequent all() call shows."""
        # Process alive, has port, port is NOT listening → crash observation
        _write_record(config, name="web", pid=99001, port=8080, crash_count=0)

        port_prober = FakePortProber(listening={99001: []})  # port absent
        liveness = FakeLivenessChecker(alive_pids={99001})

        reg = ProcessRegistry(
            config,
            port_prober=port_prober,
            liveness_checker=liveness,
            clock=lambda: 5000.0,
        )

        observations = reg.observe_all()
        records_after = reg.all()

        assert "web" in observations
        obs = observations["web"]
        assert obs["crash_count"] == 1
        assert obs["circuit_open"] is False

        # all() should reflect the same state as the observation
        web_record = next(r for r in records_after if r.name == "web")
        assert web_record.crash_count == 1
        assert web_record.circuit_open is False

    def test_circuit_opens_after_threshold(self, config: Config) -> None:
        """After crash_threshold port-absent observations, circuit_open becomes True."""
        _write_record(config, name="web", pid=99001, port=8080, crash_count=4)

        port_prober = FakePortProber(listening={99001: []})  # port absent
        liveness = FakeLivenessChecker(alive_pids={99001})

        reg = ProcessRegistry(
            config,
            port_prober=port_prober,
            liveness_checker=liveness,
            clock=lambda: 5000.0,
        )

        observations = reg.observe_all(crash_threshold=5)
        assert observations["web"]["circuit_open"] is True
        assert observations["web"]["crash_count"] == 5

        # Verify state was persisted
        record = reg.get("web")
        assert record is not None
        assert record.circuit_open is True
        assert record.crash_count == 5


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
