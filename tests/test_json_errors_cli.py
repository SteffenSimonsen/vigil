"""Tests: error paths in --json mode emit JSON to stdout (not plain text to stderr)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from vigil.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestJsonErrorsStop:
    def test_stop_unknown_name_json_error_to_stdout(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["stop", "ghost", "--json"])
            assert result.exit_code != 0
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1


class TestJsonErrorsStart:
    def test_start_duplicate_json_error_to_stdout(self, runner: CliRunner) -> None:
        import contextlib

        import psutil

        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            r1 = runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            pid: int = json.loads(r1.output)["pid"]
            try:
                result = runner.invoke(
                    main,
                    ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                )
                assert result.exit_code != 0
                data = json.loads(result.output)
                assert "error" in data
                assert data["code"] == 1
            finally:
                with contextlib.suppress(Exception):
                    psutil.Process(pid).kill()


class TestJsonErrorsRestart:
    def test_restart_unknown_name_json_error_to_stdout(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["restart", "ghost", "--json"])
            assert result.exit_code != 0
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1


class TestJsonErrorsRemove:
    def test_remove_unknown_name_json_error_to_stdout(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["remove", "ghost", "--json"])
            assert result.exit_code != 0
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1


class TestJsonErrorsLogs:
    def test_logs_unknown_name_json_error_to_stdout(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil/logs").mkdir(parents=True)
            result = runner.invoke(main, ["logs", "ghost", "--json"])
            assert result.exit_code != 0
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1


class TestJsonErrorsOpen:
    def test_open_unknown_name_json_error_to_stdout(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["open", "ghost", "--json"])
            assert result.exit_code != 0
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1
