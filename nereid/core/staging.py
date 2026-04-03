"""
Nereid Staging — manages the staging schema in PostgreSQL.

Changesets are written here first.
Production is only touched after explicit review + approval.
"""

import pandas as pd
from sqlalchemy import text, inspect
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


def _df_to_sql(df: pd.DataFrame, table: str, engine: Engine, schema: str, if_exists: str = "append"):
    """Write a DataFrame to PostgreSQL using raw INSERT."""
    with engine.connect() as conn:
        df.head(0).to_sql(table, conn, schema=schema, if_exists=if_exists, index=False)
        conn.commit()

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
    """
    Upsert a DataFrame into a production table.
    Uses INSERT ... ON CONFLICT (pk) DO UPDATE to handle existing rows.
    """
    if df.empty:
        return

    cols = [c for c in df.columns]
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
        _df_to_sql(changeset.inserts, table, engine, staging_schema, if_exists="append")
        logger.dim(f"    Staged {len(changeset.inserts)} inserts for '{table}'")

    if len(changeset.updates) > 0:
        _df_to_sql(changeset.updates, table, engine, staging_schema, if_exists="append")
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

        # Detect PK from production table
        pk_col = _get_pk_column(engine, table_name, production_schema)
        if not pk_col:
            logger.warning(f"  No PK found for '{table_name}' — skipping promotion.")
            continue

        # Deduplicate staged rows — keep last version of each PK
        staged_df = staged_df.drop_duplicates(subset=[pk_col], keep="last")

        _upsert_df(staged_df, table_name, engine, production_schema, pk_col)
        promoted += 1
        logger.success(f"  Promoted '{table_name}' → {production_schema} ({len(staged_df)} rows)")

    _apply_staged_deletes(engine, staging_schema, production_schema)
    clear_staging(engine, staging_schema)
    return promoted


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