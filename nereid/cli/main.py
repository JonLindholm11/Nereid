"""
Nereid CLI — main entry point.
Two commands: export and watch.
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
@click.option(
    "--mode",
    type=click.Choice(["single", "multi"]),
    envvar="NEREID_MODE",
    default="single",
    show_default=True,
    help="Sync mode: single XLSX file or folder of CSVs.",
)
@click.option(
    "--output",
    "-o",
    envvar="NEREID_FILE_PATH",
    required=True,
    help="Output path — XLSX file (single) or folder (multi).",
)
@click.option(
    "--db-url",
    envvar="NEREID_DB_URL",
    required=True,
    help="PostgreSQL connection string.",
)
@click.option(
    "--tables",
    "-t",
    multiple=True,
    help="Tables to export. Exports all tables if not specified.",
)
def export(mode, output, db_url, tables):
    """
    Export data from PostgreSQL to a spreadsheet or CSV folder.

    In single mode, each table becomes a tab in one XLSX file.
    In multi mode, each table becomes its own CSV file in a folder.
    """
    from nereid.core.exporter import run_export

    console.print(f"[bold green]Nereid Export[/bold green] — mode: [cyan]{mode}[/cyan]")
    console.print(f"Output: [cyan]{output}[/cyan]")

    try:
        run_export(
            mode=mode,
            output_path=output,
            db_url=db_url,
            tables=list(tables) if tables else None,
        )
        console.print("[bold green]✓ Export complete.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]✗ Export failed:[/bold red] {e}")
        raise SystemExit(1)


@cli.command()
@click.option(
    "--mode",
    type=click.Choice(["single", "multi"]),
    envvar="NEREID_MODE",
    default="single",
    show_default=True,
    help="Sync mode: single XLSX file or folder of CSVs.",
)
@click.option(
    "--path",
    "-p",
    envvar="NEREID_FILE_PATH",
    required=True,
    help="Path to watch — XLSX file (single) or folder (multi).",
)
@click.option(
    "--db-url",
    envvar="NEREID_DB_URL",
    required=True,
    help="PostgreSQL connection string.",
)
@click.option(
    "--pk",
    envvar="NEREID_PK_COLUMN",
    default="id",
    show_default=True,
    help="Primary key column name used for diffing.",
)
@click.option(
    "--staging-schema",
    envvar="NEREID_STAGING_SCHEMA",
    default="nereid_staging",
    show_default=True,
    help="Staging schema name within the same PostgreSQL database.",
)
@click.option(
    "--debounce",
    envvar="NEREID_DEBOUNCE_SECONDS",
    default=2.0,
    show_default=True,
    type=float,
    help="Seconds to wait after a file change before syncing.",
)
def watch(mode, path, db_url, pk, staging_schema, debounce):
    """
    Watch a file or folder for changes and sync to PostgreSQL staging.

    Changes are written to the staging schema first.
    Use `nereid review` to inspect and promote changes to production.
    """
    from nereid.core.watcher import run_watch

    console.print(f"[bold green]Nereid Watch[/bold green] — mode: [cyan]{mode}[/cyan]")
    console.print(f"Watching: [cyan]{path}[/cyan]")
    console.print(f"Staging schema: [cyan]{staging_schema}[/cyan]")
    console.print(f"Debounce: [cyan]{debounce}s[/cyan]")
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    try:
        run_watch(
            mode=mode,
            watch_path=path,
            db_url=db_url,
            pk_column=pk,
            staging_schema=staging_schema,
            debounce_seconds=debounce,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Nereid watch stopped.[/yellow]")


@cli.command()
@click.option(
    "--db-url",
    envvar="NEREID_DB_URL",
    required=True,
    help="PostgreSQL connection string.",
)
@click.option(
    "--staging-schema",
    envvar="NEREID_STAGING_SCHEMA",
    default="nereid_staging",
    show_default=True,
    help="Staging schema to review.",
)
@click.option(
    "--approve",
    is_flag=True,
    default=False,
    help="Promote all staged changes to production.",
)
@click.option(
    "--reject",
    is_flag=True,
    default=False,
    help="Clear all staged changes without applying them.",
)
def review(db_url, staging_schema, approve, reject):
    """
    Review pending changes in the staging schema.

    Shows a diff of what will change in production.
    Use --approve to promote changes, --reject to discard them.
    """
    from nereid.core.reviewer import run_review

    console.print(f"[bold green]Nereid Review[/bold green] — staging: [cyan]{staging_schema}[/cyan]")

    try:
        run_review(
            db_url=db_url,
            staging_schema=staging_schema,
            approve=approve,
            reject=reject,
        )
    except Exception as e:
        console.print(f"[bold red]✗ Review failed:[/bold red] {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    cli()