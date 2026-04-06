"""Tests: corrupted or unreadable state.json produces clean errors (not tracebacks)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from vigil.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestCorruptedStateJson:
    def test_status_json_decode_error_emits_clean_json(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            Path(".vigil/state.json").write_text('"not a dict"')
            result = runner.invoke(main, ["status", "--json"])
            assert result.exit_code != 0
            data = json.loads(result.output)
            assert "error" in data
            assert isinstance(data["code"], str)

    def test_status_missing_fields_emits_clean_json(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            Path(".vigil/state.json").write_text('{"x": {"name": "x"}}')
            result = runner.invoke(main, ["status", "--json"])
            assert result.exit_code != 0
            data = json.loads(result.output)
            assert "error" in data
            assert isinstance(data["code"], str)

    def test_status_permission_error_emits_clean_json(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            state_file = Path(".vigil/state.json")
            state_file.write_text("{}")
            state_file.chmod(0o000)
            try:
                result = runner.invoke(main, ["status", "--json"])
                assert result.exit_code != 0
                data = json.loads(result.output)
                assert "error" in data
                assert isinstance(data["code"], str)
            finally:
                state_file.chmod(0o644)


class TestCorruptedStateStart:
    def test_start_with_corrupted_state_emits_clean_json(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            Path(".vigil/state.json").write_text("not json at all")
            result = runner.invoke(main, ["start", "web", "echo hi", "--json"])
            assert result.exit_code != 0
            data = json.loads(result.output)
            assert "error" in data
            assert isinstance(data["code"], str)


class TestCorruptedStateStop:
    def test_stop_with_corrupted_state_emits_clean_json(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            Path(".vigil/state.json").write_text("not json at all")
            result = runner.invoke(main, ["stop", "web", "--json"])
            assert result.exit_code != 0
            data = json.loads(result.output)
            assert "error" in data
            assert isinstance(data["code"], str)
