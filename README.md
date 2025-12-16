# pys3local

[![PyPI - Version](https://img.shields.io/pypi/v/pys3local)](https://pypi.org/project/pys3local/)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/pys3local)

Local S3-compatible server for backup software with pluggable storage backends.

This package provides a Python implementation of an S3-compatible API with support for
multiple storage backends, including local filesystem and Drime Cloud storage. It's
designed to work seamlessly with backup tools like **rclone** and **duplicati**.

## Features

- **S3-compatible API** - Works with standard S3 clients and backup tools
- **Pluggable storage backends** - Support for local filesystem and cloud storage
  (Drime)
- **AWS Signature V2/V4 authentication** - Full authentication support with presigned
  URLs
- **FastAPI-powered** - Modern async support with high performance
- **Easy configuration** - Simple CLI interface and configuration management
- **Backup tool integration** - Tested with rclone and duplicati

## Supported S3 Operations

- **Bucket Operations**

  - CreateBucket
  - DeleteBucket
  - ListBuckets
  - HeadBucket

- **Object Operations**

  - PutObject
  - GetObject
  - DeleteObject
  - DeleteObjects (multiple objects)
  - ListObjects / ListObjectsV2
  - CopyObject
  - HeadObject

- **Authentication**
  - AWS Signature Version 2
  - AWS Signature Version 4
  - Presigned URLs (GET and PUT)

## Installation

### Basic Installation (Local filesystem only)

```bash
pip install pys3local
```

### With Drime Cloud Backend

```bash
pip install pys3local[drime]
```

### Development Installation

```bash
git clone https://github.com/holgern/pys3local.git
cd pys3local
pip install -e ".[dev,drime]"
```

## Quick Start

### Local Filesystem Backend

Start a server with local filesystem storage:

```bash
# Start server with default settings (no auth, data in /tmp/s3store)
pys3local serve --path /tmp/s3store --no-auth

# Start with authentication
pys3local serve --path /srv/s3 --access-key-id mykey --secret-access-key mysecret

# Start on different port
pys3local serve --path /srv/s3 --listen :9000
```

### Drime Cloud Backend

Start a server with Drime Cloud storage:

```bash
# Set environment variable for Drime API key
export DRIME_API_KEY="your-api-key"

# Start server with Drime backend
pys3local serve --backend drime --no-auth
```

### Using with rclone

Configure rclone to use pys3local:

```ini
# ~/.config/rclone/rclone.conf
[pys3local]
type = s3
provider = Other
access_key_id = mykey
secret_access_key = mysecret
endpoint = http://localhost:10001
region = us-east-1
```

Then use it:

```bash
# Start pys3local server
pys3local serve --path /srv/s3 --access-key-id mykey --secret-access-key mysecret

# Use with rclone
rclone mkdir pys3local:mybucket
rclone copy /data pys3local:mybucket/backup
rclone ls pys3local:mybucket
rclone sync /data pys3local:mybucket/backup
```

### Using with duplicati

1. Start pys3local server:

```bash
pys3local serve --path /srv/s3 --access-key-id mykey --secret-access-key mysecret
```

2. In Duplicati, add a new backup:
   - Choose "S3 Compatible" as storage type
   - Server URL: `http://localhost:10001`
   - Bucket name: `mybackup`
   - AWS Access ID: `mykey`
   - AWS Secret Key: `mysecret`
   - Storage class: Leave empty or use `STANDARD`

### Using with boto3 (Python)

```python
import boto3

# Create S3 client
s3 = boto3.client(
    's3',
    endpoint_url='http://localhost:10001',
    aws_access_key_id='mykey',
    aws_secret_access_key='mysecret',
    region_name='us-east-1'
)

# Create bucket
s3.create_bucket(Bucket='mybucket')

# Upload file
s3.upload_file('/path/to/file.txt', 'mybucket', 'file.txt')

# List objects
response = s3.list_objects_v2(Bucket='mybucket')
for obj in response.get('Contents', []):
    print(obj['Key'])

# Download file
s3.download_file('mybucket', 'file.txt', '/path/to/download.txt')
```

## Command Line Interface

The `pys3local` command provides a CLI interface:

```
Usage: pys3local [OPTIONS] COMMAND [ARGS]...

Commands:
  serve    Start the S3-compatible server
  config   Enter an interactive configuration session
  obscure  Obscure a password for use in config files
  cache    Manage MD5 metadata cache for Drime backend
```

### Server Options

```bash
pys3local serve --help

Options:
  --path TEXT                Data directory (default: /tmp/s3store)
  --listen TEXT              Listen address (default: :10001)
  --access-key-id TEXT       AWS access key ID (default: test)
  --secret-access-key TEXT   AWS secret access key (default: test)
  --region TEXT              AWS region (default: us-east-1)
  --no-auth                  Disable authentication
  --debug                    Enable debug logging
  --backend [local|drime]    Storage backend (default: local)
  --backend-config TEXT      Backend configuration name
```

## Configuration Management

pys3local supports storing backend configurations for easy reuse:

```bash
# Enter interactive configuration mode
pys3local config

# Obscure a password
pys3local obscure mypassword
```

Configuration files are stored in `~/.config/pys3local/backends.toml`:

```toml
[mylocal]
type = "local"
path = "/srv/s3data"

[mydrime]
type = "drime"
api_key = "obscured_key_here"
workspace_id = 0
```

Use a saved configuration:

```bash
pys3local serve --backend-config mylocal
pys3local serve --backend-config mydrime
```

## MD5 Cache Management (Drime Backend)

When using the Drime backend, pys3local maintains a local SQLite cache of MD5 hashes to
ensure S3 compatibility. The cache stores MD5 hashes for uploaded files, since Drime's
internal hashes are not MD5-compatible.

### Cache Commands

#### View Cache Statistics

```bash
# Show overall statistics
pys3local cache stats

# Show statistics for specific workspace
pys3local cache stats --workspace 1465
```

Example output:

```
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
```

#### Clean Cache Entries

```bash
# Clean all entries for a workspace
pys3local cache cleanup --workspace 1465

# Clean specific bucket in a workspace
pys3local cache cleanup --workspace 1465 --bucket my-bucket

# Clean entire cache (with confirmation prompt)
pys3local cache cleanup --all
```

#### Optimize Database

```bash
# Reclaim unused space after deletions
pys3local cache vacuum
```

Example output:

```
Optimizing cache database...
✓ Database optimized
  Before: 40.0 KB
  After: 35.0 KB
  Saved: 5.0 KB
```

#### Pre-populate Cache (Migration)

For files uploaded before MD5 caching was implemented, you can pre-populate the cache:

```bash
# Migrate all files in a backend configuration
pys3local cache migrate --backend-config mydrime

# Migrate specific bucket
pys3local cache migrate --backend-config mydrime --bucket my-bucket

# Dry run to see what would be migrated
pys3local cache migrate --backend-config mydrime --dry-run
```

### Cache Location

The MD5 cache database is stored at:

- Linux/macOS: `~/.config/pys3local/metadata.db`
- Windows: `%APPDATA%/pys3local/metadata.db`

### How It Works

1. **On Upload**: When you upload a file through pys3local to Drime, the MD5 hash is
   calculated and stored in the local cache along with the Drime file ID.

2. **On Download/List**: When S3 clients request file metadata (ETag), pys3local returns
   the cached MD5 hash, ensuring S3 compatibility.

3. **Fallback**: For files uploaded before caching was implemented, pys3local falls back
   to using Drime's internal hash with a warning.

## Storage Backends

### Local Filesystem

The local filesystem backend stores S3 buckets and objects on disk:

```
/path/to/data/
├── bucket1/
│   ├── .metadata/          # Object metadata (JSON files)
│   │   ├── file1.txt.json
│   │   └── dir/file2.txt.json
│   └── objects/            # Object data
│       ├── file1.txt
│       └── dir/
│           └── file2.txt
└── bucket2/
```

Features:

- Automatic directory creation
- Proper file permissions (0700 for directories, 0600 for files)
- Metadata stored separately from object data
- Support for nested keys (directories)

### Drime Cloud

The Drime backend stores data in Drime Cloud storage.

Features:

- Full S3 API compatibility through Drime's file API
- Local MD5 cache for S3 ETag compatibility
- Support for chunked uploads (AWS SDK v4)
- Concurrent folder creation with retry logic
- Workspace isolation

Configuration:

```bash
# Using environment variables
export DRIME_API_KEY="your-api-key"
export DRIME_WORKSPACE_ID="1465"
pys3local serve --backend drime

# Using saved configuration
pys3local config  # Add Drime backend
pys3local serve --backend-config mydrime
```

The Drime backend automatically manages an MD5 cache at
`~/.config/pys3local/metadata.db` to ensure S3 compatibility. See the
[MD5 Cache Management](#md5-cache-management-drime-backend) section for details.

## Programmatic Usage

You can use pys3local as a library in your Python code:

```python
from pathlib import Path
import uvicorn
from pys3local.providers.local import LocalStorageProvider
from pys3local.server import create_s3_app

# Create a storage provider
provider = LocalStorageProvider(
    base_path=Path("/srv/s3"),
    readonly=False
)

# Create the FastAPI application
app = create_s3_app(
    provider=provider,
    access_key="mykey",
    secret_key="mysecret",
    region="us-east-1",
    no_auth=False
)

# Run with uvicorn
uvicorn.run(app, host="0.0.0.0", port=10001)
```

## Development

### Running Tests

```bash
pytest
```

### Code Quality

```bash
# Run ruff linter
ruff check .

# Format code
ruff format .
```

## Differences from similar projects

### vs. local-s3-server

- **Architecture**: pys3local uses a pluggable provider architecture similar to
  pyrestserver
- **Configuration**: Built-in configuration management with vaultconfig
- **Backends**: Support for multiple storage backends (local and cloud)
- **CLI**: Comprehensive CLI interface matching pyrestserver style

### vs. minio

- **Simplicity**: pys3local is designed for local development and testing, not
  production
- **Size**: Much smaller and simpler codebase
- **Purpose**: Focused on backup tool integration rather than full S3 compatibility

## Architecture

### Storage Provider Interface

All storage backends implement the `StorageProvider` abstract base class:

```python
class StorageProvider(ABC):
    @abstractmethod
    def list_buckets(self) -> list[Bucket]: ...

    @abstractmethod
    def create_bucket(self, bucket_name: str) -> Bucket: ...

    @abstractmethod
    def put_object(self, bucket_name: str, key: str, data: bytes, ...) -> S3Object: ...

    @abstractmethod
    def get_object(self, bucket_name: str, key: str) -> S3Object: ...

    # ... and more
```

This makes it easy to implement new storage backends.

## License

MIT License - See LICENSE file for details

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Credits

- Inspired by [pyrestserver](https://github.com/holgern/pyrestserver) architecture
- Based on concepts from [local-s3-server](https://github.com/oeway/local-s3-server)
- Uses [vaultconfig](https://github.com/holgern/vaultconfig) for configuration
  management

## Links

- [rclone](https://rclone.org/) - rsync for cloud storage
- [duplicati](https://www.duplicati.com/) - Free backup software
- [restic](https://restic.net/) - Fast, secure, efficient backup program
- [AWS S3 Documentation](https://docs.aws.amazon.com/s3/)
