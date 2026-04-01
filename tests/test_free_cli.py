"""Integration tests for `vigil free` CLI command."""

from __future__ import annotations

import json
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from vigil.cli import main

_MockAddr = namedtuple("MockAddr", ["ip", "port"])
_MockConn = namedtuple("MockConn", ["fd", "family", "type", "laddr", "raddr", "status", "pid"])


def _make_conn(pid: int, port: int, status: str = "LISTEN") -> _MockConn:
    return _MockConn(
        fd=-1,
        family=2,
        type=1,
        laddr=_MockAddr("0.0.0.0", port),
        raddr=None,
        status=status,
        pid=pid,
    )


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestFreeManagedProcess:
    def test_free_managed_process_stops_it_and_returns_was_managed(self, runner: CliRunner) -> None:
        """vigil free on a port used by a managed process stops it via manager.stop()."""
        import contextlib

        import psutil

        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            # Start a managed process
            start_result = runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            pid: int = json.loads(start_result.output)["pid"]
            try:
                # Mock only net_connections — state manager needs real psutil to verify aliveness
                conn = _make_conn(pid, 3000)
                with (
                    patch("psutil.net_connections", return_value=[conn]),
                    patch("shutil.which", return_value=None),  # no docker
                ):
                    result = runner.invoke(main, ["free", "3000", "--json"], catch_exceptions=False)
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                assert data["port"] == 3000
                assert data["freed"] is True
                assert data["was"] == "managed"
                assert not psutil.pid_exists(pid)
            finally:
                with contextlib.suppress(Exception):
                    psutil.Process(pid).kill()


_DOCKER_PS_LINE = json.dumps(
    {
        "Names": "myapp-postgres-1",
        "Image": "postgres:16",
        "Labels": "com.docker.compose.service=postgres,com.docker.compose.project=myapp",
        "Ports": "0.0.0.0:5432->5432/tcp",
    }
)


class TestFreeUnmanagedProcess:
    def test_free_unmanaged_process_kills_it_and_returns_was_unmanaged(
        self, runner: CliRunner
    ) -> None:
        """vigil free on an unmanaged process sends SIGTERM/SIGKILL and returns was=unmanaged."""
        import contextlib
        import subprocess as real_subprocess

        import psutil

        # Start a real process outside of vigil
        proc = real_subprocess.Popen(
            ["python", "-c", "import time; time.sleep(30)"],
            stdin=real_subprocess.DEVNULL,
        )
        pid = proc.pid
        try:
            conn = _make_conn(pid, 3000)
            with runner.isolated_filesystem():
                Path(".vigil").mkdir()
                with (
                    patch("psutil.net_connections", return_value=[conn]),
                    patch("shutil.which", return_value=None),  # no docker
                ):
                    result = runner.invoke(main, ["free", "3000", "--json"], catch_exceptions=False)
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert data["port"] == 3000
            assert data["freed"] is True
            assert data["was"] == "unmanaged"
            assert not psutil.pid_exists(pid)
        finally:
            with contextlib.suppress(Exception):
                proc.kill()
                proc.wait()


class TestFreeDockerContainer:
    def test_free_docker_container_runs_docker_stop_and_returns_was_docker(
        self, runner: CliRunner
    ) -> None:
        """vigil free on a Docker container port runs docker stop and returns was=docker."""
        conn = _make_conn(9921, 5432)
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with (
                patch("psutil.net_connections", return_value=[conn]),
                patch("shutil.which", return_value="/usr/bin/docker"),
                patch("subprocess.run") as mock_run,
            ):
                mock_run.return_value.stdout = _DOCKER_PS_LINE + "\n"
                mock_run.return_value.returncode = 0
                result = runner.invoke(main, ["free", "5432", "--json"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["port"] == 5432
        assert data["freed"] is True
        assert data["was"] == "docker"
        # Verify docker stop was called with the container name
        stop_calls = [c for c in mock_run.call_args_list if "stop" in (c.args[0] if c.args else [])]
        assert any("myapp-postgres-1" in str(c) for c in stop_calls)


class TestFreeTimeWaitPort:
    def test_free_time_wait_port_returns_was_time_wait(self, runner: CliRunner) -> None:
        """vigil free on a TIME_WAIT port returns was=time_wait, freed=false."""
        conn = _make_conn(0, 3000, status="TIME_WAIT")
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("psutil.net_connections", return_value=[conn]):
                result = runner.invoke(main, ["free", "3000", "--json"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["port"] == 3000
        assert data["freed"] is False
        assert data["was"] == "time_wait"
        assert "retry_after_seconds" in data
        assert isinstance(data["retry_after_seconds"], int)


class TestFreeAlreadyFreePort:
    def test_free_already_free_port_returns_was_free(self, runner: CliRunner) -> None:
        """vigil free on a port with nothing listening returns was=free."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("psutil.net_connections", return_value=[]):
                result = runner.invoke(main, ["free", "3000", "--json"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data == {"port": 3000, "freed": True, "was": "free"}

    def test_free_time_wait_port_human_output(self, runner: CliRunner) -> None:
        """vigil free human output explains TIME_WAIT and suggests waiting or different port."""
        conn = _make_conn(0, 3000, status="TIME_WAIT")
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("psutil.net_connections", return_value=[conn]):
                result = runner.invoke(main, ["free", "3000"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "3000" in result.output
        assert "TIME_WAIT" in result.output

    def test_free_already_free_port_human_output(self, runner: CliRunner) -> None:
        """vigil free human output says port is already free."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("psutil.net_connections", return_value=[]):
                result = runner.invoke(main, ["free", "3000"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "3000" in result.output
        assert "free" in result.output.lower()
