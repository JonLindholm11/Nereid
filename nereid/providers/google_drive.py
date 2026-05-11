"""
Google Drive cloud provider for Nereid.

Authentication: service account credentials via environment variables.
No JSON key file needed in the project directory.

Required env vars:
  NEREID_GDRIVE_CLIENT_EMAIL   — service account email
  NEREID_GDRIVE_PRIVATE_KEY    — private key (copy from JSON key file)
  NEREID_GDRIVE_PROJECT_ID     — google cloud project ID

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

from dotenv import load_dotenv
from nereid.providers.base import CloudProvider

load_dotenv()

_GSHEET_MIME = "application/vnd.google-apps.spreadsheet"
_GDRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
_XLSX_EXPORT_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _require_gdrive_deps():
    try:
        import googleapiclient  # noqa: F401
        import google.oauth2     # noqa: F401
    except ImportError:
        raise RuntimeError(
            "Google Drive dependencies are not installed.\n"
            "  Run: pip install nereid[gdrive]"
        )


def _build_credentials():
    """
    Build Google service account credentials from environment variables.
    Falls back to a credentials file if NEREID_GDRIVE_CREDENTIALS_FILE is set,
    for backwards compatibility.
    """
    _require_gdrive_deps()
    from google.oauth2.service_account import Credentials

    # Legacy file-based auth — still supported as fallback
    creds_file = os.getenv("NEREID_GDRIVE_CREDENTIALS_FILE")
    if creds_file:
        return Credentials.from_service_account_file(
            creds_file,
            scopes=["https://www.googleapis.com/auth/drive"],
        )

    # Preferred: env var based auth
    client_email = os.getenv("NEREID_GDRIVE_CLIENT_EMAIL")
    private_key = os.getenv("NEREID_GDRIVE_PRIVATE_KEY")
    project_id = os.getenv("NEREID_GDRIVE_PROJECT_ID")

    if not all([client_email, private_key, project_id]):
        raise RuntimeError(
            "Google Drive credentials not found.\n"
            "  Set these in your .env:\n"
            "    NEREID_GDRIVE_CLIENT_EMAIL\n"
            "    NEREID_GDRIVE_PRIVATE_KEY\n"
            "    NEREID_GDRIVE_PROJECT_ID\n"
            "  Or set NEREID_GDRIVE_CREDENTIALS_FILE to a service account JSON path."
        )

    # The private key in .env has literal \n — convert to real newlines
    private_key = private_key.replace("\\n", "\n")

    info = {
        "type": "service_account",
        "project_id": project_id,
        "client_email": client_email,
        "private_key": private_key,
        "token_uri": "https://oauth2.googleapis.com/token",
    }

    return Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/drive"],
    )


class GoogleDriveProvider(CloudProvider):
    """
    Downloads files from Google Drive using service account credentials
    sourced from environment variables. No JSON key file required in project.

    Parameters
    ----------
    file_id:
        Google Drive file ID (the long alphanumeric string in the file URL).
    credentials_file:
        Optional path to service account JSON — only used as legacy fallback.
    """

    def __init__(self, file_id: str, credentials_file: str | None = None) -> None:
        self._file_id = file_id
        self._credentials_file = credentials_file  # legacy fallback
        self._service = None
        self._cached_meta: dict | None = None

    def _get_service(self):
        if self._service is not None:
            return self._service

        _require_gdrive_deps()
        from googleapiclient.discovery import build

        # If legacy credentials_file was passed, set it temporarily
        if self._credentials_file:
            import os
            os.environ.setdefault("NEREID_GDRIVE_CREDENTIALS_FILE", self._credentials_file)

        creds = _build_credentials()
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def _get_meta(self) -> dict:
        service = self._get_service()
        meta = (
            service.files()
            .get(fileId=self._file_id, fields="id,name,mimeType,modifiedTime")
            .execute()
        )
        self._cached_meta = meta
        return meta

    def validate_credentials(self) -> None:
        meta = self._get_meta()
        if meta.get("mimeType") == _GDRIVE_FOLDER_MIME:
            raise ValueError(
                f"The file ID '{self._file_id}' points to a folder, not a file.\n"
                "  Provide the ID of the specific XLSX file or Google Sheet."
            )

    def get_last_modified(self) -> float:
        meta = self._get_meta()
        raw = meta["modifiedTime"]
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.timestamp()

    def download_to_tempfile(self, dest_path: Path) -> None:
        _require_gdrive_deps()
        from googleapiclient.http import MediaIoBaseDownload

        service = self._get_service()
        meta = self._get_meta()
        mime = meta.get("mimeType", "")

        if mime == _GSHEET_MIME:
            request = service.files().export_media(
                fileId=self._file_id,
                mimeType=_XLSX_EXPORT_MIME,
            )
        else:
            request = service.files().get_media(fileId=self._file_id)

        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        dest_path.write_bytes(buf.getvalue())

    def get_file_name(self) -> str:
        return self._get_meta().get("name", "nereid_drive_file")

    def get_file_mime(self) -> str:
        return self._get_meta().get("mimeType", "")

    def list_folder_files(self, folder_id: str) -> list[dict]:
        service = self._get_service()
        _XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        _CSV_MIME  = "text/csv"

        query = (
            f"'{folder_id}' in parents and trashed = false and "
            f"(mimeType = '{_XLSX_MIME}' or mimeType = '{_CSV_MIME}' or mimeType = '{_GSHEET_MIME}')"
        )

        result = (
            service.files()
            .list(q=query, fields="files(id,name,mimeType,modifiedTime)")
            .execute()
        )
        return result.get("files", [])

    def upload_file(self, folder_id: str, local_path: Path, file_name: str) -> str:
        _require_gdrive_deps()
        from googleapiclient.http import MediaFileUpload

        service   = self._get_service()
        suffix    = Path(file_name).suffix.lower()
        mime_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if suffix == ".xlsx" else "text/csv"
        )

        metadata = {"name": file_name, "parents": [folder_id]}
        media    = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)

        file = (
            service.files()
            .create(body=metadata, media_body=media, fields="id")
            .execute()
        )
        return file.get("id")

    def overwrite_file(self, file_id: str, local_path: Path) -> None:
        _require_gdrive_deps()
        from googleapiclient.http import MediaFileUpload

        service   = self._get_service()
        suffix    = Path(local_path).suffix.lower()
        mime_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if suffix == ".xlsx" else "text/csv"
        )

        media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)
        service.files().update(fileId=file_id, media_body=media).execute()