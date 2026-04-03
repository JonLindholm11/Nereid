"""
Nereid CLI — main entry point.
Commands: export, watch, review.
"""

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


if __name__ == "__main__":
    cli()