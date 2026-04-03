"""
Nereid Reviewer — shows pending staged changes and handles approve/reject.
"""

import pandas as pd
from sqlalchemy import text
from rich.console import Console
from rich.table import Table

from nereid.utils.db import get_engine, get_table_names
from nereid.core.staging import promote_to_production, clear_staging, _META_TABLE
from nereid.utils import logger

console = Console()


def run_review(
    db_url: str,
    staging_schema: str,
    approve: bool = False,
    reject: bool = False,
):
    """
    Main review entrypoint.
    Shows a summary of all staged changes.
    Optionally approves (promotes to production) or rejects (clears staging).
    """
    engine = get_engine(db_url)
    tables = get_table_names(engine, schema=staging_schema)
    data_tables = [t for t in tables if t != _META_TABLE]

    if not data_tables:
        logger.info("No staged changes found.")
        return

    # ── Display staged changes ────────────────────────────────────────────────
    console.print(f"\n[bold]Pending staged changes in '[cyan]{staging_schema}[/cyan]':[/bold]\n")
    total_rows = 0

    for table_name in data_tables:
        with engine.connect() as conn:
            df = pd.read_sql(
                text(f'SELECT * FROM "{staging_schema}"."{table_name}"'),
                conn,
            )

        if df.empty:
            continue

        total_rows += len(df)

        rich_table = Table(title=f"Table: {table_name}", show_lines=True)
        for col in df.columns:
            rich_table.add_column(str(col), overflow="fold", max_width=30)
        for _, row in df.head(20).iterrows():
            rich_table.add_row(*[str(v) for v in row.values])

        console.print(rich_table)
        if len(df) > 20:
            console.print(f"[dim]  ... and {len(df) - 20} more rows[/dim]")

    # ── Pending deletes ───────────────────────────────────────────────────────
    try:
        with engine.connect() as conn:
            meta_df = pd.read_sql(
                text(f'SELECT * FROM "{staging_schema}"."{_META_TABLE}" WHERE operation = \'DELETE\''),
                conn,
            )
        if not meta_df.empty:
            console.print(f"\n[bold yellow]Pending deletes:[/bold yellow] {len(meta_df)} row(s) flagged for deletion.\n")
    except Exception:
        pass

    console.print(f"\n[bold]{total_rows} row(s) staged across {len(data_tables)} table(s).[/bold]\n")

    # ── Approve or reject ─────────────────────────────────────────────────────
    if approve and reject:
        logger.error("Cannot use --approve and --reject together.")
        return

    if approve:
        console.print("[bold green]Approving — promoting staged changes to production...[/bold green]")
        promote_to_production(engine, staging_schema)
        logger.success("All staged changes promoted to production.")

    elif reject:
        console.print("[bold yellow]Rejecting — clearing all staged changes...[/bold yellow]")
        clear_staging(engine, staging_schema)
        logger.success("Staging cleared. No changes applied to production.")

    else:
        console.print("[dim]Run with --approve to promote or --reject to discard.[/dim]")