"""
Nereid database utilities — connection management and schema helpers.
"""

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import Engine


def get_engine(db_url: str) -> Engine:
    """Create and return a SQLAlchemy engine."""
    return create_engine(db_url, future=True)


def ensure_staging_schema(engine: Engine, staging_schema: str):
    """Create the staging schema if it doesn't exist."""
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{staging_schema}"'))
        conn.commit()


def get_table_names(engine: Engine, schema: str = "public") -> list[str]:
    """Return all table names in a given schema."""
    inspector = inspect(engine)
    return inspector.get_table_names(schema=schema)


def table_exists(engine: Engine, table_name: str, schema: str = "public") -> bool:
    """Check if a table exists in a given schema."""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names(schema=schema)


def get_primary_key_columns(engine: Engine, table_name: str, schema: str = "public") -> list[str]:
    """Return the primary key column names for a table."""
    inspector = inspect(engine)
    pk_info = inspector.get_pk_constraint(table_name, schema=schema)
    return pk_info.get("constrained_columns", [])