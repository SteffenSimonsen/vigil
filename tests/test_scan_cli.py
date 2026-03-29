"""Tests for vigil scan and vigil next CLI commands."""

from __future__ import annotations

import json
from collections import namedtuple
from unittest.mock import patch

from click.testing import CliRunner

from vigil.cli import main

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


class TestVigilScan:
    def test_scan_json_returns_listeners_schema(self) -> None:
        """vigil scan --json returns {"listeners": [...]} with docker: null."""
        conns = [_make_conn(1234, 3000)]
        runner = CliRunner()
        with (
            patch("psutil.net_connections", return_value=conns),
            patch("psutil.Process") as mock_proc,
        ):
            mock_proc.return_value.name.return_value = "node"
            result = runner.invoke(main, ["scan", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "listeners" in data
        listener = next(entry for entry in data["listeners"] if entry["port"] == 3000)
        assert listener["pid"] == 1234
        assert listener["docker"] is None

    def test_scan_defaults_to_dev_ranges(self) -> None:
        """vigil scan without flags only reports ports in dev ranges."""
        # port 1234 is outside dev ranges — should not appear
        conns = [_make_conn(111, 1234), _make_conn(222, 3000)]
        runner = CliRunner()
        with (
            patch("psutil.net_connections", return_value=conns),
            patch("psutil.Process") as mock_proc,
        ):
            mock_proc.return_value.name.return_value = "python"
            result = runner.invoke(main, ["scan", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        ports = [entry["port"] for entry in data["listeners"]]
        assert 3000 in ports
        assert 1234 not in ports

    def test_scan_port_checks_single_port(self) -> None:
        """vigil scan --port 3000 returns only that port."""
        conns = [_make_conn(1234, 3000), _make_conn(5678, 4000)]
        runner = CliRunner()
        with (
            patch("psutil.net_connections", return_value=conns),
            patch("psutil.Process") as mock_proc,
        ):
            mock_proc.return_value.name.return_value = "node"
            result = runner.invoke(main, ["scan", "--port", "3000", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data["listeners"]) == 1
        assert data["listeners"][0]["port"] == 3000

    def test_scan_range_checks_that_range(self) -> None:
        """vigil scan --range 3000-3005 checks only that range."""
        conns = [_make_conn(1, 3002), _make_conn(2, 8000)]
        runner = CliRunner()
        with (
            patch("psutil.net_connections", return_value=conns),
            patch("psutil.Process") as mock_proc,
        ):
            mock_proc.return_value.name.return_value = "node"
            result = runner.invoke(main, ["scan", "--range", "3000-3005", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        ports = [entry["port"] for entry in data["listeners"]]
        assert 3002 in ports
        assert 8000 not in ports

    def test_scan_all_returns_full_socket_table(self) -> None:
        """vigil scan --all returns every listener regardless of port."""
        conns = [_make_conn(1, 1234), _make_conn(2, 55555)]
        runner = CliRunner()
        with (
            patch("psutil.net_connections", return_value=conns),
            patch("psutil.Process") as mock_proc,
        ):
            mock_proc.return_value.name.return_value = "custom"
            result = runner.invoke(main, ["scan", "--all", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        ports = [entry["port"] for entry in data["listeners"]]
        assert 1234 in ports
        assert 55555 in ports


class TestVigilNext:
    def test_next_returns_next_free_port_from_3000(self) -> None:
        """vigil next returns first free port starting from 3000."""
        runner = CliRunner()
        with patch("psutil.net_connections", return_value=[]):
            result = runner.invoke(main, ["next", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["port"] == 3000

    def test_next_start_overrides_default(self) -> None:
        """vigil next 8000 starts search from 8000."""
        runner = CliRunner()
        with patch("psutil.net_connections", return_value=[]):
            result = runner.invoke(main, ["next", "8000", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["port"] == 8000

    def test_next_count_returns_multiple_ports(self) -> None:
        """vigil next --count 3 returns 3 consecutive free ports."""
        runner = CliRunner()
        with patch("psutil.net_connections", return_value=[]):
            result = runner.invoke(main, ["next", "--count", "3", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "ports" in data
        assert len(data["ports"]) == 3

    def test_next_json_single_port(self) -> None:
        """vigil next --json returns {"port": N} when count=1."""
        runner = CliRunner()
        with patch("psutil.net_connections", return_value=[]):
            result = runner.invoke(main, ["next", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "port" in data
        assert "ports" not in data

    def test_next_skips_occupied_ports(self) -> None:
        """vigil next skips ports that are in use."""
        conns = [_make_conn(1, 3000), _make_conn(2, 3001)]
        runner = CliRunner()
        with patch("psutil.net_connections", return_value=conns):
            result = runner.invoke(main, ["next", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["port"] == 3002
