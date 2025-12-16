"""Tests for CLI cache management commands."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from pys3local.cli import cache, cache_cleanup, cache_migrate, cache_stats, cache_vacuum
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
    """Create a database with test data."""
    # Add some test entries
    temp_db.set_md5(
        file_entry_id=1,
        workspace_id=1465,
        md5_hash="d41d8cd98f00b204e9800998ecf8427e",
        file_size=1024,
        bucket_name="test-bucket",
        object_key="file1.txt",
    )
    temp_db.set_md5(
        file_entry_id=2,
        workspace_id=1465,
        md5_hash="098f6bcd4621d373cade4e832627b4f6",
        file_size=2048,
        bucket_name="test-bucket",
        object_key="file2.txt",
    )
    temp_db.set_md5(
        file_entry_id=3,
        workspace_id=2000,
        md5_hash="5d41402abc4b2a76b9719d911017c592",
        file_size=512,
        bucket_name="other-bucket",
        object_key="file3.txt",
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


def test_cache_stats_all_workspaces(populated_db):
    """Test cache stats showing all workspaces."""
    runner = CliRunner()

    with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
        mock_db_class.return_value = populated_db
        result = runner.invoke(cache_stats)

    assert result.exit_code == 0
    assert "Overall Statistics" in result.output
    assert "Total files: 3" in result.output
    assert "Workspace 1465" in result.output
    assert "Workspace 2000" in result.output


def test_cache_stats_specific_workspace(populated_db):
    """Test cache stats for specific workspace."""
    runner = CliRunner()

    with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
        mock_db_class.return_value = populated_db
        result = runner.invoke(cache_stats, ["--workspace", "1465"])

    assert result.exit_code == 0
    assert "Workspace 1465" in result.output
    assert "Total files: 2" in result.output
    assert "Workspace 2000" not in result.output


def test_cache_stats_empty_workspace(populated_db):
    """Test cache stats for workspace with no entries."""
    runner = CliRunner()

    with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
        mock_db_class.return_value = populated_db
        result = runner.invoke(cache_stats, ["--workspace", "9999"])

    assert result.exit_code == 0
    assert "No cache entries for workspace 9999" in result.output


def test_cache_cleanup_workspace(populated_db):
    """Test cleaning cache for specific workspace."""
    runner = CliRunner()

    with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
        mock_db_class.return_value = populated_db
        result = runner.invoke(cache_cleanup, ["--workspace", "1465"])

    assert result.exit_code == 0
    assert "Removed 2 entries for workspace 1465" in result.output

    # Verify entries were removed
    assert populated_db.get_md5(1, 1465) is None
    assert populated_db.get_md5(2, 1465) is None
    # Other workspace should still exist
    assert populated_db.get_md5(3, 2000) is not None


def test_cache_cleanup_bucket(populated_db):
    """Test cleaning cache for specific bucket."""
    runner = CliRunner()

    with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
        mock_db_class.return_value = populated_db
        result = runner.invoke(
            cache_cleanup, ["--workspace", "1465", "--bucket", "test-bucket"]
        )

    assert result.exit_code == 0
    assert "Removed 2 entries" in result.output
    assert "test-bucket" in result.output


def test_cache_cleanup_bucket_without_workspace(temp_db):
    """Test that bucket cleanup requires workspace."""
    runner = CliRunner()

    with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
        mock_db_class.return_value = temp_db
        result = runner.invoke(cache_cleanup, ["--bucket", "test-bucket"])

    assert result.exit_code == 1
    assert "--bucket requires --workspace" in result.output


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
    assert "Removed 3 entries" in result.output


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
    assert populated_db.get_md5(1, 1465) is not None


def test_cache_cleanup_conflicting_options(temp_db):
    """Test that --all cannot be combined with --workspace."""
    runner = CliRunner()

    with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
        mock_db_class.return_value = temp_db
        result = runner.invoke(cache_cleanup, ["--all", "--workspace", "123"])

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


def test_cache_migrate_missing_backend_config():
    """Test that migrate requires backend-config."""
    runner = CliRunner()
    result = runner.invoke(cache_migrate)

    assert result.exit_code == 2  # Click error for missing required option
    assert "backend-config" in result.output.lower()


def test_cache_migrate_dry_run():
    """Test cache migrate in dry-run mode."""
    runner = CliRunner()

    # Mock the provider creation
    mock_provider = MagicMock()
    mock_provider.list_buckets.return_value = MagicMock(buckets=[])

    with patch("pys3local.cli._create_drime_provider") as mock_create:
        mock_create.return_value = (mock_provider, {"workspace_id": 1465})

        with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
            mock_db = MagicMock()
            mock_db_class.return_value = mock_db

            result = runner.invoke(
                cache_migrate, ["--backend-config", "test", "--dry-run"]
            )

    assert result.exit_code == 0
    assert "DRY RUN" in result.output


def test_cache_migrate_with_bucket():
    """Test cache migrate for specific bucket."""
    runner = CliRunner()

    # Mock bucket and objects
    mock_bucket = MagicMock()
    mock_bucket.name = "test-bucket"

    mock_obj = MagicMock()
    mock_obj.key = "file.txt"

    mock_provider = MagicMock()
    mock_provider.list_buckets.return_value = MagicMock(buckets=[mock_bucket])
    mock_provider.list_objects.return_value = MagicMock(contents=[mock_obj])

    with patch("pys3local.cli._create_drime_provider") as mock_create:
        mock_create.return_value = (mock_provider, {"workspace_id": 1465})

        with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
            mock_db = MagicMock()
            mock_db.get_md5_by_key.return_value = None  # Not cached
            mock_db_class.return_value = mock_db

            result = runner.invoke(
                cache_migrate,
                ["--backend-config", "test", "--bucket", "test-bucket", "--dry-run"],
            )

    assert result.exit_code == 0
    assert "test-bucket" in result.output


def test_cache_migrate_nonexistent_bucket():
    """Test cache migrate with nonexistent bucket."""
    runner = CliRunner()

    mock_bucket = MagicMock()
    mock_bucket.name = "other-bucket"

    mock_provider = MagicMock()
    mock_provider.list_buckets.return_value = MagicMock(buckets=[mock_bucket])

    with patch("pys3local.cli._create_drime_provider") as mock_create:
        mock_create.return_value = (mock_provider, {"workspace_id": 1465})

        with patch("pys3local.metadata_db.MetadataDB") as mock_db_class:
            mock_db = MagicMock()
            mock_db_class.return_value = mock_db

            result = runner.invoke(
                cache_migrate, ["--backend-config", "test", "--bucket", "missing"]
            )

    assert result.exit_code == 1
    assert "not found" in result.output


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
    assert "Manage MD5 metadata cache" in result.output
    assert "stats" in result.output
    assert "cleanup" in result.output
    assert "vacuum" in result.output
    assert "migrate" in result.output
