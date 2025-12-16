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
