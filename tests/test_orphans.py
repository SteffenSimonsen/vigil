"""Unit tests for vigil.orphans.find_orphans."""

from __future__ import annotations

from collections import namedtuple
from pathlib import Path
from unittest.mock import MagicMock, patch

from vigil.orphans import find_orphans

MockAddr = namedtuple("MockAddr", ["ip", "port"])
MockConn = namedtuple("MockConn", ["fd", "family", "type", "laddr", "raddr", "status", "pid"])


def _make_proc(pid: int, cwd: str, cmdline: list[str]) -> MagicMock:
    mock = MagicMock()
    mock.pid = pid
    mock.cwd.return_value = cwd
    mock.cmdline.return_value = cmdline
    mock.name.return_value = cmdline[0] if cmdline else "unknown"
    return mock


class TestNetConnectionsCalledOnce:
    def test_net_connections_called_once_with_multiple_orphans(self, tmp_path: Path) -> None:
        """net_connections() is called exactly once even when N orphans are found."""
        procs = [
            _make_proc(101, str(tmp_path), ["python3", "a.py"]),
            _make_proc(102, str(tmp_path), ["python3", "b.py"]),
            _make_proc(103, str(tmp_path), ["python3", "c.py"]),
        ]
        with (
            patch("psutil.process_iter", return_value=procs) as _mock_iter,
            patch("psutil.net_connections", return_value=[]) as mock_net,
        ):
            result = find_orphans(tmp_path, set())

        assert len(result) == 3
        mock_net.assert_called_once()

    def test_ports_attributed_correctly_from_snapshot(self, tmp_path: Path) -> None:
        """Each orphan's ports come from the single net_connections snapshot."""
        conn_101 = MockConn(-1, 2, 1, MockAddr("0.0.0.0", 8001), None, "LISTEN", 101)
        conn_102 = MockConn(-1, 2, 1, MockAddr("0.0.0.0", 8002), None, "LISTEN", 102)
        procs = [
            _make_proc(101, str(tmp_path), ["python3", "a.py"]),
            _make_proc(102, str(tmp_path), ["python3", "b.py"]),
        ]
        with (
            patch("psutil.process_iter", return_value=procs),
            patch("psutil.net_connections", return_value=[conn_101, conn_102]),
        ):
            result = find_orphans(tmp_path, set())

        by_pid = {r["pid"]: r for r in result}
        assert by_pid[101]["ports"] == [8001]
        assert by_pid[102]["ports"] == [8002]
