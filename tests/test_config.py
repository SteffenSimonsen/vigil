"""Tests for config module."""

from pathlib import Path

import pytest

from vigil.config import Config, ConfigError, find_vigil_root, load_config


class TestConfigDefaults:
    def test_config_has_default_log_retention(self) -> None:
        config = Config(root=Path("/tmp/fake"))
        assert config.log_retention_lines == 500

    def test_config_has_default_scan_port_range(self) -> None:
        config = Config(root=Path("/tmp/fake"))
        assert config.scan_port_range == (3000, 9999)

    def test_config_has_default_health_check_timeout(self) -> None:
        config = Config(root=Path("/tmp/fake"))
        assert config.health_check_timeout == 5

    def test_config_has_default_stop_grace_period(self) -> None:
        config = Config(root=Path("/tmp/fake"))
        assert config.stop_grace_period == 5


class TestFindVigilRoot:
    def test_finds_vigil_dir_in_current_directory(self, tmp_path: Path) -> None:
        vigil_dir = tmp_path / ".vigil"
        vigil_dir.mkdir()
        found = find_vigil_root(tmp_path)
        assert found == tmp_path

    def test_finds_vigil_dir_in_parent_directory(self, tmp_path: Path) -> None:
        vigil_dir = tmp_path / ".vigil"
        vigil_dir.mkdir()
        subdir = tmp_path / "subdir" / "nested"
        subdir.mkdir(parents=True)
        found = find_vigil_root(subdir)
        assert found == tmp_path

    def test_raises_config_error_when_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="No .vigil"):
            find_vigil_root(tmp_path)


class TestLoadConfig:
    def test_load_config_without_toml_uses_defaults(self, tmp_path: Path) -> None:
        (tmp_path / ".vigil").mkdir()
        config = load_config(tmp_path)
        assert config.log_retention_lines == 500
        assert config.root == tmp_path

    def test_load_config_from_vigil_toml(self, tmp_path: Path) -> None:
        (tmp_path / ".vigil").mkdir()
        (tmp_path / "vigil.toml").write_text("[defaults]\nlog_retention_lines = 200\n")
        config = load_config(tmp_path)
        assert config.log_retention_lines == 200

    def test_load_config_partial_toml_keeps_other_defaults(self, tmp_path: Path) -> None:
        (tmp_path / ".vigil").mkdir()
        (tmp_path / "vigil.toml").write_text("[defaults]\nstop_grace_period = 10\n")
        config = load_config(tmp_path)
        assert config.stop_grace_period == 10
        assert config.log_retention_lines == 500  # default unchanged
