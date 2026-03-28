"""Tests for vigil init command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from vigil.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestInitNonInteractive:
    def test_creates_vigil_directory(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["init", "--process", "web,python -m http.server,8000"])
            assert result.exit_code == 0
            assert Path(".vigil").is_dir()

    def test_creates_vigilfile(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["init", "--process", "web,python -m http.server,8000"])
            assert result.exit_code == 0
            assert Path("Vigilfile").exists()

    def test_vigilfile_contains_process_entry(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(main, ["init", "--process", "web,python -m http.server,8000"])
            content = Path("Vigilfile").read_text()
            assert "web" in content
            assert "python -m http.server" in content

    def test_creates_gitignore_in_vigil_dir(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(main, ["init", "--process", "web,python -m http.server,8000"])
            gitignore = Path(".vigil") / ".gitignore"
            assert gitignore.exists()
            content = gitignore.read_text()
            assert "state.json" in content
            assert "logs/" in content

    def test_json_output_contains_status_created(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                main, ["init", "--process", "web,python -m http.server,8000", "--json"]
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "created"

    def test_json_output_contains_processes(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                main, ["init", "--process", "web,python -m http.server,8000", "--json"]
            )
            data = json.loads(result.output)
            assert len(data["processes"]) == 1
            assert data["processes"][0]["name"] == "web"

    def test_multiple_process_flags(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                main,
                [
                    "init",
                    "--process",
                    "web,python -m http.server,8000",
                    "--process",
                    "api,uvicorn main:app,8001",
                    "--json",
                ],
            )
            data = json.loads(result.output)
            assert len(data["processes"]) == 2
            names = {p["name"] for p in data["processes"]}
            assert names == {"web", "api"}

    def test_process_without_port(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["init", "--process", "worker,celery worker", "--json"])
            data = json.loads(result.output)
            assert data["processes"][0]["port"] is None


class TestInitOutsideProject:
    def test_command_outside_project_gives_error(self, runner: CliRunner, tmp_path: Path) -> None:
        # Running vigil status (not init) outside a project should error
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["status"])
            assert result.exit_code != 0
            assert "vigil init" in result.output.lower() or "no .vigil" in result.output.lower()
