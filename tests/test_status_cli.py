"""Tests for vigil status CLI command."""

from __future__ import annotations

import json
import time
from collections import namedtuple
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from vigil.cli import main

_DOCKER_PS_LINE = json.dumps(
    {
        "Names": "myapp-postgres-1",
        "Image": "postgres:16",
        "Labels": "com.docker.compose.service=postgres,com.docker.compose.project=myapp",
        "Ports": "0.0.0.0:5432->5432/tcp",
    }
)

_MockAddr = namedtuple("MockAddr", ["ip", "port"])
_MockConn = namedtuple("MockConn", ["fd", "family", "type", "laddr", "raddr", "status", "pid"])


def _make_conn(pid: int, port: int, status: str = "LISTEN") -> _MockConn:
    return _MockConn(-1, 2, 1, _MockAddr("0.0.0.0", port), None, status, pid)


def _write_state(vigil_dir: Path, records: dict[str, object]) -> None:
    (vigil_dir / "state.json").write_text(json.dumps(records))


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestStatusCLIJson:
    def test_empty_managed_when_no_statefile(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)
            assert result.exit_code == 0
            assert json.loads(result.output) == {"managed": []}

    def test_alive_process_appears_with_pid_and_ports(self, runner: CliRunner) -> None:
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 1234,
                        "command": "python -m http.server",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": None,
                    }
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1
            conn = _make_conn(1234, 8000)

            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[conn]),
            ):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data["managed"]) == 1
            entry = data["managed"][0]
            assert entry["name"] == "web"
            assert entry["pid"] == 1234
            assert entry["alive"] is True
            assert entry["ports"] == [8000]
            assert "crashed" not in entry

    def test_crashed_process_appears_with_crashed_flag(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 9999,
                        "command": "python -m http.server",
                        "started_at": time.time() - 100,
                        "port": 8000,
                        "cwd": None,
                    }
                },
            )
            with patch("psutil.pid_exists", return_value=False):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

            assert result.exit_code == 2
            data = json.loads(result.output)
            assert len(data["managed"]) == 1
            entry = data["managed"][0]
            assert entry["name"] == "web"
            assert entry["pid"] is None
            assert entry["alive"] is False
            assert entry["crashed"] is True
            assert entry["ports"] == []

    def test_no_records_when_statefile_is_empty(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(Path(".vigil"), {})
            result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)
            assert result.exit_code == 0
            assert json.loads(result.output) == {"managed": []}


class TestStatusCLIText:
    def test_alive_process_shows_pid_and_alive(self, runner: CliRunner) -> None:
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 1234,
                        "command": "python -m http.server",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": None,
                    }
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1
            conn = _make_conn(1234, 8000)

            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[conn]),
            ):
                result = runner.invoke(main, ["status"], catch_exceptions=False)

            assert result.exit_code == 0
            assert "web" in result.output
            assert "alive" in result.output
            assert "1234" in result.output

    def test_crashed_process_shows_crashed_warning(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 9999,
                        "command": "python -m http.server",
                        "started_at": time.time() - 100,
                        "port": 8000,
                        "cwd": None,
                    }
                },
            )
            with patch("psutil.pid_exists", return_value=False):
                result = runner.invoke(main, ["status"], catch_exceptions=False)

            assert result.exit_code == 2
            assert "web" in result.output
            assert "crashed" in result.output

    def test_no_processes_message_when_empty(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["status"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "No managed processes" in result.output

    def test_alive_process_shows_env_file_when_set(self, runner: CliRunner) -> None:
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 1234,
                        "command": "uvicorn main:app",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": None,
                        "env_file": ".env.staging",
                        "env_keys": ["DATABASE_URL"],
                    }
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1

            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[]),
            ):
                result = runner.invoke(main, ["status"], catch_exceptions=False)

        assert result.exit_code == 0
        assert ".env.staging" in result.output


class TestStatusEnvTracking:
    def test_json_includes_env_file_and_env_keys_when_set(self, runner: CliRunner) -> None:
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 1234,
                        "command": "uvicorn main:app",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": None,
                        "env_file": ".env.staging",
                        "env_keys": ["DATABASE_URL", "API_KEY"],
                    }
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1

            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[]),
            ):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

        assert result.exit_code == 0
        data = json.loads(result.output)
        entry = data["managed"][0]
        assert entry["env_file"] == ".env.staging"
        assert set(entry["env_overrides"].keys()) == {"DATABASE_URL", "API_KEY"}
        assert all(v == "[set]" for v in entry["env_overrides"].values())

    def test_json_env_file_and_keys_null_when_not_set(self, runner: CliRunner) -> None:
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 1234,
                        "command": "python -m http.server",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": None,
                    }
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1

            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[]),
            ):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

        assert result.exit_code == 0
        data = json.loads(result.output)
        entry = data["managed"][0]
        assert entry["env_file"] is None
        assert entry["env_overrides"] == {}


class TestStatusSessionId:
    def test_json_includes_session_id_for_alive_process(self, runner: CliRunner) -> None:
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 1234,
                        "command": "python -m http.server",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": None,
                        "session_id": "sess-abc",
                    }
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1

            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[]),
            ):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

        assert result.exit_code == 0
        data = json.loads(result.output)
        entry = data["managed"][0]
        assert entry["session_id"] == "sess-abc"

    def test_json_session_id_null_when_not_set(self, runner: CliRunner) -> None:
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 1234,
                        "command": "python -m http.server",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": None,
                    }
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1

            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[]),
            ):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

        assert result.exit_code == 0
        data = json.loads(result.output)
        entry = data["managed"][0]
        assert entry["session_id"] is None


class TestStatusSessionText:
    def test_text_shows_session_id_abbreviated(self, runner: CliRunner) -> None:
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 1234,
                        "command": "python -m http.server",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": None,
                        "session_id": "abcdef1234567890",
                    }
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1

            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[]),
                patch.dict("os.environ", {}, clear=True),
            ):
                result = runner.invoke(main, ["status"], catch_exceptions=False)

        assert result.exit_code == 0
        # abbreviated session_id should appear
        assert "abcdef12" in result.output

    def test_text_marks_current_session(self, runner: CliRunner) -> None:
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 1234,
                        "command": "python -m http.server",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": None,
                        "session_id": "my-session-id",
                    }
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1

            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[]),
                patch.dict("os.environ", {"VIGIL_SESSION_ID": "my-session-id"}),
            ):
                result = runner.invoke(main, ["status"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "this session" in result.output


class TestStatusDockerEnrichment:
    def test_alive_container_process_includes_docker_in_json(self, runner: CliRunner) -> None:
        """vigil status --json includes docker object when process is a container."""
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "db": {
                        "name": "db",
                        "pid": 9921,
                        "command": "docker compose up db",
                        "started_at": start_time,
                        "port": 5432,
                        "cwd": None,
                    }
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1
            conn = _make_conn(9921, 5432)

            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[conn]),
                patch("shutil.which", return_value="/usr/bin/docker"),
                patch("subprocess.run") as mock_run,
            ):
                mock_run.return_value.stdout = _DOCKER_PS_LINE + "\n"
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

        assert result.exit_code == 0
        data = json.loads(result.output)
        entry = data["managed"][0]
        assert entry["docker"] is not None
        assert entry["docker"]["container_name"] == "myapp-postgres-1"
        assert entry["docker"]["image"] == "postgres:16"

    def test_native_process_has_docker_null_in_json(self, runner: CliRunner) -> None:
        """vigil status --json has docker=null for non-container processes."""
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 1234,
                        "command": "python -m http.server",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": None,
                    }
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1
            conn = _make_conn(1234, 8000)

            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[conn]),
                patch("shutil.which", return_value=None),
            ):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

        assert result.exit_code == 0
        data = json.loads(result.output)
        entry = data["managed"][0]
        assert entry["docker"] is None


# ---------------------------------------------------------------------------
# Degraded status (alive but dependency is down)
# ---------------------------------------------------------------------------


class TestDegradedStatus:
    def test_degraded_when_alive_but_dependency_crashed(self, runner: CliRunner) -> None:
        """Process is alive but a dependency is dead → status is 'degraded'."""
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "database": {
                        "name": "database",
                        "pid": 9999,
                        "command": "postgres",
                        "started_at": start_time,
                        "port": 5432,
                        "cwd": None,
                        "depends_on": [],
                    },
                    "backend": {
                        "name": "backend",
                        "pid": 1234,
                        "command": "uvicorn main:app",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": None,
                        "depends_on": ["database"],
                    },
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1
            conn = _make_conn(1234, 8000)

            def pid_exists(pid: int) -> bool:
                return pid == 1234  # only backend alive, database dead

            with (
                patch("psutil.pid_exists", side_effect=pid_exists),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[conn]),
            ):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

            assert result.exit_code == 2
            data = json.loads(result.output)
            entries = {e["name"]: e for e in data["managed"]}
            assert entries["backend"]["status"] == "degraded"
            assert entries["database"]["status"] == "crashed"

    def test_json_includes_depends_on_and_dependency_status(self, runner: CliRunner) -> None:
        """JSON output for an alive process includes depends_on and dependency_status."""
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "database": {
                        "name": "database",
                        "pid": 9999,
                        "command": "postgres",
                        "started_at": start_time,
                        "port": 5432,
                        "cwd": None,
                        "depends_on": [],
                    },
                    "backend": {
                        "name": "backend",
                        "pid": 1234,
                        "command": "uvicorn main:app",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": None,
                        "depends_on": ["database"],
                    },
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1
            conn = _make_conn(1234, 8000)

            def pid_exists(pid: int) -> bool:
                return pid == 1234

            with (
                patch("psutil.pid_exists", side_effect=pid_exists),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[conn]),
            ):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

            data = json.loads(result.output)
            entries = {e["name"]: e for e in data["managed"]}
            backend = entries["backend"]
            assert "depends_on" in backend
            assert backend["depends_on"] == ["database"]
            assert "dependency_status" in backend
            assert backend["dependency_status"]["database"] in ("alive", "crashed", "dead")


class TestStatusNetConnectionsCallCount:
    def test_net_connections_called_once_for_port_display_with_multiple_alive_processes(
        self, runner: CliRunner
    ) -> None:
        """With N alive processes (no port configured), net_connections for port
        display should be called exactly once, not once per process."""
        start_time = time.time() - 10
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            # port: None so observe_all skips net_connections (no crash-loop check)
            # All net_connections calls come solely from the display loop.
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 1001,
                        "command": "python -m http.server 8001",
                        "started_at": start_time,
                        "port": None,
                        "cwd": None,
                    },
                    "api": {
                        "name": "api",
                        "pid": 1002,
                        "command": "python -m http.server 8002",
                        "started_at": start_time,
                        "port": None,
                        "cwd": None,
                    },
                    "worker": {
                        "name": "worker",
                        "pid": 1003,
                        "command": "python worker.py",
                        "started_at": start_time,
                        "port": None,
                        "cwd": None,
                    },
                },
            )
            mock_proc = MagicMock()
            mock_proc.create_time.return_value = start_time + 0.1

            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=mock_proc),
                patch("psutil.net_connections", return_value=[]) as mock_nc,
            ):
                result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data["managed"]) == 3
            # After fix: exactly 1 call (snapshot before loop), not 3 (one per process)
            assert mock_nc.call_count == 1
