"""
Nereid Differ — computes row-level diffs between two DataFrames.

Given an "old" state (last synced snapshot) and a "new" state (current file),
produces categorized changesets: inserts, updates, deletes.
"""

import pandas as pd
from dataclasses import dataclass


@dataclass
class Changeset:
    table_name: str
    inserts: pd.DataFrame
    updates: pd.DataFrame
    deletes: pd.DataFrame

    @property
    def is_empty(self) -> bool:
        return (
            len(self.inserts) == 0
            and len(self.updates) == 0
            and len(self.deletes) == 0
        )

    def summary(self) -> str:
        parts = []
        if len(self.inserts):
            parts.append(f"+{len(self.inserts)} inserts")
        if len(self.updates):
            parts.append(f"~{len(self.updates)} updates")
        if len(self.deletes):
            parts.append(f"-{len(self.deletes)} deletes")
        return ", ".join(parts) if parts else "no changes"


def compute_diff(
    old_df: pd.DataFrame,
    new_df: pd.DataFrame,
    pk_column: str,
    table_name: str,
) -> Changeset:
    """
    Compute a row-level diff between old and new DataFrames.

    Args:
        old_df: The last known state (snapshot from previous sync).
        new_df: The current state from the file.
        pk_column: Column used as the unique row identifier.
        table_name: Name of the table being diffed (for labeling).

    Returns:
        A Changeset with inserts, updates, and deletes.
    """
    if pk_column not in old_df.columns:
        raise ValueError(f"PK column '{pk_column}' not found in old snapshot for table '{table_name}'.")
    if pk_column not in new_df.columns:
        raise ValueError(f"PK column '{pk_column}' not found in new data for table '{table_name}'.")

    # Normalize types — convert everything to string for safe comparison
    old_df = old_df.copy().astype(str)
    new_df = new_df.copy().astype(str)

    old_indexed = old_df.set_index(pk_column)
    new_indexed = new_df.set_index(pk_column)

    old_pks = set(old_indexed.index)
    new_pks = set(new_indexed.index)

    # ── Inserts: PKs in new but not in old ──────────────────────────────────
    inserted_pks = new_pks - old_pks
    inserts = new_df[new_df[pk_column].isin(inserted_pks)].reset_index(drop=True)

    # ── Deletes: PKs in old but not in new ──────────────────────────────────
    deleted_pks = old_pks - new_pks
    deletes = old_df[old_df[pk_column].isin(deleted_pks)].reset_index(drop=True)

    # ── Updates: PKs in both, but row content changed ────────────────────────
    common_pks = old_pks & new_pks
    common_cols = [c for c in old_indexed.columns if c in new_indexed.columns]

    old_common = old_indexed.loc[list(common_pks), common_cols].sort_index()
    new_common = new_indexed.loc[list(common_pks), common_cols].sort_index()

    # Find rows where any column value changed
    changed_mask = ~(old_common == new_common).all(axis=1)
    changed_pks = old_common[changed_mask].index.tolist()

    updates = new_df[new_df[pk_column].isin(changed_pks)].reset_index(drop=True)

    return Changeset(
        table_name=table_name,
        inserts=inserts,
        updates=updates,
        deletes=deletes,
    )