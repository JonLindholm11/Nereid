"""
Nereid Watcher — monitors a file or folder for changes and triggers sync.

Uses watchdog to detect file system events.
Waits for the file to fully stabilize (size stops changing) before syncing.
This handles cloud sync clients and Excel which write files in multiple passes.
"""

import time
import os
import threading
import pandas as pd
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from nereid.core.differ import compute_diff
from nereid.core.staging import write_to_staging, load_staging_snapshot
from nereid.utils.db import get_engine, ensure_staging_schema
from nereid.utils import logger


def _wait_for_file_stable(path: str, stable_seconds: float = 2.0, timeout: float = 30.0) -> bool:
    """
    Wait until a file's size stops changing.
    Returns True if stable, False if timed out.

    This prevents syncing a partially-written file from Excel or a cloud client
    that writes in multiple chunks.
    """
    deadline = time.time() + timeout
    last_size = -1

    while time.time() < deadline:
        try:
            current_size = os.path.getsize(path)
        except OSError:
            # File temporarily locked or missing mid-write — wait and retry
            time.sleep(0.5)
            continue

        if current_size == last_size and current_size > 0:
            # Size hasn't changed — file is stable
            return True

        last_size = current_size
        time.sleep(stable_seconds)

    return False


class _DebounceHandler(FileSystemEventHandler):
    """
    Watchdog event handler with debounce logic.
    Ignores temp files written by Office and cloud clients.
    """

    def __init__(self, callback, watch_path: str, debounce_seconds: float):
        super().__init__()
        self._callback = callback
        self._watch_path = Path(watch_path)
        self._debounce_seconds = debounce_seconds
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def _is_relevant(self, event_path: str) -> bool:
        p = Path(event_path)
        # Ignore temp/lock files written by Office and cloud clients
        if p.name.startswith("~$") or p.name.startswith(".~"):
            return False
        if p.suffix.lower() in (".tmp", ".lock", ".partial"):
            return False
        # Ignore Google Drive's .gdoc/.gsheet temp files
        if p.suffix.lower() in (".gdoc", ".gsheet", ".gslides"):
            return False
        if self._watch_path.is_file():
            return p == self._watch_path
        return p.parent == self._watch_path and p.suffix.lower() == ".csv"

    def on_modified(self, event):
        if not event.is_directory and self._is_relevant(event.src_path):
            self._schedule(event.src_path)

    def on_created(self, event):
        if not event.is_directory and self._is_relevant(event.src_path):
            self._schedule(event.src_path)

    def _schedule(self, path: str):
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(
                self._debounce_seconds,
                self._callback,
                args=[path],
            )
            self._timer.start()


def _load_file(path: str, mode: str) -> dict[str, pd.DataFrame]:
    """Load file(s) into a dict of {table_name: DataFrame}."""
    p = Path(path)

    if mode == "single":
        sheets = pd.read_excel(p, sheet_name=None, engine="openpyxl")
        return {name: df for name, df in sheets.items()}
    elif mode == "multi":
        table_name = p.stem
        df = pd.read_csv(p)
        return {table_name: df}

    raise ValueError(f"Unknown mode: {mode}")


def _on_file_changed(
    changed_path: str,
    mode: str,
    engine,
    pk_column: str,
    staging_schema: str,
    stable_seconds: float,
    snapshots: dict[str, pd.DataFrame],
):
    """Called (debounced) when a file change is detected."""
    logger.info(f"Change detected: {Path(changed_path).name}")
    logger.dim("  Waiting for file to stabilize...")

    stable = _wait_for_file_stable(changed_path, stable_seconds=stable_seconds)
    if not stable:
        logger.warning(f"  File did not stabilize in time — skipping this sync cycle.")
        return

    try:
        current_data = _load_file(changed_path, mode)
    except Exception as e:
        logger.error(f"Failed to read file: {e}")
        return

    for table_name, new_df in current_data.items():
        old_df = snapshots.get(table_name)

        if old_df is None:
            logger.dim(f"  First sync for '{table_name}' — treating all {len(new_df)} rows as inserts.")
            old_df = pd.DataFrame(columns=new_df.columns)

        try:
            changeset = compute_diff(old_df, new_df, pk_column, table_name)
        except ValueError as e:
            logger.error(f"Diff failed for '{table_name}': {e}")
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


def run_watch(
    mode: str,
    watch_path: str,
    db_url: str,
    pk_column: str,
    staging_schema: str,
    debounce_seconds: float,
):
    """Main watch entrypoint. Blocks until Ctrl+C."""
    engine = get_engine(db_url)
    ensure_staging_schema(engine, staging_schema)

    snapshots: dict[str, pd.DataFrame] = load_staging_snapshot(engine, staging_schema)
    logger.dim(f"Loaded {len(snapshots)} table snapshot(s) from staging.")

    # stable_seconds is how long the file size must be unchanged before we read it
    stable_seconds = min(debounce_seconds, 2.0)

    def on_change(changed_path: str):
        _on_file_changed(
            changed_path=changed_path,
            mode=mode,
            engine=engine,
            pk_column=pk_column,
            staging_schema=staging_schema,
            stable_seconds=stable_seconds,
            snapshots=snapshots,
        )

    watch_target = Path(watch_path)
    watch_dir = watch_target if watch_target.is_dir() else watch_target.parent

    handler = _DebounceHandler(
        callback=on_change,
        watch_path=watch_path,
        debounce_seconds=debounce_seconds,
    )

    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=False)
    observer.start()
    logger.success("Nereid is watching. Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(1)
    finally:
        observer.stop()
        observer.join()