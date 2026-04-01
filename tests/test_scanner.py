"""Tests for scanner module — port/PID mapping."""

from __future__ import annotations

from collections import namedtuple
from unittest.mock import MagicMock, patch

from vigil.scanner import next_free_port, pid_for_port, ports_for_pid, scan_all, scan_ports

_MockAddr = namedtuple("MockAddr", ["ip", "port"])
_MockConn = namedtuple("MockConn", ["fd", "family", "type", "laddr", "raddr", "status", "pid"])


def _make_conn(pid: int, port: int, status: str = "LISTEN") -> _MockConn:
    return _MockConn(
        fd=-1,
        family=2,
        type=1,
        laddr=_MockAddr("0.0.0.0", port),
        raddr=None,
        status=status,
        pid=pid,
    )


class TestPortsForPid:
    def test_returns_empty_when_no_connections(self) -> None:
        with patch("psutil.net_connections", return_value=[]):
            assert ports_for_pid(1234) == []

    def test_returns_port_for_matching_pid(self) -> None:
        conns = [_make_conn(1234, 8000), _make_conn(5678, 9000)]
        with patch("psutil.net_connections", return_value=conns):
            assert ports_for_pid(1234) == [8000]

    def test_returns_multiple_ports_for_pid(self) -> None:
        conns = [_make_conn(1234, 8000), _make_conn(1234, 8001), _make_conn(9999, 9000)]
        with patch("psutil.net_connections", return_value=conns):
            assert sorted(ports_for_pid(1234)) == [8000, 8001]

    def test_excludes_non_listen_connections(self) -> None:
        conns = [_make_conn(1234, 8000, status="ESTABLISHED")]
        with patch("psutil.net_connections", return_value=conns):
            assert ports_for_pid(1234) == []

    def test_reads_socket_table_exactly_once(self) -> None:
        mock_net = MagicMock(return_value=[_make_conn(1234, 8000)])
        with patch("psutil.net_connections", mock_net):
            ports_for_pid(1234)
        assert mock_net.call_count == 1


class TestPidForPort:
    def test_returns_none_when_no_listener(self) -> None:
        with patch("psutil.net_connections", return_value=[]):
            assert pid_for_port(8000) is None

    def test_returns_pid_for_listening_port(self) -> None:
        conns = [_make_conn(1234, 8000)]
        with patch("psutil.net_connections", return_value=conns):
            assert pid_for_port(8000) == 1234

    def test_returns_none_for_unmatched_port(self) -> None:
        conns = [_make_conn(1234, 9000)]
        with patch("psutil.net_connections", return_value=conns):
            assert pid_for_port(8000) is None

    def test_ignores_non_listen_connections(self) -> None:
        conns = [_make_conn(1234, 8000, status="ESTABLISHED")]
        with patch("psutil.net_connections", return_value=conns):
            assert pid_for_port(8000) is None

    def test_reads_socket_table_exactly_once(self) -> None:
        mock_net = MagicMock(return_value=[_make_conn(1234, 8000)])
        with patch("psutil.net_connections", mock_net):
            pid_for_port(8000)
        assert mock_net.call_count == 1


class TestScanAll:
    def test_returns_all_listeners(self) -> None:
        conns = [_make_conn(100, 3000), _make_conn(200, 8080)]
        with (
            patch("psutil.net_connections", return_value=conns),
            patch("psutil.Process") as mock_proc,
        ):
            mock_proc.return_value.name.return_value = "python"
            result = scan_all()
        ports = [r["port"] for r in result]
        assert 3000 in ports
        assert 8080 in ports

    def test_excludes_non_listen_connections(self) -> None:
        conns = [_make_conn(100, 3000, status="ESTABLISHED")]
        with patch("psutil.net_connections", return_value=conns):
            result = scan_all()
        assert result == []

    def test_reads_socket_table_exactly_once(self) -> None:
        mock_net = MagicMock(return_value=[])
        with patch("psutil.net_connections", mock_net):
            scan_all()
        assert mock_net.call_count == 1


class TestPortSocketState:
    def test_returns_free_when_no_connections(self) -> None:
        with patch("psutil.net_connections", return_value=[]):
            from vigil.scanner import port_socket_state

            assert port_socket_state(3000) == "free"

    def test_returns_listen_for_listen_socket(self) -> None:
        conn = _make_conn(1234, 3000, status="LISTEN")
        with patch("psutil.net_connections", return_value=[conn]):
            from vigil.scanner import port_socket_state

            assert port_socket_state(3000) == "listen"

    def test_returns_time_wait_for_time_wait_socket(self) -> None:
        conn = _make_conn(0, 3000, status="TIME_WAIT")
        with patch("psutil.net_connections", return_value=[conn]):
            from vigil.scanner import port_socket_state

            assert port_socket_state(3000) == "time_wait"

    def test_returns_free_for_other_port(self) -> None:
        conn = _make_conn(0, 4000, status="TIME_WAIT")
        with patch("psutil.net_connections", return_value=[conn]):
            from vigil.scanner import port_socket_state

            assert port_socket_state(3000) == "free"


class TestNextFreePort:
    def test_returns_start_when_free(self) -> None:
        with patch("psutil.net_connections", return_value=[]):
            result = next_free_port(3000)
        assert result == 3000

    def test_skips_occupied_ports(self) -> None:
        conns = [_make_conn(100, 3000), _make_conn(101, 3001)]
        with patch("psutil.net_connections", return_value=conns):
            result = next_free_port(3000)
        assert result == 3002

    def test_count_returns_consecutive_free_ports(self) -> None:
        conns = [_make_conn(100, 3000)]
        with patch("psutil.net_connections", return_value=conns):
            result = next_free_port(3000, count=3)
        assert result == [3001, 3002, 3003]

    def test_reads_socket_table_exactly_once(self) -> None:
        mock_net = MagicMock(return_value=[])
        with patch("psutil.net_connections", mock_net):
            next_free_port(3000, count=3)
        assert mock_net.call_count == 1

    def test_skips_time_wait_ports(self) -> None:
        """next_free_port treats TIME_WAIT ports as unavailable."""
        conns = [_make_conn(0, 3000, status="TIME_WAIT"), _make_conn(0, 3001, status="TIME_WAIT")]
        with patch("psutil.net_connections", return_value=conns):
            result = next_free_port(3000)
        assert result == 3002


class TestScanPorts:
    def test_returns_listener_for_occupied_port(self) -> None:
        conns = [_make_conn(1234, 3000)]
        with (
            patch("psutil.net_connections", return_value=conns),
            patch("psutil.Process") as mock_proc,
        ):
            mock_proc.return_value.name.return_value = "node"
            result = scan_ports([3000])
        assert len(result) == 1
        assert result[0]["port"] == 3000
        assert result[0]["pid"] == 1234
        assert result[0]["process"] == "node"
        assert result[0]["docker"] is None

    def test_returns_empty_for_free_port(self) -> None:
        with patch("psutil.net_connections", return_value=[]):
            result = scan_ports([3000])
        assert result == []

    def test_reads_socket_table_exactly_once_for_many_ports(self) -> None:
        mock_net = MagicMock(return_value=[_make_conn(1234, 3000)])
        with patch("psutil.net_connections", mock_net), patch("psutil.Process") as mock_proc:
            mock_proc.return_value.name.return_value = "node"
            scan_ports([3000, 3001, 3002, 3003])
        assert mock_net.call_count == 1
