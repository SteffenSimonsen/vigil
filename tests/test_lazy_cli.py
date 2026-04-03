"""Tests for lazy command registration in cli.py (issue #48)."""

from __future__ import annotations

import sys

import click

from vigil.cli import LazyGroup, main


class TestLazyLoading:
    def test_importing_cli_does_not_import_command_modules(self) -> None:
        """Importing vigil.cli must not eagerly import any command module."""
        # By the time this test runs, cli is already imported, but we can
        # verify that each command module was NOT imported at import time by
        # removing them from sys.modules and checking they're absent at rest.
        command_modules = [
            "vigil.commands.down",
            "vigil.commands.health",
            "vigil.commands.status",
            "vigil.commands.up",
            "vigil.commands.scan",
        ]
        # Unload to get a clean baseline
        for mod in command_modules:
            sys.modules.pop(mod, None)

        # Re-import cli (should be a no-op since it's cached, but this
        # verifies that importing cli itself doesn't pull in command modules)
        import importlib

        import vigil.cli

        importlib.reload(vigil.cli)

        for mod in command_modules:
            assert mod not in sys.modules, f"{mod} was eagerly imported when vigil.cli was loaded"

    def test_get_command_loads_correct_module(self) -> None:
        """get_command() for 'status' returns the cmd_status Click command."""
        # Remove module to ensure fresh import
        sys.modules.pop("vigil.commands.status", None)

        ctx = click.Context(main)
        cmd = main.get_command(ctx, "status")
        assert cmd is not None
        assert cmd.name == "status"
        assert "vigil.commands.status" in sys.modules

    def test_get_command_returns_none_for_unknown(self) -> None:
        ctx = click.Context(main)
        assert main.get_command(ctx, "nonexistent") is None


class TestLazyGroupListCommands:
    def test_list_commands_returns_all_expected_names(self) -> None:
        ctx = click.Context(main)
        names = main.list_commands(ctx)
        expected = sorted(
            [
                "init",
                "start",
                "stop",
                "restart",
                "remove",
                "logs",
                "wait",
                "status",
                "scan",
                "health",
                "free",
                "open",
                "next",
                "up",
                "down",
                "orphans",
            ]
        )
        assert names == expected

    def test_list_commands_returns_sorted(self) -> None:
        ctx = click.Context(main)
        names = main.list_commands(ctx)
        assert names == sorted(names)

    def test_main_is_lazy_group(self) -> None:
        assert isinstance(main, LazyGroup)
