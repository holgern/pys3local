"""Local filesystem storage provider for S3."""

from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from pys3local.errors import (
    BucketAlreadyExists,
    BucketNotEmpty,
    InvalidBucketName,
    InvalidKeyName,
    NoSuchBucket,
    NoSuchKey,
)
from pys3local.metadata_db import MetadataDB
from pys3local.models import Bucket, S3Object
from pys3local.provider import StorageProvider

logger = logging.getLogger(__name__)

# Bucket name validation regex (AWS S3 rules)
BUCKET_NAME_REGEX = re.compile(r"^[a-z0-9][a-z0-9\-]{1,61}[a-z0-9]$")


class LocalStorageProvider(StorageProvider):
    """Local filesystem storage provider.

    Stores S3 buckets and objects on the local filesystem.
    Metadata is stored in SQLite database for efficient access.
    """

    def __init__(
        self,
        base_path: Path | str,
        readonly: bool = False,
        metadata_db: MetadataDB | None = None,
    ):
        """Initialize local storage provider.

        Args:
            base_path: Base directory for storing buckets
            readonly: If True, disable write operations
            metadata_db: MetadataDB instance (created if None)
        """
        self.base_path = Path(base_path)
        self.readonly = readonly

        # Initialize metadata database
        if metadata_db is None:
            metadata_db = MetadataDB()
        self.metadata_db = metadata_db

        # Create base directory if it doesn't exist
        if not self.base_path.exists():
            self.base_path.mkdir(parents=True, mode=0o700)

        logger.info(f"Local storage initialized at {self.base_path}")

    def _get_bucket_path(self, bucket_name: str) -> Path:
        """Get path to bucket directory.

        Args:
            bucket_name: Bucket name

        Returns:
            Path to bucket directory
        """
        return self.base_path / bucket_name

    def _get_object_path(self, bucket_name: str, key: str) -> Path:
        """Get path to object file.

        Args:
            bucket_name: Bucket name
            key: Object key

        Returns:
            Path to object file
        """
        bucket_path = self._get_bucket_path(bucket_name)
        return bucket_path / "objects" / key

    def _validate_bucket_name(self, bucket_name: str) -> None:
        """Validate bucket name according to S3 rules.

        Args:
            bucket_name: Bucket name to validate

        Raises:
            InvalidBucketName: If bucket name is invalid
        """
        if not bucket_name:
            raise InvalidBucketName(bucket_name)

        if len(bucket_name) < 3 or len(bucket_name) > 63:
            raise InvalidBucketName(bucket_name)

        if not BUCKET_NAME_REGEX.match(bucket_name):
            raise InvalidBucketName(bucket_name)

        # Additional checks
        if ".." in bucket_name or ".-" in bucket_name or "-." in bucket_name:
            raise InvalidBucketName(bucket_name)

    def _validate_key_name(self, key: str) -> None:
        """Validate object key name.

        Args:
            key: Object key to validate

        Raises:
            InvalidKeyName: If key name is invalid
        """
        if not key:
            raise InvalidKeyName(key)

        if len(key) > 1024:
            raise InvalidKeyName(key)

        # Check for invalid characters
        if "\x00" in key:
            raise InvalidKeyName(key)

    def _save_metadata(self, bucket_name: str, key: str, obj: S3Object) -> None:
        """Save object metadata to database.

        Args:
            bucket_name: Bucket name
            key: Object key
            obj: S3Object with metadata
        """
        self.metadata_db.set_local_object(
            bucket_name=bucket_name,
            object_key=key,
            size=obj.size,
            etag=obj.etag,
            last_modified=obj.last_modified,
            content_type=obj.content_type,
            metadata=obj.metadata,
            storage_class=obj.storage_class,
        )

    def _load_metadata(self, bucket_name: str, key: str) -> S3Object:
        """Load object metadata from database.

        Args:
            bucket_name: Bucket name
            key: Object key

        Returns:
            S3Object with metadata

        Raises:
            NoSuchKey: If metadata doesn't exist
        """
        from typing import cast

        metadata = self.metadata_db.get_local_object(bucket_name, key)

        if not metadata:
            raise NoSuchKey(key)

        return S3Object(
            key=cast(str, metadata["object_key"]),
            size=cast(int, metadata["size"]),
            etag=cast(str, metadata["etag"]),
            last_modified=cast(datetime, metadata["last_modified"]),
            content_type=cast(str, metadata["content_type"]),
            metadata=cast(dict[str, str], metadata["metadata"]),
            storage_class=cast(str, metadata["storage_class"]),
        )

    def list_buckets(self) -> list[Bucket]:
        """List all buckets.

        Returns:
            List of Bucket objects
        """
        buckets = []

        for item in self.base_path.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                # Get bucket creation time from directory
                stat = item.stat()
                creation_date = datetime.fromtimestamp(stat.st_ctime)

                buckets.append(Bucket(name=item.name, creation_date=creation_date))

        return sorted(buckets, key=lambda b: b.name)

    def create_bucket(self, bucket_name: str) -> Bucket:
        """Create a new bucket.

        Args:
            bucket_name: Name of the bucket to create

        Returns:
            Created Bucket object

        Raises:
            BucketAlreadyExists: If bucket already exists
            InvalidBucketName: If bucket name is invalid
        """
        self._validate_bucket_name(bucket_name)

        bucket_path = self._get_bucket_path(bucket_name)

        if bucket_path.exists():
            raise BucketAlreadyExists(bucket_name)

        # Create bucket directory structure
        bucket_path.mkdir(parents=True, mode=0o700)
        (bucket_path / "objects").mkdir(mode=0o700)

        logger.info(f"Created bucket: {bucket_name}")

        return Bucket(name=bucket_name, creation_date=datetime.utcnow())

    def delete_bucket(self, bucket_name: str) -> bool:
        """Delete a bucket.

        Args:
            bucket_name: Name of the bucket to delete

        Returns:
            True if deleted successfully

        Raises:
            NoSuchBucket: If bucket doesn't exist
            BucketNotEmpty: If bucket is not empty
        """
        bucket_path = self._get_bucket_path(bucket_name)

        if not bucket_path.exists():
            raise NoSuchBucket(bucket_name)

        # Check if bucket is empty
        objects_path = bucket_path / "objects"
        if objects_path.exists():
            # Check for any files in the objects directory
            for _root, _dirs, files in os.walk(objects_path):
                if files:
                    raise BucketNotEmpty(bucket_name)

        # Delete bucket directory
        shutil.rmtree(bucket_path)

        # Clean up metadata from database
        self.metadata_db.cleanup_local_bucket(bucket_name)

        logger.info(f"Deleted bucket: {bucket_name}")

        return True

    def bucket_exists(self, bucket_name: str) -> bool:
        """Check if a bucket exists.

        Args:
            bucket_name: Name of the bucket

        Returns:
            True if bucket exists
        """
        bucket_path = self._get_bucket_path(bucket_name)
        return bucket_path.exists() and bucket_path.is_dir()

    def get_bucket(self, bucket_name: str) -> Bucket:
        """Get bucket information.

        Args:
            bucket_name: Name of the bucket

        Returns:
            Bucket object

        Raises:
            NoSuchBucket: If bucket doesn't exist
        """
        if not self.bucket_exists(bucket_name):
            raise NoSuchBucket(bucket_name)

        bucket_path = self._get_bucket_path(bucket_name)
        stat = bucket_path.stat()
        creation_date = datetime.fromtimestamp(stat.st_ctime)

        return Bucket(name=bucket_name, creation_date=creation_date)

    def list_objects(
        self,
        bucket_name: str,
        prefix: str = "",
        marker: str = "",
        max_keys: int = 1000,
        delimiter: str = "",
    ) -> dict[str, Any]:
        """List objects in a bucket.

        Args:
            bucket_name: Name of the bucket
            prefix: Prefix filter
            marker: Pagination marker
            max_keys: Maximum number of keys to return
            delimiter: Delimiter for grouping keys

        Returns:
            Dictionary with keys: contents (list of S3Object), common_prefixes,
            is_truncated, next_marker

        Raises:
            NoSuchBucket: If bucket doesn't exist
        """
        if not self.bucket_exists(bucket_name):
            raise NoSuchBucket(bucket_name)

        # Get all objects from database (much faster than filesystem walk)
        objects_metadata = self.metadata_db.list_local_objects(bucket_name, prefix)
        all_keys = [obj["object_key"] for obj in objects_metadata]

        # Create lookup dict for fast metadata access
        metadata_lookup = {obj["object_key"]: obj for obj in objects_metadata}

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

        # Load metadata for contents from our lookup dict
        contents = []
        for key in contents_keys:
            if key in metadata_lookup:
                meta = metadata_lookup[key]
                obj = S3Object(
                    key=meta["object_key"],
                    size=meta["size"],
                    etag=meta["etag"],
                    last_modified=meta["last_modified"],
                    content_type=meta["content_type"],
                    metadata=meta["metadata"],
                    storage_class=meta["storage_class"],
                )
                contents.append(obj)
            else:
                # Shouldn't happen, but log if it does
                logger.warning(f"Metadata not found for key: {key}")

        return {
            "contents": contents,
            "common_prefixes": sorted(list(common_prefixes)),
            "is_truncated": is_truncated,
            "next_marker": next_marker,
        }

    def put_object(
        self,
        bucket_name: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
        md5_hash: str | None = None,
    ) -> S3Object:
        """Store an object.

        Args:
            bucket_name: Name of the bucket
            key: Object key
            data: Object data
            content_type: Content type
            metadata: User metadata
            md5_hash: Pre-calculated MD5 hash (optional, always recalculated for local)

        Returns:
            Created S3Object

        Raises:
            NoSuchBucket: If bucket doesn't exist
            InvalidKeyName: If key name is invalid

        Note:
            The md5_hash parameter is accepted for API consistency but always
            recalculated from data for local storage to ensure integrity.
        """
        if not self.bucket_exists(bucket_name):
            raise NoSuchBucket(bucket_name)

        self._validate_key_name(key)

        # Always calculate ETag from data for local storage (ignore md5_hash parameter)
        etag = S3Object.calculate_etag(data)

        # Create object
        obj = S3Object(
            key=key,
            size=len(data),
            etag=etag,
            last_modified=datetime.utcnow(),
            content_type=content_type,
            data=data,
            metadata=metadata or {},
        )

        # Save object data
        object_path = self._get_object_path(bucket_name, key)
        object_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

        with open(object_path, "wb") as f:
            f.write(data)

        # Set permissions
        os.chmod(object_path, 0o600)

        # Save metadata
        self._save_metadata(bucket_name, key, obj)

        logger.info(f"Stored object: {bucket_name}/{key} ({len(data)} bytes)")

        # Return object without data
        obj.data = None
        return obj

    def get_object(self, bucket_name: str, key: str) -> S3Object:
        """Retrieve an object.

        Args:
            bucket_name: Name of the bucket
            key: Object key

        Returns:
            S3Object with data

        Raises:
            NoSuchBucket: If bucket doesn't exist
            NoSuchKey: If object doesn't exist
        """
        if not self.bucket_exists(bucket_name):
            raise NoSuchBucket(bucket_name)

        object_path = self._get_object_path(bucket_name, key)

        if not object_path.exists():
            raise NoSuchKey(key)

        # Load metadata
        obj = self._load_metadata(bucket_name, key)

        # Load data
        with open(object_path, "rb") as f:
            obj.data = f.read()

        return obj

    def head_object(self, bucket_name: str, key: str) -> S3Object:
        """Get object metadata.

        Args:
            bucket_name: Name of the bucket
            key: Object key

        Returns:
            S3Object (metadata only, no data)

        Raises:
            NoSuchBucket: If bucket doesn't exist
            NoSuchKey: If object doesn't exist
        """
        if not self.bucket_exists(bucket_name):
            raise NoSuchBucket(bucket_name)

        if not self.object_exists(bucket_name, key):
            raise NoSuchKey(key)

        return self._load_metadata(bucket_name, key)

    def delete_object(self, bucket_name: str, key: str) -> bool:
        """Delete an object.

        Args:
            bucket_name: Name of the bucket
            key: Object key

        Returns:
            True if deleted successfully

        Raises:
            NoSuchBucket: If bucket doesn't exist
        """
        if not self.bucket_exists(bucket_name):
            raise NoSuchBucket(bucket_name)

        object_path = self._get_object_path(bucket_name, key)

        # Delete object file
        if object_path.exists():
            object_path.unlink()

        # Delete metadata from database
        self.metadata_db.delete_local_object(bucket_name, key)

        # Clean up empty directories
        try:
            object_path.parent.rmdir()
        except OSError:
            pass  # Directory not empty

        logger.info(f"Deleted object: {bucket_name}/{key}")

        return True

    def delete_objects(self, bucket_name: str, keys: list[str]) -> dict[str, Any]:
        """Delete multiple objects.

        Args:
            bucket_name: Name of the bucket
            keys: List of object keys

        Returns:
            Dictionary with deleted and errors lists

        Raises:
            NoSuchBucket: If bucket doesn't exist
        """
        if not self.bucket_exists(bucket_name):
            raise NoSuchBucket(bucket_name)

        deleted = []
        errors = []

        for key in keys:
            try:
                self.delete_object(bucket_name, key)
                deleted.append(key)
            except Exception as e:
                errors.append({"key": key, "code": "InternalError", "message": str(e)})

        return {"deleted": deleted, "errors": errors}

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
            Copied S3Object

        Raises:
            NoSuchBucket: If source or destination bucket doesn't exist
            NoSuchKey: If source object doesn't exist
        """
        # Get source object
        src_obj = self.get_object(src_bucket, src_key)

        if src_obj.data is None:
            raise NoSuchKey(src_key)

        # Put to destination
        return self.put_object(
            dst_bucket,
            dst_key,
            src_obj.data,
            content_type=src_obj.content_type,
            metadata=src_obj.metadata,
        )

    def object_exists(self, bucket_name: str, key: str) -> bool:
        """Check if an object exists.

        Args:
            bucket_name: Name of the bucket
            key: Object key

        Returns:
            True if object exists
        """
        if not self.bucket_exists(bucket_name):
            return False

        object_path = self._get_object_path(bucket_name, key)
        return object_path.exists()

    def is_readonly(self) -> bool:
        """Check if the provider is in read-only mode.

        Returns:
            True if read-only mode is enabled
        """
        return self.readonly
