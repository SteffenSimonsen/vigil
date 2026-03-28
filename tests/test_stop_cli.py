"""Integration tests for `vigil stop` CLI command."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import psutil
import pytest
from click.testing import CliRunner

from vigil.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestStopCLI:
    def test_stop_json_confirms_stopped(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            start_result = runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            pid: int = json.loads(start_result.output)["pid"]
            try:
                result = runner.invoke(main, ["stop", "web", "--json"], catch_exceptions=False)
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                assert data["name"] == "web"
                assert data["status"] == "stopped"
                assert not psutil.pid_exists(pid)
            finally:
                with contextlib.suppress(Exception):
                    psutil.Process(pid).kill()

    def test_stop_unknown_name_exits_with_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["stop", "ghost", "--json"])
            assert result.exit_code != 0

    def test_stop_all_stops_all_processes(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            r1 = runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            r2 = runner.invoke(
                main,
                ["start", "worker", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            pid1: int = json.loads(r1.output)["pid"]
            pid2: int = json.loads(r2.output)["pid"]
            try:
                result = runner.invoke(main, ["stop", "--all", "--json"], catch_exceptions=False)
                assert result.exit_code == 0, result.output
                data = json.loads(result.output)
                assert data["status"] == "stopped"
                assert set(data["names"]) == {"web", "worker"}
                assert not psutil.pid_exists(pid1)
                assert not psutil.pid_exists(pid2)
            finally:
                with contextlib.suppress(Exception):
                    psutil.Process(pid1).kill()
                with contextlib.suppress(Exception):
                    psutil.Process(pid2).kill()
