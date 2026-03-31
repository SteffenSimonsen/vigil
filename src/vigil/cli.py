"""Vigil CLI entry point."""

from __future__ import annotations

import click

from vigil.commands.down import cmd_down
from vigil.commands.free import cmd_free
from vigil.commands.health import cmd_health
from vigil.commands.init import cmd_init
from vigil.commands.logs import cmd_logs
from vigil.commands.next import cmd_next
from vigil.commands.open import cmd_open
from vigil.commands.remove import cmd_remove
from vigil.commands.restart import cmd_restart
from vigil.commands.scan import cmd_scan
from vigil.commands.start import cmd_start
from vigil.commands.status import cmd_status
from vigil.commands.stop import cmd_stop
from vigil.commands.up import cmd_up
from vigil.commands.wait import cmd_wait


@click.group()
def main() -> None:
    """Vigil — local dev process manager."""


main.add_command(cmd_init)
main.add_command(cmd_start)
main.add_command(cmd_stop)
main.add_command(cmd_restart)
main.add_command(cmd_remove)
main.add_command(cmd_logs)
main.add_command(cmd_wait)
main.add_command(cmd_status)
main.add_command(cmd_scan)
main.add_command(cmd_health)
main.add_command(cmd_free)
main.add_command(cmd_open)
main.add_command(cmd_next)
main.add_command(cmd_up)
main.add_command(cmd_down)
