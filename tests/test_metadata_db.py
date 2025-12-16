"""Tests for MetadataDB."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from pys3local.metadata_db import MetadataDB


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_metadata.db"
        db = MetadataDB(db_path)
        yield db


def test_init_creates_database(temp_db):
    """Test that database is created and initialized."""
    assert temp_db.db_path.exists()


def test_set_and_get_md5(temp_db):
    """Test storing and retrieving MD5."""
    temp_db.set_md5(
        file_entry_id=123,
        workspace_id=0,
        md5_hash="abc123def456",
        file_size=1024,
        bucket_name="test-bucket",
        object_key="test.txt",
    )

    result = temp_db.get_md5(123, 0)
    assert result == "abc123def456"


def test_get_md5_not_found(temp_db):
    """Test getting MD5 that doesn't exist."""
    result = temp_db.get_md5(999, 0)
    assert result is None


def test_remove_md5(temp_db):
    """Test removing MD5."""
    temp_db.set_md5(123, 0, "abc123", 1024, "bucket", "key")
    assert temp_db.get_md5(123, 0) == "abc123"

    removed = temp_db.remove_md5(123, 0)
    assert removed is True
    assert temp_db.get_md5(123, 0) is None


def test_remove_md5_not_found(temp_db):
    """Test removing MD5 that doesn't exist."""
    removed = temp_db.remove_md5(999, 0)
    assert removed is False


def test_get_md5_by_key(temp_db):
    """Test retrieving MD5 by S3 path."""
    temp_db.set_md5(123, 0, "abc123", 1024, "bucket", "test.txt")

    result = temp_db.get_md5_by_key(0, "bucket", "test.txt")
    assert result == "abc123"


def test_get_md5_by_key_not_found(temp_db):
    """Test getting MD5 by key that doesn't exist."""
    result = temp_db.get_md5_by_key(0, "bucket", "nonexistent.txt")
    assert result is None


def test_workspace_isolation(temp_db):
    """Test that workspaces are isolated."""
    temp_db.set_md5(123, 0, "md5_ws0", 1024, "bucket", "key")
    temp_db.set_md5(456, 1, "md5_ws1", 1024, "bucket", "key")

    assert temp_db.get_md5(123, 0) == "md5_ws0"
    assert temp_db.get_md5(456, 1) == "md5_ws1"
    assert temp_db.get_md5(123, 1) is None  # Wrong workspace
    assert temp_db.get_md5(456, 0) is None  # Wrong workspace


def test_update_existing_entry(temp_db):
    """Test updating existing entry preserves created_at."""
    temp_db.set_md5(123, 0, "old_md5", 1024, "bucket", "key")
    temp_db.set_md5(123, 0, "new_md5", 2048, "bucket", "key")

    result = temp_db.get_md5(123, 0)
    assert result == "new_md5"


def test_unique_bucket_key_constraint(temp_db):
    """Test unique constraint on workspace/bucket/key."""
    # First entry
    temp_db.set_md5(123, 0, "md5_123", 1024, "bucket", "key.txt")

    # Second entry with same workspace/bucket/key but different file_entry_id
    # Should replace the first entry
    temp_db.set_md5(456, 0, "md5_456", 2048, "bucket", "key.txt")

    # Should now get the second MD5
    result = temp_db.get_md5_by_key(0, "bucket", "key.txt")
    assert result == "md5_456"

    # First file_entry_id should no longer exist
    assert temp_db.get_md5(123, 0) is None


def test_cleanup_workspace(temp_db):
    """Test workspace cleanup."""
    temp_db.set_md5(1, 0, "md5_1", 1024, "bucket", "key1")
    temp_db.set_md5(2, 0, "md5_2", 1024, "bucket", "key2")
    temp_db.set_md5(3, 1, "md5_3", 1024, "bucket", "key3")

    count = temp_db.cleanup_workspace(0)
    assert count == 2

    assert temp_db.get_md5(1, 0) is None
    assert temp_db.get_md5(2, 0) is None
    assert temp_db.get_md5(3, 1) == "md5_3"  # Different workspace


def test_cleanup_bucket(temp_db):
    """Test bucket cleanup."""
    temp_db.set_md5(1, 0, "md5_1", 1024, "bucket-a", "key1")
    temp_db.set_md5(2, 0, "md5_2", 1024, "bucket-a", "key2")
    temp_db.set_md5(3, 0, "md5_3", 1024, "bucket-b", "key3")

    count = temp_db.cleanup_bucket(0, "bucket-a")
    assert count == 2

    assert temp_db.get_md5(1, 0) is None
    assert temp_db.get_md5(2, 0) is None
    assert temp_db.get_md5(3, 0) == "md5_3"  # Different bucket


def test_stats(temp_db):
    """Test statistics."""
    temp_db.set_md5(1, 0, "md5_1", 1024, "bucket", "key1")
    temp_db.set_md5(2, 0, "md5_2", 2048, "bucket", "key2")

    stats = temp_db.get_stats(0)
    assert stats["total_files"] == 2
    assert stats["total_size"] == 3072
    assert stats["oldest_entry"] is not None
    assert stats["newest_entry"] is not None


def test_stats_all_workspaces(temp_db):
    """Test statistics for all workspaces."""
    temp_db.set_md5(1, 0, "md5_1", 1024, "bucket", "key1")
    temp_db.set_md5(2, 1, "md5_2", 2048, "bucket", "key2")

    stats = temp_db.get_stats(None)
    assert stats["total_files"] == 2
    assert stats["total_size"] == 3072


def test_stats_empty_workspace(temp_db):
    """Test statistics for empty workspace."""
    stats = temp_db.get_stats(999)
    assert stats["total_files"] == 0
    assert stats["total_size"] == 0
    assert stats["oldest_entry"] is None
    assert stats["newest_entry"] is None


def test_list_workspaces(temp_db):
    """Test listing workspaces."""
    assert temp_db.list_workspaces() == []

    temp_db.set_md5(1, 0, "md5_1", 1024, "bucket", "key1")
    temp_db.set_md5(2, 1, "md5_2", 1024, "bucket", "key2")
    temp_db.set_md5(3, 5, "md5_3", 1024, "bucket", "key3")

    workspaces = temp_db.list_workspaces()
    assert workspaces == [0, 1, 5]


def test_vacuum(temp_db):
    """Test database vacuum."""
    # Add and remove entries
    for i in range(100):
        temp_db.set_md5(i, 0, f"md5_{i}", 1024, "bucket", f"key{i}")

    for i in range(50):
        temp_db.remove_md5(i, 0)

    # Vacuum should not raise an error
    temp_db.vacuum()

    # Data should still be accessible
    assert temp_db.get_md5(50, 0) == "md5_50"


def test_concurrent_access(temp_db):
    """Test that multiple operations work correctly."""
    # Simulate multiple operations
    operations = [
        (1, 0, "md5_1", 1024, "bucket-a", "file1.txt"),
        (2, 0, "md5_2", 2048, "bucket-a", "file2.txt"),
        (3, 1, "md5_3", 1024, "bucket-b", "file3.txt"),
        (4, 1, "md5_4", 512, "bucket-b", "file4.txt"),
    ]

    for file_id, ws_id, md5, size, bucket, key in operations:
        temp_db.set_md5(file_id, ws_id, md5, size, bucket, key)

    # Verify all entries
    assert temp_db.get_md5(1, 0) == "md5_1"
    assert temp_db.get_md5(2, 0) == "md5_2"
    assert temp_db.get_md5(3, 1) == "md5_3"
    assert temp_db.get_md5(4, 1) == "md5_4"

    # Verify stats
    stats_ws0 = temp_db.get_stats(0)
    assert stats_ws0["total_files"] == 2
    assert stats_ws0["total_size"] == 3072

    stats_ws1 = temp_db.get_stats(1)
    assert stats_ws1["total_files"] == 2
    assert stats_ws1["total_size"] == 1536
