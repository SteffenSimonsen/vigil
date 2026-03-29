"""Tests for vigilfile module — Vigilfile parsing and up/down orchestration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vigil.config import Config
from vigil.vigilfile import ParseError, VigilEntry, down, load, up


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create a minimal vigil project directory."""
    (tmp_path / ".vigil").mkdir()
    return tmp_path


@pytest.fixture
def config(project: Path) -> Config:
    return Config(root=project)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestLoad:
    def test_minimal_entry(self, project: Path) -> None:
        (project / "Vigilfile").write_text(
            '[[process]]\nname = "web"\ncommand = "python -m http.server"\n'
        )
        entries = load(project)
        assert len(entries) == 1
        e = entries[0]
        assert e.name == "web"
        assert e.command == "python -m http.server"

    def test_optional_fields(self, project: Path) -> None:
        (project / "Vigilfile").write_text(
            "[process.web]\n"  # wrong format — use [[process]] array
            "[[process]]\n"
            'name = "api"\n'
            'command = "uvicorn main:app"\n'
            "port = 8001\n"
            "order = 2\n"
            "wait_timeout = 15.0\n"
            'cwd = "/app"\n'
            'url = "https://api.local"\n'
            'health_endpoint = "/health"\n'
            "[process.env]\n"
        )
        # This will hit a parse error due to mixing table and array-of-tables.
        # Let's write it correctly:
        (project / "Vigilfile").write_text(
            "[[process]]\n"
            'name = "api"\n'
            'command = "uvicorn main:app"\n'
            "port = 8001\n"
            "order = 2\n"
            "wait_timeout = 15.0\n"
            'cwd = "/app"\n'
            'url = "https://api.local"\n'
            'health_endpoint = "/health"\n'
            "[process.env]\n"
            'MY_VAR = "hello"\n'
        )
        entries = load(project)
        assert len(entries) == 1
        e = entries[0]
        assert e.port == 8001
        assert e.order == 2
        assert e.wait_timeout == 15.0
        assert e.cwd == "/app"
        assert e.url == "https://api.local"
        assert e.health_endpoint == "/health"
        assert e.env == {"MY_VAR": "hello"}

    def test_multiple_entries(self, project: Path) -> None:
        (project / "Vigilfile").write_text(
            "[[process]]\n"
            'name = "db"\n'
            'command = "postgres"\n'
            "order = 1\n"
            "\n"
            "[[process]]\n"
            'name = "api"\n'
            'command = "uvicorn main:app"\n'
            "order = 2\n"
        )
        entries = load(project)
        assert len(entries) == 2
        names = [e.name for e in entries]
        assert "db" in names
        assert "api" in names

    def test_missing_vigilfile_raises_parse_error(self, project: Path) -> None:
        with pytest.raises(ParseError, match="Vigilfile"):
            load(project)

    def test_malformed_toml_raises_parse_error(self, project: Path) -> None:
        (project / "Vigilfile").write_text("[[process\nname = oops\n")
        with pytest.raises(ParseError):
            load(project)

    def test_entry_missing_name_raises_parse_error(self, project: Path) -> None:
        (project / "Vigilfile").write_text("[[process]]\ncommand = 'echo hi'\n")
        with pytest.raises(ParseError, match="name"):
            load(project)

    def test_entry_missing_command_raises_parse_error(self, project: Path) -> None:
        (project / "Vigilfile").write_text('[[process]]\nname = "web"\n')
        with pytest.raises(ParseError, match="command"):
            load(project)


# ---------------------------------------------------------------------------
# up() orchestration
# ---------------------------------------------------------------------------


def _make_entries(*names_orders: tuple[str, int | None]) -> list[VigilEntry]:
    """Helper: build VigilEntry list from (name, order) pairs."""
    entries = []
    for name, order in names_orders:
        entries.append(VigilEntry(name=name, command="echo hi", order=order))
    return entries


class TestUp:
    def test_up_starts_processes_in_order(self, config: Config) -> None:
        """Processes with lower order values start first."""
        entries = _make_entries(("api", 2), ("db", 1))
        started: list[str] = []

        def fake_start(cfg: Config, name: str, command: str, **kwargs: object) -> MagicMock:
            started.append(name)
            rec = MagicMock()
            rec.pid = 1234
            rec.name = name
            return rec

        def fake_wait(cfg: Config, name: str, **kwargs: object) -> None:
            pass  # instant

        with (
            patch("vigil.vigilfile._start", side_effect=fake_start),
            patch("vigil.vigilfile._wait", side_effect=fake_wait),
        ):
            results = up(config, entries)

        assert started == ["db", "api"]
        assert [r["name"] for r in results] == ["db", "api"]
        assert all(r["status"] == "started" for r in results)

    def test_up_unordered_after_ordered(self, config: Config) -> None:
        """Entries without an order run after those with order, in definition order."""
        entries = _make_entries(("c", None), ("a", 1), ("b", None))
        started: list[str] = []

        def fake_start(cfg: Config, name: str, command: str, **kwargs: object) -> MagicMock:
            started.append(name)
            rec = MagicMock()
            rec.pid = 1234
            rec.name = name
            return rec

        def fake_wait(cfg: Config, name: str, **kwargs: object) -> None:
            pass

        with (
            patch("vigil.vigilfile._start", side_effect=fake_start),
            patch("vigil.vigilfile._wait", side_effect=fake_wait),
        ):
            up(config, entries)

        assert started[0] == "a"  # ordered first
        assert started[1:] == ["c", "b"]  # unordered, definition order

    def test_up_skips_already_alive(self, config: Config) -> None:
        """up() skips processes that are already running."""
        from vigil.manager import ProcessAlreadyRunning

        entries = _make_entries(("web", 1))

        def fake_start(cfg: Config, name: str, command: str, **kwargs: object) -> MagicMock:
            raise ProcessAlreadyRunning("already running")

        def fake_wait(cfg: Config, name: str, **kwargs: object) -> None:
            pass

        with (
            patch("vigil.vigilfile._start", side_effect=fake_start),
            patch("vigil.vigilfile._wait", side_effect=fake_wait),
        ):
            results = up(config, entries)

        assert results[0]["status"] == "skipped"

    def test_up_continues_on_failure(self, config: Config) -> None:
        """If one process fails to start, others still run."""
        entries = _make_entries(("db", 1), ("api", 2), ("worker", 3))
        call_count = 0

        def fake_start(cfg: Config, name: str, command: str, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if name == "api":
                raise RuntimeError("start failed")
            rec = MagicMock()
            rec.pid = 1234
            rec.name = name
            return rec

        def fake_wait(cfg: Config, name: str, **kwargs: object) -> None:
            pass

        with (
            patch("vigil.vigilfile._start", side_effect=fake_start),
            patch("vigil.vigilfile._wait", side_effect=fake_wait),
        ):
            results = up(config, entries)

        statuses = {r["name"]: r["status"] for r in results}
        assert statuses["db"] == "started"
        assert statuses["api"] == "failed"
        assert statuses["worker"] == "started"
        assert call_count == 3

    def test_up_failure_recorded_with_error(self, config: Config) -> None:
        """Failed process result contains an error message."""
        entries = _make_entries(("api", 1))

        def fake_start(cfg: Config, name: str, command: str, **kwargs: object) -> MagicMock:
            raise RuntimeError("boom")

        def fake_wait(cfg: Config, name: str, **kwargs: object) -> None:
            pass

        with (
            patch("vigil.vigilfile._start", side_effect=fake_start),
            patch("vigil.vigilfile._wait", side_effect=fake_wait),
        ):
            results = up(config, entries)

        assert results[0]["status"] == "failed"
        assert "boom" in results[0]["error"]

    def test_up_only_filter(self, config: Config) -> None:
        """--only starts just the named subset."""
        entries = _make_entries(("db", 1), ("api", 2), ("worker", 3))
        started: list[str] = []

        def fake_start(cfg: Config, name: str, command: str, **kwargs: object) -> MagicMock:
            started.append(name)
            rec = MagicMock()
            rec.pid = 1234
            rec.name = name
            return rec

        def fake_wait(cfg: Config, name: str, **kwargs: object) -> None:
            pass

        with (
            patch("vigil.vigilfile._start", side_effect=fake_start),
            patch("vigil.vigilfile._wait", side_effect=fake_wait),
        ):
            results = up(config, entries, only=["db", "worker"])

        assert started == ["db", "worker"]
        assert len(results) == 2

    def test_up_force_restarts_running(self, config: Config) -> None:
        """--force passes force=True to start so running processes restart."""
        entries = _make_entries(("web", 1))
        force_received: list[bool] = []

        def fake_start(cfg: Config, name: str, command: str, **kwargs: object) -> MagicMock:
            force_received.append(bool(kwargs.get("force")))
            rec = MagicMock()
            rec.pid = 1234
            rec.name = name
            return rec

        def fake_wait(cfg: Config, name: str, **kwargs: object) -> None:
            pass

        with (
            patch("vigil.vigilfile._start", side_effect=fake_start),
            patch("vigil.vigilfile._wait", side_effect=fake_wait),
        ):
            up(config, entries, force=True)

        assert force_received == [True]


# ---------------------------------------------------------------------------
# down() orchestration
# ---------------------------------------------------------------------------


class TestDown:
    def test_down_stops_in_reverse_order(self, config: Config) -> None:
        """down() stops processes in reverse startup order."""
        entries = _make_entries(("db", 1), ("api", 2), ("worker", 3))
        stopped: list[str] = []

        def fake_stop(cfg: Config, name: str) -> None:
            stopped.append(name)

        with patch("vigil.vigilfile._stop", side_effect=fake_stop):
            results = down(config, entries)

        assert stopped == ["worker", "api", "db"]
        assert [r["name"] for r in results] == ["worker", "api", "db"]
        assert all(r["status"] == "stopped" for r in results)

    def test_down_only_filter(self, config: Config) -> None:
        """--only stops just the named subset, still in reverse order."""
        entries = _make_entries(("db", 1), ("api", 2), ("worker", 3))
        stopped: list[str] = []

        def fake_stop(cfg: Config, name: str) -> None:
            stopped.append(name)

        with patch("vigil.vigilfile._stop", side_effect=fake_stop):
            results = down(config, entries, only=["db", "api"])

        assert stopped == ["api", "db"]
        assert len(results) == 2

    def test_down_not_found_recorded(self, config: Config) -> None:
        """If a process is not managed, down() records not_running."""
        from vigil.manager import ProcessNotFound

        entries = _make_entries(("web", 1))

        def fake_stop(cfg: Config, name: str) -> None:
            raise ProcessNotFound("not found")

        with patch("vigil.vigilfile._stop", side_effect=fake_stop):
            results = down(config, entries)

        assert results[0]["status"] == "not_running"
