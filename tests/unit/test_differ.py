"""
Unit tests for the Nereid diff engine.
"""

import pandas as pd
import pytest
from nereid.core.differ import compute_diff


def make_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_no_changes():
    df = make_df([{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}])
    cs = compute_diff(df, df.copy(), pk_column="id", table_name="users")
    assert cs.is_empty


def test_insert():
    old = make_df([{"id": 1, "name": "Alice"}])
    new = make_df([{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}])
    cs = compute_diff(old, new, pk_column="id", table_name="users")
    assert len(cs.inserts) == 1
    assert len(cs.updates) == 0
    assert len(cs.deletes) == 0


def test_delete():
    old = make_df([{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}])
    new = make_df([{"id": 1, "name": "Alice"}])
    cs = compute_diff(old, new, pk_column="id", table_name="users")
    assert len(cs.inserts) == 0
    assert len(cs.updates) == 0
    assert len(cs.deletes) == 1


def test_update():
    old = make_df([{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}])
    new = make_df([{"id": 1, "name": "Alice"}, {"id": 2, "name": "Robert"}])
    cs = compute_diff(old, new, pk_column="id", table_name="users")
    assert len(cs.inserts) == 0
    assert len(cs.updates) == 1
    assert len(cs.deletes) == 0


def test_mixed_changes():
    old = make_df([
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
        {"id": 3, "name": "Charlie"},
    ])
    new = make_df([
        {"id": 1, "name": "Alicia"},   # update
        {"id": 3, "name": "Charlie"},   # unchanged
        {"id": 4, "name": "Diana"},     # insert
        # id=2 deleted
    ])
    cs = compute_diff(old, new, pk_column="id", table_name="users")
    assert len(cs.inserts) == 1
    assert len(cs.updates) == 1
    assert len(cs.deletes) == 1


def test_missing_pk_raises():
    old = make_df([{"id": 1, "name": "Alice"}])
    new = make_df([{"name": "Alice"}])  # no id column
    with pytest.raises(ValueError, match="PK column"):
        compute_diff(old, new, pk_column="id", table_name="users")


def test_empty_old_all_inserts():
    old = pd.DataFrame(columns=["id", "name"])
    new = make_df([{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}])
    cs = compute_diff(old, new, pk_column="id", table_name="users")
    assert len(cs.inserts) == 2
    assert cs.is_empty is False