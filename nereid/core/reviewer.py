"""
Nereid Reviewer — shows pending staged changes and handles approve/reject.

Supports granular approval:
  --approve-all        promote everything
  --approve-table      promote a specific table
  --reject-all         discard everything
  --reject-table       discard a specific table
"""

import pandas as pd
from sqlalchemy import text
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt

from nereid.utils.db import get_engine, get_table_names
from nereid.core.staging import (
    promote_to_production,
    clear_staging,
    _upsert_df,
    _get_pk_column,
    _apply_staged_deletes,
    _META_TABLE,
)
from nereid.utils import logger

console = Console()


def _get_staged_tables(engine, staging_schema: str) -> list[str]:
    tables = get_table_names(engine, schema=staging_schema)
    return [t for t in tables if t != _META_TABLE]


def _display_table(engine, staging_schema: str, table_name: str) -> int:
    """Display staged rows for a single table. Returns row count."""
    with engine.connect() as conn:
        result = conn.execute(text(f'SELECT * FROM "{staging_schema}"."{table_name}"'))
        df = pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    if df.empty:
        return 0

    rich_table = Table(title=f"Table: {table_name}", show_lines=True)
    for col in df.columns:
        rich_table.add_column(str(col), overflow="fold", max_width=30)
    for _, row in df.head(20).iterrows():
        rich_table.add_row(*[str(v) for v in row.values])

    console.print(rich_table)
    if len(df) > 20:
        console.print(f"[dim]  ... and {len(df) - 20} more rows[/dim]")

    return len(df)


def _promote_table(engine, staging_schema: str, table_name: str, production_schema: str = "public"):
    """Promote a single table from staging to production."""
    with engine.connect() as conn:
        result = conn.execute(text(f'SELECT * FROM "{staging_schema}"."{table_name}"'))
        staged_df = pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    if staged_df.empty:
        logger.info(f"  No staged rows for '{table_name}'.")
        return

    pk_col = _get_pk_column(engine, table_name, production_schema)
    if not pk_col:
        logger.warning(f"  No PK found for '{table_name}' — skipping.")
        return

    staged_df = staged_df.drop_duplicates(subset=[pk_col], keep="last")
    _upsert_df(staged_df, table_name, engine, production_schema, pk_col)
    logger.success(f"  Promoted '{table_name}' → {production_schema} ({len(staged_df)} rows)")

    # Clear just this table from staging
    with engine.connect() as conn:
        conn.execute(text(f'TRUNCATE TABLE "{staging_schema}"."{table_name}" RESTART IDENTITY'))
        conn.commit()


def _reject_table(engine, staging_schema: str, table_name: str):
    """Discard staged changes for a single table."""
    with engine.connect() as conn:
        conn.execute(text(f'TRUNCATE TABLE "{staging_schema}"."{table_name}" RESTART IDENTITY'))
        conn.commit()
    logger.success(f"  Rejected '{table_name}' — staging cleared.")


def run_review(
    db_url: str,
    staging_schema: str,
    approve_all: bool = False,
    approve_table: str | None = None,
    reject_all: bool = False,
    reject_table: str | None = None,
    interactive: bool = False,
):
    engine = get_engine(db_url)
    data_tables = _get_staged_tables(engine, staging_schema)

    if not data_tables:
        logger.info("No staged changes found.")
        return

    # ── Display all staged changes ────────────────────────────────────────────
    console.print(f"\n[bold]Pending staged changes in '[cyan]{staging_schema}[/cyan]':[/bold]\n")
    total_rows = 0

    # Filter display to specific table if requested
    display_tables = [approve_table or reject_table] if (approve_table or reject_table) else data_tables

    for table_name in display_tables:
        if table_name not in data_tables:
            logger.error(f"Table '{table_name}' has no staged changes.")
            return
        total_rows += _display_table(engine, staging_schema, table_name)

    # Pending deletes summary
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT * FROM \"{staging_schema}\".\"{_META_TABLE}\" WHERE operation = 'DELETE'")
            )
            meta_df = pd.DataFrame(result.fetchall(), columns=list(result.keys()))
        if not meta_df.empty:
            console.print(f"\n[bold yellow]Pending deletes:[/bold yellow] {len(meta_df)} row(s) flagged for deletion.\n")
    except Exception:
        pass

    console.print(f"\n[bold]{total_rows} row(s) staged across {len(display_tables)} table(s).[/bold]\n")

    # ── Action ────────────────────────────────────────────────────────────────
    if approve_all:
        console.print("[bold green]Approving all — promoting staged changes to production...[/bold green]")
        promote_to_production(engine, staging_schema)
        logger.success("All staged changes promoted to production.")

    elif approve_table:
        console.print(f"[bold green]Approving table '{approve_table}'...[/bold green]")
        _promote_table(engine, staging_schema, approve_table)
        _apply_staged_deletes(engine, staging_schema, "public")

    elif reject_all:
        console.print("[bold yellow]Rejecting all — clearing all staged changes...[/bold yellow]")
        clear_staging(engine, staging_schema)
        logger.success("Staging cleared. No changes applied to production.")

    elif reject_table:
        console.print(f"[bold yellow]Rejecting table '{reject_table}'...[/bold yellow]")
        _reject_table(engine, staging_schema, reject_table)

    elif interactive:
        # Interactive mode — go table by table
        console.print("[dim]Interactive mode — review each table one at a time.[/dim]\n")
        for table_name in data_tables:
            console.print(f"\n[bold]Table: [cyan]{table_name}[/cyan][/bold]")
            _display_table(engine, staging_schema, table_name)
            choice = Prompt.ask(
                "  Action",
                choices=["approve", "reject", "skip"],
                default="skip"
            )
            if choice == "approve":
                _promote_table(engine, staging_schema, table_name)
            elif choice == "reject":
                _reject_table(engine, staging_schema, table_name)
            else:
                console.print(f"  [dim]Skipped '{table_name}'.[/dim]")

    else:
        console.print("Options:")
        console.print("  [green]--approve-all[/green]              Promote all staged changes to production")
        console.print("  [green]--approve-table TABLE[/green]      Promote a specific table only")
        console.print("  [yellow]--reject-all[/yellow]               Discard all staged changes")
        console.print("  [yellow]--reject-table TABLE[/yellow]       Discard a specific table only")
        console.print("  [cyan]--interactive[/cyan]               Review and decide table by table")