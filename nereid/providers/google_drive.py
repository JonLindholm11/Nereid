"""
Google Drive cloud provider for Nereid.

Authentication: service account JSON key (downloaded from Google Cloud Console).
The target file must be shared with the service account's email address.

Supports:
  - Native Google Sheets  → exported to XLSX on download
  - Uploaded XLSX files   → downloaded directly
  - Uploaded CSV files    → downloaded directly

Install dependencies:
  pip install nereid[gdrive]
"""

import io
import os
from datetime import datetime, timezone
from pathlib import Path

from nereid.providers.base import CloudProvider

_GSHEET_MIME = "application/vnd.google-apps.spreadsheet"
_GDRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
_XLSX_EXPORT_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _require_gdrive_deps():
    """Raise a clear error if the optional google-drive extras are not installed."""
    try:
        import googleapiclient  # noqa: F401
        import google.oauth2  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "Google Drive dependencies are not installed.\n"
            "  Run: pip install nereid[gdrive]"
        )


class GoogleDriveProvider(CloudProvider):
    """
    Downloads files from Google Drive using a service account key.

    Parameters
    ----------
    credentials_file:
        Absolute path to the service account JSON key file.
    file_id:
        Google Drive file ID (the long alphanumeric string in the file URL).
    """

    def __init__(self, credentials_file: str, file_id: str) -> None:
        self._credentials_file = credentials_file
        self._file_id = file_id
        self._service = None
        self._cached_meta: dict | None = None

    # ── Internal helpers ────────────────────────────────────────────────────

    def _get_service(self):
        """Build and cache the Drive API service client."""
        if self._service is not None:
            return self._service

        _require_gdrive_deps()
        from googleapiclient.discovery import build
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_file(
            self._credentials_file,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def _get_meta(self) -> dict:
        """Fetch (and cache) file metadata: id, name, mimeType, modifiedTime."""
        service = self._get_service()
        meta = (
            service.files()
            .get(fileId=self._file_id, fields="id,name,mimeType,modifiedTime")
            .execute()
        )
        self._cached_meta = meta
        return meta

    # ── CloudProvider interface ─────────────────────────────────────────────

    def validate_credentials(self) -> None:
        """
        Verify credentials and file accessibility.
        Raises ValueError/RuntimeError with a user-friendly message on failure.
        """
        meta = self._get_meta()
        if meta.get("mimeType") == _GDRIVE_FOLDER_MIME:
            raise ValueError(
                f"The file ID '{self._file_id}' points to a folder, not a file.\n"
                "  Provide the ID of the specific XLSX file or Google Sheet."
            )

    def get_last_modified(self) -> float:
        """Return the file's modifiedTime as a Unix timestamp."""
        meta = self._get_meta()
        raw = meta["modifiedTime"]  # ISO 8601, e.g. "2024-01-15T10:30:00.000Z"
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.timestamp()

    def download_to_tempfile(self, dest_path: Path) -> None:
        """Download the Drive file to dest_path (overwrites existing content)."""
        _require_gdrive_deps()
        from googleapiclient.http import MediaIoBaseDownload

        service = self._get_service()
        meta = self._get_meta()
        mime = meta.get("mimeType", "")

        if mime == _GSHEET_MIME:
            # Native Google Sheet — export as XLSX so openpyxl can read it
            request = service.files().export_media(
                fileId=self._file_id,
                mimeType=_XLSX_EXPORT_MIME,
            )
        else:
            # Uploaded file (XLSX, CSV, etc.) — stream bytes directly
            request = service.files().get_media(fileId=self._file_id)

        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        dest_path.write_bytes(buf.getvalue())

    def get_file_name(self) -> str:
        """Return the Drive file's display name (e.g. 'clients.xlsx')."""
        return self._get_meta().get("name", "nereid_drive_file")

    def get_file_mime(self) -> str:
        """Return the Drive file's MIME type."""
        return self._get_meta().get("mimeType", "")
