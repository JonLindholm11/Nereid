"""
Nereid Exporter — pulls data from PostgreSQL and writes to XLSX or CSV.

Single mode: one XLSX file, each table = one tab.
Multi mode:  one CSV per table in a folder.
"""

import pandas as pd
from pathlib import Path
from sqlalchemy import text

from nereid.utils.db import get_engine, get_table_names
from nereid.utils import logger


def run_export(
    mode: str,
    output_path: str,
    db_url: str,
    tables: list[str] | None = None,
    schema: str = "public",
):
    engine = get_engine(db_url)

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
    """Read a full table into a DataFrame using SQLAlchemy connection directly."""
    with engine.connect() as conn:
        result = conn.execute(text(f'SELECT * FROM "{schema}"."{table_name}"'))
        df = pd.DataFrame(result.fetchall(), columns=list(result.keys()))
    return df


def _export_single(engine, tables: list[str], output_path: str, schema: str):
    """Export all tables to a single XLSX file. Each table = one sheet."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    # Pre-load all data before opening writer to avoid empty workbook errors
    loaded = {}
    for table_name in tables:
        logger.dim(f"  → Reading table: {table_name}")
        df = _read_table(engine, table_name, schema)
        loaded[table_name] = df
        logger.dim(f"    {len(df)} rows loaded")

    if not loaded:
        raise ValueError("No data to export — all tables were empty or unreadable.")

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for table_name, df in loaded.items():
            sheet_name = table_name[:31]  # Excel sheet name 31 char limit
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            logger.dim(f"  → Written sheet '{sheet_name}' ({len(df)} rows)")

    logger.success(f"Exported to {output}")


def _export_multi(engine, tables: list[str], output_path: str, schema: str):
    """Export each table to its own CSV file in a folder."""
    folder = Path(output_path)
    folder.mkdir(parents=True, exist_ok=True)

    for table_name in tables:
        logger.dim(f"  → Exporting table: {table_name}")
        df = _read_table(engine, table_name, schema)
        csv_path = folder / f"{table_name}.csv"
        df.to_csv(csv_path, index=False)
        logger.dim(f"    {len(df)} rows written to {csv_path.name}")

    logger.success(f"Exported {len(tables)} CSV(s) to {folder}")