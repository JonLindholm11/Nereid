"""
Nereid Staging — manages the staging schema in PostgreSQL.

Changesets are written here first.
Production is only touched after explicit review + approval.
"""

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from nereid.core.differ import Changeset
from nereid.utils import logger


# ── Staging table name convention ────────────────────────────────────────────
# Each staging table mirrors the production table name within the staging schema.
# A _nereid_meta table tracks pending change summaries.

_META_TABLE = "_nereid_meta"


def _meta_table_ddl(schema: str) -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS "{schema}"."{_META_TABLE}" (
            id SERIAL PRIMARY KEY,
            table_name TEXT NOT NULL,
            operation TEXT NOT NULL,   -- INSERT | UPDATE | DELETE
            row_pk TEXT NOT NULL,      -- stringified PK value
            staged_at TIMESTAMPTZ DEFAULT NOW()
        )
    """


def ensure_staging_table(engine: Engine, table_name: str, df: pd.DataFrame, schema: str):
    """Create a staging table matching the DataFrame structure if it doesn't exist."""
    # Use pandas to_sql with if_exists='append' — it won't recreate if already there
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        conn.commit()

    # Write empty frame to create table structure if missing
    empty = df.head(0)
    empty.to_sql(
        table_name,
        engine,
        schema=schema,
        if_exists="replace",  # Replace schema on each watch start to stay in sync
        index=False,
    )


def write_to_staging(engine: Engine, changeset: Changeset, staging_schema: str):
    """
    Write a Changeset to the staging schema.

    Inserts and updates are upserted into the staging table.
    Deletes are recorded in _nereid_meta for review.
    """
    table = changeset.table_name

    with engine.connect() as conn:
        # Ensure meta table exists
        conn.execute(text(_meta_table_ddl(staging_schema)))
        conn.commit()

    # ── Inserts ──────────────────────────────────────────────────────────────
    if len(changeset.inserts) > 0:
        changeset.inserts.to_sql(
            table,
            engine,
            schema=staging_schema,
            if_exists="append",
            index=False,
        )
        logger.dim(f"    Staged {len(changeset.inserts)} inserts for '{table}'")

    # ── Updates ──────────────────────────────────────────────────────────────
    if len(changeset.updates) > 0:
        # For staging, we just upsert — store the updated row state
        changeset.updates.to_sql(
            table,
            engine,
            schema=staging_schema,
            if_exists="append",
            index=False,
        )
        logger.dim(f"    Staged {len(changeset.updates)} updates for '{table}'")

    # ── Deletes ──────────────────────────────────────────────────────────────
    if len(changeset.deletes) > 0:
        # Record deletions in meta table — we don't remove from staging table
        pk_col = changeset.deletes.columns[0]  # PK is first col after diff
        with engine.connect() as conn:
            for _, row in changeset.deletes.iterrows():
                conn.execute(
                    text(
                        f'INSERT INTO "{staging_schema}"."{_META_TABLE}" '
                        f'(table_name, operation, row_pk) VALUES (:t, :op, :pk)'
                    ),
                    {"t": table, "op": "DELETE", "pk": str(row[pk_col])},
                )
            conn.commit()
        logger.dim(f"    Staged {len(changeset.deletes)} deletes for '{table}'")


def load_staging_snapshot(engine: Engine, staging_schema: str) -> dict[str, pd.DataFrame]:
    """
    Load current staging tables as DataFrames (used to seed watcher snapshots on restart).
    """
    from nereid.utils.db import get_table_names

    snapshots = {}
    tables = get_table_names(engine, schema=staging_schema)
    system_tables = {_META_TABLE}

    for table_name in tables:
        if table_name in system_tables:
            continue
        try:
            with engine.connect() as conn:
                df = pd.read_sql(
                    text(f'SELECT * FROM "{staging_schema}"."{table_name}"'),
                    conn,
                )
            snapshots[table_name] = df
        except Exception:
            pass  # Table might be empty or schema mismatch — skip

    return snapshots


def promote_to_production(engine: Engine, staging_schema: str, production_schema: str = "public"):
    """
    Promote all staged changes to production.
    Called after `nereid review --approve`.
    """
    from nereid.utils.db import get_table_names

    tables = get_table_names(engine, schema=staging_schema)
    system_tables = {_META_TABLE}
    promoted = 0

    for table_name in tables:
        if table_name in system_tables:
            continue

        with engine.connect() as conn:
            staged_df = pd.read_sql(
                text(f'SELECT * FROM "{staging_schema}"."{table_name}"'),
                conn,
            )

        if staged_df.empty:
            continue

        staged_df.to_sql(
            table_name,
            engine,
            schema=production_schema,
            if_exists="append",
            index=False,
        )
        promoted += 1
        logger.success(f"  Promoted '{table_name}' → {production_schema} ({len(staged_df)} rows)")

    # Handle pending deletes from meta
    _apply_staged_deletes(engine, staging_schema, production_schema)

    # Clear staging after promotion
    clear_staging(engine, staging_schema)
    return promoted


def clear_staging(engine: Engine, staging_schema: str):
    """Truncate all staging tables after promotion or rejection."""
    from nereid.utils.db import get_table_names

    tables = get_table_names(engine, schema=staging_schema)
    with engine.connect() as conn:
        for table_name in tables:
            conn.execute(text(f'TRUNCATE TABLE "{staging_schema}"."{table_name}"'))
        conn.commit()
    logger.dim("Staging schema cleared.")


def _apply_staged_deletes(engine: Engine, staging_schema: str, production_schema: str):
    """Apply staged DELETE operations to production."""
    try:
        with engine.connect() as conn:
            meta_df = pd.read_sql(
                text(f'SELECT * FROM "{staging_schema}"."{_META_TABLE}" WHERE operation = \'DELETE\''),
                conn,
            )

        if meta_df.empty:
            return

        for _, row in meta_df.iterrows():
            table = row["table_name"]
            pk_val = row["row_pk"]
            # Note: this assumes PK column is 'id' — production review will make this configurable
            with engine.connect() as conn:
                conn.execute(
                    text(f'DELETE FROM "{production_schema}"."{table}" WHERE id = :pk'),
                    {"pk": pk_val},
                )
                conn.commit()

        logger.dim(f"Applied {len(meta_df)} staged deletes to production.")
    except Exception as e:
        logger.warning(f"Could not apply staged deletes: {e}")