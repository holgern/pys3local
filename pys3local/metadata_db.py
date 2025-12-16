"""SQLite-based metadata storage for Drime file entries.

This module provides persistent storage for MD5 hashes and other metadata
that cannot be reliably stored in the Drime API (e.g., entry.hash is not MD5).
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)


class MetadataDB:
    """SQLite-based metadata storage for Drime file entries.

    This database stores MD5 hashes and other metadata for files stored in Drime.
    The database is shared across all workspaces, with workspace_id providing isolation.

    Schema:
        drime_files:
            - file_entry_id: Drime's internal file ID (unique)
            - workspace_id: Drime workspace ID
            - md5_hash: MD5 hash of file content
            - file_size: File size in bytes
            - bucket_name: S3 bucket name
            - object_key: S3 object key
            - created_at: When MD5 was first calculated
            - updated_at: Last verification/update timestamp
    """

    def __init__(self, db_path: Path | None = None):
        """Initialize metadata database.

        Args:
            db_path: Path to SQLite database file.
                    If None, uses default location in config directory.
        """
        if db_path is None:
            from pys3local.config import CONFIG_DIR

            db_path = CONFIG_DIR / "metadata.db"

        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        # Ensure directory exists (works on Windows and Unix)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS drime_files (
                    id INTEGER PRIMARY KEY,
                    file_entry_id INTEGER UNIQUE NOT NULL,
                    workspace_id INTEGER NOT NULL,
                    md5_hash TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    bucket_name TEXT NOT NULL,
                    object_key TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    UNIQUE (workspace_id, bucket_name, object_key)
                );

                CREATE INDEX IF NOT EXISTS idx_file_entry_id
                    ON drime_files(file_entry_id);
                CREATE INDEX IF NOT EXISTS idx_workspace_bucket_key
                    ON drime_files(workspace_id, bucket_name, object_key);
                CREATE INDEX IF NOT EXISTS idx_md5_hash
                    ON drime_files(md5_hash);
            """)

        logger.debug(f"Metadata database initialized at {self.db_path}")

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get database connection with transaction handling.

        Yields:
            SQLite connection with row_factory set
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_md5(self, file_entry_id: int, workspace_id: int) -> str | None:
        """Get cached MD5 hash for a file entry.

        Args:
            file_entry_id: Drime file entry ID
            workspace_id: Drime workspace ID

        Returns:
            MD5 hash string or None if not found
        """
        with self._get_connection() as conn:
            result = conn.execute(
                "SELECT md5_hash FROM drime_files WHERE "
                "file_entry_id = ? AND workspace_id = ?",
                (file_entry_id, workspace_id),
            ).fetchone()
            return result["md5_hash"] if result else None

    def set_md5(
        self,
        file_entry_id: int,
        workspace_id: int,
        md5_hash: str,
        file_size: int,
        bucket_name: str,
        object_key: str,
    ) -> None:
        """Store or update MD5 hash for a file entry.

        Args:
            file_entry_id: Drime file entry ID
            workspace_id: Drime workspace ID
            md5_hash: MD5 hash of file content
            file_size: File size in bytes
            bucket_name: S3 bucket name
            object_key: S3 object key
        """
        now = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            # Use INSERT OR REPLACE to handle both new and existing entries
            # Preserve created_at if updating existing entry
            conn.execute(
                """
                INSERT OR REPLACE INTO drime_files
                (file_entry_id, workspace_id, md5_hash, file_size,
                 bucket_name, object_key, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?,
                    COALESCE(
                        (SELECT created_at FROM drime_files WHERE file_entry_id = ?),
                        ?
                    ),
                    ?)
            """,
                (
                    file_entry_id,
                    workspace_id,
                    md5_hash,
                    file_size,
                    bucket_name,
                    object_key,
                    file_entry_id,
                    now,
                    now,
                ),
            )

        logger.debug(
            f"Stored MD5 for file_entry_id={file_entry_id} "
            f"({bucket_name}/{object_key}): {md5_hash}"
        )

    def remove_md5(self, file_entry_id: int, workspace_id: int) -> bool:
        """Remove MD5 hash from cache.

        Args:
            file_entry_id: Drime file entry ID
            workspace_id: Drime workspace ID

        Returns:
            True if entry was removed, False if not found
        """
        with self._get_connection() as conn:
            result = conn.execute(
                "DELETE FROM drime_files WHERE file_entry_id = ? AND workspace_id = ?",
                (file_entry_id, workspace_id),
            )
            deleted = result.rowcount > 0
            if deleted:
                logger.debug(f"Removed MD5 for file_entry_id={file_entry_id}")
            return deleted

    def get_md5_by_key(
        self, workspace_id: int, bucket_name: str, object_key: str
    ) -> str | None:
        """Get MD5 hash by S3 path (without file_entry_id).

        Args:
            workspace_id: Drime workspace ID
            bucket_name: S3 bucket name
            object_key: S3 object key

        Returns:
            MD5 hash string or None if not found
        """
        with self._get_connection() as conn:
            result = conn.execute(
                """SELECT md5_hash FROM drime_files
                   WHERE workspace_id = ? AND bucket_name = ? AND object_key = ?""",
                (workspace_id, bucket_name, object_key),
            ).fetchone()
            return result["md5_hash"] if result else None

    def cleanup_workspace(self, workspace_id: int) -> int:
        """Remove all entries for a workspace.

        Args:
            workspace_id: Drime workspace ID

        Returns:
            Number of entries removed
        """
        with self._get_connection() as conn:
            result = conn.execute(
                "DELETE FROM drime_files WHERE workspace_id = ?", (workspace_id,)
            )
            count = result.rowcount
            logger.info(f"Cleaned up {count} entries for workspace {workspace_id}")
            return count

    def cleanup_bucket(self, workspace_id: int, bucket_name: str) -> int:
        """Remove all entries for a bucket.

        Args:
            workspace_id: Drime workspace ID
            bucket_name: S3 bucket name

        Returns:
            Number of entries removed
        """
        with self._get_connection() as conn:
            result = conn.execute(
                "DELETE FROM drime_files WHERE workspace_id = ? AND bucket_name = ?",
                (workspace_id, bucket_name),
            )
            count = result.rowcount
            logger.info(
                f"Cleaned up {count} entries for bucket {bucket_name} "
                f"in workspace {workspace_id}"
            )
            return count

    def get_stats(self, workspace_id: int | None = None) -> dict[str, int | str | None]:
        """Get cache statistics.

        Args:
            workspace_id: Drime workspace ID, or None for all workspaces

        Returns:
            Dictionary with statistics:
                - total_files: Number of files in cache
                - total_size: Total size of cached files
                - oldest_entry: Timestamp of oldest entry
                - newest_entry: Timestamp of newest entry
        """
        with self._get_connection() as conn:
            if workspace_id is None:
                result = conn.execute(
                    """SELECT
                        COUNT(*) as total_files,
                        SUM(file_size) as total_size,
                        MIN(created_at) as oldest_entry,
                        MAX(updated_at) as newest_entry
                    FROM drime_files"""
                ).fetchone()
            else:
                result = conn.execute(
                    """SELECT
                        COUNT(*) as total_files,
                        SUM(file_size) as total_size,
                        MIN(created_at) as oldest_entry,
                        MAX(updated_at) as newest_entry
                    FROM drime_files WHERE workspace_id = ?""",
                    (workspace_id,),
                ).fetchone()

            return {
                "total_files": result["total_files"] or 0,
                "total_size": result["total_size"] or 0,
                "oldest_entry": result["oldest_entry"],
                "newest_entry": result["newest_entry"],
            }

    def list_workspaces(self) -> list[int]:
        """List all workspace IDs in the cache.

        Returns:
            List of workspace IDs
        """
        with self._get_connection() as conn:
            results = conn.execute(
                "SELECT DISTINCT workspace_id FROM drime_files ORDER BY workspace_id"
            ).fetchall()
            return [row["workspace_id"] for row in results]

    def vacuum(self) -> None:
        """Optimize database by reclaiming unused space.

        This should be called periodically after large deletions.
        """
        with self._get_connection() as conn:
            conn.execute("VACUUM")
        logger.info("Database vacuumed successfully")
