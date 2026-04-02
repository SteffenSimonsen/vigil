"""Crash-loop detection and circuit breaker for managed processes."""

from __future__ import annotations

import time

from vigil.config import Config
from vigil.scanner import ports_for_pid
from vigil.state import StateManager

_DEFAULT_CRASH_THRESHOLD = 5


class CrashLooping(Exception):
    """Raised when a managed process is detected as crash-looping (circuit open)."""


def observe(config: Config, name: str, *, crash_threshold: int = _DEFAULT_CRASH_THRESHOLD) -> bool:
    """Observe a process's port heartbeat and update crash-loop state.

    Checks whether the process named *name* is alive but its registered port is
    no longer listening. Each such observation increments ``crash_count``. Once
    ``crash_count >= crash_threshold`` the circuit opens (``circuit_open=True``).
    When the port comes back the counter and circuit flag are cleared.

    Returns True if the circuit is open (process is crash-looping) after this
    observation; False otherwise.

    Does nothing and returns False when:
    - The process is not in the statefile.
    - The process is dead (not crash-looping — just crashed).
    - The process has no registered port (cannot detect heartbeat).
    """
    state = StateManager(config)
    records = {r.name: r for r in state.read_all()}
    if name not in records:
        return False

    record = records[name]

    if not record.alive or record.port is None:
        return False

    listening_ports = ports_for_pid(record.pid)
    if record.port in listening_ports:
        # Port is present — clear any crash-loop state
        if record.circuit_open or record.crash_count > 0:
            state.update(name, crash_count=0, last_crash_at=None, circuit_open=False)
        return False

    # Port absent while PID is alive — crash observation.
    # Once circuit is already open, don't keep incrementing the counter.
    if record.circuit_open:
        return True

    new_count = record.crash_count + 1
    circuit_open = new_count >= crash_threshold
    state.update(
        name,
        crash_count=new_count,
        last_crash_at=time.time(),
        circuit_open=circuit_open,
    )
    return circuit_open
