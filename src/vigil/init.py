"""Project initialization (interactive and flag-driven)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ProcessDef:
    """A process definition from vigil init."""

    name: str
    command: str
    port: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "command": self.command, "port": self.port}


def parse_process_spec(spec: str) -> ProcessDef:
    """Parse a process spec string: ``name,command`` or ``name,command,port``."""
    parts = spec.split(",", 2)
    name = parts[0].strip()
    command = parts[1].strip() if len(parts) > 1 else ""
    port: int | None = None
    if len(parts) > 2 and parts[2].strip():
        port = int(parts[2].strip())
    return ProcessDef(name=name, command=command, port=port)


def _write_vigilfile(root: Path, processes: list[ProcessDef]) -> None:
    lines: list[str] = []
    for proc in processes:
        lines.append("[[process]]")
        lines.append(f'name = "{proc.name}"')
        lines.append(f'command = "{proc.command}"')
        if proc.port is not None:
            lines.append(f"port = {proc.port}")
        lines.append("")
    (root / "Vigilfile").write_text("\n".join(lines))


def _write_gitignore(vigil_dir: Path) -> None:
    (vigil_dir / ".gitignore").write_text("state.json\nlogs/\n")


def init_project(root: Path, processes: list[ProcessDef]) -> None:
    """Create the `.vigil/` directory, `.gitignore`, and `Vigilfile`."""
    vigil_dir = root / ".vigil"
    vigil_dir.mkdir(parents=True, exist_ok=True)
    _write_gitignore(vigil_dir)
    _write_vigilfile(root, processes)


def prompt_for_processes() -> list[ProcessDef]:
    """Interactive TUI: prompt user for process definitions."""
    processes: list[ProcessDef] = []
    print("Define your processes (leave name blank to finish):")
    while True:
        name = input("  Process name: ").strip()
        if not name:
            break
        command = input("  Command: ").strip()
        port_str = input("  Port (optional): ").strip()
        port = int(port_str) if port_str else None
        processes.append(ProcessDef(name=name, command=command, port=port))
    return processes
