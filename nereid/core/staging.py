"""
Nereid Staging — manages the staging schema in PostgreSQL.

Changesets are written here first.
Production is only touched after explicit review + approval.
"""

import pandas as pd
from sqlalchemy import create_engine, text, inspect, Table, Column, Text, MetaData
from sqlalchemy.engine import Engine

from nereid.core.differ import Changeset
from nereid.utils import logger


_META_TABLE = "_nereid_meta"


def _meta_table_ddl(schema: str) -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS "{schema}"."{_META_TABLE}" (
            id SERIAL PRIMARY KEY,
            table_name TEXT NOT NULL,
            operation TEXT NOT NULL,
            row_pk TEXT NOT NULL,
            staged_at TIMESTAMPTZ DEFAULT NOW()
        )
    """


def _ensure_table(engine: Engine, table: str, df: pd.DataFrame, schema: str):
    """
    Create a staging table from DataFrame columns if it doesn't exist.
    Uses raw DDL — no pandas/SQLAlchemy to_sql involved.
    """
    cols_ddl = ", ".join(f'"{c}" TEXT' for c in df.columns)
    ddl = f'CREATE TABLE IF NOT EXISTS "{schema}"."{table}" ({cols_ddl})'
    with engine.connect() as conn:
        conn.execute(text(ddl))
        conn.commit()


def _insert_rows(engine: Engine, table: str, df: pd.DataFrame, schema: str):
    """Insert DataFrame rows using raw parameterized SQL."""
    if df.empty:
        return
    cols = ", ".join(f'"{c}"' for c in df.columns)
    placeholders = ", ".join(f":{c}" for c in df.columns)
    stmt = text(f'INSERT INTO "{schema}"."{table}" ({cols}) VALUES ({placeholders})')
    with engine.connect() as conn:
        for _, row in df.iterrows():
            conn.execute(stmt, row.to_dict())
        conn.commit()


def _upsert_df(df: pd.DataFrame, table: str, engine: Engine, schema: str, pk_column: str):
    """Upsert a DataFrame into a production table using INSERT ... ON CONFLICT DO UPDATE."""
    if df.empty:
        return
    cols = list(df.columns)
    col_list = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    updates = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in cols if c != pk_column)
    stmt = text(
        f'INSERT INTO "{schema}"."{table}" ({col_list}) VALUES ({placeholders}) '
        f'ON CONFLICT ("{pk_column}") DO UPDATE SET {updates}'
    )
    with engine.connect() as conn:
        for _, row in df.iterrows():
            conn.execute(stmt, row.to_dict())
        conn.commit()


def write_to_staging(engine: Engine, changeset: Changeset, staging_schema: str):
    """Write a Changeset to the staging schema."""
    table = changeset.table_name

    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{staging_schema}"'))
        conn.execute(text(_meta_table_ddl(staging_schema)))
        conn.commit()

    if len(changeset.inserts) > 0:
        _ensure_table(engine, table, changeset.inserts, staging_schema)
        _insert_rows(engine, table, changeset.inserts, staging_schema)
        logger.dim(f"    Staged {len(changeset.inserts)} inserts for '{table}'")

    if len(changeset.updates) > 0:
        _ensure_table(engine, table, changeset.updates, staging_schema)
        _insert_rows(engine, table, changeset.updates, staging_schema)
        logger.dim(f"    Staged {len(changeset.updates)} updates for '{table}'")

    if len(changeset.deletes) > 0:
        pk_col = changeset.deletes.columns[0]
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
    """Load current staging tables as DataFrames to seed watcher snapshots on restart."""
    from nereid.utils.db import get_table_names

    snapshots = {}
    try:
        tables = get_table_names(engine, schema=staging_schema)
    except Exception:
        return snapshots

    for table_name in tables:
        if table_name == _META_TABLE:
            continue
        try:
            with engine.connect() as conn:
                result = conn.execute(text(f'SELECT * FROM "{staging_schema}"."{table_name}"'))
                df = pd.DataFrame(result.fetchall(), columns=list(result.keys()))
            snapshots[table_name] = df
        except Exception:
            pass

    return snapshots


def _get_pk_column(engine: Engine, table_name: str, schema: str) -> str | None:
    """Detect the primary key column for a table."""
    inspector = inspect(engine)
    pk = inspector.get_pk_constraint(table_name, schema=schema)
    cols = pk.get("constrained_columns", [])
    return cols[0] if cols else None


def promote_to_production(engine: Engine, staging_schema: str, production_schema: str = "public"):
    """Promote all staged changes to production using UPSERT."""
    from nereid.utils.db import get_table_names

    tables = get_table_names(engine, schema=staging_schema)
    promoted = 0

    for table_name in tables:
        if table_name == _META_TABLE:
            continue

        with engine.connect() as conn:
            result = conn.execute(text(f'SELECT * FROM "{staging_schema}"."{table_name}"'))
            staged_df = pd.DataFrame(result.fetchall(), columns=list(result.keys()))

        if staged_df.empty:
            continue

        # ── Auto-create production table if it doesn't exist ──────────────
        _ensure_production_table(engine, table_name, staged_df, production_schema)

        pk_col = _get_pk_column(engine, table_name, production_schema)
        if not pk_col:
            logger.warning(f"  No PK found for '{table_name}' — skipping promotion.")
            continue

        staged_df = staged_df.drop_duplicates(subset=[pk_col], keep="last")
        _upsert_df(staged_df, table_name, engine, production_schema, pk_col)
        promoted += 1
        logger.success(f"  Promoted '{table_name}' → {production_schema} ({len(staged_df)} rows)")

    _apply_staged_deletes(engine, staging_schema, production_schema)
    clear_staging(engine, staging_schema)
    return promoted


def _ensure_production_table(engine: Engine, table_name: str, df: pd.DataFrame, schema: str):
    """
    Create the production table from DataFrame columns if it doesn't exist,
    and ensure an 'id' primary key column is present.
    """
    cols_ddl = ", ".join(f'"{c}" TEXT' for c in df.columns if c != "id")

    with engine.connect() as conn:
        # Create table with id as primary key if it doesn't exist
        if "id" in df.columns:
            conn.execute(text(
                f'CREATE TABLE IF NOT EXISTS "{schema}"."{table_name}" '
                f'("id" TEXT PRIMARY KEY, {cols_ddl})'
            ))
        else:
            # No id column — create without PK, warn the user
            all_cols = ", ".join(f'"{c}" TEXT' for c in df.columns)
            conn.execute(text(
                f'CREATE TABLE IF NOT EXISTS "{schema}"."{table_name}" ({all_cols})'
            ))
            logger.warning(
                f"  '{table_name}' has no 'id' column — created without PK. "
                "Upsert will be skipped."
            )
        conn.commit()


def clear_staging(engine: Engine, staging_schema: str):
    """Truncate all staging tables after promotion or rejection."""
    from nereid.utils.db import get_table_names

    try:
        tables = get_table_names(engine, schema=staging_schema)
    except Exception:
        return

    with engine.connect() as conn:
        for table_name in tables:
            conn.execute(text(f'TRUNCATE TABLE "{staging_schema}"."{table_name}" RESTART IDENTITY'))
        conn.commit()
    logger.dim("Staging schema cleared.")


def _apply_staged_deletes(engine: Engine, staging_schema: str, production_schema: str):
    """Apply staged DELETE operations to production."""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT * FROM \"{staging_schema}\".\"{_META_TABLE}\" WHERE operation = 'DELETE'")
            )
            meta_df = pd.DataFrame(result.fetchall(), columns=list(result.keys()))

        if meta_df.empty:
            return

        with engine.connect() as conn:
            for _, row in meta_df.iterrows():
                table = row["table_name"]
                pk_val = row["row_pk"]
                conn.execute(
                    text(f'DELETE FROM "{production_schema}"."{table}" WHERE id = :pk'),
                    {"pk": pk_val},
                )
            conn.commit()

        logger.dim(f"Applied {len(meta_df)} staged deletes to production.")
    except Exception as e:
        logger.warning(f"Could not apply staged deletes: {e}")