"""Basic tests for pys3local."""

import tempfile
from pathlib import Path

import pytest

from pys3local.errors import BucketAlreadyExists, NoSuchBucket, NoSuchKey
from pys3local.metadata_db import MetadataDB
from pys3local.providers.local import LocalStorageProvider


@pytest.fixture
def temp_provider():
    """Create a LocalStorageProvider with temporary storage and database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a temporary database for this test
        db_path = Path(tmpdir) / "test_metadata.db"
        metadata_db = MetadataDB(db_path=db_path)
        provider = LocalStorageProvider(
            base_path=Path(tmpdir) / "storage", metadata_db=metadata_db
        )
        yield provider


def test_create_and_list_buckets(temp_provider):
    """Test bucket creation and listing."""
    provider = temp_provider

    # Create buckets
    bucket1 = provider.create_bucket("test-bucket-1")
    bucket2 = provider.create_bucket("test-bucket-2")

    assert bucket1.name == "test-bucket-1"
    assert bucket2.name == "test-bucket-2"

    # List buckets
    buckets = provider.list_buckets()
    assert len(buckets) == 2
    assert buckets[0].name == "test-bucket-1"
    assert buckets[1].name == "test-bucket-2"


def test_bucket_already_exists(temp_provider):
    """Test that creating a bucket twice raises an error."""
    provider = temp_provider

    provider.create_bucket("test-bucket")

    with pytest.raises(BucketAlreadyExists):
        provider.create_bucket("test-bucket")


def test_put_and_get_object(temp_provider):
    """Test object creation and retrieval."""
    provider = temp_provider

    provider.create_bucket("test-bucket")

    # Put object
    data = b"Hello, World!"
    obj = provider.put_object(
        "test-bucket", "test.txt", data, content_type="text/plain"
    )

    assert obj.key == "test.txt"
    assert obj.size == len(data)
    assert obj.content_type == "text/plain"

    # Get object
    retrieved = provider.get_object("test-bucket", "test.txt")
    assert retrieved.data == data
    assert retrieved.content_type == "text/plain"


def test_list_objects(temp_provider):
    """Test object listing."""
    provider = temp_provider

    provider.create_bucket("test-bucket")

    # Put multiple objects
    provider.put_object("test-bucket", "file1.txt", b"data1")
    provider.put_object("test-bucket", "file2.txt", b"data2")
    provider.put_object("test-bucket", "dir/file3.txt", b"data3")

    # List all objects
    result = provider.list_objects("test-bucket")
    assert len(result["contents"]) == 3

    # List with prefix
    result = provider.list_objects("test-bucket", prefix="dir/")
    assert len(result["contents"]) == 1
    assert result["contents"][0].key == "dir/file3.txt"


def test_delete_object(temp_provider):
    """Test object deletion."""
    provider = temp_provider

    provider.create_bucket("test-bucket")
    provider.put_object("test-bucket", "test.txt", b"data")

    # Delete object
    success = provider.delete_object("test-bucket", "test.txt")
    assert success

    # Verify object is gone
    with pytest.raises(NoSuchKey):
        provider.get_object("test-bucket", "test.txt")


def test_copy_object(temp_provider):
    """Test object copying."""
    provider = temp_provider

    provider.create_bucket("src-bucket")
    provider.create_bucket("dst-bucket")

    # Create source object
    data = b"test data"
    provider.put_object("src-bucket", "source.txt", data)

    # Copy object
    copied = provider.copy_object("src-bucket", "source.txt", "dst-bucket", "dest.txt")

    assert copied.key == "dest.txt"
    assert copied.size == len(data)

    # Verify copy
    retrieved = provider.get_object("dst-bucket", "dest.txt")
    assert retrieved.data == data


def test_delete_bucket(temp_provider):
    """Test bucket deletion."""
    provider = temp_provider

    provider.create_bucket("test-bucket")

    # Delete empty bucket
    success = provider.delete_bucket("test-bucket")
    assert success

    # Verify bucket is gone
    with pytest.raises(NoSuchBucket):
        provider.get_bucket("test-bucket")


def test_bucket_validation(temp_provider):
    """Test bucket name validation."""
    provider = temp_provider

    # Valid bucket names
    provider.create_bucket("valid-bucket-name")
    provider.create_bucket("another-valid-name")

    # Invalid bucket names should raise errors
    from pys3local.errors import InvalidBucketName

    with pytest.raises(InvalidBucketName):
        provider.create_bucket("AB")  # Too short

    with pytest.raises(InvalidBucketName):
        provider.create_bucket("Invalid_Bucket")  # Invalid characters

    with pytest.raises(InvalidBucketName):
        provider.create_bucket("")  # Empty name
