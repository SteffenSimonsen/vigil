"""Tests for logs module — open_log, trim_log, read_log, follow_log."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from vigil.config import Config
from vigil.logs import LogNotFound, follow_log, read_log, trim_log


class TestReadLog:
    def test_read_log_returns_last_n_lines(self, tmp_path: Path) -> None:
        cfg = Config(root=tmp_path)
        cfg.logs_dir.mkdir(parents=True)
        log_path = cfg.logs_dir / "web.log"
        lines = [f"line {i}\n" for i in range(1, 201)]
        log_path.write_text("".join(lines))

        result = read_log(cfg, "web", tail=10)

        assert result == [f"line {i}" for i in range(191, 201)]

    def test_read_log_raises_when_log_missing(self, tmp_path: Path) -> None:
        cfg = Config(root=tmp_path)
        cfg.logs_dir.mkdir(parents=True)

        import pytest

        with pytest.raises(LogNotFound):
            read_log(cfg, "unknown")

    def test_follow_log_yields_new_lines(self, tmp_path: Path) -> None:
        cfg = Config(root=tmp_path)
        cfg.logs_dir.mkdir(parents=True)
        log_path = cfg.logs_dir / "web.log"
        log_path.write_text("")

        collected: list[str] = []
        stop_event = threading.Event()

        def _collect() -> None:
            for line in follow_log(cfg, "web", stop=stop_event):
                collected.append(line)

        t = threading.Thread(target=_collect, daemon=True)
        t.start()

        time.sleep(0.05)
        log_path.write_text("hello\nworld\n")
        time.sleep(0.3)
        stop_event.set()
        t.join(timeout=2)

        assert "hello" in collected
        assert "world" in collected


class TestTrimLog:
    def test_trim_log_keeps_last_n_lines(self, tmp_path: Path) -> None:
        cfg = Config(root=tmp_path)
        cfg.logs_dir.mkdir(parents=True)
        log_path = cfg.logs_dir / "web.log"
        lines = [f"line {i}\n" for i in range(1, 601)]
        log_path.write_text("".join(lines))

        trim_log(cfg, "web", max_lines=500)

        result = log_path.read_text().splitlines()
        assert len(result) == 500
        assert result[0] == "line 101"
        assert result[-1] == "line 600"

    def test_trim_log_noop_when_under_limit(self, tmp_path: Path) -> None:
        cfg = Config(root=tmp_path)
        cfg.logs_dir.mkdir(parents=True)
        log_path = cfg.logs_dir / "web.log"
        original = "".join(f"line {i}\n" for i in range(1, 101))
        log_path.write_text(original)

        trim_log(cfg, "web", max_lines=500)

        assert log_path.read_text() == original

    def test_trim_log_noop_when_log_missing(self, tmp_path: Path) -> None:
        cfg = Config(root=tmp_path)
        cfg.logs_dir.mkdir(parents=True)
        # Should not raise even if the log file doesn't exist
        trim_log(cfg, "web", max_lines=500)
