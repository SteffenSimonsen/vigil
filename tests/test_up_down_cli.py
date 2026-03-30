"""Integration tests for `vigil up` and `vigil down` CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from vigil.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _write_vigilfile(root: Path, content: str) -> None:
    (root / "Vigilfile").write_text(content)


def _two_process_vigilfile() -> str:
    return (
        "[[process]]\n"
        'name = "db"\n'
        'command = "postgres"\n'
        "order = 1\n"
        "\n"
        "[[process]]\n"
        'name = "api"\n'
        'command = "uvicorn main:app"\n'
        "order = 2\n"
    )


class TestUpCLI:
    def test_up_json_output(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_vigilfile(Path("."), _two_process_vigilfile())

            started: list[str] = []

            def fake_start(cfg: object, name: str, command: str, **kwargs: object) -> MagicMock:
                started.append(name)
                rec = MagicMock()
                rec.pid = 1234
                rec.name = name
                return rec

            def fake_wait(cfg: object, name: str, **kwargs: object) -> None:
                pass

            with (
                patch("vigil.vigilfile._start", side_effect=fake_start),
                patch("vigil.vigilfile._wait", side_effect=fake_wait),
            ):
                result = runner.invoke(main, ["up", "--json"], catch_exceptions=False)

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "processes" in data
            assert len(data["processes"]) == 2
            names = [p["name"] for p in data["processes"]]
            assert "db" in names
            assert "api" in names

    def test_up_text_output(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_vigilfile(Path("."), _two_process_vigilfile())

            def fake_start(cfg: object, name: str, command: str, **kwargs: object) -> MagicMock:
                rec = MagicMock()
                rec.pid = 1234
                rec.name = name
                return rec

            def fake_wait(cfg: object, name: str, **kwargs: object) -> None:
                pass

            with (
                patch("vigil.vigilfile._start", side_effect=fake_start),
                patch("vigil.vigilfile._wait", side_effect=fake_wait),
            ):
                result = runner.invoke(main, ["up"], catch_exceptions=False)

            assert result.exit_code == 0
            assert "db" in result.output
            assert "api" in result.output

    def test_up_only_flag(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_vigilfile(Path("."), _two_process_vigilfile())

            started: list[str] = []

            def fake_start(cfg: object, name: str, command: str, **kwargs: object) -> MagicMock:
                started.append(name)
                rec = MagicMock()
                rec.pid = 1234
                rec.name = name
                return rec

            def fake_wait(cfg: object, name: str, **kwargs: object) -> None:
                pass

            with (
                patch("vigil.vigilfile._start", side_effect=fake_start),
                patch("vigil.vigilfile._wait", side_effect=fake_wait),
            ):
                result = runner.invoke(
                    main, ["up", "--only", "db", "--json"], catch_exceptions=False
                )

            assert result.exit_code == 0
            assert started == ["db"]

    def test_up_force_flag(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_vigilfile(Path("."), _two_process_vigilfile())

            force_values: list[bool] = []

            def fake_start(cfg: object, name: str, command: str, **kwargs: object) -> MagicMock:
                force_values.append(bool(kwargs.get("force")))
                rec = MagicMock()
                rec.pid = 1234
                rec.name = name
                return rec

            def fake_wait(cfg: object, name: str, **kwargs: object) -> None:
                pass

            with (
                patch("vigil.vigilfile._start", side_effect=fake_start),
                patch("vigil.vigilfile._wait", side_effect=fake_wait),
            ):
                result = runner.invoke(main, ["up", "--force", "--json"], catch_exceptions=False)

            assert result.exit_code == 0
            assert all(force_values)

    def test_up_no_vigilfile_exits_with_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            # No Vigilfile
            result = runner.invoke(main, ["up", "--json"])
            assert result.exit_code != 0

    def test_up_no_vigilfile_json_outputs_json_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["up", "--json"])
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1

    def test_up_invalid_toml_json_outputs_json_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            Path("Vigilfile").write_text("not toml [[[[")
            result = runner.invoke(main, ["up", "--json"])
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1

    def test_up_no_vigilfile_plain_text_shows_human_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["up"])
            assert result.exit_code != 0

    def test_up_any_failure_exits_two(self, runner: CliRunner) -> None:
        """Any process failure causes exit 2 (partial success)."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_vigilfile(Path("."), _two_process_vigilfile())

            def fake_start(cfg: object, name: str, command: str, **kwargs: object) -> MagicMock:
                if name == "db":
                    raise RuntimeError("db failed")
                rec = MagicMock()
                rec.pid = 1234
                rec.name = name
                return rec

            def fake_wait(cfg: object, name: str, **kwargs: object) -> None:
                pass

            with (
                patch("vigil.vigilfile._start", side_effect=fake_start),
                patch("vigil.vigilfile._wait", side_effect=fake_wait),
            ):
                result = runner.invoke(main, ["up", "--json"], catch_exceptions=False)

            assert result.exit_code == 2
            data = json.loads(result.output)
            statuses = {p["name"]: p["status"] for p in data["processes"]}
            assert statuses["db"] == "failed"
            assert statuses["api"] == "started"

    def test_up_all_failures_exits_two(self, runner: CliRunner) -> None:
        """All processes failing causes exit 2 (partial success)."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_vigilfile(Path("."), _two_process_vigilfile())

            def fake_start(cfg: object, name: str, command: str, **kwargs: object) -> MagicMock:
                raise RuntimeError(f"{name} failed")

            def fake_wait(cfg: object, name: str, **kwargs: object) -> None:
                pass

            with (
                patch("vigil.vigilfile._start", side_effect=fake_start),
                patch("vigil.vigilfile._wait", side_effect=fake_wait),
            ):
                result = runner.invoke(main, ["up", "--json"], catch_exceptions=False)

            assert result.exit_code == 2
            data = json.loads(result.output)
            statuses = {p["name"]: p["status"] for p in data["processes"]}
            assert statuses["db"] == "failed"
            assert statuses["api"] == "failed"


class TestDownCLI:
    def test_down_json_output(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_vigilfile(Path("."), _two_process_vigilfile())

            stopped: list[str] = []

            def fake_stop(cfg: object, name: str) -> None:
                stopped.append(name)

            with patch("vigil.vigilfile._stop", side_effect=fake_stop):
                result = runner.invoke(main, ["down", "--json"], catch_exceptions=False)

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "processes" in data
            assert len(data["processes"]) == 2
            # reverse order
            assert data["processes"][0]["name"] == "api"
            assert data["processes"][1]["name"] == "db"

    def test_down_text_output(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_vigilfile(Path("."), _two_process_vigilfile())

            def fake_stop(cfg: object, name: str) -> None:
                pass

            with patch("vigil.vigilfile._stop", side_effect=fake_stop):
                result = runner.invoke(main, ["down"], catch_exceptions=False)

            assert result.exit_code == 0
            assert "db" in result.output
            assert "api" in result.output

    def test_down_only_flag(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            _write_vigilfile(Path("."), _two_process_vigilfile())

            stopped: list[str] = []

            def fake_stop(cfg: object, name: str) -> None:
                stopped.append(name)

            with patch("vigil.vigilfile._stop", side_effect=fake_stop):
                result = runner.invoke(
                    main, ["down", "--only", "api", "--json"], catch_exceptions=False
                )

            assert result.exit_code == 0
            assert stopped == ["api"]

    def test_down_no_vigilfile_exits_with_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["down", "--json"])
            assert result.exit_code != 0

    def test_down_no_vigilfile_json_outputs_json_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["down", "--json"])
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1

    def test_down_invalid_toml_json_outputs_json_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            Path("Vigilfile").write_text("not toml [[[[")
            result = runner.invoke(main, ["down", "--json"])
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "error" in data
            assert data["code"] == 1

    def test_down_no_vigilfile_plain_text_shows_human_error(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["down"])
            assert result.exit_code != 0
