"""Open a service or port in the browser."""

from __future__ import annotations

from vigil.config import Config
from vigil.scanner import ports_for_pid
from vigil.state import StateManager


class UnknownProcess(Exception):
    """Raised when a process name is not found in the statefile."""


def resolve_url(config: Config, target: str) -> str:
    """Resolve the URL for a target (name or port).

    - If target is a port number string, returns ``http://localhost:<port>``.
    - If target is a process name, looks up the port from the statefile.
      If the Vigilfile defines a ``url`` field for the process, that is used instead.
    - Raises UnknownProcess if the name is not in the statefile.
    """
    if target.isdigit():
        return f"http://localhost:{target}"

    # Look up by name in statefile
    sm = StateManager(config)
    records = sm.read_all()
    for record in records:
        if record.name == target:
            # Check Vigilfile for url override
            url_override = _vigilfile_url(config, target)
            if url_override:
                return url_override
            if record.port is not None:
                return f"http://localhost:{record.port}"
            # Port not stored — fall back to live scanner lookup
            live_ports = ports_for_pid(record.pid)
            if live_ports:
                return f"http://localhost:{live_ports[0]}"
            return f"http://localhost:{record.port}"

    raise UnknownProcess(f"No process named {target!r}")


def _vigilfile_url(config: Config, name: str) -> str | None:
    """Return the url override for a process from the Vigilfile, or None."""
    vigilfile = config.root / "Vigilfile"
    if not vigilfile.exists():
        return None
    try:
        import tomllib

        with vigilfile.open("rb") as f:
            data = tomllib.load(f)
    except Exception:
        return None

    for proc in data.get("process", []):
        if proc.get("name") == name:
            return proc.get("url")  # type: ignore[no-any-return]
    return None
