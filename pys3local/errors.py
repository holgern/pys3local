"""S3-specific error classes."""

from __future__ import annotations


class S3Error(Exception):
    """Base class for S3 errors."""

    def __init__(
        self, message: str, code: str = "InternalError", status_code: int = 500
    ):
        """Initialize S3 error.

        Args:
            message: Error message
            code: S3 error code
            status_code: HTTP status code
        """
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class NoSuchBucket(S3Error):
    """Bucket does not exist."""

    def __init__(self, bucket_name: str):
        """Initialize NoSuchBucket error.

        Args:
            bucket_name: Name of the bucket
        """
        super().__init__(
            f"The specified bucket does not exist: {bucket_name}",
            code="NoSuchBucket",
            status_code=404,
        )
        self.bucket_name = bucket_name


class BucketAlreadyExists(S3Error):
    """Bucket already exists."""

    def __init__(self, bucket_name: str):
        """Initialize BucketAlreadyExists error.

        Args:
            bucket_name: Name of the bucket
        """
        super().__init__(
            f"The bucket already exists: {bucket_name}",
            code="BucketAlreadyExists",
            status_code=409,
        )
        self.bucket_name = bucket_name


class BucketNotEmpty(S3Error):
    """Bucket is not empty."""

    def __init__(self, bucket_name: str):
        """Initialize BucketNotEmpty error.

        Args:
            bucket_name: Name of the bucket
        """
        super().__init__(
            f"The bucket you tried to delete is not empty: {bucket_name}",
            code="BucketNotEmpty",
            status_code=409,
        )
        self.bucket_name = bucket_name


class NoSuchKey(S3Error):
    """Object key does not exist."""

    def __init__(self, key: str):
        """Initialize NoSuchKey error.

        Args:
            key: Object key
        """
        super().__init__(
            f"The specified key does not exist: {key}",
            code="NoSuchKey",
            status_code=404,
        )
        self.key = key


class InvalidBucketName(S3Error):
    """Invalid bucket name."""

    def __init__(self, bucket_name: str):
        """Initialize InvalidBucketName error.

        Args:
            bucket_name: Name of the bucket
        """
        super().__init__(
            f"The specified bucket is not valid: {bucket_name}",
            code="InvalidBucketName",
            status_code=400,
        )
        self.bucket_name = bucket_name


class InvalidKeyName(S3Error):
    """Invalid object key name."""

    def __init__(self, key: str):
        """Initialize InvalidKeyName error.

        Args:
            key: Object key
        """
        super().__init__(
            f"The specified key is not valid: {key}",
            code="InvalidKeyName",
            status_code=400,
        )
        self.key = key


class AccessDenied(S3Error):
    """Access denied."""

    def __init__(self, message: str = "Access Denied"):
        """Initialize AccessDenied error.

        Args:
            message: Error message
        """
        super().__init__(message, code="AccessDenied", status_code=403)


class SignatureDoesNotMatch(S3Error):
    """Signature does not match."""

    def __init__(
        self,
        message: str = (
            "The request signature we calculated does not match "
            "the signature you provided"
        ),
    ):
        """Initialize SignatureDoesNotMatch error.

        Args:
            message: Error message
        """
        super().__init__(message, code="SignatureDoesNotMatch", status_code=403)


class InvalidArgument(S3Error):
    """Invalid argument."""

    def __init__(self, message: str):
        """Initialize InvalidArgument error.

        Args:
            message: Error message
        """
        super().__init__(message, code="InvalidArgument", status_code=400)
