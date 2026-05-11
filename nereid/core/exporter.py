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
    
def export_single_to_drive(
    engine,
    folder_id: str,
    provider,
    tables: list[str] | None = None,
    schema: str = "public",
    file_name: str = "nereid_export.xlsx",
) -> str:
    """
    Export all tables to a single XLSX and upload to Google Drive.
    Returns the Drive file ID of the uploaded file.
    """
    import tempfile
    import os

    available_tables = get_table_names(engine, schema=schema)
    target_tables = tables if tables else available_tables

    fd, tmp_str = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    tmp_path = Path(tmp_str)

    try:
        _export_single(engine, target_tables, str(tmp_path), schema)
        file_id = provider.upload_file(folder_id, tmp_path, file_name)
        logger.success(f"Uploaded '{file_name}' to Google Drive.")
        return file_id
    finally:
        tmp_path.unlink(missing_ok=True)


def export_multi_to_drive(
    engine,
    folder_id: str,
    provider,
    tables: list[str] | None = None,
    schema: str = "public",
) -> dict[str, str]:
    """
    Export each table to a CSV and upload to Google Drive.
    Returns a dict of {table_name: drive_file_id}.
    """
    import tempfile
    import os

    available_tables = get_table_names(engine, schema=schema)
    target_tables = tables if tables else available_tables

    file_ids = {}

    for table_name in target_tables:
        fd, tmp_str = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        tmp_path = Path(tmp_str)

        try:
            df = _read_table(engine, table_name, schema)
            df.to_csv(tmp_path, index=False)
            file_name = f"{table_name}.csv"
            file_id = provider.upload_file(folder_id, tmp_path, file_name)
            file_ids[table_name] = file_id
            logger.success(f"Uploaded '{file_name}' to Google Drive.")
        finally:
            tmp_path.unlink(missing_ok=True)

    return file_ids


def sync_drive_to_db_state(
    engine,
    folder_id: str,
    provider,
    mode: str,
    file_registry: dict,
    tables: list[str] | None = None,
    schema: str = "public",
) -> None:
    """
    Re-export the current DB state and overwrite existing Drive files.
    Called after a review session completes to keep Drive in sync with DB.

    file_registry: dict mapping table_name (multi) or file_name (single)
                   to their Drive file IDs so we overwrite not duplicate.
    """
    import tempfile
    import os

    available_tables = get_table_names(engine, schema=schema)
    target_tables = tables if tables else available_tables

    if mode == "single":
        file_id   = list(file_registry.values())[0]
        fd, tmp_str = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        tmp_path = Path(tmp_str)
        try:
            _export_single(engine, target_tables, str(tmp_path), schema)
            provider.overwrite_file(file_id, tmp_path)
            logger.success("Drive file synced to current DB state.")
        finally:
            tmp_path.unlink(missing_ok=True)

    elif mode == "multi":
        for table_name in target_tables:
            file_id = file_registry.get(table_name)
            if not file_id:
                logger.warning(f"No Drive file ID found for '{table_name}' — skipping.")
                continue
            fd, tmp_str = tempfile.mkstemp(suffix=".csv")
            os.close(fd)
            tmp_path = Path(tmp_str)
            try:
                df = _read_table(engine, table_name, schema)
                df.to_csv(tmp_path, index=False)
                provider.overwrite_file(file_id, tmp_path)
                logger.success(f"'{table_name}.csv' synced to current DB state.")
            finally:
                tmp_path.unlink(missing_ok=True)