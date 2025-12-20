"""SQLite-based metadata storage for S3 objects.

This module provides persistent storage for S3 object metadata:
- Local provider: Complete S3 object metadata (replaces JSON files)
- Drime provider: MD5 hashes (legacy, no longer actively used)
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from collections.abc import Generator


class LocalObjectMetadata(TypedDict):
    """Type definition for local object metadata."""

    bucket_name: str
    object_key: str
    size: int
    etag: str
    last_modified: datetime
    content_type: str
    metadata: dict[str, str]
    storage_class: str


logger = logging.getLogger(__name__)


class MetadataDB:
    """SQLite-based metadata storage for S3 objects.

    This database stores metadata for S3 objects from different providers.

    Schema:
        local_objects: (Used by LocalStorageProvider)
            - bucket_name: S3 bucket name
            - object_key: S3 object key
            - size: File size in bytes
            - etag: S3 ETag (MD5 hash)
            - last_modified: Last modification timestamp
            - content_type: MIME content type
            - metadata: JSON string of user metadata
            - storage_class: Storage class (e.g., STANDARD)

        drime_files: (Legacy, no longer actively used)
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
                -- Local storage objects table
                CREATE TABLE IF NOT EXISTS local_objects (
                    id INTEGER PRIMARY KEY,
                    bucket_name TEXT NOT NULL,
                    object_key TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    etag TEXT NOT NULL,
                    last_modified TIMESTAMP NOT NULL,
                    content_type TEXT NOT NULL,
                    metadata TEXT,
                    storage_class TEXT DEFAULT 'STANDARD',
                    UNIQUE (bucket_name, object_key)
                );

                CREATE INDEX IF NOT EXISTS idx_local_bucket_key
                    ON local_objects(bucket_name, object_key);
                CREATE INDEX IF NOT EXISTS idx_local_bucket
                    ON local_objects(bucket_name);

                -- Drime files table (legacy, no longer actively used)
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

    # =========================================================================
    # Local storage methods
    # =========================================================================

    def set_local_object(
        self,
        bucket_name: str,
        object_key: str,
        size: int,
        etag: str,
        last_modified: datetime,
        content_type: str,
        metadata: dict[str, str] | None = None,
        storage_class: str = "STANDARD",
    ) -> None:
        """Store or update metadata for a local object.

        Args:
            bucket_name: S3 bucket name
            object_key: S3 object key
            size: File size in bytes
            etag: S3 ETag (MD5 hash)
            last_modified: Last modification timestamp
            content_type: MIME content type
            metadata: User metadata dictionary
            storage_class: Storage class (default: STANDARD)
        """
        import json

        metadata_json = json.dumps(metadata or {})

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO local_objects
                (bucket_name, object_key, size, etag, last_modified,
                 content_type, metadata, storage_class)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    bucket_name,
                    object_key,
                    size,
                    etag,
                    last_modified.isoformat(),
                    content_type,
                    metadata_json,
                    storage_class,
                ),
            )

        logger.debug(f"Stored metadata for {bucket_name}/{object_key}")

    def get_local_object(
        self, bucket_name: str, object_key: str
    ) -> LocalObjectMetadata | None:
        """Get metadata for a local object.

        Args:
            bucket_name: S3 bucket name
            object_key: S3 object key

        Returns:
            Dictionary with object metadata or None if not found
        """
        import json

        with self._get_connection() as conn:
            result = conn.execute(
                """SELECT bucket_name, object_key, size, etag, last_modified,
                          content_type, metadata, storage_class
                   FROM local_objects
                   WHERE bucket_name = ? AND object_key = ?""",
                (bucket_name, object_key),
            ).fetchone()

            if not result:
                return None

            return {
                "bucket_name": result["bucket_name"],
                "object_key": result["object_key"],
                "size": result["size"],
                "etag": result["etag"],
                "last_modified": datetime.fromisoformat(result["last_modified"]),
                "content_type": result["content_type"],
                "metadata": json.loads(result["metadata"] or "{}"),
                "storage_class": result["storage_class"],
            }

    def delete_local_object(self, bucket_name: str, object_key: str) -> bool:
        """Delete metadata for a local object.

        Args:
            bucket_name: S3 bucket name
            object_key: S3 object key

        Returns:
            True if object was deleted, False if not found
        """
        with self._get_connection() as conn:
            result = conn.execute(
                "DELETE FROM local_objects WHERE bucket_name = ? AND object_key = ?",
                (bucket_name, object_key),
            )
            deleted = result.rowcount > 0
            if deleted:
                logger.debug(f"Deleted metadata for {bucket_name}/{object_key}")
            return deleted

    def list_local_objects(
        self, bucket_name: str, prefix: str = ""
    ) -> list[LocalObjectMetadata]:
        """List all objects in a bucket.

        Args:
            bucket_name: S3 bucket name
            prefix: Optional key prefix filter

        Returns:
            List of object metadata dictionaries
        """
        import json

        with self._get_connection() as conn:
            if prefix:
                results = conn.execute(
                    """SELECT bucket_name, object_key, size, etag, last_modified,
                              content_type, metadata, storage_class
                       FROM local_objects
                       WHERE bucket_name = ? AND object_key LIKE ?
                       ORDER BY object_key""",
                    (bucket_name, f"{prefix}%"),
                ).fetchall()
            else:
                results = conn.execute(
                    """SELECT bucket_name, object_key, size, etag, last_modified,
                              content_type, metadata, storage_class
                       FROM local_objects
                       WHERE bucket_name = ?
                       ORDER BY object_key""",
                    (bucket_name,),
                ).fetchall()

            objects = []
            for row in results:
                objects.append(
                    {
                        "bucket_name": row["bucket_name"],
                        "object_key": row["object_key"],
                        "size": row["size"],
                        "etag": row["etag"],
                        "last_modified": datetime.fromisoformat(row["last_modified"]),
                        "content_type": row["content_type"],
                        "metadata": json.loads(row["metadata"] or "{}"),
                        "storage_class": row["storage_class"],
                    }
                )

            return objects

    def cleanup_local_bucket(self, bucket_name: str) -> int:
        """Remove all objects for a bucket.

        Args:
            bucket_name: S3 bucket name

        Returns:
            Number of objects removed
        """
        with self._get_connection() as conn:
            result = conn.execute(
                "DELETE FROM local_objects WHERE bucket_name = ?", (bucket_name,)
            )
            count = result.rowcount
            logger.info(f"Cleaned up {count} objects for bucket {bucket_name}")
            return count

    def get_local_stats(self, bucket_name: str | None = None) -> dict[str, int | None]:
        """Get statistics for local storage.

        Args:
            bucket_name: Optional bucket name to filter by

        Returns:
            Dictionary with statistics:
                - total_objects: Number of objects
                - total_size: Total size in bytes
        """
        with self._get_connection() as conn:
            if bucket_name is None:
                result = conn.execute(
                    """SELECT
                        COUNT(*) as total_objects,
                        SUM(size) as total_size
                    FROM local_objects"""
                ).fetchone()
            else:
                result = conn.execute(
                    """SELECT
                        COUNT(*) as total_objects,
                        SUM(size) as total_size
                    FROM local_objects WHERE bucket_name = ?""",
                    (bucket_name,),
                ).fetchone()

            return {
                "total_objects": result["total_objects"] or 0,
                "total_size": result["total_size"] or 0,
            }

    def list_local_buckets(self) -> list[str]:
        """List all bucket names with objects.

        Returns:
            List of bucket names
        """
        with self._get_connection() as conn:
            results = conn.execute(
                "SELECT DISTINCT bucket_name FROM local_objects ORDER BY bucket_name"
            ).fetchall()
            return [row["bucket_name"] for row in results]
