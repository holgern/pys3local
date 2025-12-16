"""Drime Cloud storage provider for S3."""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pys3local.errors import (
    BucketAlreadyExists,
    BucketNotEmpty,
    NoSuchBucket,
    NoSuchKey,
)
from pys3local.models import Bucket, S3Object
from pys3local.provider import StorageProvider

if TYPE_CHECKING:
    from pydrime.api import DrimeClient  # type: ignore[import-untyped]
    from pydrime.models import FileEntry  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


class DrimeStorageProvider(StorageProvider):
    """Drime Cloud storage provider.

    Maps S3 concepts to Drime:
    - Buckets -> Top-level folders in workspace
    - Objects -> Files in those folders (supports nested paths)
    """

    def __init__(
        self,
        client: DrimeClient,
        workspace_id: int = 0,
        readonly: bool = False,
    ):
        """Initialize Drime storage provider.

        Args:
            client: Drime client instance (pydrime.DrimeClient)
            workspace_id: Drime workspace ID (0 for personal workspace)
            readonly: If True, disable write operations
        """
        self.client = client
        self.workspace_id = workspace_id
        self.readonly = readonly
        # Cache for folder IDs to reduce API calls
        self._folder_cache: dict[str, int | None] = {}

        logger.info(f"Drime storage initialized (workspace {workspace_id})")

    def _parse_datetime(self, dt_value: datetime | str | None) -> datetime:
        """Parse datetime value from pydrime (can be datetime or ISO string).

        Args:
            dt_value: Datetime object, ISO format string, or None

        Returns:
            Naive datetime object in UTC (for XML template compatibility)
        """
        if dt_value is None:
            return datetime.now(timezone.utc).replace(tzinfo=None)

        if isinstance(dt_value, datetime):
            # Convert to naive UTC datetime
            if dt_value.tzinfo is not None:
                # Convert to UTC and remove timezone info
                return dt_value.astimezone(timezone.utc).replace(tzinfo=None)
            # Already naive, assume it's UTC
            return dt_value

        # Parse ISO format string using pydrime's utility
        try:
            from pydrime.utils import parse_iso_timestamp

            parsed = parse_iso_timestamp(dt_value)
            if parsed is not None:
                # parse_iso_timestamp returns naive local time
                # We need to ensure it's in UTC format
                if parsed.tzinfo is not None:
                    # Has timezone, convert to UTC and make naive
                    return parsed.astimezone(timezone.utc).replace(tzinfo=None)
                # Already naive, assume it's UTC
                return parsed
        except (ValueError, AttributeError, ImportError) as e:
            logger.warning(f"Failed to parse datetime '{dt_value}': {e}")

        return datetime.now(timezone.utc).replace(tzinfo=None)

    def _get_folder_id_by_path(
        self, folder_path: str, create: bool = False
    ) -> int | None:
        """Get the folder ID for a given path, optionally creating it.

        Args:
            folder_path: Path like "bucket/subfolder" (without leading slash)
            create: If True, create missing folders

        Returns:
            Folder ID or None for root
        """
        if not folder_path:
            return None

        # Check cache first
        if folder_path in self._folder_cache:
            return self._folder_cache[folder_path]

        from pydrime.models import FileEntriesResult

        parts = folder_path.split("/")
        current_folder_id: int | None = None

        for i, part in enumerate(parts):
            # Check cache for partial path
            partial_path = "/".join(parts[: i + 1])
            if partial_path in self._folder_cache:
                current_folder_id = self._folder_cache[partial_path]
                continue

            # Get entries in current folder
            params: dict[str, Any] = {
                "workspace_id": self.workspace_id,
                "per_page": 1000,
            }
            if current_folder_id is not None:
                params["parent_ids"] = [current_folder_id]

            result = self.client.get_file_entries(**params)
            file_entries = FileEntriesResult.from_api_response(result)

            # Filter for root if no parent
            entries = file_entries.entries
            if current_folder_id is None:
                entries = [
                    e for e in entries if e.parent_id is None or e.parent_id == 0
                ]

            # Find the folder
            found = None
            for entry in entries:
                if entry.name == part and entry.is_folder:
                    found = entry
                    break

            if found is None:
                if create and not self.readonly:
                    # Create the folder
                    result_data = self.client.create_folder(
                        name=part,
                        parent_id=current_folder_id,
                        workspace_id=self.workspace_id,
                    )
                    # Extract folder ID from response
                    folder_data: dict[str, Any] = {}
                    if isinstance(result_data, dict):
                        if "folder" in result_data:
                            folder_data = result_data["folder"]
                        elif "fileEntry" in result_data:
                            folder_data = result_data["fileEntry"]
                        elif "id" in result_data:
                            folder_data = result_data
                    current_folder_id = folder_data.get("id")
                    logger.debug(f"Created folder '{part}' with ID {current_folder_id}")
                else:
                    return None
            else:
                current_folder_id = found.id

            # Cache the result
            self._folder_cache[partial_path] = current_folder_id

        return current_folder_id

    def _get_file_entry(self, folder_id: int | None, filename: str) -> FileEntry | None:
        """Get a file entry by name in a folder.

        Args:
            folder_id: Parent folder ID (None for root)
            filename: Name of the file

        Returns:
            FileEntry or None if not found
        """
        from pydrime.models import FileEntriesResult

        params: dict[str, Any] = {
            "workspace_id": self.workspace_id,
            "per_page": 1000,
        }
        if folder_id is not None:
            params["parent_ids"] = [folder_id]

        result = self.client.get_file_entries(**params)
        file_entries = FileEntriesResult.from_api_response(result)

        # Filter for root if no parent
        entries = file_entries.entries
        if folder_id is None:
            entries = [e for e in entries if e.parent_id is None or e.parent_id == 0]

        for entry in entries:
            if entry.name == filename and not entry.is_folder:
                return entry

        return None

    def list_buckets(self) -> list[Bucket]:
        """List all buckets (top-level folders in workspace)."""
        try:
            from pydrime.models import FileEntriesResult

            # Get top-level folders
            params: dict[str, Any] = {
                "workspace_id": self.workspace_id,
                "per_page": 1000,
            }

            result = self.client.get_file_entries(**params)
            file_entries = FileEntriesResult.from_api_response(result)

            # Filter for root folders only
            entries = [
                e
                for e in file_entries.entries
                if (e.parent_id is None or e.parent_id == 0) and e.is_folder
            ]

            buckets = []
            for entry in entries:
                # Convert Drime folder to S3 bucket
                bucket = Bucket(
                    name=entry.name,
                    creation_date=self._parse_datetime(entry.created_at),
                )
                buckets.append(bucket)

            logger.debug(f"Listed {len(buckets)} buckets")
            return buckets

        except Exception as e:
            logger.error(f"Failed to list buckets: {e}")
            raise

    def create_bucket(self, bucket_name: str) -> Bucket:
        """Create a new bucket (top-level folder)."""
        if self.readonly:
            raise PermissionError("Provider is in read-only mode")

        try:
            # Check if bucket already exists
            if self.bucket_exists(bucket_name):
                raise BucketAlreadyExists(bucket_name)

            # Create top-level folder
            self.client.create_folder(
                name=bucket_name, parent_id=None, workspace_id=self.workspace_id
            )

            logger.info(f"Created bucket: {bucket_name}")

            return Bucket(
                name=bucket_name,
                creation_date=datetime.now(timezone.utc),
            )

        except BucketAlreadyExists:
            raise
        except Exception as e:
            logger.error(f"Failed to create bucket {bucket_name}: {e}")
            raise

    def delete_bucket(self, bucket_name: str, force: bool = False) -> bool:
        """Delete a bucket (top-level folder).

        Args:
            bucket_name: Name of bucket to delete
            force: If True, delete bucket even if it contains objects
                   (Drime-specific: deletes folder with all contents)

        Returns:
            True if deleted successfully

        Raises:
            NoSuchBucket: If bucket does not exist
            BucketNotEmpty: If bucket contains objects and force=False
        """
        if self.readonly:
            raise PermissionError("Provider is in read-only mode")

        try:
            from pydrime.models import FileEntriesResult

            # Get the folder ID
            folder_id = self._get_folder_id_by_path(bucket_name)

            if folder_id is None:
                raise NoSuchBucket(bucket_name)

            # Check if bucket is empty (unless force=True)
            if not force:
                params: dict[str, Any] = {
                    "workspace_id": self.workspace_id,
                    "parent_ids": [folder_id],
                    "per_page": 1,
                }
                result = self.client.get_file_entries(**params)
                file_entries = FileEntriesResult.from_api_response(result)

                if len(file_entries.entries) > 0:
                    raise BucketNotEmpty(bucket_name)

            # Delete the folder (Drime API will delete all contents recursively)
            self.client.delete_file_entries([folder_id], workspace_id=self.workspace_id)

            # Clear cache entries for this bucket and all subfolders
            to_remove = [
                k
                for k in self._folder_cache
                if k == bucket_name or k.startswith(f"{bucket_name}/")
            ]
            for k in to_remove:
                del self._folder_cache[k]

            logger.info(f"Deleted bucket: {bucket_name}")
            return True

        except (NoSuchBucket, BucketNotEmpty):
            raise
        except Exception as e:
            logger.error(f"Failed to delete bucket {bucket_name}: {e}")
            raise

    def bucket_exists(self, bucket_name: str) -> bool:
        """Check if a bucket exists."""
        try:
            folder_id = self._get_folder_id_by_path(bucket_name)
            return folder_id is not None
        except Exception as e:
            logger.debug(f"Error checking bucket existence: {e}")
            return False

    def get_bucket(self, bucket_name: str) -> Bucket:
        """Get bucket information."""
        if not self.bucket_exists(bucket_name):
            raise NoSuchBucket(bucket_name)

        return Bucket(
            name=bucket_name,
            creation_date=datetime.now(timezone.utc),
        )

    def _collect_all_objects(
        self, folder_id: int | None, current_path: str = ""
    ) -> list[tuple[str, FileEntry]]:
        """Recursively collect all objects with their full paths.

        Args:
            folder_id: Folder ID to start from (None for root)
            current_path: Current path prefix

        Returns:
            List of tuples (full_key, entry)
        """
        from pydrime.models import FileEntriesResult

        result_objects: list[tuple[str, FileEntry]] = []

        params: dict[str, Any] = {
            "workspace_id": self.workspace_id,
            "per_page": 1000,
        }
        if folder_id is not None:
            params["parent_ids"] = [folder_id]

        logger.debug(
            f"Collecting objects from folder_id={folder_id}, path={current_path}"
        )
        result = self.client.get_file_entries(**params)
        file_entries = FileEntriesResult.from_api_response(result)

        # Filter to only include immediate children of this folder
        entries = file_entries.entries
        if folder_id is None:
            # Root level - filter for entries with no parent or parent_id=0
            entries = [e for e in entries if e.parent_id is None or e.parent_id == 0]
        else:
            # Filter for entries that are direct children of this folder
            entries = [e for e in entries if e.parent_id == folder_id]

        logger.debug(f"Found {len(entries)} immediate children")

        for entry in entries:
            # Build full key
            if current_path:
                full_key = f"{current_path}/{entry.name}"
            else:
                full_key = entry.name

            if entry.is_folder:
                # Recursively collect from subfolder
                subfolder_objects = self._collect_all_objects(entry.id, full_key)
                result_objects.extend(subfolder_objects)
            else:
                # Add file object
                result_objects.append((full_key, entry))

        return result_objects

    def list_objects(
        self,
        bucket_name: str,
        prefix: str = "",
        marker: str = "",
        max_keys: int = 1000,
        delimiter: str = "",
    ) -> dict[str, Any]:
        """List objects in a bucket with delimiter support."""
        try:
            # Get bucket folder ID
            folder_id = self._get_folder_id_by_path(bucket_name)

            if folder_id is None:
                raise NoSuchBucket(bucket_name)

            # Collect all objects recursively with full paths
            all_objects = self._collect_all_objects(folder_id)

            # Extract keys for filtering
            all_keys = [key for key, _ in all_objects]

            # Filter by prefix
            if prefix:
                all_keys = [k for k in all_keys if k.startswith(prefix)]

            # Filter by marker
            if marker:
                all_keys = [k for k in all_keys if k > marker]

            # Sort keys
            all_keys.sort()

            # Handle delimiter for common prefixes
            common_prefixes: set[str] = set()
            contents_keys = []

            if delimiter:
                for key in all_keys:
                    # Find the position of the delimiter after the prefix
                    search_start = len(prefix)
                    delimiter_pos = key.find(delimiter, search_start)

                    if delimiter_pos != -1:
                        # This key should be in common prefixes
                        common_prefix = key[: delimiter_pos + len(delimiter)]
                        common_prefixes.add(common_prefix)
                    else:
                        # This key should be in contents
                        contents_keys.append(key)
            else:
                contents_keys = all_keys

            # Apply max_keys limit
            is_truncated = len(contents_keys) > max_keys
            if is_truncated:
                contents_keys = contents_keys[:max_keys]
                next_marker = contents_keys[-1]
            else:
                next_marker = ""

            # Build S3Object instances for contents
            # Create a lookup dict for quick access
            objects_dict = {key: entry for key, entry in all_objects}

            contents = []
            for key in contents_keys:
                entry = objects_dict.get(key)
                if entry is not None:
                    obj = S3Object(
                        key=key,
                        size=entry.file_size or 0,
                        last_modified=self._parse_datetime(
                            entry.updated_at or entry.created_at
                        ),
                        etag=entry.hash or "",
                        content_type=entry.mime or "application/octet-stream",
                    )
                    contents.append(obj)

            logger.debug(
                f"Listed {len(contents)} objects, "
                f"{len(common_prefixes)} prefixes in {bucket_name}"
            )

            return {
                "contents": contents,
                "common_prefixes": sorted(list(common_prefixes)),
                "is_truncated": is_truncated,
                "next_marker": next_marker,
            }

        except NoSuchBucket:
            raise
        except Exception as e:
            logger.error(f"Failed to list objects in {bucket_name}: {e}")
            raise

    def put_object(
        self,
        bucket_name: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> S3Object:
        """Store an object (upload file)."""
        if self.readonly:
            raise PermissionError("Provider is in read-only mode")

        try:
            # Get bucket folder ID (or create path if nested)
            parts = key.split("/")
            filename = parts[-1]
            folder_path = bucket_name

            # Create nested folders if needed
            if len(parts) > 1:
                subfolder = "/".join(parts[:-1])
                folder_path = f"{bucket_name}/{subfolder}"

            folder_id = self._get_folder_id_by_path(folder_path, create=True)

            if folder_id is None and folder_path:
                raise NoSuchBucket(bucket_name)

            # Create temp file and upload
            tmp_dir = Path(tempfile.gettempdir())
            tmp_path = tmp_dir / filename
            tmp_path.write_bytes(data)

            try:
                result = self.client.upload_file(
                    tmp_path,
                    parent_id=folder_id,
                    workspace_id=self.workspace_id,
                    relative_path=filename,
                )

                logger.info(f"Uploaded object: {bucket_name}/{key}")

                # Extract hash from result
                file_hash = ""
                if isinstance(result, dict):
                    file_hash = result.get("hash", "")

                return S3Object(
                    key=key,
                    size=len(data),
                    last_modified=datetime.now(timezone.utc),
                    etag=file_hash,
                    content_type=content_type,
                    metadata=metadata or {},
                )
            finally:
                tmp_path.unlink(missing_ok=True)

        except NoSuchBucket:
            raise
        except Exception as e:
            logger.error(f"Failed to upload object {bucket_name}/{key}: {e}")
            raise

    def get_object(self, bucket_name: str, key: str) -> S3Object:
        """Retrieve an object (download file)."""
        try:
            # Parse key to get folder and filename
            parts = key.split("/")
            filename = parts[-1]
            folder_path = bucket_name

            if len(parts) > 1:
                subfolder = "/".join(parts[:-1])
                folder_path = f"{bucket_name}/{subfolder}"

            # Get folder ID
            folder_id = self._get_folder_id_by_path(folder_path)

            if folder_id is None and folder_path != bucket_name:
                raise NoSuchKey(key)

            # Find the file entry
            file_entry = self._get_file_entry(folder_id, filename)

            if not file_entry:
                raise NoSuchKey(key)

            # Download the file content using hash
            if not file_entry.hash:
                raise NoSuchKey(key)

            content: bytes = self.client.get_file_content(file_entry.hash)

            logger.debug(f"Retrieved object: {bucket_name}/{key}")

            return S3Object(
                key=key,
                size=file_entry.file_size or len(content),
                last_modified=self._parse_datetime(
                    file_entry.updated_at or file_entry.created_at
                ),
                etag=file_entry.hash or "",
                content_type=file_entry.mime or "application/octet-stream",
                data=content,
                metadata={},
            )

        except (NoSuchBucket, NoSuchKey):
            raise
        except Exception as e:
            logger.error(f"Failed to get object {bucket_name}/{key}: {e}")
            raise

    def head_object(self, bucket_name: str, key: str) -> S3Object:
        """Get object metadata without downloading content."""
        try:
            # Parse key to get folder and filename
            parts = key.split("/")
            filename = parts[-1]
            folder_path = bucket_name

            if len(parts) > 1:
                subfolder = "/".join(parts[:-1])
                folder_path = f"{bucket_name}/{subfolder}"

            # Get folder ID
            folder_id = self._get_folder_id_by_path(folder_path)

            if folder_id is None and folder_path != bucket_name:
                raise NoSuchKey(key)

            # Find the file entry
            file_entry = self._get_file_entry(folder_id, filename)

            if not file_entry:
                raise NoSuchKey(key)

            return S3Object(
                key=key,
                size=file_entry.file_size or 0,
                last_modified=self._parse_datetime(
                    file_entry.updated_at or file_entry.created_at
                ),
                etag=file_entry.hash or "",
                content_type=file_entry.mime or "application/octet-stream",
                metadata={},
            )

        except (NoSuchBucket, NoSuchKey):
            raise
        except Exception as e:
            logger.error(f"Failed to get object metadata {bucket_name}/{key}: {e}")
            raise

    def delete_object(self, bucket_name: str, key: str) -> bool:
        """Delete an object."""
        if self.readonly:
            raise PermissionError("Provider is in read-only mode")

        try:
            # Parse key to get folder and filename
            parts = key.split("/")
            filename = parts[-1]
            folder_path = bucket_name

            if len(parts) > 1:
                subfolder = "/".join(parts[:-1])
                folder_path = f"{bucket_name}/{subfolder}"

            # Get folder ID
            folder_id = self._get_folder_id_by_path(folder_path)

            if folder_id is None and folder_path != bucket_name:
                raise NoSuchKey(key)

            # Find the file entry
            file_entry = self._get_file_entry(folder_id, filename)

            if not file_entry:
                raise NoSuchKey(key)

            # Delete the file
            self.client.delete_file_entries(
                [file_entry.id], workspace_id=self.workspace_id
            )

            logger.info(f"Deleted object: {bucket_name}/{key}")
            return True

        except (NoSuchBucket, NoSuchKey):
            raise
        except Exception as e:
            logger.error(f"Failed to delete object {bucket_name}/{key}: {e}")
            raise

    def delete_objects(self, bucket_name: str, keys: list[str]) -> dict[str, Any]:
        """Delete multiple objects."""
        if self.readonly:
            raise PermissionError("Provider is in read-only mode")

        deleted = []
        errors = []

        for key in keys:
            try:
                self.delete_object(bucket_name, key)
                deleted.append({"Key": key})
            except Exception as e:
                errors.append({"Key": key, "Code": "InternalError", "Message": str(e)})

        return {"Deleted": deleted, "Errors": errors}

    def copy_object(
        self,
        src_bucket: str,
        src_key: str,
        dst_bucket: str,
        dst_key: str,
    ) -> S3Object:
        """Copy an object."""
        if self.readonly:
            raise PermissionError("Provider is in read-only mode")

        try:
            # Get source object
            src_obj = self.get_object(src_bucket, src_key)

            # Ensure we have data to copy
            if src_obj.data is None:
                raise ValueError("Source object has no data")

            # Put to destination
            return self.put_object(
                dst_bucket,
                dst_key,
                src_obj.data,
                src_obj.content_type,
                src_obj.metadata,
            )

        except Exception as e:
            logger.error(
                f"Failed to copy {src_bucket}/{src_key} to {dst_bucket}/{dst_key}: {e}"
            )
            raise

    def object_exists(self, bucket_name: str, key: str) -> bool:
        """Check if an object exists."""
        try:
            self.head_object(bucket_name, key)
            return True
        except (NoSuchBucket, NoSuchKey):
            return False
        except Exception:
            return False

    def is_readonly(self) -> bool:
        """Check if the provider is in read-only mode."""
        return self.readonly
