"""Tests for scanner module — port/PID mapping."""

from __future__ import annotations

from collections import namedtuple
from unittest.mock import MagicMock, patch

from vigil.scanner import pid_for_port, ports_for_pid

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
