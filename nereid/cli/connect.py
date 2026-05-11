"""
nereid connect — configure cloud provider credentials.

Reads credentials from environment variables — no JSON key file needed
in the project directory.

Usage:
  nereid connect google-drive
"""

import json
import re
import os
from pathlib import Path

import click
from rich.console import Console
from dotenv import load_dotenv

load_dotenv()

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
    if "google.com" in value:
        match = re.search(r"/d/([a-zA-Z0-9_-]+)", value)
        if match:
            return match.group(1)
    return value.split("?")[0].split("#")[0].strip()


def _extract_folder_id(value: str) -> str:
    if "google.com" in value:
        match = re.search(r"/folders/([a-zA-Z0-9_-]+)", value)
        if match:
            return match.group(1)
    return value.split("?")[0].split("#")[0].strip()


@click.group()
def connect():
    """Configure a cloud storage provider for direct API sync."""
    pass


@connect.command("google-drive")
@click.option("--file-id", "-f", default=None, help="Google Drive file ID or URL. Defaults to NEREID_GDRIVE_FILE_ID.")
@click.option("--folder-id", "-d", default=None, help="Google Drive folder ID or URL. Defaults to NEREID_GDRIVE_FOLDER_ID.")
@click.option("--db-url", default=None, help="PostgreSQL connection string. Defaults to NEREID_DB_URL.")
@click.option("--poll-interval", default=None, type=float, help="Poll interval in seconds. Defaults to NEREID_POLL_INTERVAL or 60.")
def google_drive(file_id, folder_id, db_url, poll_interval):
    """
    Connect Nereid to a Google Drive file using a service account.

    \b
    Set these in your .env before running:
      NEREID_GDRIVE_CLIENT_EMAIL   — from your service account JSON
      NEREID_GDRIVE_PRIVATE_KEY    — from your service account JSON
      NEREID_GDRIVE_PROJECT_ID     — from your service account JSON
      NEREID_GDRIVE_FILE_ID        — Google Drive file ID or URL
      NEREID_GDRIVE_FOLDER_ID      — Google Drive folder ID or URL
      NEREID_DB_URL                — PostgreSQL connection string
      NEREID_POLL_INTERVAL         — seconds between checks (default 60)
    """
    console.print("[bold green]Nereid Connect[/bold green] — Google Drive\n")

    # ── Resolve values ─────────────────────────────────────────────────────
    file_id       = file_id or os.getenv("NEREID_GDRIVE_FILE_ID")
    folder_id     = folder_id or os.getenv("NEREID_GDRIVE_FOLDER_ID")
    db_url        = db_url or os.getenv("NEREID_DB_URL")
    poll_interval = poll_interval or float(os.getenv("NEREID_POLL_INTERVAL", "60"))

    client_email = os.getenv("NEREID_GDRIVE_CLIENT_EMAIL")
    private_key  = os.getenv("NEREID_GDRIVE_PRIVATE_KEY")
    project_id   = os.getenv("NEREID_GDRIVE_PROJECT_ID")

    # ── Validate required fields ───────────────────────────────────────────
    missing = []
    if not client_email: missing.append("NEREID_GDRIVE_CLIENT_EMAIL")
    if not private_key:  missing.append("NEREID_GDRIVE_PRIVATE_KEY")
    if not project_id:   missing.append("NEREID_GDRIVE_PROJECT_ID")
    if not file_id:      missing.append("NEREID_GDRIVE_FILE_ID")
    if not folder_id:    missing.append("NEREID_GDRIVE_FOLDER_ID")
    if not db_url:       missing.append("NEREID_DB_URL")

    if missing:
        console.print("[red]✗ Missing required environment variables:[/red]")
        for m in missing:
            console.print(f"  [yellow]{m}[/yellow]")
        console.print("\nAdd these to your [cyan].env[/cyan] file and re-run.")
        raise SystemExit(1)

    file_id   = _extract_file_id(file_id)
    folder_id = _extract_folder_id(folder_id)

    console.print(f"[dim]Service account: {client_email}[/dim]")

    # ── Validate connection ────────────────────────────────────────────────
    console.print("\n[dim]Validating credentials and file access...[/dim]")
    try:
        from nereid.providers.google_drive import GoogleDriveProvider

        provider = GoogleDriveProvider(file_id=file_id)
        provider.validate_credentials()
        file_name = provider.get_file_name()
        mime = provider.get_file_mime()

    except RuntimeError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise SystemExit(1)
    except Exception as e:
        console.print(f"[red]✗ Could not access file: {e}[/red]")
        console.print(f"  Make sure the file is shared with: [cyan]{client_email}[/cyan]")
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
        "file_id": file_id,
        "folder_id": folder_id,
        "file_name": file_name,
        "mode": mode,
        "db_url": db_url,
        "poll_interval": poll_interval,
        "staging_schema": os.getenv("NEREID_STAGING_SCHEMA", "nereid_staging"),
        "pk_column": os.getenv("NEREID_PK_COLUMN", "id"),
    }
    _save_credentials(stored)

    console.print(f"\n[green]✓ Config saved to[/green] [cyan]{_CREDENTIALS_FILE}[/cyan]")
    console.print("[dim]  (added to .gitignore automatically)[/dim]\n")
    console.print("Next — start syncing:")
    console.print("  [cyan]nereid watch-cloud google-drive[/cyan]")