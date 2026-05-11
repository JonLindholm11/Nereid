"""
Nereid Cloud Watcher — polls a cloud provider for file changes and syncs to staging.

Mirrors the local watcher (nereid/core/watcher.py) but replaces watchdog
file-system events with a periodic API poll against a CloudProvider.
The diff → staging pipeline is identical to the local watcher.
"""

import os
import tempfile
import time
import pandas as pd
from pathlib import Path
from datetime import datetime

from nereid.core.differ import compute_diff
from nereid.core.staging import write_to_staging, load_staging_snapshot
from nereid.utils.db import get_engine, ensure_staging_schema
from nereid.utils import logger
from nereid.providers.base import CloudProvider


def _load_cloud_file(
    tmp_path: Path,
    mode: str,
    fallback_table_name: str,
) -> dict[str, pd.DataFrame]:
    """
    Load a downloaded file into {table_name: DataFrame}.

    For single/XLSX mode, table names are derived from sheet names (same as
    the local watcher).  For multi/CSV mode the Drive file's name stem is
    used as the table name, since the temp file has a generic random name.
    """
    if mode == "single":
        sheets = pd.read_excel(tmp_path, sheet_name=None, engine="openpyxl")
        return {name: df for name, df in sheets.items()}
    else:
        df = pd.read_csv(tmp_path)
        return {fallback_table_name: df}


def _sync_once(
    provider: CloudProvider,
    mode: str,
    fallback_table_name: str,
    engine,
    pk_column: str,
    staging_schema: str,
    snapshots: dict[str, pd.DataFrame],
) -> None:
    """
    Download the remote file and write any changes to the staging schema.
    Safe to call on every poll — exits early if no changes are detected.
    """
    suffix = ".csv" if mode == "multi" else ".xlsx"

    # mkstemp creates the file and returns an open file descriptor.
    # Close the fd immediately so the provider can write to the path.
    fd, tmp_str = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    tmp_path = Path(tmp_str)

    try:
        logger.dim("  Downloading remote file...")
        provider.download_to_tempfile(tmp_path)
        current_data = _load_cloud_file(tmp_path, mode, fallback_table_name)
    except Exception as e:
        logger.error(f"Failed to download or read remote file: {e}")
        return
    finally:
        tmp_path.unlink(missing_ok=True)

    for table_name, new_df in current_data.items():
        old_df = snapshots.get(table_name)

        if old_df is None:
            logger.dim(
                f"  First sync for '{table_name}' — "
                f"treating all {len(new_df)} rows as inserts."
            )
            old_df = pd.DataFrame(columns=new_df.columns)
        elif set(old_df.columns) != set(new_df.columns):
            logger.dim(
                f"  '{table_name}' column mismatch — resetting snapshot "
                f"and treating all {len(new_df)} rows as inserts."
            )
            old_df = pd.DataFrame(columns=new_df.columns)

        try:
            changeset = compute_diff(old_df, new_df, pk_column, table_name)
        except ValueError as e:
            logger.error(f"  Diff failed for '{table_name}': {e}")
            continue

        if changeset.is_empty:
            logger.dim(f"  '{table_name}': no changes detected.")
            continue

        logger.info(f"  '{table_name}': {changeset.summary()}")

        try:
            write_to_staging(engine, changeset, staging_schema)
            snapshots[table_name] = new_df.copy()
            logger.success(f"  '{table_name}' staged successfully.")
        except Exception as e:
            logger.error(f"  Failed to write staging for '{table_name}': {e}")


def run_cloud_watch(
    provider: CloudProvider,
    mode: str,
    fallback_table_name: str,
    db_url: str,
    pk_column: str,
    staging_schema: str,
    poll_interval: float,
) -> None:
    """
    Main cloud watch entry point.  Blocks until Ctrl+C.

    Parameters
    ----------
    provider:
        A configured CloudProvider instance (e.g. GoogleDriveProvider).
    mode:
        "single" for XLSX (sheets → tables) or "multi" for CSV (file → one table).
    fallback_table_name:
        Used as the table name in multi/CSV mode (the Drive file's name stem).
    db_url:
        PostgreSQL connection string.
    pk_column:
        Primary key column name used for diffing.
    staging_schema:
        Postgres schema where staged changes are written.
    poll_interval:
        Seconds between remote-file checks.
    """
    engine = get_engine(db_url)
    ensure_staging_schema(engine, staging_schema)

    snapshots: dict[str, pd.DataFrame] = load_staging_snapshot(engine, staging_schema)
    logger.dim(f"Loaded {len(snapshots)} table snapshot(s) from staging.")

    last_modified: float | None = None

    logger.success(
        f"Nereid Cloud Watch active — polling every {poll_interval}s. "
        "Press Ctrl+C to stop.\n"
    )

    while True:
        try:
            current_modified = provider.get_last_modified()

            if last_modified is None or current_modified > last_modified:
                if last_modified is not None:
                    logger.info("Remote file changed — syncing...")
                else:
                    logger.info("Starting initial sync...")

                _sync_once(
                    provider=provider,
                    mode=mode,
                    fallback_table_name=fallback_table_name,
                    engine=engine,
                    pk_column=pk_column,
                    staging_schema=staging_schema,
                    snapshots=snapshots,
                )
                last_modified = current_modified
            else:
                logger.dim(f"No changes detected. Next check in {poll_interval}s.")

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error(f"Poll error — will retry in {poll_interval}s: {e}")

        time.sleep(poll_interval)

def run_cloud_watch_folder(
    folder_id: str,
    mode: str,
    db_url: str,
    pk_column: str,
    staging_schema: str,
    poll_interval: float,
    schema: str = "public",
) -> None:
    """
    Watch a Google Drive folder for changes and sync to staging.
    On first run, exports DB state to Drive if folder is empty.
    Blocks until Ctrl+C.

    Parameters
    ----------
    folder_id:
        Google Drive folder ID to watch.
    mode:
        "single" for one XLSX (sheets = tables) or "multi" for CSVs (filename = table).
    db_url:
        PostgreSQL connection string.
    pk_column:
        Primary key column used for diffing.
    staging_schema:
        Postgres schema where staged changes are written.
    poll_interval:
        Seconds between folder checks.
    schema:
        DB schema to read/write from. Defaults to public.
    """
    from nereid.providers.google_drive import GoogleDriveProvider
    from nereid.core.exporter import (
        export_single_to_drive,
        export_multi_to_drive,
    )

    engine = get_engine(db_url)
    ensure_staging_schema(engine, staging_schema)

    provider = GoogleDriveProvider(file_id="folder_mode")

    file_registry: dict[str, str] = {}

    logger.info("Checking Google Drive folder for existing files...")
    existing_files = provider.list_folder_files(folder_id)

    if not existing_files:
        logger.info("Folder is empty — exporting DB state to Google Drive...")
        if mode == "single":
            file_id = export_single_to_drive(
                engine=engine,
                folder_id=folder_id,
                provider=provider,
                schema=schema,
                file_name="nereid_export.xlsx",
            )
            file_registry["nereid_export.xlsx"] = file_id
        elif mode == "multi":
            file_registry = export_multi_to_drive(
                engine=engine,
                folder_id=folder_id,
                provider=provider,
                schema=schema,
            )
        logger.success("Initial export complete. Watching for changes...")
    else:
        logger.info(f"Found {len(existing_files)} file(s) in folder — skipping initial export.")
        for f in existing_files:
            name_stem = Path(f["name"]).stem
            file_registry[name_stem] = f["id"]
        logger.success("File registry loaded. Watching for changes...")

    snapshots: dict[str, pd.DataFrame] = load_staging_snapshot(engine, staging_schema)
    last_modified: dict[str, float] = {}

    logger.success(
        f"Nereid Folder Watch active — polling every {poll_interval}s. "
        "Press Ctrl+C to stop.\n"
    )

    while True:
        try:
            current_files = provider.list_folder_files(folder_id)

            for file_meta in current_files:
                file_id   = file_meta["id"]
                file_name = file_meta["name"]
                name_stem = Path(file_name).stem
                raw_mod   = file_meta["modifiedTime"]
                dt        = datetime.fromisoformat(raw_mod.replace("Z", "+00:00"))
                current_mod = dt.timestamp()

                if last_modified.get(file_id) == current_mod:
                    continue

                logger.info(f"Change detected in '{file_name}' — syncing...")

                file_provider = GoogleDriveProvider(file_id=file_id)

                _sync_once(
                    provider=file_provider,
                    mode=mode,
                    fallback_table_name=name_stem,
                    engine=engine,
                    pk_column=pk_column,
                    staging_schema=staging_schema,
                    snapshots=snapshots,
                )

                last_modified[file_id] = current_mod

                if name_stem not in file_registry:
                    file_registry[name_stem] = file_id

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error(f"Poll error — will retry in {poll_interval}s: {e}")

        time.sleep(poll_interval)
