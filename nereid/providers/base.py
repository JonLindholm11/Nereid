"""
Abstract base class for Nereid cloud storage providers.

To add a new provider (Dropbox, OneDrive, etc.):
  1. Create nereid/providers/<name>.py
  2. Subclass CloudProvider and implement the three abstract methods
  3. Add a subcommand to `nereid connect` and `nereid watch-cloud`
"""

from abc import ABC, abstractmethod
from pathlib import Path


class CloudProvider(ABC):
    """
    Interface that every cloud storage provider must implement.

    Nereid calls these methods to detect changes and download files
    without knowing anything about the underlying storage service.
    """

    @abstractmethod
    def validate_credentials(self) -> None:
        """
        Verify that stored credentials are valid and the target file is accessible.

        Raises a descriptive exception if anything is wrong so the user
        gets a clear error at `nereid connect` time rather than at sync time.
        """

    @abstractmethod
    def get_last_modified(self) -> float:
        """
        Return the remote file's last-modified time as a Unix timestamp (float).

        Called on every poll cycle. A cheap metadata-only request — must NOT
        download the file. The cloud watcher compares this against the
        previously seen value to decide whether a download is needed.
        """

    @abstractmethod
    def download_to_tempfile(self, dest_path: Path) -> None:
        """
        Download the remote file and write its bytes to dest_path.

        dest_path already exists (created by mkstemp). Overwrite it.
        The caller is responsible for deleting the file afterwards.
        """

    @abstractmethod
    def get_file_name(self) -> str:
        """Return the human-readable file name of the remote file."""

    @abstractmethod
    def get_file_mime(self) -> str:
        """Return the MIME type of the remote file."""
