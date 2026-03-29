"""Tests for docker enrichment module."""

from __future__ import annotations

import json
from unittest.mock import patch

from vigil.docker import enrich
from vigil.scanner import Listener


def _make_listener(port: int, pid: int = 1234, process: str = "python") -> Listener:
    return Listener(port=port, pid=pid, process=process, docker=None)


class TestEnrichWhenDockerUnavailable:
    def test_no_op_when_docker_not_in_path(self) -> None:
        """enrich() silently returns listeners unchanged when docker is not in PATH."""
        listeners = [_make_listener(5432)]
        with patch("shutil.which", return_value=None):
            result = enrich(listeners)
        assert result[0]["docker"] is None

    def test_no_op_when_docker_daemon_unreachable(self) -> None:
        """enrich() silently returns listeners unchanged when docker daemon is down."""
        import subprocess

        listeners = [_make_listener(5432)]
        with (
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "docker ps"),
            ),
        ):
            result = enrich(listeners)
        assert result[0]["docker"] is None


class TestEnrichWithDockerContainers:
    def _docker_ps_line(
        self,
        name: str,
        image: str,
        ports: str,
        compose_service: str | None = None,
        compose_project: str | None = None,
    ) -> str:
        labels: list[str] = []
        if compose_service:
            labels.append(f"com.docker.compose.service={compose_service}")
        if compose_project:
            labels.append(f"com.docker.compose.project={compose_project}")
        return json.dumps(
            {
                "Names": name,
                "Image": image,
                "Labels": ",".join(labels),
                "Ports": ports,
            }
        )

    def test_listener_enriched_when_port_matches_container(self) -> None:
        """enrich() sets docker field when listener port matches a container port."""
        listeners = [_make_listener(5432, pid=9921, process="docker-proxy")]
        ps_output = self._docker_ps_line(
            name="myapp-postgres-1",
            image="postgres:16",
            ports="0.0.0.0:5432->5432/tcp",
            compose_service="postgres",
            compose_project="myapp",
        )
        with (
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = ps_output + "\n"
            result = enrich(listeners)

        docker_info = result[0]["docker"]
        assert docker_info is not None
        assert docker_info["container_name"] == "myapp-postgres-1"
        assert docker_info["image"] == "postgres:16"
        assert docker_info["compose_service"] == "postgres"
        assert docker_info["compose_project"] == "myapp"

    def test_non_container_port_carries_docker_null(self) -> None:
        """enrich() leaves docker=None for ports not belonging to any container."""
        listeners = [_make_listener(3000, process="node")]
        ps_output = self._docker_ps_line(
            name="myapp-postgres-1",
            image="postgres:16",
            ports="0.0.0.0:5432->5432/tcp",
        )
        with (
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = ps_output + "\n"
            result = enrich(listeners)

        assert result[0]["docker"] is None

    def test_docker_ps_called_exactly_once(self) -> None:
        """enrich() calls docker ps at most once regardless of listener count."""
        listeners = [_make_listener(5432), _make_listener(6379), _make_listener(3000)]
        ps_output = self._docker_ps_line(
            name="myapp-redis-1",
            image="redis:7",
            ports="0.0.0.0:6379->6379/tcp",
        )
        with (
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = ps_output + "\n"
            enrich(listeners)

        assert mock_run.call_count == 1

    def test_compose_labels_parsed_correctly(self) -> None:
        """enrich() reads compose_service and compose_project from container labels."""
        listeners = [_make_listener(6379)]
        ps_output = self._docker_ps_line(
            name="webapp-redis-1",
            image="redis:7",
            ports="0.0.0.0:6379->6379/tcp",
            compose_service="redis",
            compose_project="webapp",
        )
        with (
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = ps_output + "\n"
            result = enrich(listeners)

        docker_info = result[0]["docker"]
        assert docker_info is not None
        assert docker_info["compose_service"] == "redis"
        assert docker_info["compose_project"] == "webapp"

    def test_compose_labels_none_when_not_compose_managed(self) -> None:
        """enrich() sets compose_service/project to None when labels are absent."""
        listeners = [_make_listener(27017)]
        ps_output = self._docker_ps_line(
            name="mongo",
            image="mongo:7",
            ports="0.0.0.0:27017->27017/tcp",
        )
        with (
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = ps_output + "\n"
            result = enrich(listeners)

        docker_info = result[0]["docker"]
        assert docker_info is not None
        assert docker_info["compose_service"] is None
        assert docker_info["compose_project"] is None

    def test_multiple_containers_matched_correctly(self) -> None:
        """enrich() can enrich multiple listeners from multiple containers."""
        listeners = [_make_listener(5432), _make_listener(6379)]
        ps_lines = "\n".join(
            [
                self._docker_ps_line(
                    "myapp-postgres-1",
                    "postgres:16",
                    "0.0.0.0:5432->5432/tcp",
                    "postgres",
                    "myapp",
                ),
                self._docker_ps_line(
                    "myapp-redis-1",
                    "redis:7",
                    "0.0.0.0:6379->6379/tcp",
                    "redis",
                    "myapp",
                ),
            ]
        )
        with (
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = ps_lines + "\n"
            result = enrich(listeners)

        assert result[0]["docker"] is not None
        assert result[0]["docker"]["container_name"] == "myapp-postgres-1"
        assert result[1]["docker"] is not None
        assert result[1]["docker"]["container_name"] == "myapp-redis-1"
