# pys3local

[![PyPI - Version](https://img.shields.io/pypi/v/pys3local)](https://pypi.org/project/pys3local/)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/pys3local)

Local S3-compatible server for backup software with pluggable storage backends.

This package provides a Python implementation of an S3-compatible API with support for
multiple storage backends, including local filesystem and Drime Cloud storage. It's
designed to work seamlessly with backup tools like **rclone** and **duplicati**.

## Features

- **S3-compatible API** - Works with standard S3 clients and backup tools
- **Two bucket modes** - Default mode (virtual "default" bucket) or advanced mode
  (custom buckets)
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

### Bucket Modes

pys3local supports two bucket modes:

**1. Default Mode (Recommended for backup tools)**

By default, pys3local uses a virtual "default" bucket. This simplifies backup tool
configuration and mirrors the behavior of drime-s3 gateway.

```bash
# Start in default mode (only "default" bucket available)
pys3local serve --path /tmp/s3store --no-auth

# Use with rclone
rclone lsd pys3local:              # Shows "default" bucket
rclone copy /data pys3local:default/backup
rclone ls pys3local:default/
```

**2. Advanced Mode (Custom buckets)**

Enable custom bucket creation with the `--allow-bucket-creation` flag:

```bash
# Start in advanced mode (allows custom buckets)
pys3local serve --path /srv/s3 --no-auth --allow-bucket-creation

# Use with rclone
rclone mkdir pys3local:mybucket
rclone mkdir pys3local:another-bucket
rclone copy /data pys3local:mybucket/backup
```

**Choosing a mode:**

- Use **default mode** for simpler backup configurations (recommended)
- Use **advanced mode** if you need multiple custom buckets

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

**Step 1: Start pys3local server**

The server will display the rclone configuration when it starts. Choose one of:

```bash
# Option A: No authentication, default mode (easiest for testing)
pys3local serve --path /srv/s3 --no-auth

# Option B: With authentication, default mode
pys3local serve --path /srv/s3 --access-key-id mykey --secret-access-key mysecret

# Option C: Advanced mode with custom buckets
pys3local serve --path /srv/s3 --no-auth --allow-bucket-creation
```

**Step 2: Configure rclone**

The server will print the configuration. Copy it to `~/.config/rclone/rclone.conf`:

```ini
# For --no-auth servers (default credentials work)
[pys3local]
type = s3
provider = Other
access_key_id = test
secret_access_key = test
endpoint = http://localhost:10001
region = us-east-1

# OR for authenticated servers (use your actual credentials)
[pys3local]
type = s3
provider = Other
access_key_id = mykey
secret_access_key = mysecret
endpoint = http://localhost:10001
region = us-east-1
```

**Step 3: Use rclone**

```bash
# List buckets (shows "default" in default mode)
rclone lsd pys3local:

# In default mode - use the "default" bucket
rclone copy /data pys3local:default/backup
rclone ls pys3local:default
rclone sync /data pys3local:default/backup

# In advanced mode - create and use custom buckets
rclone mkdir pys3local:mybucket
rclone copy /data pys3local:mybucket/backup
rclone ls pys3local:mybucket
```

**Note:** When starting the server, pys3local will print the exact rclone configuration
you need!

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
  cache    Manage metadata cache (local storage backend uses SQLite cache)
```

### Server Options

```bash
pys3local serve --help

Options:
  --path TEXT                   Data directory (default: /tmp/s3store)
  --listen TEXT                 Listen address (default: :10001)
  --access-key-id TEXT          AWS access key ID (default: test)
  --secret-access-key TEXT      AWS secret access key (default: test)
  --region TEXT                 AWS region (default: us-east-1)
  --no-auth                     Disable authentication
  --debug                       Enable debug logging
  --backend [local|drime]       Storage backend (default: local)
  --backend-config TEXT         Backend configuration name
  --root-folder TEXT            Root folder for Drime backend (e.g., 'backups/s3')
  --allow-bucket-creation       Allow custom bucket creation (default: only 'default'
                                bucket)
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
root_folder = "backups/s3"  # Optional: limit S3 scope to this folder
```

Use a saved configuration:

```bash
pys3local serve --backend-config mylocal
pys3local serve --backend-config mydrime
```

## ETag Implementation (Drime Backend)

### How ETags Work

When using the Drime backend, pys3local uses **Drime's native UUID** as the ETag (Entity
Tag). This UUID is provided by Drime in the `file_name` field (also called `disk_prefix`
in the API) and uniquely identifies each file.

**Example ETags:**

- `e77ad830-97f8-42a2-a13e-722fa10f02f5`
- `a88be940-08e9-53b3-b24f-833gb21g13g6`

### Why Not MD5?

S3-compatible APIs don't actually require MD5 for ETags. Real-world examples:

- **AWS multipart uploads**: `{hash}-{partcount}` (not pure MD5)
- **AWS SSE-KMS encryption**: Random string (not MD5)
- **Filen S3**: File UUID (not MD5)
- **pys3local Drime**: UUID from file_name (not MD5)

Our approach provides:

- ✅ **Works across multiple PCs** - No local cache synchronization needed
- ✅ **Detects all changes** - UUID changes when file content changes
- ✅ **Fast operations** - No downloads or MD5 calculations required
- ✅ **rclone compatible** - Tested with rclone, duplicati, restic
- ✅ **Uses Drime's native identifier** - Consistent with Drime's internal system

### Optional MD5 Cache (Legacy)

For backward compatibility, pys3local still maintains an optional MD5 cache. Files
uploaded before the UUID format will use cached MD5 if available.

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

1. **New files**: ETags are generated using Drime's UUID from the `file_name` field

   - No cache needed - works across all PCs immediately
   - Changes when file is replaced (new UUID assigned)
   - Fast - no downloads or calculations needed

2. **Legacy files** (uploaded with old MD5 cache system):

   - Uses cached MD5 if available
   - Otherwise uses UUID format

3. **On Upload**: MD5 is calculated and cached for compatibility with tools that expect
   pure MD5

### Multi-PC Setup

**No configuration needed!** The UUID ETag format works automatically across multiple
PCs. You don't need to migrate or synchronize any cache.

If you have files uploaded with the old MD5 cache system and want pure MD5 ETags, you
can optionally run:

```bash
# Only needed for old files uploaded before UUID format
pys3local cache migrate --backend-config mydrime
```

## Troubleshooting

### rclone: "Invalid HTTP request received"

**Problem:** Server shows `Invalid HTTP request received` error when using rclone.

**Solution:** pys3local uses the `h11` HTTP backend for better compatibility with S3
clients like rclone. This is configured automatically.

If you still get errors:

1. **Update your installation** to get the latest uvicorn with h11 support:

   ```bash
   pip install --upgrade 'uvicorn[standard]'
   ```

2. **Check your rclone config** (`~/.config/rclone/rclone.conf`):

   ```ini
   [pys3local]
   type = s3
   provider = Other
   access_key_id = test
   secret_access_key = test
   endpoint = http://localhost:8000
   region = us-east-1
   force_path_style = true
   ```

3. **Run with debug mode** to see detailed logs:

   ```bash
   pys3local serve --debug
   rclone -vv lsd pys3local:
   ```

4. **Try signature v2** if v4 auth has issues (add to rclone config):
   ```ini
   v2_auth = true
   ```

See `tests/test_rclone_compatibility.md` for more detailed troubleshooting.

### rclone: "secret_access_key not found"

**Problem:** rclone gives error: `failed to make Fs: secret_access_key not found`

**Solution:** You need to configure rclone with S3 credentials. The server displays the
correct configuration on startup.

1. Start pys3local (it will show the configuration):

   ```bash
   pys3local serve --backend drime --no-auth
   ```

2. Copy the displayed configuration to `~/.config/rclone/rclone.conf`:
   ```ini
   [pys3local]
   type = s3
   provider = Other
   access_key_id = test
   secret_access_key = test
   endpoint = http://localhost:10001
   region = us-east-1
   force_path_style = true
   disable_http2 = true
   ```

**Important:** Even with `--no-auth`, rclone still needs credentials configured (use
`test/test`).

### rclone: "http: server gave HTTP response to HTTPS client"

**Problem:** Error:
`https response error StatusCode: 0... http: server gave HTTP response to HTTPS client`

**Solution:** rclone is trying to use HTTPS, but pys3local runs on HTTP by default.

Fix your rclone configuration:

```ini
[pys3local]
type = s3
provider = Other
access_key_id = test
secret_access_key = test
endpoint = http://localhost:10001    # Must be http:// not https://
region = us-east-1
force_path_style = true
disable_http2 = true
no_check_bucket = true
```

### Server shows wrong credentials

**Problem:** Server started but you don't know the credentials to use with rclone.

**Solution:** pys3local always displays the credentials when starting:

```bash
$ pys3local serve --backend drime --no-auth
Authentication disabled
Note: Clients can use any credentials when auth is disabled

Starting S3 server at http://0.0.0.0:10001/

rclone configuration:
Add this to ~/.config/rclone/rclone.conf:

[pys3local]
type = s3
provider = Other
access_key_id = test           # <- Use these credentials
secret_access_key = test       # <-
endpoint = http://localhost:10001
region = us-east-1
```

**Quick test:**

```bash
# After configuring rclone, test the connection:
rclone lsd pys3local:

# If it works, you'll see your buckets listed
```

### Backend config not found

**Problem:** Error: `Backend config 'drime_test' not found`

**Solution:** Create the backend configuration first:

```bash
# Enter configuration mode
pys3local config

# Choose "Add backend" and follow prompts
# Or use environment variables instead:
export DRIME_API_KEY="your-api-key"
pys3local serve --backend drime --no-auth
```

### S3 Browser / Windows Clients: Access Denied

**Problem:** When using S3 Browser on Windows, you get `AccessDenied` errors even with
correct credentials.

**Solution:** S3 Browser and some Windows-based S3 clients use **AWS Signature Version
2** authentication by default. As of the latest version, pys3local supports both
Signature V2 and V4.

**Configuration for S3 Browser:**

1. Start the server:

   ```bash
   pys3local serve --path /srv/s3 --access-key-id test --secret-access-key test
   ```

2. In S3 Browser, configure:

   - **Account Type**: S3 Compatible Storage
   - **REST Endpoint**: `localhost:10001` (or your server address)
   - **Access Key ID**: `test` (must match server config)
   - **Secret Access Key**: `test` (must match server config)
   - **Signature Version**: V2 or V4 (both work now)
   - **Use SSL**: Unchecked (unless you have HTTPS configured)

3. If you still see authentication errors, enable debug logging to troubleshoot:

   ```bash
   pys3local serve --path /srv/s3 --access-key-id test --secret-access-key test --debug
   ```

   Look for log messages like:

   - `"Detected AWS Signature V2 authentication"`
   - `"Signature V2 verified successfully"`
   - `"Access key mismatch"` (if credentials don't match)

**Note:** Both AWS Signature V2 and V4 are fully supported. The server will
automatically detect which version the client is using and supports various
authorization header formats from different S3 clients.

### Bucket Mode Details

pys3local offers two bucket modes to accommodate different use cases:

#### Default Mode (Virtual "default" Bucket)

In default mode, pys3local exposes only a virtual "default" bucket. This mode:

- **Simplifies backup tool configuration** - No need to create buckets manually
- **Mirrors drime-s3 gateway behavior** - Consistent with other S3 gateways
- **Prevents bucket management complexity** - Focus on data, not bucket organization
- **Creates "default" bucket automatically** - Ready to use immediately

```bash
# Start in default mode (default behavior)
pys3local serve --path /srv/s3 --no-auth

# ListBuckets always returns: ["default"]
# PUT/GET operations must use "default" bucket
rclone copy /data pys3local:default/myfiles
```

**Restrictions in default mode:**

- `ListBuckets` returns only "default"
- Operations on non-default buckets return `NoSuchBucket` error
- `CreateBucket` for "default" succeeds silently (already exists)
- `CreateBucket` for other buckets succeeds but doesn't create real buckets
- `DeleteBucket` on "default" returns `BucketNotEmpty` error

#### Advanced Mode (Custom Buckets)

In advanced mode (with `--allow-bucket-creation`), you can create and manage multiple
custom buckets:

```bash
# Start in advanced mode
pys3local serve --path /srv/s3 --no-auth --allow-bucket-creation

# Create multiple buckets
rclone mkdir pys3local:documents
rclone mkdir pys3local:photos
rclone mkdir pys3local:backups

# Use them independently
rclone copy /docs pys3local:documents/
rclone copy /pics pys3local:photos/
```

**Benefits of advanced mode:**

- Full S3 bucket API compatibility
- Multiple isolated storage namespaces
- Traditional S3 bucket management

**When to use each mode:**

- **Default mode**: Backup tools (rclone, duplicati, restic), simple deployments
- **Advanced mode**: Applications requiring multiple buckets, testing S3 clients

### Complete rclone Configuration Reference

Here's a complete, working rclone configuration with all recommended options:

```ini
[pys3local]
type = s3
provider = Other

# Credentials (use test/test for --no-auth servers)
access_key_id = test
secret_access_key = test

# Connection settings
endpoint = http://localhost:10001
region = us-east-1

# Important: These options prevent common errors
force_path_style = true      # Use path-style URLs (required)
disable_http2 = true          # Disable HTTP/2 (prevents connection issues)
no_check_bucket = true        # Skip bucket existence checks
```

**For authenticated servers**, replace credentials:

```ini
access_key_id = mykey
secret_access_key = mysecret
```

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
- Smart ETag generation using native UUID (works across multiple PCs)
- Support for chunked uploads (AWS SDK v4)
- Concurrent folder creation with retry logic
- Workspace isolation
- Optional root folder for scope limiting

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

The Drime backend uses Drime's native UUID to generate S3-compatible ETags. This works
automatically across multiple PCs without any cache synchronization. See the
[ETag Implementation](#etag-implementation-drime-backend) section for details.

#### Root Folder (Scope Limiting)

You can limit the S3 scope to a specific folder within your Drime workspace using the
`--root-folder` option. This is useful when you want to dedicate a specific folder for
S3 backups rather than exposing the entire workspace.

**Use Cases:**

- Organize different backup systems in separate folders
- Share a workspace with other applications while isolating S3 data
- Create separate environments (dev/staging/prod) within one workspace

**Usage:**

```bash
# Limit S3 to a specific folder
pys3local serve --backend drime --root-folder "backups/s3" --no-auth

# With backend configuration
pys3local serve --backend-config mydrime --root-folder "my-backups"
```

**How it works:**

- When you specify `--root-folder "backups/s3"`:
  - `list_buckets()` lists folders in `backups/s3/` instead of workspace root
  - `create_bucket("mybucket")` creates `backups/s3/mybucket/`
  - All object paths are relative to `backups/s3/`
- The root folder is automatically created if it doesn't exist
- Works with nested paths: `--root-folder "backups/s3/prod"`

**Configuration:**

You can save the root_folder in your backend configuration:

```toml
[mydrime]
type = "drime"
api_key = "obscured_key_here"
workspace_id = 1465
root_folder = "backups/s3"
```

Then use it without the CLI flag:

```bash
pys3local serve --backend-config mydrime --no-auth
```

**With rclone:**

```bash
# Start server with root folder
pys3local serve --backend drime --root-folder "backups/s3" --no-auth

# rclone will only see buckets within backups/s3/
rclone lsd pys3local:              # Lists folders in backups/s3/
rclone mkdir pys3local:mybucket    # Creates backups/s3/mybucket/
```

**Cache migration with root folder:**

```bash
# Migrate only files within the root folder
pys3local cache migrate --backend-config mydrime --root-folder "backups/s3"
```

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
    no_auth=False,
    allow_bucket_creation=False  # Default mode (only "default" bucket)
)

# Or enable advanced mode with custom buckets
app = create_s3_app(
    provider=provider,
    access_key="mykey",
    secret_key="mysecret",
    region="us-east-1",
    no_auth=False,
    allow_bucket_creation=True  # Advanced mode (custom buckets allowed)
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
