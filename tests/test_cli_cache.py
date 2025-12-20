"""Tests for CLI cache management commands."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from pys3local.cli import cache, cache_cleanup, cache_stats, cache_vacuum
from pys3local.metadata_db import MetadataDB


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cache.db"
        db = MetadataDB(db_path=db_path)
        yield db


@pytest.fixture
def populated_db(temp_db):
    """Create a database with test data for local storage."""
    from datetime import datetime

    # Add some test entries for local storage
    temp_db.set_local_object(
        bucket_name="test-bucket",
        object_key="file1.txt",
        size=1024,
        etag="d41d8cd98f00b204e9800998ecf8427e",
        last_modified=datetime.utcnow(),
        content_type="text/plain",
        metadata={},
    )
    temp_db.set_local_object(
        bucket_name="test-bucket",
        object_key="file2.txt",
        size=2048,
        etag="098f6bcd4621d373cade4e832627b4f6",
        last_modified=datetime.utcnow(),
        content_type="text/plain",
        metadata={},
    )
    temp_db.set_local_object(
        bucket_name="other-bucket",
        object_key="file3.txt",
        size=512,
        etag="5d41402abc4b2a76b9719d911017c592",
        last_modified=datetime.utcnow(),
        content_type="text/plain",
        metadata={},
    )
    return temp_db


def test_cache_stats_empty(temp_db):
    """Test cache stats with empty database."""
    runner = CliRunner()

    with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
        mock_db_class.return_value = temp_db
        result = runner.invoke(cache_stats)

    assert result.exit_code == 0
    assert "Cache is empty" in result.output


def test_cache_stats_all_buckets(populated_db):
    """Test cache stats showing all buckets."""
    runner = CliRunner()

    with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
        mock_db_class.return_value = populated_db
        result = runner.invoke(cache_stats)

    assert result.exit_code == 0
    assert "Overall Statistics" in result.output
    assert "Total objects: 3" in result.output
    assert "test-bucket" in result.output
    assert "other-bucket" in result.output


def test_cache_stats_specific_bucket(populated_db):
    """Test cache stats for specific bucket."""
    runner = CliRunner()

    with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
        mock_db_class.return_value = populated_db
        result = runner.invoke(cache_stats, ["--bucket", "test-bucket"])

    assert result.exit_code == 0
    assert "test-bucket" in result.output
    assert "Total objects: 2" in result.output
    assert "other-bucket" not in result.output


def test_cache_stats_empty_bucket(populated_db):
    """Test cache stats for bucket with no entries."""
    runner = CliRunner()

    with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
        mock_db_class.return_value = populated_db
        result = runner.invoke(cache_stats, ["--bucket", "empty-bucket"])

    assert result.exit_code == 0
    assert "No cache entries for bucket 'empty-bucket'" in result.output


def test_cache_cleanup_bucket(populated_db):
    """Test cleaning cache for specific bucket."""
    runner = CliRunner()

    with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
        mock_db_class.return_value = populated_db
        result = runner.invoke(cache_cleanup, ["--bucket", "test-bucket"])

    assert result.exit_code == 0
    assert "Removed 2 objects" in result.output
    assert "test-bucket" in result.output

    # Verify entries were removed
    assert populated_db.get_local_object("test-bucket", "file1.txt") is None
    assert populated_db.get_local_object("test-bucket", "file2.txt") is None
    # Other bucket should still exist
    assert populated_db.get_local_object("other-bucket", "file3.txt") is not None


def test_cache_cleanup_no_options(temp_db):
    """Test that cleanup requires at least one option."""
    runner = CliRunner()

    with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
        mock_db_class.return_value = temp_db
        result = runner.invoke(cache_cleanup)

    assert result.exit_code == 1
    assert "Must specify" in result.output


def test_cache_cleanup_all_with_confirmation(populated_db):
    """Test cleaning entire cache with confirmation."""
    runner = CliRunner()

    with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
        mock_db_class.return_value = populated_db
        # Simulate user confirming
        result = runner.invoke(cache_cleanup, ["--all"], input="y\n")

    assert result.exit_code == 0
    assert "Removed 3 objects" in result.output


def test_cache_cleanup_all_abort(populated_db):
    """Test aborting cache cleanup."""
    runner = CliRunner()

    with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
        mock_db_class.return_value = populated_db
        # Simulate user declining
        result = runner.invoke(cache_cleanup, ["--all"], input="n\n")

    assert result.exit_code == 0
    assert "Aborted" in result.output
    # Verify nothing was deleted
    assert populated_db.get_local_object("test-bucket", "file1.txt") is not None


def test_cache_cleanup_conflicting_options(temp_db):
    """Test that --all cannot be combined with --bucket."""
    runner = CliRunner()

    with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
        mock_db_class.return_value = temp_db
        result = runner.invoke(cache_cleanup, ["--all", "--bucket", "test-bucket"])

    assert result.exit_code == 1
    assert "Cannot combine" in result.output


def test_cache_vacuum(populated_db):
    """Test cache vacuum command."""
    runner = CliRunner()

    with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
        mock_db_class.return_value = populated_db
        result = runner.invoke(cache_vacuum)

    assert result.exit_code == 0
    assert "Database optimized" in result.output
    assert "Before:" in result.output
    assert "After:" in result.output


def test_format_size():
    """Test the _format_size helper function."""
    from pys3local.cli import _format_size

    assert "0.0 B" in _format_size(0)
    assert "1.0 KB" in _format_size(1024)
    assert "1.0 MB" in _format_size(1024 * 1024)
    assert "1.0 GB" in _format_size(1024 * 1024 * 1024)
    assert "1.0 TB" in _format_size(1024 * 1024 * 1024 * 1024)


def test_cache_group_help():
    """Test cache command group help."""
    runner = CliRunner()
    result = runner.invoke(cache, ["--help"])

    assert result.exit_code == 0
    assert "metadata cache" in result.output.lower()
    assert "stats" in result.output
    assert "cleanup" in result.output
    assert "vacuum" in result.output
