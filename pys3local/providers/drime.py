"""Drime Cloud storage provider for S3."""

from __future__ import annotations

import hashlib
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pys3local.errors import (
    BucketAlreadyExists,
    BucketNotEmpty,
    NoSuchBucket,
    NoSuchKey,
)
from pys3local.models import Bucket, S3Object
from pys3local.provider import StorageProvider

if TYPE_CHECKING:
    from pydrime.api import DrimeClient  # type: ignore[import-not-found]
    from pydrime.models import FileEntry  # type: ignore[import-not-found]

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
        root_folder: str | None = None,
    ):
        """Initialize Drime storage provider.

        Args:
            client: Drime client instance (pydrime.DrimeClient)
            workspace_id: Drime workspace ID (0 for personal workspace)
            readonly: If True, disable write operations
            root_folder: Optional folder path in Drime to use as root
                        (e.g., "backups" or "backups/s3"). If specified, all
                        S3 buckets will be created within this folder instead
                        of at the workspace root.
        """
        self.client = client
        self.workspace_id = workspace_id
        self.readonly = readonly
        self.root_folder = root_folder
        self._root_folder_id: int | None = None
        # Cache for folder IDs to reduce API calls
        self._folder_cache: dict[str, int | None] = {}

        # Initialize root folder if specified
        if root_folder:
            self._root_folder_id = self._get_folder_id_by_path(root_folder)
            if self._root_folder_id is None and not readonly:
                # Create the root folder structure if it doesn't exist
                logger.info(f"Creating root folder: {root_folder}")
                self._root_folder_id = self._get_folder_id_by_path(
                    root_folder, create=True
                )
            logger.info(
                f"Drime storage initialized (workspace {workspace_id}, "
                f"root_folder: {root_folder})"
            )
        else:
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
            from pydrime.utils import (  # type: ignore[import-not-found]
                parse_iso_timestamp,
            )

            parsed = parse_iso_timestamp(dt_value)
            if parsed is not None:
                # parse_iso_timestamp returns naive local time
                # We need to ensure it's in UTC format
                parsed_dt = cast(datetime, parsed)
                if parsed_dt.tzinfo is not None:
                    # Has timezone, convert to UTC and make naive
                    return parsed_dt.astimezone(timezone.utc).replace(tzinfo=None)
                # Already naive, assume it's UTC
                return parsed_dt
        except (ValueError, AttributeError, ImportError) as e:
            logger.warning(f"Failed to parse datetime '{dt_value}': {e}")

        return datetime.now(timezone.utc).replace(tzinfo=None)

    def _get_etag_for_entry(self, entry: FileEntry, bucket_name: str, key: str) -> str:
        """Get ETag for file entry.

        Returns an S3-compatible ETag using Drime's UUID (disk_prefix/file_name).
        Format: UUID (e.g., "e77ad830-97f8-42a2-a13e-722fa10f02f5")

        ETags in S3-compatible APIs don't need to be MD5 - they just need to be:
        1. Unique per file content
        2. Consistent for the same file
        3. Change when file changes

        Examples of non-MD5 ETags in real S3 implementations:
        - AWS multipart uploads: "d41d8cd98f00b204e9800998ecf8427e-5"
        - AWS SSE-KMS encrypted: random string
        - Filen S3: file UUID
        - Drime (this implementation): UUID from file_name field

        This approach:
        - Works across multiple PCs (no cache needed)
        - Uses Drime's native UUID identifier
        - No downloads or MD5 calculations required
        - Compatible with rclone, duplicati, restic, etc.

        Args:
            entry: Drime file entry
            bucket_name: S3 bucket name
            key: S3 object key

        Returns:
            ETag string (UUID without quotes)
        """
        # Use Drime's UUID from file_name field (disk_prefix in API response)
        # This provides a consistent, stable identifier that:
        # - Works across multiple PCs (no local cache needed)
        # - Is unique per file
        # - Is S3-compatible (similar to Filen S3 format)
        # - Doesn't require MD5 calculation or caching

        etag = entry.file_name or entry.hash or str(entry.id)

        logger.debug(f"Using Drime UUID ETag for {bucket_name}/{key}: {etag}")
        return etag

    def _create_folder_with_retry(
        self, name: str, parent_id: int | None, max_retries: int = 3
    ) -> int | None:
        """Create folder with retry logic for race conditions.

        Args:
            name: Folder name
            parent_id: Parent folder ID (None for root)
            max_retries: Maximum number of retries

        Returns:
            Folder ID if successful

        Raises:
            Exception if folder creation fails after all retries
        """
        import time

        for attempt in range(max_retries):
            try:
                result_data = self.client.create_folder(
                    name=name, parent_id=parent_id, workspace_id=self.workspace_id
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

                folder_id = folder_data.get("id")
                logger.debug(f"Created folder '{name}' with ID {folder_id}")
                return folder_id

            except Exception as e:
                error_str = str(e)
                # Check for 422 error (folder already exists)
                if "422" in error_str:
                    logger.warning(
                        f"Folder '{name}' got 422 (try {attempt + 1}/{max_retries}), "
                        f"likely race condition. Retrying..."
                    )

                    # Sleep with exponential backoff
                    if attempt < max_retries - 1:
                        sleep_time = 0.1 * (2**attempt)  # 0.1s, 0.2s, 0.4s
                        time.sleep(sleep_time)

                        # Try to find the folder that was created by another process
                        from pydrime.models import (
                            FileEntriesResult,
                        )

                        params: dict[str, Any] = {
                            "workspace_id": self.workspace_id,
                            "per_page": 1000,
                        }
                        if parent_id is not None:
                            params["parent_ids"] = [parent_id]

                        result = self.client.get_file_entries(**params)
                        file_entries = FileEntriesResult.from_api_response(result)

                        # Filter for root if no parent
                        entries = file_entries.entries
                        if parent_id is None:
                            entries = [
                                e
                                for e in entries
                                if e.parent_id is None or e.parent_id == 0
                            ]

                        # Find the folder
                        for entry in entries:
                            if entry.name.lower() == name.lower() and entry.is_folder:
                                logger.info(
                                    f"Found folder '{name}' after 422 error "
                                    f"(ID: {entry.id})"
                                )
                                return cast(int, entry.id)

                        logger.warning(
                            f"Could not find folder '{name}' after 422 error "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                    else:
                        # Max retries exhausted
                        logger.error(
                            f"Failed to create or find folder '{name}' "
                            f"after {max_retries} attempts"
                        )
                        raise Exception(
                            f"Race condition: folder '{name}' failed "
                            f"after {max_retries} retries"
                        ) from e
                else:
                    # Other error, don't retry
                    logger.error(f"Failed to create folder '{name}': {e}")
                    raise

        return None

    def _get_folder_id_by_path(
        self, folder_path: str, create: bool = False
    ) -> int | None:
        """Get the folder ID for a given path, optionally creating it.

        Args:
            folder_path: Path like "bucket/subfolder" (without leading slash)
                        Path is relative to root_folder if set
            create: If True, create missing folders

        Returns:
            Folder ID or None for workspace root (when root_folder is not set)
        """
        if not folder_path:
            # If root_folder is set, return its ID, otherwise workspace root
            return self._root_folder_id if self.root_folder else None

        # Check cache first
        if folder_path in self._folder_cache:
            return self._folder_cache[folder_path]

        from pydrime.models import FileEntriesResult

        parts = folder_path.split("/")
        # Start from root_folder if set, otherwise workspace root
        current_folder_id: int | None = (
            self._root_folder_id if self.root_folder else None
        )

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
                    # Create the folder with retry logic
                    current_folder_id = self._create_folder_with_retry(
                        part, current_folder_id
                    )
                    if current_folder_id is None:
                        return None
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
        """List all buckets (top-level folders in workspace or root_folder)."""
        try:
            from pydrime.models import (
                FileEntriesResult,
            )

            # Determine parent folder for buckets
            parent_folder_id = self._root_folder_id if self.root_folder else None

            # Get folders at the appropriate level
            params: dict[str, Any] = {
                "workspace_id": self.workspace_id,
                "per_page": 1000,
            }

            result = self.client.get_file_entries(**params)
            file_entries = FileEntriesResult.from_api_response(result)

            # Filter for folders at the correct level
            if parent_folder_id is not None:
                # List folders within root_folder
                entries = [
                    e
                    for e in file_entries.entries
                    if e.parent_id == parent_folder_id and e.is_folder
                ]
            else:
                # List folders at workspace root
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

            if self.root_folder:
                logger.debug(
                    f"Listed {len(buckets)} buckets in root_folder '{self.root_folder}'"
                )
            else:
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

            # Create folder at appropriate level
            parent_id = self._root_folder_id if self.root_folder else None
            self.client.create_folder(
                name=bucket_name, parent_id=parent_id, workspace_id=self.workspace_id
            )

            if self.root_folder:
                logger.info(
                    f"Created bucket: {bucket_name} in root_folder '{self.root_folder}'"
                )
            else:
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
            from pydrime.models import (
                FileEntriesResult,
            )

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
                        etag=self._get_etag_for_entry(entry, bucket_name, key),
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
        md5_hash: str | None = None,
    ) -> S3Object:
        """Store an object (upload file).

        Args:
            bucket_name: Name of bucket
            key: Object key
            data: Object data
            content_type: MIME content type
            metadata: Custom metadata
            md5_hash: Pre-calculated MD5 hash (calculated if None)

        Returns:
            S3Object with metadata

        Raises:
            NoSuchBucket: If bucket doesn't exist
            PermissionError: If provider is read-only
        """
        if self.readonly:
            raise PermissionError("Provider is in read-only mode")

        try:
            # Calculate MD5 if not provided
            if md5_hash is None:
                md5_hash = hashlib.md5(data).hexdigest()

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

                # Extract UUID (file_name) from result
                file_uuid = None
                if isinstance(result, dict):
                    if "file" in result:
                        file_uuid = result["file"].get("file_name")
                    elif "fileEntry" in result:
                        file_uuid = result["fileEntry"].get("file_name")

                # Use UUID for ETag (from file_name field)
                # This ensures consistency across multiple PCs and API calls
                if not file_uuid:
                    # Fallback to hash or ID if UUID not available
                    file_hash = None
                    file_entry_id = None
                    if isinstance(result, dict):
                        if "file" in result:
                            file_hash = result["file"].get("hash")
                            file_entry_id = result["file"].get("id")
                        elif "fileEntry" in result:
                            file_hash = result["fileEntry"].get("hash")
                            file_entry_id = result["fileEntry"].get("id")
                    file_uuid = file_hash or str(file_entry_id or 0)

                etag = file_uuid
                logger.debug(f"Generated UUID ETag for {bucket_name}/{key}: {etag}")

                return S3Object(
                    key=key,
                    size=len(data),
                    last_modified=datetime.now(timezone.utc),
                    etag=etag,  # Use UUID format
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
                etag=self._get_etag_for_entry(file_entry, bucket_name, key),
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
                etag=self._get_etag_for_entry(file_entry, bucket_name, key),
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
        """Copy an object.

        Args:
            src_bucket: Source bucket name
            src_key: Source object key
            dst_bucket: Destination bucket name
            dst_key: Destination object key

        Returns:
            S3Object with destination metadata

        Raises:
            PermissionError: If provider is read-only
        """
        if self.readonly:
            raise PermissionError("Provider is in read-only mode")

        try:
            # Get source object
            src_obj = self.get_object(src_bucket, src_key)

            # Ensure we have data to copy
            if src_obj.data is None:
                raise ValueError("Source object has no data")

            # Put to destination, reusing MD5 from source
            return self.put_object(
                dst_bucket,
                dst_key,
                src_obj.data,
                src_obj.content_type,
                src_obj.metadata,
                md5_hash=src_obj.etag,  # Reuse source MD5
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
