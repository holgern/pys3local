Project Summary
===============

Overview
--------

**pys3local** is a local S3-compatible server designed for backup software with pluggable storage backends. It follows the architecture pattern of pyrestserver but implements the AWS S3 API instead of the restic REST API.

Key Features
------------

✅ **S3-Compatible API** - Full AWS S3 API implementation using FastAPI

✅ **Pluggable Backends** - Support for local filesystem and Drime Cloud storage

✅ **AWS Authentication** - Signature V2 and V4 support with presigned URLs

✅ **Backup Tool Integration** - Tested with rclone and duplicati

✅ **Configuration Management** - Built-in config management with vaultconfig

✅ **Rich CLI** - User-friendly command-line interface

✅ **Modern Stack** - FastAPI, uvicorn, Python 3.9+

Architecture
------------

Core Components
~~~~~~~~~~~~~~~

::

   pys3local/
   ├── __init__.py           # Package initialization
   ├── constants.py          # Configuration constants
   ├── errors.py             # S3-specific error classes
   ├── models.py             # Data models (Bucket, S3Object)
   ├── provider.py           # Abstract StorageProvider interface
   ├── xml_templates.py      # S3 XML response templates
   ├── auth.py               # AWS Signature V2/V4 authentication
   ├── config.py             # Configuration management (vaultconfig)
   ├── server.py             # FastAPI S3 server implementation
   ├── cli.py                # Click-based CLI interface
   └── providers/
       ├── __init__.py
       ├── local.py          # Local filesystem provider
       └── drime.py          # Drime cloud provider (stub)

Storage Provider Pattern
~~~~~~~~~~~~~~~~~~~~~~~~

All backends implement the abstract ``StorageProvider`` interface:

.. code-block:: python

   class StorageProvider(ABC):
       # Bucket operations
       def list_buckets() -> list[Bucket]
       def create_bucket(bucket_name: str) -> Bucket
       def delete_bucket(bucket_name: str) -> bool
       def bucket_exists(bucket_name: str) -> bool

       # Object operations
       def put_object(bucket_name, key, data, ...) -> S3Object
       def get_object(bucket_name, key) -> S3Object
       def delete_object(bucket_name, key) -> bool
       def list_objects(bucket_name, prefix, ...) -> dict
       def copy_object(src_bucket, src_key, dst_bucket, dst_key) -> S3Object
       def head_object(bucket_name, key) -> S3Object
       def object_exists(bucket_name, key) -> bool
       def delete_objects(bucket_name, keys) -> dict

       # Provider info
       def is_readonly() -> bool

Implementation Details
----------------------

1. Local Storage Provider
~~~~~~~~~~~~~~~~~~~~~~~~~~

**Features:**

- Stores buckets as directories
- Objects stored with metadata in separate JSON files
- Proper permission handling (0700 for dirs, 0600 for files)
- Support for nested keys (directory structure)
- AWS S3 bucket name validation
- Efficient object listing with prefix/delimiter support

**Storage Structure:**

::

   /path/to/data/
   ├── bucket1/
   │   ├── .metadata/          # Object metadata
   │   │   ├── file1.txt.json
   │   │   └── dir/file2.txt.json
   │   └── objects/            # Object data
   │       ├── file1.txt
   │       └── dir/file2.txt

2. S3 API Server
~~~~~~~~~~~~~~~~

**Implemented Operations:**

- ``GET /`` - List buckets
- ``PUT /{bucket}`` - Create bucket
- ``DELETE /{bucket}`` - Delete bucket
- ``HEAD /{bucket}`` - Check bucket exists
- ``GET /{bucket}`` - List objects
- ``PUT /{bucket}/{key}`` - Upload object
- ``GET /{bucket}/{key}`` - Download object
- ``HEAD /{bucket}/{key}`` - Get object metadata
- ``DELETE /{bucket}/{key}`` - Delete object
- ``POST /{bucket}?delete`` - Delete multiple objects
- Copy operations via ``x-amz-copy-source`` header

**Authentication:**

- AWS Signature Version 2 (legacy)
- AWS Signature Version 4 (modern)
- Presigned URLs (for temporary access)
- Optional no-auth mode for testing

3. CLI Interface
~~~~~~~~~~~~~~~~

**Commands:**

.. code-block:: bash

   pys3local serve      # Start server
   pys3local config     # Interactive configuration
   pys3local obscure    # Obscure passwords

**Serve Options:**

- ``--path`` - Data directory
- ``--listen`` - Listen address (host:port)
- ``--access-key-id`` - AWS access key
- ``--secret-access-key`` - AWS secret key
- ``--region`` - AWS region
- ``--no-auth`` - Disable authentication
- ``--debug`` - Enable debug logging
- ``--backend`` - Storage backend (local/drime)
- ``--backend-config`` - Use saved configuration

Integration Examples
--------------------

With rclone
~~~~~~~~~~~

.. code-block:: bash

   # Start server
   pys3local serve --path /srv/backup --access-key-id key --secret-access-key secret

   # Configure rclone
   rclone config create pys3 s3 \
       provider=Other \
       access_key_id=key \
       secret_access_key=secret \
       endpoint=http://localhost:10001 \
       region=us-east-1

   # Use it
   rclone sync /data pys3:mybucket/backup

With duplicati
~~~~~~~~~~~~~~

1. Start: ``pys3local serve --path /srv/duplicati``
2. Configure Duplicati:

   - Storage: S3 Compatible
   - Server URL: ``http://localhost:10001``
   - Credentials: As configured

With boto3 (Python)
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import boto3

   s3 = boto3.client(
       's3',
       endpoint_url='http://localhost:10001',
       aws_access_key_id='test',
       aws_secret_access_key='test'
   )

   s3.create_bucket(Bucket='mybucket')
   s3.put_object(Bucket='mybucket', Key='file.txt', Body=b'data')

Comparison with Related Projects
---------------------------------

vs. pyrestserver
~~~~~~~~~~~~~~~~

- **Same:** Architecture pattern, provider interface, configuration management
- **Different:** S3 API instead of restic REST API, FastAPI instead of WSGI

vs. local-s3-server
~~~~~~~~~~~~~~~~~~~

- **Same:** S3 API implementation, FastAPI-based
- **Different:** Pluggable backends, configuration management, CLI interface

vs. MinIO
~~~~~~~~~

- **Different:** Lightweight, Python-based, focused on backup tools
- **Same:** S3 compatibility

Technical Stack
---------------

**Core:**

- Python 3.9+
- FastAPI (async web framework)
- uvicorn (ASGI server)

**CLI & Config:**

- Click (CLI framework)
- Rich (terminal formatting)
- vaultconfig (config management)

**Security:**

- defusedxml (safe XML parsing)
- HMAC-SHA256 signatures

Testing
-------

Test suite includes:

- Bucket operations (create, list, delete)
- Object operations (put, get, delete, copy)
- Listing with prefix/delimiter
- Bucket name validation
- Multi-delete operations

Run tests:

.. code-block:: bash

   pytest tests/

Future Enhancements
-------------------

**Planned:**

- Full Drime backend implementation
- Multipart upload support
- Object versioning
- Lifecycle policies
- Encryption at rest
- More comprehensive tests
- Performance benchmarks

**Possible:**

- Additional cloud backends (S3, GCS, Azure)
- Web UI for management
- Metrics and monitoring
- Rate limiting
- Caching layer

Dependencies
------------

**Required:**

- click>=8.0.0
- fastapi>=0.68.0
- uvicorn>=0.15.0
- rich>=13.0.0
- vaultconfig>=0.2.0
- defusedxml>=0.7.1
- python-multipart>=0.0.5

**Optional:**

- pydrime>=0.1.0 (for Drime backend)

**Development:**

- pytest>=7.0.0
- pytest-asyncio>=0.18.0
- boto3>=1.20.0 (for testing)
- ruff>=0.1.0 (linting)

Configuration Files
-------------------

**Backend Config:** ``~/.config/pys3local/backends.toml``

**rclone Config:** ``~/.config/rclone/rclone.conf``

Ports
-----

- **Default:** 10001 (matching local-s3-server)
- **Configurable:** via ``--listen`` option

License
-------

MIT License

Credits
-------

- Architecture inspired by **pyrestserver**
- S3 implementation based on **local-s3-server**
- Configuration management via **vaultconfig**

Links
-----

- Repository: https://github.com/holgern/pys3local
- PyPI: https://pypi.org/project/pys3local/
- Issues: https://github.com/holgern/pys3local/issues

Installation
------------

.. code-block:: bash

   pip install pys3local

Quick Test
----------

.. code-block:: bash

   # Terminal 1
   pys3local serve --no-auth

   # Terminal 2
   python3 -c "
   import boto3
   s3 = boto3.client('s3', endpoint_url='http://localhost:10001', aws_access_key_id='test', aws_secret_access_key='test')
   s3.create_bucket(Bucket='test')
   print('Success!')
   "

Status
------

✅ **Core implementation complete and functional**

**Version:** 0.1.0 (initial release)

**Date:** December 2024
