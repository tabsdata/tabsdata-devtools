#
# Copyright 2026 Tabsdata Inc.
#

"""Consistent terminal reporting for every tool."""

from __future__ import annotations

from rich.console import Console


class Report:
    """Uniform [ok]/[fail] output so every tool reads the same."""

    def __init__(self, title: str | None = None):
        self._console = Console()
        self.failures = 0
        if title:
            self._console.print(f"[bold]{title}[/bold]")

    def ok(self, message: str) -> None:
        self._console.print(f"  [green][ok][/green]      {message}")

    def fail(self, message: str) -> None:
        self.failures += 1
        self._console.print(f"  [red][fail][/red]    {message}")

    def note(self, message: str) -> None:
        self._console.print(f"  [dim]{message}[/dim]")

    @property
    def exit_code(self) -> int:
        return 1 if self.failures else 0
