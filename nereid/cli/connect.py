"""
nereid connect — configure cloud provider credentials.

Stores provider configuration in .nereid-credentials.json (project-local,
auto-added to .gitignore) so that nereid watch-cloud can run without
repeating these flags every time.

Usage:
  nereid connect google-drive
  nereid connect google-drive --credentials /path/to/sa-key.json --file-id FILE_ID
"""

import json
import re
from pathlib import Path

import click
from rich.console import Console

console = Console()

_CREDENTIALS_FILE = ".nereid-credentials.json"


def _load_credentials() -> dict:
    p = Path(_CREDENTIALS_FILE)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_credentials(data: dict) -> None:
    Path(_CREDENTIALS_FILE).write_text(json.dumps(data, indent=2))
    _ensure_gitignored()


def _ensure_gitignored() -> None:
    """
    Add .nereid-credentials.json to the local .gitignore if it is not
    already listed there.  Creates .gitignore if it doesn't exist.
    """
    gitignore = Path(".gitignore")
    entry = _CREDENTIALS_FILE

    if gitignore.exists():
        content = gitignore.read_text()
        if entry in content:
            return
        gitignore.write_text(content.rstrip() + f"\n\n# Nereid cloud credentials\n{entry}\n")
    else:
        gitignore.write_text(f"# Nereid cloud credentials\n{entry}\n")


def _extract_file_id(value: str) -> str:
    """
    Accept either a raw file ID or any Google Drive / Docs URL and return
    just the file ID portion.

    Handles URLs like:
      https://drive.google.com/file/d/FILE_ID/view
      https://docs.google.com/spreadsheets/d/FILE_ID/edit
    """
    if "google.com" in value:
        match = re.search(r"/d/([a-zA-Z0-9_-]+)", value)
        if match:
            return match.group(1)
    return value.strip()


# ── CLI group ──────────────────────────────────────────────────────────────────

@click.group()
def connect():
    """Configure a cloud storage provider for direct API sync."""
    pass


# ── google-drive subcommand ────────────────────────────────────────────────────

@connect.command("google-drive")
@click.option(
    "--credentials", "-c",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to service account JSON key file.",
)
@click.option(
    "--file-id", "-f",
    default=None,
    help="Google Drive file ID or URL of the XLSX/Google Sheet to sync.",
)
def google_drive(credentials, file_id):
    """
    Connect Nereid to a Google Drive file using a service account.

    \b
    One-time setup:
      1. Create a Google Cloud project and enable the Drive API
      2. Create a service account and download its JSON key
      3. Share your XLSX or Google Sheet with the service account email
      4. Run this command

    \b
    Example:
      nereid connect google-drive \\
        --credentials /path/to/service-account.json \\
        --file-id 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms
    """
    console.print("[bold green]Nereid Connect[/bold green] — Google Drive\n")

    # ── Credentials file ───────────────────────────────────────────────────
    if not credentials:
        credentials = click.prompt(
            "Path to service account JSON key file",
            type=click.Path(exists=True, dir_okay=False),
        )

    cred_path = Path(credentials).resolve()

    try:
        key_data = json.loads(cred_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        console.print(f"[red]✗ Could not read credentials file: {e}[/red]")
        raise SystemExit(1)

    if key_data.get("type") != "service_account":
        console.print("[red]✗ File does not look like a service account key.[/red]")
        console.print("  Download a service account JSON key from Google Cloud Console.")
        raise SystemExit(1)

    sa_email = key_data.get("client_email", "unknown")
    console.print(f"[dim]Service account: {sa_email}[/dim]")

    # ── File ID ────────────────────────────────────────────────────────────
    if not file_id:
        file_id = click.prompt("Google Drive file ID or URL")

    file_id = _extract_file_id(file_id)

    # ── Validate connection ────────────────────────────────────────────────
    console.print("\n[dim]Validating credentials and file access...[/dim]")
    try:
        from nereid.providers.google_drive import GoogleDriveProvider

        provider = GoogleDriveProvider(
            credentials_file=str(cred_path),
            file_id=file_id,
        )
        provider.validate_credentials()
        file_name = provider.get_file_name()
        mime = provider.get_file_mime()

    except RuntimeError as e:
        # Missing optional dependencies
        console.print(f"[red]✗ {e}[/red]")
        raise SystemExit(1)
    except Exception as e:
        console.print(f"[red]✗ Could not access file: {e}[/red]")
        console.print(f"  Make sure the file is shared with: [cyan]{sa_email}[/cyan]")
        raise SystemExit(1)

    # ── Determine sync mode ────────────────────────────────────────────────
    is_csv = mime == "text/csv"
    mode = "multi" if is_csv else "single"

    type_label = {
        "application/vnd.google-apps.spreadsheet": "Google Sheet (exported as XLSX)",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
        "text/csv": "CSV",
    }.get(mime, mime)

    console.print(f"\n[green]✓ Connected:[/green] {file_name}")
    console.print(f"  Type: {type_label}")
    console.print(f"  Sync mode: {mode}")

    # ── Persist config ─────────────────────────────────────────────────────
    stored = _load_credentials()
    stored["google_drive"] = {
        "credentials_file": str(cred_path),
        "file_id": file_id,
        "file_name": file_name,
        "mode": mode,
    }
    _save_credentials(stored)

    console.print(f"\n[green]✓ Config saved to[/green] [cyan]{_CREDENTIALS_FILE}[/cyan]")
    console.print("[dim]  (added to .gitignore automatically)[/dim]\n")
    console.print("Next — start syncing:")
    console.print(
        "  [cyan]nereid watch-cloud google-drive --db-url postgresql://...[/cyan]"
    )
