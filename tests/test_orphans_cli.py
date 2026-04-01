"""Tests for vigil orphans command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from vigil.cli import main


def _write_state(vigil_dir: Path, records: dict[str, object]) -> None:
    (vigil_dir / "state.json").write_text(json.dumps(records))


class TestVigilOrphansDetection:
    def test_process_with_cwd_in_project_root_is_orphan(self) -> None:
        """A process whose CWD is the project root appears in orphans output."""
        runner = CliRunner()
        with runner.isolated_filesystem() as tmpdir:
            Path(".vigil").mkdir()
            mock_proc = MagicMock()
            mock_proc.pid = 9999
            mock_proc.cwd.return_value = tmpdir
            mock_proc.cmdline.return_value = ["python3", "-m", "http.server"]
            mock_proc.name.return_value = "python3"
            with (
                patch("psutil.process_iter", return_value=[mock_proc]),
                patch("psutil.net_connections", return_value=[]),
            ):
                result = runner.invoke(main, ["orphans", "--json"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data["orphans"]) == 1
        assert data["orphans"][0]["pid"] == 9999

    def test_process_with_cwd_in_subdirectory_is_orphan(self) -> None:
        """A process whose CWD is a subdirectory of project root is an orphan."""
        runner = CliRunner()
        with runner.isolated_filesystem() as tmpdir:
            Path(".vigil").mkdir()
            subdir = Path(tmpdir) / "src"
            subdir.mkdir()
            mock_proc = MagicMock()
            mock_proc.pid = 8888
            mock_proc.cwd.return_value = str(subdir)
            mock_proc.cmdline.return_value = ["uvicorn", "main:app"]
            mock_proc.name.return_value = "uvicorn"
            with (
                patch("psutil.process_iter", return_value=[mock_proc]),
                patch("psutil.net_connections", return_value=[]),
            ):
                result = runner.invoke(main, ["orphans", "--json"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data["orphans"]) == 1
        assert data["orphans"][0]["pid"] == 8888

    def test_process_with_cwd_outside_project_is_not_orphan(self) -> None:
        """A process whose CWD is outside the project root is not listed."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            mock_proc = MagicMock()
            mock_proc.pid = 7777
            mock_proc.cwd.return_value = "/tmp/other-project"
            mock_proc.cmdline.return_value = ["node", "server.js"]
            mock_proc.name.return_value = "node"
            with (
                patch("psutil.process_iter", return_value=[mock_proc]),
                patch("psutil.net_connections", return_value=[]),
            ):
                result = runner.invoke(main, ["orphans", "--json"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["orphans"] == []


class TestVigilOrphansHumanOutput:
    def test_human_output_no_orphans_shows_none_message(self) -> None:
        """Without --json, no orphans prints a human-friendly message."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("psutil.process_iter", return_value=[]):
                result = runner.invoke(main, ["orphans"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "No orphaned processes" in result.output

    def test_human_output_shows_pid_command_cwd(self) -> None:
        """Without --json, orphan output includes PID, command, and CWD."""
        runner = CliRunner()
        with runner.isolated_filesystem() as tmpdir:
            Path(".vigil").mkdir()
            mock_proc = MagicMock()
            mock_proc.pid = 9999
            mock_proc.cwd.return_value = tmpdir
            mock_proc.cmdline.return_value = ["uvicorn", "main:app"]
            mock_proc.name.return_value = "uvicorn"
            with (
                patch("psutil.process_iter", return_value=[mock_proc]),
                patch("psutil.net_connections", return_value=[]),
            ):
                result = runner.invoke(main, ["orphans"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "9999" in result.output
        assert "uvicorn main:app" in result.output
        assert tmpdir in result.output


class TestVigilOrphansEmptyRegistry:
    def test_fresh_session_no_state_file_still_detects_orphans(self) -> None:
        """With no state.json, all project-CWD processes are orphans."""
        runner = CliRunner()
        with runner.isolated_filesystem() as tmpdir:
            Path(".vigil").mkdir()
            # No state.json written — fresh session
            mock_proc = MagicMock()
            mock_proc.pid = 4321
            mock_proc.cwd.return_value = tmpdir
            mock_proc.cmdline.return_value = ["python3", "app.py"]
            mock_proc.name.return_value = "python3"
            with (
                patch("psutil.process_iter", return_value=[mock_proc]),
                patch("psutil.net_connections", return_value=[]),
            ):
                result = runner.invoke(main, ["orphans", "--json"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data["orphans"]) == 1
        assert data["orphans"][0]["pid"] == 4321


class TestVigilOrphansAccessDenied:
    def test_access_denied_on_cwd_skips_process(self) -> None:
        """If psutil.AccessDenied is raised getting cwd, process is skipped."""
        import psutil as _psutil

        runner = CliRunner()
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            mock_proc = MagicMock()
            mock_proc.pid = 1234
            mock_proc.cwd.side_effect = _psutil.AccessDenied(1234)
            with (
                patch("psutil.process_iter", return_value=[mock_proc]),
                patch("psutil.net_connections", return_value=[]),
            ):
                result = runner.invoke(main, ["orphans", "--json"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["orphans"] == []

    def test_access_denied_on_cmdline_skips_process(self) -> None:
        """If psutil.AccessDenied is raised getting cmdline, process is skipped."""
        import psutil as _psutil

        runner = CliRunner()
        with runner.isolated_filesystem() as tmpdir:
            Path(".vigil").mkdir()
            mock_proc = MagicMock()
            mock_proc.pid = 5678
            mock_proc.cwd.return_value = tmpdir
            mock_proc.cmdline.side_effect = _psutil.AccessDenied(5678)
            with (
                patch("psutil.process_iter", return_value=[mock_proc]),
                patch("psutil.net_connections", return_value=[]),
            ):
                result = runner.invoke(main, ["orphans", "--json"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["orphans"] == []


class TestVigilOrphansFields:
    def test_orphan_entry_includes_pid_command_cwd_ports(self) -> None:
        """Each orphan entry has pid, command, cwd, and ports fields."""
        from collections import namedtuple

        MockAddr = namedtuple("MockAddr", ["ip", "port"])
        MockConn = namedtuple(
            "MockConn", ["fd", "family", "type", "laddr", "raddr", "status", "pid"]
        )
        conn = MockConn(
            fd=-1,
            family=2,
            type=1,
            laddr=MockAddr("0.0.0.0", 8000),
            raddr=None,
            status="LISTEN",
            pid=9999,
        )

        runner = CliRunner()
        with runner.isolated_filesystem() as tmpdir:
            Path(".vigil").mkdir()
            mock_proc = MagicMock()
            mock_proc.pid = 9999
            mock_proc.cwd.return_value = tmpdir
            mock_proc.cmdline.return_value = ["uvicorn", "main:app", "--reload"]
            mock_proc.name.return_value = "uvicorn"
            with (
                patch("psutil.process_iter", return_value=[mock_proc]),
                patch("psutil.net_connections", return_value=[conn]),
            ):
                result = runner.invoke(main, ["orphans", "--json"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data["orphans"]) == 1
        orphan = data["orphans"][0]
        assert orphan["pid"] == 9999
        assert orphan["command"] == "uvicorn main:app --reload"
        assert orphan["cwd"] == tmpdir
        assert orphan["ports"] == [8000]


class TestVigilOrphansRegistryExclusion:
    def test_registered_process_not_in_orphans(self) -> None:
        """A process whose PID is in the vigil registry is excluded from orphans."""
        import time

        start_time = time.time() - 10
        runner = CliRunner()
        with runner.isolated_filesystem() as tmpdir:
            Path(".vigil").mkdir()
            _write_state(
                Path(".vigil"),
                {
                    "web": {
                        "name": "web",
                        "pid": 5555,
                        "command": "uvicorn main:app",
                        "started_at": start_time,
                        "port": 8000,
                        "cwd": tmpdir,
                    }
                },
            )
            mock_proc = MagicMock()
            mock_proc.pid = 5555
            mock_proc.cwd.return_value = tmpdir
            mock_proc.cmdline.return_value = ["uvicorn", "main:app"]
            mock_proc.name.return_value = "uvicorn"
            with (
                patch("psutil.process_iter", return_value=[mock_proc]),
                patch("psutil.net_connections", return_value=[]),
                patch("psutil.pid_exists", return_value=True),
                patch("psutil.Process") as mock_psutil_proc,
            ):
                mock_psutil_proc.return_value.create_time.return_value = start_time + 0.1
                result = runner.invoke(main, ["orphans", "--json"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["orphans"] == []


class TestVigilOrphansEmpty:
    def test_orphans_json_no_orphans_returns_empty_list(self) -> None:
        """vigil orphans --json returns {"orphans": []} when no matching processes."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path(".vigil").mkdir()
            with patch("psutil.process_iter", return_value=[]):
                result = runner.invoke(main, ["orphans", "--json"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data == {"orphans": []}
