"""Data models for S3 objects and buckets."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Bucket:
    """Represents an S3 bucket."""

    name: str
    creation_date: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "Name": self.name,
            "CreationDate": self.creation_date.isoformat() + "Z",
        }


@dataclass
class S3Object:
    """Represents an S3 object."""

    key: str
    size: int
    etag: str
    last_modified: datetime
    content_type: str = "application/octet-stream"
    data: bytes | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    storage_class: str = "STANDARD"

    @staticmethod
    def calculate_etag(data: bytes) -> str:
        """Calculate ETag (MD5 hash) for data.

        Args:
            data: Object data

        Returns:
            MD5 hash as hex string
        """
        return hashlib.md5(data).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "Key": self.key,
            "Size": self.size,
            "ETag": f'"{self.etag}"',
            "LastModified": self.last_modified.isoformat() + "Z",
            "StorageClass": self.storage_class,
        }


@dataclass
class ListObjectsResult:
    """Result of list objects operation."""

    name: str  # Bucket name
    prefix: str
    marker: str
    max_keys: int
    is_truncated: bool
    contents: list[S3Object] = field(default_factory=list)
    common_prefixes: list[str] = field(default_factory=list)
    next_marker: str = ""
    delimiter: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation
        """
        result: dict[str, Any] = {
            "Name": self.name,
            "Prefix": self.prefix,
            "Marker": self.marker,
            "MaxKeys": self.max_keys,
            "IsTruncated": str(self.is_truncated).lower(),
            "Contents": [obj.to_dict() for obj in self.contents],
        }

        if self.delimiter:
            result["Delimiter"] = self.delimiter

        if self.common_prefixes:
            result["CommonPrefixes"] = [
                {"Prefix": prefix} for prefix in self.common_prefixes
            ]

        if self.is_truncated:
            result["NextMarker"] = self.next_marker

        return result
