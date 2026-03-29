# Log capture and trimming
"""Log file management for managed processes."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Generator
from typing import IO

from vigil.config import Config


class LogNotFound(Exception):
    """Raised when the log file for a process does not exist."""


def read_log(config: Config, name: str, tail: int = 50) -> list[str]:
    """Return the last *tail* lines from the log file for *name*.

    Reads from the end of the file without loading the entire file into memory.
    Raises LogNotFound if no log file exists for *name*.
    """
    log_path = config.logs_dir / f"{name}.log"
    if not log_path.exists():
        raise LogNotFound(f"No log file found for process {name!r}")

    chunk_size = 8192
    newlines_found = 0
    file_size = log_path.stat().st_size
    offset = file_size
    cut_pos = 0

    with log_path.open("rb") as f:
        while offset > 0:
            read_size = min(chunk_size, offset)
            offset -= read_size
            f.seek(offset)
            chunk = f.read(read_size)
            for i in range(len(chunk) - 1, -1, -1):
                if chunk[i] == ord(b"\n"):
                    newlines_found += 1
                    if newlines_found > tail:
                        cut_pos = offset + i + 1
                        break
            if newlines_found > tail:
                break

        f.seek(cut_pos)
        tail_bytes = f.read()

    lines = tail_bytes.decode("utf-8", errors="replace").splitlines()
    # Drop trailing empty line from a file ending with \n
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


def follow_log(
    config: Config,
    name: str,
    *,
    stop: threading.Event | None = None,
    poll_interval: float = 0.1,
) -> Generator[str, None, None]:
    """Yield new lines appended to the log file for *name* (tail -f style).

    Starts at the current end of file and yields each new complete line as it
    arrives. Stops when *stop* is set (or runs forever if *stop* is None).
    Raises LogNotFound if no log file exists for *name*.
    """
    log_path = config.logs_dir / f"{name}.log"
    if not log_path.exists():
        raise LogNotFound(f"No log file found for process {name!r}")

    with log_path.open("r", encoding="utf-8", errors="replace") as f:
        f.seek(0, 2)  # seek to end
        buf = ""
        while stop is None or not stop.is_set():
            chunk = f.read(4096)
            if chunk:
                buf += chunk
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    yield line
            else:
                time.sleep(poll_interval)


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
