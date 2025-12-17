"""Tests for Drime storage provider.

Note: These tests use mocks since they don't require actual Drime API credentials.
For integration tests with real API, run benchmarks/drime_s3_benchmark.py
"""

from datetime import datetime
from typing import Optional
from unittest.mock import MagicMock, Mock, patch

import pytest

from pys3local.errors import BucketAlreadyExists, NoSuchBucket, NoSuchKey
from pys3local.providers.drime import DrimeStorageProvider


@pytest.fixture
def mock_drime_client():
    """Create a mock Drime client."""
    client = MagicMock()
    return client


@pytest.fixture
def mock_file_entry():
    """Create a mock FileEntry."""

    def _create_entry(
        name: str,
        is_folder: bool = False,
        entry_id: int = 1,
        parent_id: Optional[int] = None,
        file_size: int = 0,
        file_hash: str = "abc123",
        description: Optional[str] = None,
    ):
        entry = Mock()
        entry.id = entry_id
        entry.name = name
        entry.is_folder = is_folder
        entry.parent_id = parent_id
        entry.file_size = file_size
        entry.hash = file_hash
        entry.mime = "application/octet-stream"
        entry.created_at = "2025-01-01T00:00:00Z"
        entry.updated_at = "2025-01-01T00:00:00Z"
        entry.description = description
        return entry

    return _create_entry


@pytest.fixture
def drime_provider(mock_drime_client):
    """Create a Drime storage provider with mock client."""
    return DrimeStorageProvider(
        client=mock_drime_client, workspace_id=0, readonly=False
    )


def test_init_provider(mock_drime_client):
    """Test provider initialization."""
    provider = DrimeStorageProvider(
        client=mock_drime_client, workspace_id=123, readonly=True
    )

    assert provider.client == mock_drime_client
    assert provider.workspace_id == 123
    assert provider.readonly is True
    assert isinstance(provider._folder_cache, dict)


def test_list_buckets(drime_provider, mock_drime_client, mock_file_entry):
    """Test listing buckets (top-level folders)."""
    # Mock the API response
    mock_entries_result = Mock()
    mock_entries_result.entries = [
        mock_file_entry("bucket1", is_folder=True, entry_id=1),
        mock_file_entry("bucket2", is_folder=True, entry_id=2),
        mock_file_entry("file.txt", is_folder=False, entry_id=3),  # Should be filtered
    ]

    mock_drime_client.get_file_entries.return_value = {"data": []}
    with patch(
        "pydrime.models.FileEntriesResult.from_api_response",
        return_value=mock_entries_result,
    ):
        buckets = drime_provider.list_buckets()

    assert len(buckets) == 2
    assert buckets[0].name == "bucket1"
    assert buckets[1].name == "bucket2"


def test_create_bucket(drime_provider, mock_drime_client, mock_file_entry):
    """Test bucket creation."""
    # Mock folder creation
    mock_drime_client.create_folder.return_value = {"id": 123, "name": "test-bucket"}

    # Mock folder doesn't exist initially
    mock_entries_result = Mock()
    mock_entries_result.entries = []
    mock_drime_client.get_file_entries.return_value = {"data": []}

    with patch(
        "pydrime.models.FileEntriesResult.from_api_response",
        return_value=mock_entries_result,
    ):
        bucket = drime_provider.create_bucket("test-bucket")

    assert bucket.name == "test-bucket"
    assert isinstance(bucket.creation_date, datetime)


def test_create_bucket_already_exists(
    drime_provider, mock_drime_client, mock_file_entry
):
    """Test creating a bucket that already exists."""
    # Mock that folder already exists
    mock_entries_result = Mock()
    mock_entries_result.entries = [
        mock_file_entry("test-bucket", is_folder=True, entry_id=1)
    ]
    mock_drime_client.get_file_entries.return_value = {"data": []}

    with patch(
        "pydrime.models.FileEntriesResult.from_api_response",
        return_value=mock_entries_result,
    ):
        with pytest.raises(BucketAlreadyExists):
            drime_provider.create_bucket("test-bucket")


def test_bucket_exists(drime_provider, mock_drime_client, mock_file_entry):
    """Test checking if bucket exists."""
    # Mock that folder exists
    mock_entries_result = Mock()
    mock_entries_result.entries = [
        mock_file_entry("test-bucket", is_folder=True, entry_id=1)
    ]
    mock_drime_client.get_file_entries.return_value = {"data": []}

    with patch(
        "pydrime.models.FileEntriesResult.from_api_response",
        return_value=mock_entries_result,
    ):
        assert drime_provider.bucket_exists("test-bucket") is True
        assert drime_provider.bucket_exists("nonexistent") is False


def test_delete_bucket_empty(drime_provider, mock_drime_client, mock_file_entry):
    """Test deleting an empty bucket."""
    # Mock bucket exists but is empty
    mock_entries_result_bucket = Mock()
    mock_entries_result_bucket.entries = [
        mock_file_entry("test-bucket", is_folder=True, entry_id=1)
    ]

    mock_entries_result_empty = Mock()
    mock_entries_result_empty.entries = []

    call_count = [0]

    def mock_from_api(response):
        call_count[0] += 1
        if call_count[0] == 1:
            return mock_entries_result_bucket
        else:
            return mock_entries_result_empty

    mock_drime_client.get_file_entries.return_value = {"data": []}
    mock_drime_client.delete_file_entries.return_value = True

    with patch(
        "pydrime.models.FileEntriesResult.from_api_response",
        side_effect=mock_from_api,
    ):
        result = drime_provider.delete_bucket("test-bucket")

    assert result is True
    mock_drime_client.delete_file_entries.assert_called_once()


def test_folder_id_caching(drime_provider, mock_drime_client, mock_file_entry):
    """Test that folder IDs are cached to reduce API calls."""
    # Mock folder structure: bucket/subfolder
    mock_bucket_result = Mock()
    mock_bucket_result.entries = [
        mock_file_entry("bucket", is_folder=True, entry_id=100)
    ]

    mock_subfolder_result = Mock()
    mock_subfolder_result.entries = [
        mock_file_entry("subfolder", is_folder=True, entry_id=200, parent_id=100)
    ]

    call_count = [0]

    def mock_from_api(response):
        call_count[0] += 1
        if call_count[0] == 1:
            return mock_bucket_result
        else:
            return mock_subfolder_result

    mock_drime_client.get_file_entries.return_value = {"data": []}

    with patch(
        "pydrime.models.FileEntriesResult.from_api_response",
        side_effect=mock_from_api,
    ):
        # First call - should make API requests
        folder_id_1 = drime_provider._get_folder_id_by_path("bucket/subfolder")
        assert folder_id_1 == 200

        # Reset call count
        call_count[0] = 0

        # Second call - should use cache
        folder_id_2 = drime_provider._get_folder_id_by_path("bucket/subfolder")
        assert folder_id_2 == 200

        # Should not have made any API calls (used cache)
        assert call_count[0] == 0


def test_parse_datetime_with_string(drime_provider):
    """Test datetime parsing from ISO string."""
    dt = drime_provider._parse_datetime("2025-01-15T10:30:00Z")
    assert isinstance(dt, datetime)
    assert dt.tzinfo is None  # Should return naive UTC datetime


def test_parse_datetime_with_datetime(drime_provider):
    """Test datetime parsing from datetime object."""
    from datetime import timezone

    now = datetime.now(timezone.utc)
    dt = drime_provider._parse_datetime(now)
    assert isinstance(dt, datetime)
    assert dt.tzinfo is None  # Should return naive UTC datetime


def test_parse_datetime_with_none(drime_provider):
    """Test datetime parsing with None."""
    dt = drime_provider._parse_datetime(None)
    assert isinstance(dt, datetime)
    assert dt.tzinfo is None


def test_readonly_mode(mock_drime_client):
    """Test that readonly mode prevents write operations."""
    provider = DrimeStorageProvider(
        client=mock_drime_client, workspace_id=0, readonly=True
    )

    with pytest.raises(PermissionError):
        provider.create_bucket("test-bucket")

    with pytest.raises(PermissionError):
        provider.put_object("bucket", "key", b"data")

    with pytest.raises(PermissionError):
        provider.delete_bucket("bucket")

    with pytest.raises(PermissionError):
        provider.delete_object("bucket", "key")


def test_nested_folder_creation(drime_provider, mock_drime_client, mock_file_entry):
    """Test creating nested folder structure."""
    # Mock responses for traversing path
    mock_root_result = Mock()
    mock_root_result.entries = []

    mock_bucket_result = Mock()
    mock_bucket_result.entries = []

    call_count = [0]

    def mock_from_api(response):
        call_count[0] += 1
        if call_count[0] == 1:
            return mock_root_result
        else:
            return mock_bucket_result

    mock_drime_client.get_file_entries.return_value = {"data": []}
    mock_drime_client.create_folder.return_value = {
        "id": 100 + call_count[0],
        "name": "folder",
    }

    with patch(
        "pydrime.models.FileEntriesResult.from_api_response",
        side_effect=mock_from_api,
    ):
        folder_id = drime_provider._get_folder_id_by_path(
            "bucket/subfolder/nested", create=True
        )

    assert folder_id is not None
    assert mock_drime_client.create_folder.call_count == 3  # 3 levels created


def test_get_bucket(drime_provider, mock_drime_client, mock_file_entry):
    """Test getting bucket information."""
    # Mock bucket exists
    mock_entries_result = Mock()
    mock_entries_result.entries = [
        mock_file_entry("test-bucket", is_folder=True, entry_id=1)
    ]
    mock_drime_client.get_file_entries.return_value = {"data": []}

    with patch(
        "pydrime.models.FileEntriesResult.from_api_response",
        return_value=mock_entries_result,
    ):
        bucket = drime_provider.get_bucket("test-bucket")

    assert bucket.name == "test-bucket"
    assert isinstance(bucket.creation_date, datetime)


def test_get_bucket_not_found(drime_provider, mock_drime_client):
    """Test getting non-existent bucket."""
    # Mock bucket doesn't exist
    mock_entries_result = Mock()
    mock_entries_result.entries = []
    mock_drime_client.get_file_entries.return_value = {"data": []}

    with patch(
        "pydrime.models.FileEntriesResult.from_api_response",
        return_value=mock_entries_result,
    ):
        with pytest.raises(NoSuchBucket):
            drime_provider.get_bucket("nonexistent")


def test_put_object_simple(drime_provider, mock_drime_client, mock_file_entry):
    """Test uploading a simple object."""
    # Mock bucket exists
    mock_bucket_result = Mock()
    mock_bucket_result.entries = [
        mock_file_entry("bucket", is_folder=True, entry_id=100)
    ]

    mock_drime_client.get_file_entries.return_value = {"data": []}
    mock_drime_client.upload_file.return_value = {
        "id": 123,
        "name": "file.txt",
        "file_size": 11,
    }

    with patch(
        "pydrime.models.FileEntriesResult.from_api_response",
        return_value=mock_bucket_result,
    ):
        result = drime_provider.put_object("bucket", "file.txt", b"hello world")

    assert result.key == "file.txt"
    assert result.size == 11
    mock_drime_client.upload_file.assert_called_once()


def test_put_object_nested_path(drime_provider, mock_drime_client, mock_file_entry):
    """Test uploading object with nested path (creates folders)."""
    # Mock bucket exists
    mock_bucket_result = Mock()
    mock_bucket_result.entries = [
        mock_file_entry("bucket", is_folder=True, entry_id=100)
    ]

    # Mock empty subfolder (will be created)
    mock_empty_result = Mock()
    mock_empty_result.entries = []

    call_count = [0]

    def mock_from_api(response):
        call_count[0] += 1
        if call_count[0] == 1:
            return mock_bucket_result
        else:
            return mock_empty_result

    mock_drime_client.get_file_entries.return_value = {"data": []}
    mock_drime_client.create_folder.return_value = {"id": 200, "name": "subfolder"}
    mock_drime_client.upload_file.return_value = {
        "id": 123,
        "name": "file.txt",
        "file_size": 11,
    }

    with patch(
        "pydrime.models.FileEntriesResult.from_api_response",
        side_effect=mock_from_api,
    ):
        result = drime_provider.put_object(
            "bucket", "subfolder/file.txt", b"hello world"
        )

    assert result.key == "subfolder/file.txt"
    assert result.size == 11
    mock_drime_client.create_folder.assert_called()  # Folder was created
    mock_drime_client.upload_file.assert_called_once()


def test_get_object(drime_provider, mock_drime_client, mock_file_entry):
    """Test getting an object."""
    # Mock bucket and file exist
    mock_bucket_result = Mock()
    mock_bucket_result.entries = [
        mock_file_entry("bucket", is_folder=True, entry_id=100)
    ]

    mock_file_result = Mock()
    mock_file_result.entries = [
        mock_file_entry(
            "file.txt",
            is_folder=False,
            entry_id=123,
            parent_id=100,
            file_size=11,
            file_hash="abc123",
        )
    ]

    call_count = [0]

    def mock_from_api(response):
        call_count[0] += 1
        if call_count[0] == 1:
            return mock_bucket_result
        else:
            return mock_file_result

    mock_drime_client.get_file_entries.return_value = {"data": []}
    mock_drime_client.get_file_content.return_value = b"hello world"

    with patch(
        "pydrime.models.FileEntriesResult.from_api_response",
        side_effect=mock_from_api,
    ):
        result = drime_provider.get_object("bucket", "file.txt")

    assert result.key == "file.txt"
    assert result.size == 11
    assert result.data == b"hello world"
    mock_drime_client.get_file_content.assert_called_once_with("abc123")


def test_get_object_not_found(drime_provider, mock_drime_client, mock_file_entry):
    """Test getting non-existent object."""
    # Mock bucket exists but file doesn't
    mock_bucket_result = Mock()
    mock_bucket_result.entries = [
        mock_file_entry("bucket", is_folder=True, entry_id=100)
    ]

    mock_empty_result = Mock()
    mock_empty_result.entries = []

    call_count = [0]

    def mock_from_api(response):
        call_count[0] += 1
        if call_count[0] == 1:
            return mock_bucket_result
        else:
            return mock_empty_result

    mock_drime_client.get_file_entries.return_value = {"data": []}

    with patch(
        "pydrime.models.FileEntriesResult.from_api_response",
        side_effect=mock_from_api,
    ):
        with pytest.raises(NoSuchKey):
            drime_provider.get_object("bucket", "nonexistent.txt")


def test_head_object(drime_provider, mock_drime_client, mock_file_entry):
    """Test getting object metadata without content."""
    # Mock bucket and file exist
    mock_bucket_result = Mock()
    mock_bucket_result.entries = [
        mock_file_entry("bucket", is_folder=True, entry_id=100)
    ]

    mock_file_result = Mock()
    mock_file_result.entries = [
        mock_file_entry(
            "file.txt", is_folder=False, entry_id=123, parent_id=100, file_size=11
        )
    ]

    call_count = [0]

    def mock_from_api(response):
        call_count[0] += 1
        if call_count[0] == 1:
            return mock_bucket_result
        else:
            return mock_file_result

    mock_drime_client.get_file_entries.return_value = {"data": []}

    with patch(
        "pydrime.models.FileEntriesResult.from_api_response",
        side_effect=mock_from_api,
    ):
        result = drime_provider.head_object("bucket", "file.txt")

    assert result.key == "file.txt"
    assert result.size == 11
    assert result.data is None  # head_object doesn't include data
    mock_drime_client.download_file.assert_not_called()


def test_delete_object(drime_provider, mock_drime_client, mock_file_entry):
    """Test deleting an object."""
    # Mock bucket and file exist
    mock_bucket_result = Mock()
    mock_bucket_result.entries = [
        mock_file_entry("bucket", is_folder=True, entry_id=100)
    ]

    mock_file_result = Mock()
    mock_file_result.entries = [
        mock_file_entry("file.txt", is_folder=False, entry_id=123, parent_id=100)
    ]

    call_count = [0]

    def mock_from_api(response):
        call_count[0] += 1
        if call_count[0] == 1:
            return mock_bucket_result
        else:
            return mock_file_result

    mock_drime_client.get_file_entries.return_value = {"data": []}
    mock_drime_client.delete_file_entries.return_value = True

    with patch(
        "pydrime.models.FileEntriesResult.from_api_response",
        side_effect=mock_from_api,
    ):
        result = drime_provider.delete_object("bucket", "file.txt")

    assert result is True
    mock_drime_client.delete_file_entries.assert_called_once()


def test_copy_object(drime_provider, mock_drime_client, mock_file_entry):
    """Test copying an object."""
    # Mock source bucket and file exist
    mock_bucket_result = Mock()
    mock_bucket_result.entries = [
        mock_file_entry("bucket", is_folder=True, entry_id=100)
    ]

    mock_file_result = Mock()
    mock_file_result.entries = [
        mock_file_entry(
            "source.txt",
            is_folder=False,
            entry_id=123,
            parent_id=100,
            file_size=11,
            file_hash="abc123",
        )
    ]

    # Mock destination bucket exists
    mock_dest_bucket_result = Mock()
    mock_dest_bucket_result.entries = [
        mock_file_entry("dest-bucket", is_folder=True, entry_id=200)
    ]

    call_count = [0]

    def mock_from_api(response):
        call_count[0] += 1
        if call_count[0] == 1:
            return mock_bucket_result  # Source bucket
        elif call_count[0] == 2:
            return mock_file_result  # Source file
        else:
            return mock_dest_bucket_result  # Dest bucket

    mock_drime_client.get_file_entries.return_value = {"data": []}
    mock_drime_client.get_file_content.return_value = b"hello world"
    mock_drime_client.upload_file.return_value = {
        "id": 456,
        "name": "dest.txt",
        "file_size": 11,
    }

    with patch(
        "pydrime.models.FileEntriesResult.from_api_response",
        side_effect=mock_from_api,
    ):
        result = drime_provider.copy_object(
            "bucket", "source.txt", "dest-bucket", "dest.txt"
        )

    assert result.key == "dest.txt"
    assert result.size == 11
    mock_drime_client.get_file_content.assert_called_once_with("abc123")
    mock_drime_client.upload_file.assert_called_once()


def test_object_exists(drime_provider, mock_drime_client, mock_file_entry):
    """Test checking if object exists."""
    # Mock bucket and file exist
    mock_bucket_result = Mock()
    mock_bucket_result.entries = [
        mock_file_entry("bucket", is_folder=True, entry_id=100)
    ]

    mock_file_result = Mock()
    mock_file_result.entries = [
        mock_file_entry("file.txt", is_folder=False, entry_id=123, parent_id=100)
    ]

    call_count = [0]

    def mock_from_api(response):
        call_count[0] += 1
        if call_count[0] == 1:
            return mock_bucket_result
        else:
            return mock_file_result

    mock_drime_client.get_file_entries.return_value = {"data": []}

    with patch(
        "pydrime.models.FileEntriesResult.from_api_response",
        side_effect=mock_from_api,
    ):
        assert drime_provider.object_exists("bucket", "file.txt") is True
        # Reset for next check
        call_count[0] = 0
        assert drime_provider.object_exists("bucket", "nonexistent.txt") is False
