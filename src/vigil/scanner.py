# Port scanning and process discovery

from __future__ import annotations

import psutil


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
