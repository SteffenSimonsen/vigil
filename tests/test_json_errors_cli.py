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
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "not_running"


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
                assert isinstance(data["code"], str)
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
            assert isinstance(data["code"], str)


class TestJsonErrorsRemove:
    def test_remove_unknown_name_json_error_to_stdout(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["remove", "ghost", "--json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "not_found"


class TestJsonErrorsLogs:
    def test_logs_unknown_name_json_error_to_stdout(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil/logs").mkdir(parents=True)
            result = runner.invoke(main, ["logs", "ghost", "--json"])
            assert result.exit_code != 0
            data = json.loads(result.output)
            assert "error" in data
            assert isinstance(data["code"], str)


class TestJsonErrorsOpen:
    def test_open_unknown_name_json_error_to_stdout(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["open", "ghost", "--json"])
            assert result.exit_code != 0
            data = json.loads(result.output)
            assert "error" in data
            assert isinstance(data["code"], str)


class TestJsonErrorsMissingProject:
    """--json flag must produce JSON output even when no .vigil/ directory exists."""

    def _assert_json_error(self, result: object) -> None:
        import click.testing

        assert isinstance(result, click.testing.Result)
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert "error" in data
        assert isinstance(data["code"], str)

    def test_status_json_missing_project(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["status", "--json"])
            self._assert_json_error(result)

    def test_start_json_missing_project(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["start", "web", "echo hi", "--json"])
            self._assert_json_error(result)

    def test_stop_json_missing_project(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["stop", "web", "--json"])
            self._assert_json_error(result)

    def test_logs_json_missing_project(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["logs", "web", "--json"])
            self._assert_json_error(result)

    def test_restart_json_missing_project(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["restart", "web", "--json"])
            self._assert_json_error(result)

    def test_remove_json_missing_project(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["remove", "web", "--json"])
            self._assert_json_error(result)

    def test_wait_json_missing_project(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["wait", "web", "--json"])
            self._assert_json_error(result)

    def test_health_json_missing_project(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["health", "--json"])
            self._assert_json_error(result)

    def test_free_json_missing_project(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["free", "3000", "--json"])
            self._assert_json_error(result)

    def test_open_json_missing_project(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["open", "web", "--json"])
            self._assert_json_error(result)

    def test_up_json_missing_project(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["up", "--json"])
            self._assert_json_error(result)

    def test_down_json_missing_project(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["down", "--json"])
            self._assert_json_error(result)


class TestJsonErrorsNext:
    def test_next_error_returns_string_code(self, runner: CliRunner) -> None:
        """vigil next --json with an out-of-range port returns string code, not numeric 1."""
        result = runner.invoke(main, ["next", "99999", "--json"])
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert "error" in data
        assert isinstance(data["code"], str)
