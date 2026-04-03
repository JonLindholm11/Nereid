"""
Nereid logging — consistent rich-based logging across the app.
"""

from rich.console import Console
from rich.theme import Theme

_theme = Theme({
    "info": "cyan",
    "success": "bold green",
    "warning": "bold yellow",
    "error": "bold red",
    "dim": "dim white",
})

console = Console(theme=_theme)


def info(msg: str):
    console.print(f"[info]ℹ[/info]  {msg}")


def success(msg: str):
    console.print(f"[success]✓[/success]  {msg}")


def warning(msg: str):
    console.print(f"[warning]⚠[/warning]  {msg}")


def error(msg: str):
    console.print(f"[error]✗[/error]  {msg}")


def dim(msg: str):
    console.print(f"[dim]{msg}[/dim]")