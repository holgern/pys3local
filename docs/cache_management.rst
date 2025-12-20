Cache Management
================

.. warning::
   This documentation is outdated and describes the legacy MD5 caching system for the
   Drime backend. As of recent versions, the cache system has been repurposed for the
   **local storage backend** to store object metadata in SQLite instead of individual
   JSON files. The cache commands now use ``--bucket`` instead of ``--workspace``.

   For current usage, see the README.md file or run ``pys3local cache --help``.

Legacy Documentation (Drime Backend)
-------------------------------------

When using the Drime Cloud backend, pys3local maintains a local SQLite cache of MD5
hashes to ensure full S3 compatibility. This is necessary because Drime's internal
file hashes are not MD5-based, while S3 clients expect ETags to be MD5 hashes for
integrity verification.

Why Cache MD5 Hashes?
---------------------

The S3 protocol uses MD5 hashes (exposed as ETags) for:

* **Integrity verification**: Clients verify downloaded files match their expected hash
* **Conditional requests**: ETags enable If-Match and If-None-Match headers
* **Deduplication**: Some backup tools use ETags to avoid re-uploading identical files
* **Multi-part uploads**: MD5 hashes are required for completing multi-part uploads

Since Drime doesn't provide MD5 hashes, pys3local:

1. Calculates MD5 during file upload
2. Stores it in a local SQLite database
3. Returns the cached MD5 when clients request file metadata

Cache Location
--------------

The MD5 cache database is stored at:

* **Linux/macOS**: ``~/.config/pys3local/metadata.db``
* **Windows**: ``%APPDATA%\pys3local\metadata.db``

The database is shared across all workspaces, with workspace_id providing isolation.

Database Schema
~~~~~~~~~~~~~~~

.. code-block:: sql

    CREATE TABLE drime_files (
        id INTEGER PRIMARY KEY,
        file_entry_id INTEGER UNIQUE NOT NULL,  -- Drime's internal ID
        workspace_id INTEGER NOT NULL,
        md5_hash TEXT NOT NULL,
        file_size INTEGER NOT NULL,
        bucket_name TEXT NOT NULL,
        object_key TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL,
        updated_at TIMESTAMP NOT NULL,
        UNIQUE (workspace_id, bucket_name, object_key)
    );

Cache Commands
--------------

stats - View Cache Statistics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Show statistics about cached files:

.. code-block:: bash

    # Show overall statistics
    pys3local cache stats

    # Show statistics for specific workspace
    pys3local cache stats --workspace 1465

**Example output**::

    MD5 Cache Statistics

    Overall Statistics:
      Total files: 63
      Total size: 30.1 MB
      Oldest entry: 2025-12-16T16:38:11.801768+00:00
      Newest entry: 2025-12-16T16:46:57.111257+00:00

    Per-Workspace Statistics:

      Workspace 1465:
        Files: 63
        Size: 30.1 MB
        Oldest: 2025-12-16T16:38:11.801768+00:00
        Newest: 2025-12-16T16:46:57.111257+00:00

**Options**:

* ``--workspace INTEGER`` - Show stats for specific workspace only

cleanup - Clean Cache Entries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Remove cached entries for workspaces or buckets you no longer use:

.. code-block:: bash

    # Clean all entries for a workspace
    pys3local cache cleanup --workspace 1465

    # Clean specific bucket in a workspace
    pys3local cache cleanup --workspace 1465 --bucket my-bucket

    # Clean entire cache (prompts for confirmation)
    pys3local cache cleanup --all

**Options**:

* ``--workspace INTEGER`` - Clean specific workspace
* ``--bucket TEXT`` - Clean specific bucket (requires --workspace)
* ``--all`` - Clean entire cache (requires confirmation)

**Important**: Cleaning the cache doesn't delete files from Drime, only the local
MD5 records. Files will continue to work but will use Drime's internal hash until
re-uploaded.

vacuum - Optimize Database
~~~~~~~~~~~~~~~~~~~~~~~~~~

Reclaim unused disk space after deletions:

.. code-block:: bash

    pys3local cache vacuum

**Example output**::

    Optimizing cache database...
    ✓ Database optimized
      Before: 40.0 KB
      After: 35.0 KB
      Saved: 5.0 KB

This command runs SQLite's VACUUM operation to reclaim space from deleted entries.
Run this periodically after large cleanup operations.

migrate - Pre-populate Cache
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For files uploaded before MD5 caching was implemented, you can pre-populate the cache
by downloading files and calculating their MD5 hashes:

.. code-block:: bash

    # Migrate all files in a backend configuration
    pys3local cache migrate --backend-config mydrime

    # Migrate specific bucket
    pys3local cache migrate --backend-config mydrime --bucket my-bucket

    # Dry run to see what would be migrated
    pys3local cache migrate --backend-config mydrime --dry-run

**Options**:

* ``--backend-config TEXT`` - Backend configuration name (required)
* ``--workspace INTEGER`` - Migrate specific workspace (uses config default if omitted)
* ``--bucket TEXT`` - Migrate specific bucket only
* ``--dry-run`` - Show what would be migrated without actually doing it

**Note**: The migrate command currently requires manual implementation for full
functionality. Files already in cache are skipped automatically.

How Caching Works
-----------------

Upload Flow
~~~~~~~~~~~

1. Client uploads file to pys3local
2. pys3local receives the data
3. MD5 hash is calculated during upload
4. File is uploaded to Drime
5. Drime returns file_entry_id
6. MD5 is stored in cache with file_entry_id

.. code-block:: python

    # Simplified upload process
    md5_hash = hashlib.md5(data).hexdigest()
    entry = drime_client.upload(data)
    metadata_db.set_md5(
        file_entry_id=entry.id,
        workspace_id=workspace_id,
        md5_hash=md5_hash,
        # ... other metadata
    )

Download/List Flow
~~~~~~~~~~~~~~~~~~

1. Client requests file metadata
2. pys3local looks up file_entry_id from Drime
3. pys3local queries cache for MD5 using file_entry_id
4. If found: returns cached MD5 as ETag
5. If not found: falls back to entry.hash with warning

.. code-block:: python

    # Simplified lookup process
    entry = drime_client.get_file(file_id)
    md5_hash = metadata_db.get_md5(entry.id)

    if md5_hash is None:
        # Fallback for old files
        logger.warning(f"No MD5 cache for {entry.name}")
        md5_hash = entry.hash  # Not actually MD5!

    return S3Object(etag=md5_hash, ...)

Chunked Upload Support
~~~~~~~~~~~~~~~~~~~~~~~

pys3local supports AWS SDK v4 chunked uploads (``STREAMING-AWS4-HMAC-SHA256-PAYLOAD``):

1. Client sends chunked data stream
2. pys3local decodes chunks while calculating MD5
3. MD5 is calculated over decoded data
4. Upload proceeds as normal with correct MD5

This ensures compatibility with boto3, AWS CLI, and other AWS SDK v4 clients.

Best Practices
--------------

Regular Maintenance
~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Monthly: Check cache size
    pys3local cache stats

    # After deleting buckets: Clean cache and vacuum
    pys3local cache cleanup --workspace 1465 --bucket old-bucket
    pys3local cache vacuum

Backup Your Cache
~~~~~~~~~~~~~~~~~

While the cache can be rebuilt, backing it up saves time:

.. code-block:: bash

    # Linux/macOS
    cp ~/.config/pys3local/metadata.db ~/.config/pys3local/metadata.db.backup

    # Restore if needed
    cp ~/.config/pys3local/metadata.db.backup ~/.config/pys3local/metadata.db

Multiple Workspaces
~~~~~~~~~~~~~~~~~~~

The cache supports multiple workspaces automatically:

.. code-block:: bash

    # Each workspace is isolated
    pys3local serve --backend-config workspace-1465
    pys3local serve --backend-config workspace-2000

    # View stats for all workspaces
    pys3local cache stats

    # Or view specific workspace
    pys3local cache stats --workspace 1465

Troubleshooting
---------------

Cache Size Growing Too Large
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Check size breakdown
    pys3local cache stats

    # Clean unused workspaces
    pys3local cache cleanup --workspace 999

    # Optimize database
    pys3local cache vacuum

Missing MD5 for Old Files
~~~~~~~~~~~~~~~~~~~~~~~~~

If you see warnings about missing MD5 hashes:

.. code-block:: bash

    # Option 1: Re-upload files (preferred)
    # Files will automatically get cached on upload

    # Option 2: Use migrate command (when implemented)
    pys3local cache migrate --backend-config mydrime

Cache Corruption
~~~~~~~~~~~~~~~~

If the cache database becomes corrupted:

.. code-block:: bash

    # Remove cache (files still safe in Drime)
    rm ~/.config/pys3local/metadata.db

    # Restart server - cache will be recreated
    pys3local serve --backend-config mydrime

    # Re-upload files or use migrate to rebuild cache

Performance Considerations
--------------------------

* **Cache size**: Each entry uses ~200 bytes. 1 million files ≈ 200 MB
* **Lookup speed**: SQLite indexes provide O(log n) lookup time
* **Concurrent access**: SQLite handles concurrent reads automatically
* **Write performance**: MD5 calculation adds ~50ms per 10MB file

The cache database is optimized for read-heavy workloads, which matches typical
S3 usage patterns (many metadata requests, fewer uploads).

Advanced Usage
--------------

Programmatic Access
~~~~~~~~~~~~~~~~~~~

You can access the cache directly in Python:

.. code-block:: python

    from pys3local.metadata_db import MetadataDB

    db = MetadataDB()

    # Get statistics
    stats = db.get_stats()
    print(f"Total files: {stats['total_files']}")

    # Get MD5 for a file
    md5 = db.get_md5_by_key(
        workspace_id=1465,
        bucket_name="my-bucket",
        object_key="path/to/file.txt"
    )

    # Clean workspace
    removed = db.cleanup_workspace(1465)
    print(f"Removed {removed} entries")

Custom Cache Location
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from pathlib import Path
    from pys3local.metadata_db import MetadataDB

    # Use custom location
    db = MetadataDB(db_path=Path("/custom/path/cache.db"))

See Also
--------

* :doc:`quickstart` - Getting started with pys3local
* :doc:`installation` - Installation instructions
* ``pys3local cache --help`` - Command-line help
