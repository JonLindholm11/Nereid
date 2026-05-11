"""
Nereid CLI — main entry point.
Commands: export, watch, review, connect, watch-cloud.
"""

import json
from pathlib import Path

import click
from rich.console import Console
from dotenv import load_dotenv

load_dotenv()

console = Console()


@click.group()
@click.version_option(package_name="nereid")
def cli():
    """
    Nereid — CSV/XLSX ↔ PostgreSQL two-way sync engine.

    A Lunar Systems open source tool.
    """
    pass


# ── Cloud provider commands ────────────────────────────────────────────────────
from nereid.cli.connect import connect  # noqa: E402
cli.add_command(connect)


@cli.command()
@click.option("--mode", type=click.Choice(["single", "multi"]), envvar="NEREID_MODE", default="single", show_default=True)
@click.option("--output", "-o", envvar="NEREID_FILE_PATH", required=True, help="Output path — XLSX file (single) or folder (multi).")
@click.option("--db-url", envvar="NEREID_DB_URL", required=True, help="PostgreSQL connection string.")
@click.option("--tables", "-t", multiple=True, help="Tables to export. Exports all if not specified.")
def export(mode, output, db_url, tables):
    """Export data from PostgreSQL to a spreadsheet or CSV folder."""
    from nereid.core.exporter import run_export

    console.print(f"[bold green]Nereid Export[/bold green] — mode: [cyan]{mode}[/cyan]")
    console.print(f"Output: [cyan]{output}[/cyan]")

    try:
        run_export(mode=mode, output_path=output, db_url=db_url, tables=list(tables) if tables else None)
        console.print("[bold green]✓ Export complete.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]✗ Export failed:[/bold red] {e}")
        raise SystemExit(1)


@cli.command()
@click.option("--mode", type=click.Choice(["single", "multi"]), envvar="NEREID_MODE", default="single", show_default=True)
@click.option("--path", "-p", envvar="NEREID_FILE_PATH", required=True, help="Path to watch — XLSX file (single) or folder (multi).")
@click.option("--db-url", envvar="NEREID_DB_URL", required=True, help="PostgreSQL connection string.")
@click.option("--pk", envvar="NEREID_PK_COLUMN", default="id", show_default=True, help="Primary key column name.")
@click.option("--staging-schema", envvar="NEREID_STAGING_SCHEMA", default="nereid_staging", show_default=True)
@click.option("--debounce", envvar="NEREID_DEBOUNCE_SECONDS", default=2.0, show_default=True, type=float, help="Seconds to wait after a file change before syncing.")
def watch(mode, path, db_url, pk, staging_schema, debounce):
    """Watch a file or folder for changes and sync to PostgreSQL staging."""
    from nereid.core.watcher import run_watch

    console.print(f"[bold green]Nereid Watch[/bold green] — mode: [cyan]{mode}[/cyan]")
    console.print(f"Watching: [cyan]{path}[/cyan]")
    console.print(f"Staging schema: [cyan]{staging_schema}[/cyan]")
    console.print(f"Debounce: [cyan]{debounce}s[/cyan]")
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    try:
        run_watch(mode=mode, watch_path=path, db_url=db_url, pk_column=pk, staging_schema=staging_schema, debounce_seconds=debounce)
    except KeyboardInterrupt:
        console.print("\n[yellow]Nereid watch stopped.[/yellow]")


@cli.command()
@click.option("--db-url", envvar="NEREID_DB_URL", required=True, help="PostgreSQL connection string.")
@click.option("--staging-schema", envvar="NEREID_STAGING_SCHEMA", default="nereid_staging", show_default=True)
@click.option("--approve-all", is_flag=True, default=False, help="Promote all staged changes to production.")
@click.option("--approve-table", default=None, metavar="TABLE", help="Promote a specific table only.")
@click.option("--reject-all", is_flag=True, default=False, help="Discard all staged changes.")
@click.option("--reject-table", default=None, metavar="TABLE", help="Discard a specific table only.")
@click.option("--interactive", "-i", is_flag=True, default=False, help="Review and decide table by table.")
def review(db_url, staging_schema, approve_all, approve_table, reject_all, reject_table, interactive):
    """
    Review pending changes in the staging schema.

    \b
    Examples:
      nereid review                          # show what's staged
      nereid review --approve-all            # promote everything
      nereid review --approve-table orders   # promote orders only
      nereid review --reject-table customers # discard customers changes
      nereid review --interactive            # decide table by table
    """
    from nereid.core.reviewer import run_review

    console.print(f"[bold green]Nereid Review[/bold green] — staging: [cyan]{staging_schema}[/cyan]")

    try:
        run_review(
            db_url=db_url,
            staging_schema=staging_schema,
            approve_all=approve_all,
            approve_table=approve_table,
            reject_all=reject_all,
            reject_table=reject_table,
            interactive=interactive,
        )
    except Exception as e:
        console.print(f"[bold red]✗ Review failed:[/bold red] {e}")
        raise SystemExit(1)


@cli.group("watch-cloud")
def watch_cloud():
    """Poll a cloud-hosted file for changes and sync to PostgreSQL staging."""
    pass


@watch_cloud.command("google-drive")
@click.option("--db-url", envvar="NEREID_DB_URL", required=True, help="PostgreSQL connection string.")
@click.option("--pk", envvar="NEREID_PK_COLUMN", default="id", show_default=True, help="Primary key column name.")
@click.option("--staging-schema", envvar="NEREID_STAGING_SCHEMA", default="nereid_staging", show_default=True)
@click.option(
    "--poll-interval",
    envvar="NEREID_POLL_INTERVAL",
    default=60.0,
    show_default=True,
    type=float,
    help="Seconds between Drive polls.",
)
@click.option(
    "--file-id", "-f",
    default=None,
    envvar="NEREID_GDRIVE_FILE_ID",
    help="Google Drive file ID (overrides stored config).",
)
def watch_cloud_gdrive(db_url, pk, staging_schema, poll_interval, file_id):
    """
    Poll a Google Drive file for changes and sync to PostgreSQL staging.

    \b
    Reads connection config from .nereid-credentials.json (written by
    nereid connect google-drive). Any option here overrides the stored value.

    \b
    Example:
      nereid watch-cloud google-drive
    """
    from nereid.providers.google_drive import GoogleDriveProvider
    from nereid.core.cloud_watcher import run_cloud_watch

    # Load stored config; CLI flags take precedence
    stored_config: dict = {}
    creds_file = Path(".nereid-credentials.json")
    if creds_file.exists():
        try:
            stored_config = json.loads(creds_file.read_text()).get("google_drive", {})
        except (json.JSONDecodeError, KeyError):
            pass

    resolved_file_id = file_id or stored_config.get("file_id")
    mode = stored_config.get("mode", "single")
    file_name = stored_config.get("file_name", "nereid_drive_file")
    fallback_table_name = Path(file_name).stem

    if not resolved_file_id:
        console.print("[red]✗ Google Drive file ID not configured.[/red]")
        console.print("  Run: [cyan]nereid connect google-drive[/cyan]")
        raise SystemExit(1)

    console.print("[bold green]Nereid Cloud Watch[/bold green] — Google Drive")
    console.print(f"File:           [cyan]{file_name}[/cyan]")
    console.print(f"Staging schema: [cyan]{staging_schema}[/cyan]")
    console.print(f"Poll interval:  [cyan]{poll_interval}s[/cyan]")
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    try:
        provider = GoogleDriveProvider(file_id=resolved_file_id)
        run_cloud_watch(
            provider=provider,
            mode=mode,
            fallback_table_name=fallback_table_name,
            db_url=db_url,
            pk_column=pk,
            staging_schema=staging_schema,
            poll_interval=poll_interval,
        )
    except RuntimeError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise SystemExit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Nereid cloud watch stopped.[/yellow]")


if __name__ == "__main__":
    cli()