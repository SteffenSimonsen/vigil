"""Tests for vigil open CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from vigil.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestOpenPort:
    def test_open_port_json_returns_url(self, runner: CliRunner) -> None:
        """vigil open <port> --json returns the URL without opening a browser."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["open", "8000", "--json"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data == {"url": "http://localhost:8000"}


class TestOpenDeadProcess:
    def test_open_name_works_when_process_not_alive(self, runner: CliRunner) -> None:
        """vigil open <name> returns a URL even when the process is not alive."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            # Write a statefile with a stopped process (pid=999999 which won't exist)
            import json as _json

            state = {
                "web": {
                    "name": "web",
                    "pid": 999999,
                    "command": "python -m http.server 8888",
                    "started_at": 0.0,
                    "port": 8888,
                    "cwd": None,
                }
            }
            Path(".vigil/state.json").write_text(_json.dumps(state))
            result = runner.invoke(main, ["open", "web", "--json"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data == {"url": "http://localhost:8888"}


class TestOpenErrors:
    def test_open_unknown_name_exits_with_error(self, runner: CliRunner) -> None:
        """vigil open <unknown-name> exits non-zero with an error message."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            result = runner.invoke(main, ["open", "nonexistent", "--json"])
        assert result.exit_code != 0
        assert "nonexistent" in result.output or "nonexistent" in (result.stderr or "")


class TestOpenBrowser:
    def test_open_port_opens_browser(self, runner: CliRunner) -> None:
        """vigil open <port> without --json calls webbrowser.open."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("webbrowser.open") as mock_open:
                result = runner.invoke(main, ["open", "8000"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        mock_open.assert_called_once_with("http://localhost:8000")


class TestOpenNameLiveScanner:
    def test_open_name_falls_back_to_live_scanner_when_port_is_null(
        self, runner: CliRunner
    ) -> None:
        """vigil open <name> falls back to live scanner when statefile port is null."""
        import json as _json
        from unittest.mock import MagicMock, patch

        fake_pid = 88888
        fake_started_at = 1000.0

        # Build a fake psutil connection: pid=fake_pid, LISTEN on port 8765
        fake_conn = MagicMock()
        fake_conn.status = "LISTEN"
        fake_conn.pid = fake_pid
        fake_conn.laddr.port = 8765

        # Fake process with matching create_time
        fake_proc = MagicMock()
        fake_proc.create_time.return_value = fake_started_at

        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            state = {
                "backend": {
                    "name": "backend",
                    "pid": fake_pid,
                    "command": "python -m myapp",
                    "started_at": fake_started_at,
                    "port": None,
                    "cwd": None,
                }
            }
            Path(".vigil/state.json").write_text(_json.dumps(state))

            with (
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process", return_value=fake_proc),
                patch("psutil.net_connections", return_value=[fake_conn]),
            ):
                result = runner.invoke(main, ["open", "backend", "--json"], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data == {"url": "http://localhost:8765"}


class TestOpenName:
    def test_open_name_json_resolves_port_from_statefile(self, runner: CliRunner) -> None:
        """vigil open <name> --json looks up port from statefile."""
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            start_result = runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            assert start_result.exit_code == 0, start_result.output

            # Update the port on the state record directly
            import json as _json

            state_path = Path(".vigil/state.json")
            state = _json.loads(state_path.read_text())
            state["web"]["port"] = 9000
            state_path.write_text(_json.dumps(state))

            # Stop the process so we don't leave it running
            import psutil

            pid = _json.loads(start_result.output)["pid"]
            try:
                result = runner.invoke(main, ["open", "web", "--json"], catch_exceptions=False)
            finally:
                import contextlib

                with contextlib.suppress(Exception):
                    psutil.Process(pid).kill()

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data == {"url": "http://localhost:9000"}

    def test_open_name_json_uses_vigilfile_url_override(self, runner: CliRunner) -> None:
        """vigil open <name> --json uses the url from Vigilfile if defined."""
        import contextlib

        import psutil

        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            start_result = runner.invoke(
                main,
                ["start", "web", "python -c 'import time; time.sleep(30)'", "--json"],
                catch_exceptions=False,
            )
            assert start_result.exit_code == 0, start_result.output
            pid = json.loads(start_result.output)["pid"]

            # Update state with a port
            import json as _json

            state_path = Path(".vigil/state.json")
            state = _json.loads(state_path.read_text())
            state["web"]["port"] = 9000
            state_path.write_text(_json.dumps(state))

            # Write a Vigilfile with a url override
            Path("Vigilfile").write_text(
                '[[process]]\nname = "web"\ncommand = "python ..."\nport = 9000\nurl = "http://localhost:9000/app/"\n'
            )

            try:
                result = runner.invoke(main, ["open", "web", "--json"], catch_exceptions=False)
            finally:
                with contextlib.suppress(Exception):
                    psutil.Process(pid).kill()

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data == {"url": "http://localhost:9000/app/"}
