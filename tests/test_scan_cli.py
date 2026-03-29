"""Tests for vigil scan and vigil next CLI commands."""

from __future__ import annotations

import json
from collections import namedtuple
from unittest.mock import patch

from click.testing import CliRunner

from vigil.cli import main

_DOCKER_PS_LINE = json.dumps(
    {
        "Names": "myapp-postgres-1",
        "Image": "postgres:16",
        "Labels": "com.docker.compose.service=postgres,com.docker.compose.project=myapp",
        "Ports": "0.0.0.0:5432->5432/tcp",
    }
)

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


class TestVigilScanDockerEnrichment:
    def test_scan_json_enriches_container_backed_port(self) -> None:
        """vigil scan --json sets docker object for container-backed ports."""
        conns = [_make_conn(9921, 5432)]
        runner = CliRunner()
        with (
            patch("psutil.net_connections", return_value=conns),
            patch("psutil.Process") as mock_proc,
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.run") as mock_run,
        ):
            mock_proc.return_value.name.return_value = "docker-proxy"
            mock_run.return_value.stdout = _DOCKER_PS_LINE + "\n"
            result = runner.invoke(main, ["scan", "--port", "5432", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        listener = data["listeners"][0]
        assert listener["docker"] is not None
        assert listener["docker"]["container_name"] == "myapp-postgres-1"
        assert listener["docker"]["image"] == "postgres:16"
        assert listener["docker"]["compose_service"] == "postgres"
        assert listener["docker"]["compose_project"] == "myapp"

    def test_scan_json_docker_null_for_native_process(self) -> None:
        """vigil scan --json keeps docker=null for native (non-container) ports."""
        conns = [_make_conn(1234, 3000)]
        runner = CliRunner()
        with (
            patch("psutil.net_connections", return_value=conns),
            patch("psutil.Process") as mock_proc,
            patch("shutil.which", return_value=None),
        ):
            mock_proc.return_value.name.return_value = "node"
            result = runner.invoke(main, ["scan", "--port", "3000", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["listeners"][0]["docker"] is None

    def test_scan_human_shows_container_name_and_image(self) -> None:
        """vigil scan human output includes container name, image, and compose service."""
        conns = [_make_conn(9921, 5432)]
        runner = CliRunner()
        with (
            patch("psutil.net_connections", return_value=conns),
            patch("psutil.Process") as mock_proc,
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.run") as mock_run,
        ):
            mock_proc.return_value.name.return_value = "docker-proxy"
            mock_run.return_value.stdout = _DOCKER_PS_LINE + "\n"
            result = runner.invoke(main, ["scan", "--port", "5432"])
        assert result.exit_code == 0, result.output
        assert "myapp-postgres-1" in result.output
        assert "postgres:16" in result.output
        assert "postgres" in result.output


class TestVigilScanBadRange:
    def test_scan_range_nonnumeric_exits_with_json_error(self) -> None:
        """vigil scan --range abc-def exits 1 with JSON error."""
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "--range", "abc-def", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "error" in data
        assert data["code"] == 1

    def test_scan_range_no_hyphen_exits_with_json_error(self) -> None:
        """vigil scan --range 8000 (no hyphen) exits 1 with JSON error."""
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "--range", "8000", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "error" in data
        assert data["code"] == 1

    def test_scan_range_nonnumeric_text_output_exits_with_error(self) -> None:
        """vigil scan --range abc-def (text mode) exits 1."""
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "--range", "abc-def"])
        assert result.exit_code == 1


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
