# Docker enrichment (cross-cutting, lazy)

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from vigil.scanner import Listener


class DockerInfo(TypedDict):
    container_name: str
    image: str
    compose_service: str | None
    compose_project: str | None


def _run_docker_ps() -> list[dict[str, str]]:
    """Run ``docker ps --format json`` and return parsed records.

    Returns an empty list if Docker is unavailable or the daemon is unreachable.
    """
    if shutil.which("docker") is None:
        return []
    try:
        proc = subprocess.run(
            ["docker", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return []

    records: list[dict[str, str]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _parse_host_ports(ports_str: str) -> list[int]:
    """Extract host port numbers from a docker ps Ports string.

    E.g. ``"0.0.0.0:5432->5432/tcp, :::5432->5432/tcp"`` → ``[5432]``
    """
    return [int(m) for m in re.findall(r"(?:[\d.]+|:::?):(\d+)->", ports_str)]


def _parse_labels(labels_str: str) -> dict[str, str]:
    """Parse comma-separated ``key=value`` label string into a dict."""
    result: dict[str, str] = {}
    for part in labels_str.split(","):
        part = part.strip()
        if "=" in part:
            key, _, value = part.partition("=")
            result[key.strip()] = value.strip()
    return result


def _build_port_map(records: list[dict[str, str]]) -> dict[int, DockerInfo]:
    """Build a mapping from host port number to DockerInfo."""
    port_map: dict[int, DockerInfo] = {}
    for rec in records:
        labels = _parse_labels(rec.get("Labels", ""))
        info = DockerInfo(
            container_name=rec.get("Names", ""),
            image=rec.get("Image", ""),
            compose_service=labels.get("com.docker.compose.service") or None,
            compose_project=labels.get("com.docker.compose.project") or None,
        )
        for port in _parse_host_ports(rec.get("Ports", "")):
            port_map[port] = info
    return port_map


def lookup(ports: list[int]) -> DockerInfo | None:
    """Return Docker metadata for the first port in *ports* that matches a container.

    Calls ``docker ps`` at most once per invocation. Returns ``None`` if Docker
    is unavailable or no container matches.
    """
    records = _run_docker_ps()
    if not records:
        return None
    port_map = _build_port_map(records)
    for port in ports:
        info = port_map.get(port)
        if info is not None:
            return info
    return None


def enrich(listeners: list[Listener]) -> list[Listener]:
    """Enrich listener records with Docker container metadata.

    Calls ``docker ps`` at most once per invocation. Silently skips enrichment
    if Docker is not in PATH or the daemon is unreachable. Non-container
    processes keep ``docker: None``.
    """
    records = _run_docker_ps()
    if not records:
        return listeners

    port_map = _build_port_map(records)
    for listener in listeners:
        info = port_map.get(listener["port"])
        if info is not None:
            listener["docker"] = info  # type: ignore[typeddict-item]
    return listeners
