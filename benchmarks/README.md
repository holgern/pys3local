# Pys3local Benchmarks

This directory contains benchmark scripts for testing pys3local performance with boto3
S3 client.

## Available Benchmarks

### local_s3_benchmark.py

A comprehensive benchmark that tests pys3local with a local backend and boto3 S3 client.

**What it does:**

1. Starts pys3local server in the background with local backend
2. Creates a directory with random test files
3. Creates an S3 bucket
4. Uploads all files to the bucket
5. Downloads all files to a different directory
6. Compares both directories to verify integrity
7. Generates a performance report
8. Cleans up all test data

**Requirements:**

- boto3 must be installed (`pip install boto3`)
- pys3local must be installed

**Usage:**

```bash
# Run with default settings (100 files)
python -m benchmarks.local_s3_benchmark

# Run with custom settings
python -m benchmarks.local_s3_benchmark \
  --files 50 \
  --min-size 1024 \
  --max-size 1048576 \
  --subdirs 5 \
  --port 10001

# Show help
python -m benchmarks.local_s3_benchmark --help
```

**Options:**

- `--files N`: Number of files to create (default: 100)
- `--min-size BYTES`: Minimum file size in bytes (default: 1024)
- `--max-size BYTES`: Maximum file size in bytes (default: 1048576)
- `--subdirs N`: Number of subdirectories (default: 5)
- `--port PORT`: Server port (default: 10001)

**Example Output:**

```
======================================================================
  BENCHMARK REPORT
======================================================================

Configuration:
  Files:           50
  File size range: 1.00 KB - 1.00 MB
  Subdirectories:  3
  Server:          127.0.0.1:10001
  Backend:         Local

Test Data:
  Total files:     50
  Total size:      26.73 MB

Performance:
  Bucket create:   125.34 ms
  Upload time:     1.06 s
  Download time:   774.18 ms
  Total time:      1.96 s
  Upload rate:     25.16 MB/s
  Download rate:   34.52 MB/s

Verification:
  ✓ Upload and download successful - all files match!

======================================================================
```

### drime_s3_benchmark.py

Benchmark for testing pys3local with Drime cloud backend (currently a stub).

**Status:** This benchmark is currently a placeholder. The Drime backend support is not
yet fully implemented in pys3local.

**What it will do:**

1. Prompt for Drime credentials (workspace_id, api_key)
2. Start pys3local server with Drime backend
3. Run the same tests as the local benchmark
4. Clean up Drime cloud storage

**Requirements:**

- boto3 must be installed (`pip install boto3`)
- pydrime must be installed (`pip install pydrime`)
- Valid Drime API credentials
- pys3local must be installed with Drime support

**Usage:**

```bash
# Run with default settings
python -m benchmarks.drime_s3_benchmark

# Run with custom settings
python -m benchmarks.drime_s3_benchmark \
  --files 50 \
  --min-size 1024 \
  --max-size 1048576
```

### sync_workflow_test.py

**CRITICAL TEST:** Validates rclone-like sync workflow with ETag-based change detection.

This test simulates the complete workflow that rclone uses to sync files:

1. Initial sync - upload files to S3
2. Modify files locally (simulate user editing files)
3. Re-sync - rclone checks ETags to detect changes
4. Verify files are re-uploaded with new content
5. Confirm ETags changed (if not, rclone would skip upload = DATA LOSS!)

**Why This Test Matters:**

rclone relies on ETags to determine if a file needs re-uploading:

- If `local_etag == remote_etag` → Skip (already synced)
- If `local_etag != remote_etag` → Upload (changed)

If ETags don't change when file content changes, rclone will not detect the changes and
will skip uploading the modified files. This causes **data loss** - your remote storage
will have old file versions.

**What It Tests:**

1. **Initial Sync**: Upload files, get initial ETags
2. **Local Modification**: Change file content (different hashes)
3. **Change Detection**: Verify ETags are still unchanged in S3 (before re-upload)
4. **Re-Upload**: Upload modified files
5. **ETag Change Verification**: Confirm ETags changed (CRITICAL!)
6. **Content Verification**: Verify correct content in S3

**Requirements:**

- boto3 must be installed (`pip install boto3`)
- pys3local must be installed
- For Drime backend: Valid Drime API credentials

**Usage:**

```bash
# Test local backend only (fast, no credentials needed)
python -m benchmarks.sync_workflow_test --backend local --files 5

# Test Drime backend only (requires credentials)
python -m benchmarks.sync_workflow_test --backend drime --files 5

# Test both backends
python -m benchmarks.sync_workflow_test --backend both --files 10
```

**Options:**

- `--backend {local,drime,both}`: Backend to test (default: local)
- `--files N`: Number of test files (default: 5)

**Example Output:**

```
======================================================================
  PHASE 1: Initial Sync
======================================================================

→ Creating 5 test files in /tmp/pys3local_sync_test_xxx/local_files...
  • Created file00.txt (42 bytes, hash: a1b2c3d4e5f6...)
  • Created file01.txt (84 bytes, hash: f6e5d4c3b2a1...)
  ...

→ Syncing 5 files to S3 bucket 'sync-test-1234567890'...
  • Uploaded file00.txt → ETag: abc123def456-42
  • Uploaded file01.txt → ETag: 456def789abc-84
  ...

======================================================================
  PHASE 2: Modify Local Files
======================================================================

→ Modifying 5 test files...
  • Modified file00.txt (64 bytes, hash: 9876543210fe...)
  ...

======================================================================
  PHASE 3: Re-Sync (Detect Changes)
======================================================================

→ Checking if rclone would detect changes (ETag comparison)...
  • file00.txt: remote ETag = abc123def456-42
  ...

→ Uploading modified files...
  • Uploaded file00.txt → ETag: fedcba987654-64
  ...

======================================================================
  PHASE 4: Verify ETag Change Detection
======================================================================

  ✓ file00.txt ETag changed: abc123def456-42 → fedcba987654-64
  ✓ file01.txt ETag changed: 456def789abc-84 → 123abc456def-128
  ...
  ✓ All ETags changed correctly

======================================================================
  PHASE 5: Verify Modified Content
======================================================================

→ Verifying S3 content matches expected hashes...
  ✓ file00.txt content verified (hash: 9876543210fe...)
  ...
  ✓ All modified files have correct content in S3

======================================================================
  TEST RESULTS
======================================================================

✓ PASS: Local Backend
  Complete sync workflow test PASSED

======================================================================
  FINAL RESULT
======================================================================

✓ ALL TESTS PASSED

The sync workflow works correctly!
Files are properly detected as changed via ETags.
rclone sync would work correctly with this backend.
```

**Failure Scenarios:**

If ETags don't change when files change, you'll see:

```
======================================================================
  PHASE 4: Verify ETag Change Detection
======================================================================

  ✗ CRITICAL: file00.txt ETag unchanged! (abc123def456-42)
    This means rclone would SKIP this file (DATA LOSS!)

✗ FAIL: Local Backend
  CRITICAL: Some ETags didn't change! rclone would not detect changes.
```

This indicates a **critical bug** in the ETag implementation that would cause data loss
with rclone sync.

### drime_etag.py

Comprehensive ETag format validation for Drime backend (uses UUID format).

Tests the UUID ETag format:

1. Verifies format is correct (UUID from file_name field)
2. Tests change detection (UUID changes when file changes)
3. Tests consistency (same file = same ETag)
4. Simulates rclone sync scenario
5. Confirms boto3 compatibility
6. Validates listing performance (no downloads)

**Usage:**

```bash
python -m benchmarks.drime_etag
# You'll be prompted for Drime credentials
```

## Benchmark Methodology

### Test Data Generation

The benchmarks create realistic test data:

- **File sizes**: Random sizes between min-size and max-size
- **Content**: Mix of compressible (repeated characters) and random bytes
- **Structure**: Files distributed across multiple subdirectories
- **Naming**: Random filenames to avoid caching effects

### Performance Metrics

The benchmarks measure:

- **Bucket creation time**: Time to create S3 bucket
- **Upload time**: Time to upload all files using S3 PutObject
- **Download time**: Time to download all files using S3 GetObject
- **Throughput**: MB/s for upload and download operations
- **Integrity**: SHA256 hash comparison of all files

### S3 API Testing

The benchmarks use boto3 S3 client to test:

- `CreateBucket`: Bucket creation
- `PutObject`: Individual file uploads
- `ListObjectsV2`: Listing objects with pagination
- `GetObject`: Individual file downloads
- `DeleteObjects`: Bulk object deletion
- `DeleteBucket`: Bucket deletion

This ensures full S3 API compatibility.

## Interpreting Results

### Upload/Download Rates

- **> 50 MB/s**: Excellent for local backend
- **20-50 MB/s**: Good performance
- **10-20 MB/s**: Acceptable for network storage
- **< 10 MB/s**: May indicate bottlenecks

### Factors Affecting Performance

- **File size**: Larger files = better throughput (less overhead)
- **File count**: Many small files = more HTTP requests
- **Storage backend**: Local filesystem vs. network storage
- **Disk speed**: SSD vs. HDD makes a big difference
- **Network**: For remote backends like Drime

### Comparison with Native Operations

For reference, typical performance benchmarks:

- **Local filesystem copy**: 100-500 MB/s (SSD)
- **AWS S3**: 25-90 MB/s per connection
- **Local S3 server**: 50-200 MB/s (depends on implementation)

## Adding New Benchmarks

To add a new benchmark:

1. Create a new Python file in this directory
2. Follow the naming convention: `{backend}_s3_benchmark.py`
3. Import common utilities from `benchmark_common.py`
4. Include command-line arguments for configurability
5. Use boto3 S3 client for API testing
6. Provide clear output and reporting
7. Clean up all test data after completion
8. Add documentation to this README

## Troubleshooting

### Server Fails to Start

Check the server log file in the temporary directory:

- Look for port conflicts (default: 10001)
- Verify pys3local is installed correctly
- Check backend configuration

### Import Errors

Make sure dependencies are installed:

```bash
pip install boto3  # For S3 client
pip install pydrime  # For Drime backend (optional)
```

### Permission Errors

- Ensure write permissions for temporary directories
- On Windows, antivirus may block file operations
- Use administrator privileges if needed

### Slow Performance

- Close other applications consuming disk I/O
- Use SSD instead of HDD for better results
- Reduce file count or size for faster tests
- Check system resources (CPU, memory, disk)
