"""
Nereid Exporter — pulls data from PostgreSQL and writes to XLSX or CSV.

Single mode: one XLSX file, each table = one tab.
Multi mode:  one CSV per table in a folder.
"""

import os
import pandas as pd
from pathlib import Path
from sqlalchemy import text

from nereid.utils.db import get_engine, get_table_names, table_exists
from nereid.utils import logger


def run_export(
    mode: str,
    output_path: str,
    db_url: str,
    tables: list[str] | None = None,
    schema: str = "public",
):
    """
    Main export entrypoint.

    Args:
        mode: "single" or "multi"
        output_path: path to the XLSX file (single) or folder (multi)
        db_url: PostgreSQL connection string
        tables: list of table names to export; None = all tables
        schema: source schema in PostgreSQL (default: public)
    """
    engine = get_engine(db_url)

    # Resolve which tables to export
    available_tables = get_table_names(engine, schema=schema)
    if not available_tables:
        logger.warning(f"No tables found in schema '{schema}'.")
        return

    target_tables = tables if tables else available_tables
    missing = [t for t in target_tables if t not in available_tables]
    if missing:
        raise ValueError(f"Tables not found in schema '{schema}': {', '.join(missing)}")

    logger.info(f"Exporting {len(target_tables)} table(s): {', '.join(target_tables)}")

    if mode == "single":
        _export_single(engine, target_tables, output_path, schema)
    elif mode == "multi":
        _export_multi(engine, target_tables, output_path, schema)
    else:
        raise ValueError(f"Unknown mode: {mode}")


def _read_table(engine, table_name: str, schema: str) -> pd.DataFrame:
    """Read a full table into a DataFrame."""
    with engine.connect() as conn:
        df = pd.read_sql(
            text(f'SELECT * FROM "{schema}"."{table_name}"'),
            conn
        )
    return df


def _export_single(engine, tables: list[str], output_path: str, schema: str):
    """
    Export all tables to a single XLSX file.
    Each table becomes a separate sheet (tab).
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for table_name in tables:
            logger.dim(f"  → Exporting table: {table_name}")
            df = _read_table(engine, table_name, schema)
            # Sheet names are limited to 31 chars in Excel
            sheet_name = table_name[:31]
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            logger.dim(f"    {len(df)} rows written to sheet '{sheet_name}'")

    logger.success(f"Exported to {output}")


def _export_multi(engine, tables: list[str], output_path: str, schema: str):
    """
    Export each table to its own CSV file in a folder.
    Filename = table name + .csv
    """
    folder = Path(output_path)
    folder.mkdir(parents=True, exist_ok=True)

    for table_name in tables:
        logger.dim(f"  → Exporting table: {table_name}")
        df = _read_table(engine, table_name, schema)
        csv_path = folder / f"{table_name}.csv"
        df.to_csv(csv_path, index=False)
        logger.dim(f"    {len(df)} rows written to {csv_path.name}")

    logger.success(f"Exported {len(tables)} CSV(s) to {folder}")