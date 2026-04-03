"""
Nereid configuration — loads and validates environment settings.
"""

import os
from dataclasses import dataclass, field


@dataclass
class NereidConfig:
    db_url: str
    mode: str  # "single" | "multi"
    file_path: str | None = None
    folder_path: str | None = None
    pk_column: str = "id"
    staging_schema: str = "nereid_staging"
    debounce_seconds: float = 2.0
    tables: list[str] = field(default_factory=list)

    def validate(self):
        if not self.db_url:
            raise ValueError("NEREID_DB_URL is required.")
        if self.mode == "single" and not self.file_path:
            raise ValueError("NEREID_FILE_PATH is required in single mode.")
        if self.mode == "multi" and not self.folder_path:
            raise ValueError("NEREID_FOLDER_PATH is required in multi mode.")
        if self.mode not in ("single", "multi"):
            raise ValueError(f"Invalid mode: {self.mode}. Must be 'single' or 'multi'.")


def load_config() -> NereidConfig:
    """Load config from environment variables."""
    config = NereidConfig(
        db_url=os.getenv("NEREID_DB_URL", ""),
        mode=os.getenv("NEREID_MODE", "single"),
        file_path=os.getenv("NEREID_FILE_PATH"),
        folder_path=os.getenv("NEREID_FOLDER_PATH"),
        pk_column=os.getenv("NEREID_PK_COLUMN", "id"),
        staging_schema=os.getenv("NEREID_STAGING_SCHEMA", "nereid_staging"),
        debounce_seconds=float(os.getenv("NEREID_DEBOUNCE_SECONDS", "2")),
    )
    return config