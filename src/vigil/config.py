"""Configuration loading and defaults."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    """Raised when vigil cannot locate an initialized project."""


@dataclass
class Config:
    """Vigil configuration with sensible defaults."""

    root: Path
    log_retention_lines: int = 500
    port_range: tuple[int, int] = field(default_factory=lambda: (3000, 9999))
    health_check_timeout: int = 5
    stop_grace_period: int = 5

    @property
    def vigil_dir(self) -> Path:
        return self.root / ".vigil"

    @property
    def state_file(self) -> Path:
        return self.vigil_dir / "state.json"

    @property
    def logs_dir(self) -> Path:
        return self.vigil_dir / "logs"


def find_vigil_root(start: Path) -> Path:
    """Walk up the directory tree to find the directory containing `.vigil/`."""
    current = start.resolve()
    while True:
        if (current / ".vigil").is_dir():
            return current
        parent = current.parent
        if parent == current:
            raise ConfigError(
                "No .vigil/ directory found. Run 'vigil init' to initialize a project."
            )
        current = parent


def load_config(root: Path | None = None) -> Config:
    """Load config from vigil.toml if present, otherwise use defaults."""
    if root is None:
        root = find_vigil_root(Path.cwd())

    config = Config(root=root)

    toml_path = root / "vigil.toml"
    if toml_path.exists():
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        defaults = data.get("defaults", {})
        if "log_retention_lines" in defaults:
            config.log_retention_lines = int(defaults["log_retention_lines"])
        if "port_range" in defaults:
            r = defaults["port_range"]
            config.port_range = (int(r[0]), int(r[1]))
        if "health_check_timeout" in defaults:
            config.health_check_timeout = int(defaults["health_check_timeout"])
        if "stop_grace_period" in defaults:
            config.stop_grace_period = int(defaults["stop_grace_period"])

    return config
