"""Integration tests for `vigil logs` CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from vigil.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestLogsCLI:
    def test_logs_shows_last_50_lines_by_default(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil/logs").mkdir(parents=True)
            log_path = Path(".vigil/logs/web.log")
            lines = [f"line {i}\n" for i in range(1, 101)]
            log_path.write_text("".join(lines))

            result = runner.invoke(main, ["logs", "web"], catch_exceptions=False)

            assert result.exit_code == 0
            output_lines = result.output.strip().splitlines()
            assert len(output_lines) == 50
            assert output_lines[0] == "line 51"
            assert output_lines[-1] == "line 100"

    def test_logs_tail_returns_n_lines(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil/logs").mkdir(parents=True)
            log_path = Path(".vigil/logs/web.log")
            lines = [f"line {i}\n" for i in range(1, 21)]
            log_path.write_text("".join(lines))

            result = runner.invoke(main, ["logs", "web", "--tail", "5"], catch_exceptions=False)

            assert result.exit_code == 0
            output_lines = result.output.strip().splitlines()
            assert output_lines == ["line 16", "line 17", "line 18", "line 19", "line 20"]

    def test_logs_json_returns_structured_array(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil/logs").mkdir(parents=True)
            log_path = Path(".vigil/logs/web.log")
            log_path.write_text("alpha\nbeta\ngamma\n")

            result = runner.invoke(
                main, ["logs", "web", "--tail", "3", "--json"], catch_exceptions=False
            )

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data == {"lines": ["alpha", "beta", "gamma"]}

    def test_logs_errors_on_unknown_process(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil/logs").mkdir(parents=True)

            result = runner.invoke(main, ["logs", "ghost"], catch_exceptions=False)

            assert result.exit_code != 0
