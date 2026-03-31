"""Shared helpers used across multiple CLI commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from click.shell_completion import CompletionItem

from vigil.config import Config, ConfigError, find_vigil_root
from vigil.state import StateManager


def json_error(message: str, code: int = 1) -> None:
    """Emit a JSON error to stdout and exit. Used when --json is active."""
    click.echo(json.dumps({"error": message, "code": code}))
    sys.exit(code)


def require_project(as_json: bool = False) -> Path:
    """Return project root or exit with a clear error message."""
    try:
        return find_vigil_root(Path.cwd())
    except ConfigError as e:
        if as_json:
            json_error(str(e))
        click.echo(str(e))
        sys.exit(1)


def complete_process_names(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    """Shell completion callback: return process names from the statefile."""
    try:
        root = find_vigil_root(Path.cwd())
        config = Config(root=root)
        records = StateManager(config).read_all()
        return [CompletionItem(r.name) for r in records if r.name.startswith(incomplete)]
    except ConfigError:
        return []
