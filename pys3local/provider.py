"""Abstract base class for storage providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pys3local.models import Bucket, S3Object


class StorageProvider(ABC):
    """Abstract base class for S3 storage providers.

    This interface defines all operations required to implement a storage backend
    for the S3 API. Concrete implementations can use local filesystem,
    cloud storage, or any other storage mechanism.
    """

    @abstractmethod
    def list_buckets(self) -> list[Bucket]:
        """List all buckets.

        Returns:
            List of Bucket objects
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def bucket_exists(self, bucket_name: str) -> bool:
        """Check if a bucket exists.

        Args:
            bucket_name: Name of the bucket

        Returns:
            True if bucket exists
        """
        pass

    @abstractmethod
    def get_bucket(self, bucket_name: str) -> Bucket:
        """Get bucket information.

        Args:
            bucket_name: Name of the bucket

        Returns:
            Bucket object

        Raises:
            NoSuchBucket: If bucket doesn't exist
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
            md5_hash: Pre-calculated MD5 hash (optional, calculated if None)

        Returns:
            Created S3Object

        Raises:
            NoSuchBucket: If bucket doesn't exist
            InvalidKeyName: If key name is invalid
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def object_exists(self, bucket_name: str, key: str) -> bool:
        """Check if an object exists.

        Args:
            bucket_name: Name of the bucket
            key: Object key

        Returns:
            True if object exists
        """
        pass

    @abstractmethod
    def is_readonly(self) -> bool:
        """Check if the provider is in read-only mode.

        Returns:
            True if read-only mode is enabled
        """
        pass
