# Log capture and trimming
"""Log file management for managed processes."""

from __future__ import annotations

import os
from typing import IO

from vigil.config import Config


def open_log(config: Config, name: str) -> IO[bytes]:
    """Open (create if needed) the log file for *name* in append+binary mode.

    The caller is responsible for closing the file descriptor.
    """
    log_path = config.logs_dir / f"{name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return open(log_path, "ab")  # noqa: SIM115 — intentionally kept open for subprocess


def trim_log(config: Config, name: str, max_lines: int = 500) -> None:
    """Trim the log file for *name* to the last *max_lines* lines.

    Reads from the end of the file without loading the entire file into memory.
    No-op if the file does not exist or is already within the limit.
    """
    log_path = config.logs_dir / f"{name}.log"
    if not log_path.exists():
        return

    # Collect the last max_lines+1 newlines by scanning backwards in chunks
    chunk_size = 8192
    newlines_found = 0
    file_size = log_path.stat().st_size
    offset = file_size
    cut_pos = 0  # byte position of the start of line (max_lines from end)

    with log_path.open("rb") as f:
        while offset > 0:
            read_size = min(chunk_size, offset)
            offset -= read_size
            f.seek(offset)
            chunk = f.read(read_size)
            for i in range(len(chunk) - 1, -1, -1):
                if chunk[i] == ord(b"\n"):
                    newlines_found += 1
                    if newlines_found > max_lines:
                        cut_pos = offset + i + 1
                        break
            if newlines_found > max_lines:
                break

    if cut_pos == 0:
        return  # file has <= max_lines lines, nothing to trim

    # Read the tail and write it back atomically
    with log_path.open("rb") as f:
        f.seek(cut_pos)
        tail = f.read()

    tmp_path = log_path.with_suffix(".log.tmp")
    tmp_path.write_bytes(tail)
    os.replace(tmp_path, log_path)
