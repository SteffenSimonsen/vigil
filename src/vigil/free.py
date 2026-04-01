"""Port freeing — clear any port regardless of occupant type."""

from __future__ import annotations

import contextlib
import subprocess
from typing import Literal, NotRequired, TypedDict

import psutil

from vigil.config import Config
from vigil.docker import enrich as docker_enrich
from vigil.manager import stop as manager_stop
from vigil.scanner import port_socket_state, scan_ports
from vigil.state import StateManager


class FreeResult(TypedDict):
    port: int
    freed: bool
    was: Literal["managed", "unmanaged", "docker", "free", "time_wait"]
    retry_after_seconds: NotRequired[int]


def free_port(config: Config, port: int) -> FreeResult:
    """Free the given port regardless of what is using it.

    Dispatch order:
    1. Nothing listening → return was=free immediately.
    2. Docker container → run ``docker stop <name>``.
    3. Managed process → call manager.stop().
    4. Unmanaged process → SIGTERM, wait grace period, SIGKILL.
    """
    listeners = scan_ports([port])
    docker_enrich(listeners)

    if not listeners:
        if port_socket_state(port) == "time_wait":
            return FreeResult(port=port, freed=False, was="time_wait", retry_after_seconds=60)
        return FreeResult(port=port, freed=True, was="free")

    listener = listeners[0]
    pid = listener["pid"]
    docker_info = listener["docker"]

    if docker_info is not None:
        subprocess.run(
            ["docker", "stop", docker_info["container_name"]],
            capture_output=True,
            check=False,
        )
        return FreeResult(port=port, freed=True, was="docker")

    if pid is not None:
        state = StateManager(config)
        managed_by_pid = {r.pid: r for r in state.read_all() if r.alive}
        if pid in managed_by_pid:
            record = managed_by_pid[pid]
            manager_stop(config, record.name)
            return FreeResult(port=port, freed=True, was="managed")

    if pid is not None:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=config.stop_grace_period)
            except psutil.TimeoutExpired:
                proc.kill()
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    proc.wait(timeout=5)

    return FreeResult(port=port, freed=True, was="unmanaged")
