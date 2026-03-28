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

            assert result.exit_code == 0
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

            assert result.exit_code == 0
            assert "web" in result.output
            assert "crashed" in result.output

    def test_no_processes_message_when_empty(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["status"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "No managed processes" in result.output
