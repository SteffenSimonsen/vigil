"""Tests for logs module — open_log and trim_log."""

from __future__ import annotations

from pathlib import Path

from vigil.config import Config
from vigil.logs import trim_log


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
