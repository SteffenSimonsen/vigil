"""Tests for shell completion of process names."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from click.shell_completion import ShellComplete
from click.testing import CliRunner

from vigil.cli import _complete_process_names, main


def _write_state(processes: list[dict[str, Any]]) -> None:
    Path(".vigil").mkdir(exist_ok=True)
    state = {p["name"]: p for p in processes}
    (Path(".vigil") / "state.json").write_text(json.dumps(state))


def _proc(name: str, pid: int = 1234) -> dict[str, Any]:
    return {"name": name, "pid": pid, "command": f"run {name}", "started_at": 1.0}


class TestCompleteProcessNames:
    def test_returns_all_names_with_empty_prefix(self) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem():
            _write_state([_proc("web"), _proc("worker", pid=5678)])
            completions = _complete_process_names(MagicMock(), MagicMock(), "")
            names = {c.value for c in completions}
            assert names == {"web", "worker"}

    def test_returns_empty_list_outside_project(self) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem():
            # no .vigil directory → ConfigError → should return []
            completions = _complete_process_names(MagicMock(), MagicMock(), "")
            assert completions == []

    def test_filters_completions_by_incomplete_prefix(self) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem():
            _write_state([_proc("web"), _proc("worker", pid=5678)])
            completions = _complete_process_names(MagicMock(), MagicMock(), "wo")
            names = [c.value for c in completions]
            assert names == ["worker"]

    def test_includes_crashed_processes(self) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem():
            # PID 99999999 is almost certainly not alive → crashed
            _write_state([_proc("web", pid=99999999)])
            completions = _complete_process_names(MagicMock(), MagicMock(), "")
            names = [c.value for c in completions]
            assert "web" in names


class _TestShellComplete(ShellComplete):
    """Minimal ShellComplete subclass for testing completion items."""

    name = "test"
    source_template = "# test"

    def format_completion(self, item: object) -> str:  # type: ignore[override]
        return str(item)


def _get_completions(cmd: str, incomplete: str) -> list[str]:
    """Return completion values for a subcommand with the given incomplete word."""
    complete = _TestShellComplete(main, {}, "vigil", "_VIGIL_COMPLETE")
    items = complete.get_completions([cmd], incomplete)
    return [item.value for item in items]


class TestCompletionWiring:
    """Verify completions are wired to the correct commands."""

    @pytest.mark.parametrize("cmd", ["stop", "restart", "logs", "open", "wait"])
    def test_command_completes_process_names(self, cmd: str) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem():
            _write_state([_proc("web"), _proc("worker", pid=5678)])
            names = _get_completions(cmd, "")
            assert "web" in names
            assert "worker" in names

    @pytest.mark.parametrize("cmd", ["stop", "restart", "logs", "open", "wait"])
    def test_command_filters_by_prefix(self, cmd: str) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem():
            _write_state([_proc("web"), _proc("worker", pid=5678)])
            names = _get_completions(cmd, "wo")
            assert names == ["worker"]
