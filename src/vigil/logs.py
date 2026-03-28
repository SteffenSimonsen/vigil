# Log capture and trimming
"""Log file management for managed processes."""

from __future__ import annotations

from typing import IO

from vigil.config import Config


def open_log(config: Config, name: str) -> IO[bytes]:
    """Open (create if needed) the log file for *name* in append+binary mode.

    The caller is responsible for closing the file descriptor.
    """
    log_path = config.logs_dir / f"{name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return open(log_path, "ab")  # noqa: SIM115 — intentionally kept open for subprocess
