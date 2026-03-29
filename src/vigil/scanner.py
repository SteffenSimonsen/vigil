# Port scanning and process discovery

from __future__ import annotations

import contextlib
from typing import TypedDict

import psutil


class Listener(TypedDict):
    port: int
    pid: int | None
    process: str | None
    docker: None


def _snapshot() -> list[Listener]:
    """Read the OS socket table once and return all LISTEN entries."""
    conns = psutil.net_connections(kind="inet")
    result: list[Listener] = []
    for c in conns:
        if c.status == "LISTEN":
            port = getattr(c.laddr, "port", None)
            if isinstance(port, int):
                pid: int | None = c.pid if isinstance(c.pid, int) else None
                proc_name: str | None = None
                if pid is not None:
                    with contextlib.suppress(psutil.NoSuchProcess):
                        proc_name = psutil.Process(pid).name()
                result.append(Listener(port=port, pid=pid, process=proc_name, docker=None))
    return result


def scan_ports(ports: list[int]) -> list[Listener]:
    """Return listener info for each port in *ports* that is actively listening.

    Reads the OS socket table exactly once.
    """
    port_set = set(ports)
    return [entry for entry in _snapshot() if entry["port"] in port_set]


def scan_all() -> list[Listener]:
    """Return listener info for every port currently listening on the OS.

    Reads the OS socket table exactly once.
    """
    return _snapshot()


def next_free_port(start: int = 3000, count: int = 1) -> int | list[int]:
    """Find free port(s) starting from *start*.

    Reads the OS socket table exactly once. Returns a single int when
    count=1, or a list[int] when count>1.
    """
    occupied = {entry["port"] for entry in _snapshot()}
    found: list[int] = []
    port = start
    while len(found) < count:
        if port not in occupied:
            found.append(port)
        port += 1
    return found[0] if count == 1 else found


def ports_for_pid(pid: int) -> list[int]:
    """Return all TCP/UDP ports this PID is listening on.

    Reads the OS socket table in a single psutil call — not per-port.
    """
    conns = psutil.net_connections(kind="inet")
    result: list[int] = []
    for c in conns:
        if c.pid == pid and c.status == "LISTEN":
            # laddr is addr | tuple[()]; addr has .port, empty tuple does not.
            port = getattr(c.laddr, "port", None)
            if isinstance(port, int):
                result.append(port)
    return result


def pid_for_port(port: int) -> int | None:
    """Return the PID listening on this port, or None if nothing is listening.

    Reads the OS socket table in a single psutil call — not per-port.
    """
    conns = psutil.net_connections(kind="inet")
    for c in conns:
        if c.status == "LISTEN" and c.pid is not None:
            laddr_port = getattr(c.laddr, "port", None)
            if laddr_port == port:
                return c.pid
    return None
