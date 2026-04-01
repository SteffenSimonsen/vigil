"""Orphan process detection — processes in the project directory not in the vigil registry."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TypedDict

import psutil


class OrphanProcess(TypedDict):
    pid: int
    command: str
    cwd: str
    ports: list[int]


def find_orphans(project_root: Path, registry_pids: set[int]) -> list[OrphanProcess]:
    """Return processes whose CWD is inside *project_root* but not in *registry_pids*.

    Handles psutil.AccessDenied and psutil.NoSuchProcess gracefully — those
    processes are silently skipped.
    """
    project_root = project_root.resolve()
    orphans: list[OrphanProcess] = []

    for proc in psutil.process_iter():
        if proc.pid in registry_pids:
            continue
        try:
            cwd = proc.cwd()
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue

        try:
            cwd_path = Path(cwd).resolve()
        except (ValueError, OSError):
            continue

        # Check if CWD is inside (or equal to) the project root
        try:
            cwd_path.relative_to(project_root)
        except ValueError:
            continue

        # This process belongs to our project — collect info
        try:
            cmdline = proc.cmdline()
            command = " ".join(cmdline) if cmdline else proc.name()
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue

        ports = _listening_ports(proc.pid)

        orphans.append(
            OrphanProcess(
                pid=proc.pid,
                command=command,
                cwd=cwd,
                ports=ports,
            )
        )

    return orphans


def _listening_ports(pid: int) -> list[int]:
    """Return TCP ports this PID is listening on. Returns [] on any error."""
    ports: list[int] = []
    with contextlib.suppress(Exception):
        for conn in psutil.net_connections(kind="inet"):
            if conn.pid == pid and conn.status == "LISTEN":
                port = getattr(conn.laddr, "port", None)
                if isinstance(port, int):
                    ports.append(port)
    return ports
