"""
Nereid configuration — loads and validates environment settings.
"""

import os
import json
from pathlib import Path
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


# ── Hosted multi-connection config ────────────────────────────────────────────

@dataclass
class ConnectionConfig:
    name: str
    folder_id: str
    db_url: str
    staging_schema: str = "nereid_staging"
    pk_column: str = "id"
    mode: str = "single"
    schema: str = "public"


@dataclass
class NereidHostedConfig:
    credentials_file: str
    poll_interval: float
    connections: list[ConnectionConfig]


def load_hosted_config(path: str = ".nereid-credentials.json") -> NereidHostedConfig:
    """
    Load hosted multi-connection config from .nereid-credentials.json.
    Generated automatically by `nereid connect google-drive`.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f".nereid-credentials.json not found at '{config_path.resolve()}'\n"
            "Run `nereid connect google-drive` to generate it."
        )

    with open(config_path) as f:
        raw = json.load(f)

    gdrive = raw.get("google_drive")
    if not gdrive:
        raise ValueError(
            "No google_drive config found in .nereid-credentials.json.\n"
            "Run `nereid connect google-drive` to set it up."
        )

    # Build credentials from env vars
    credentials_file = gdrive.get("credentials_file")  # legacy fallback

    connection = ConnectionConfig(
        name="default",
        folder_id=gdrive.get("folder_id", ""),
        db_url=gdrive.get("db_url") or os.getenv("NEREID_DB_URL", ""),
        staging_schema=gdrive.get("staging_schema", "nereid_staging"),
        pk_column=gdrive.get("pk_column", "id"),
        mode=gdrive.get("mode", "single"),
        schema="public",
    )

    return NereidHostedConfig(
        credentials_file=credentials_file or "",
        poll_interval=gdrive.get("poll_interval", 60),
        connections=[connection],
    )