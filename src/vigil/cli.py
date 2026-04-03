"""Vigil CLI entry point."""

from __future__ import annotations

import importlib
from typing import Any

import click


class LazyGroup(click.Group):
    """A Click group that defers importing command modules until dispatch."""

    def __init__(
        self,
        *args: Any,  # noqa: ANN401 — pass-through to click.Group.__init__ which uses Any
        lazy_subcommands: dict[str, str],
        **kwargs: Any,  # noqa: ANN401 — pass-through to click.Group.__init__ which uses Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self._lazy = lazy_subcommands  # {"status": "vigil.commands.status.cmd_status"}

    def list_commands(self, ctx: click.Context) -> list[str]:
        return sorted(self._lazy)

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        if cmd_name not in self._lazy:
            return None
        module_path, attr = self._lazy[cmd_name].rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, attr)  # type: ignore[no-any-return]


@click.command(
    cls=LazyGroup,
    lazy_subcommands={
        "init": "vigil.commands.init.cmd_init",
        "start": "vigil.commands.start.cmd_start",
        "stop": "vigil.commands.stop.cmd_stop",
        "restart": "vigil.commands.restart.cmd_restart",
        "remove": "vigil.commands.remove.cmd_remove",
        "logs": "vigil.commands.logs.cmd_logs",
        "wait": "vigil.commands.wait.cmd_wait",
        "status": "vigil.commands.status.cmd_status",
        "scan": "vigil.commands.scan.cmd_scan",
        "health": "vigil.commands.health.cmd_health",
        "free": "vigil.commands.free.cmd_free",
        "open": "vigil.commands.open.cmd_open",
        "next": "vigil.commands.next.cmd_next",
        "up": "vigil.commands.up.cmd_up",
        "down": "vigil.commands.down.cmd_down",
        "orphans": "vigil.commands.orphans.cmd_orphans",
    },
)
def main() -> None:
    """Vigil — local dev process manager."""
