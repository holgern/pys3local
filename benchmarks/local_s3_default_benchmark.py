#!/usr/bin/env python3
"""Benchmark script for pys3local with local backend in DEFAULT MODE.

This script demonstrates the default bucket mode where only the 'default'
bucket exists as a virtual bucket, and all files are stored at the root
level without bucket directories.

This script:
1. Starts pys3local server in DEFAULT MODE (no --allow-bucket-creation flag)
2. Creates a directory with random test files
3. Uses the virtual 'default' bucket (auto-created)
4. Uploads all files to the default bucket
5. Downloads all files to a different directory
6. Compares both directories
7. Generates a performance report
8. Cleans up all test data
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import boto3
except ImportError:
    print("Error: boto3 is required for benchmarks")
    print("Install it with: pip install boto3")
    sys.exit(1)

try:
    # Try relative import first (when run as module)
    from .benchmark_common import (
        BenchmarkResult,
        cleanup_local_dirs,
        compare_directories,
        create_test_files,
        download_files_from_s3,
        download_files_from_s3_parallel,
        format_bytes,
        print_header,
        print_report,
        print_step,
        stop_server,
        upload_files_to_s3,
        upload_files_to_s3_parallel,
    )
except ImportError:
    # Fall back to direct import (when run as script)
    from benchmark_common import (  # type: ignore[import-not-found]
        BenchmarkResult,
        cleanup_local_dirs,
        compare_directories,
        create_test_files,
        download_files_from_s3,
        download_files_from_s3_parallel,
        format_bytes,
        print_header,
        print_report,
        print_step,
        stop_server,
        upload_files_to_s3,
        upload_files_to_s3_parallel,
    )


@dataclass
class BenchmarkConfig:
    """Configuration for benchmark run."""

    # File generation settings
    num_files: int = 100
    min_file_size: int = 1024  # 1 KB
    max_file_size: int = 1024 * 1024  # 1 MB
    num_subdirs: int = 5

    # Server settings
    server_host: str = "127.0.0.1"
    server_port: int = 10001
    access_key: str = "test"
    secret_key: str = "test"

    # Bucket settings (fixed to "default" for this benchmark)
    bucket_name: str = "default"

    # Parallel settings
    parallel: bool = False
    parallel_workers: int = 5


def start_server(
    config: BenchmarkConfig, data_dir: Path, log_file: Path
) -> subprocess.Popen:
    """Start pys3local server in DEFAULT MODE (no custom buckets).

    Args:
        config: Benchmark configuration
        data_dir: Directory for server data
        log_file: Path to log file

    Returns:
        Process handle
    """
    print_step("Starting pys3local server in DEFAULT MODE...")

    listen_addr = f"{config.server_host}:{config.server_port}"

    cmd = [
        sys.executable,
        "-m",
        "pys3local.cli",
        "serve",
        "--listen",
        listen_addr,
        "--backend",
        "local",
        "--path",
        str(data_dir),
        "--no-auth",  # Disable auth for benchmark
        # NOTE: No --allow-bucket-creation flag = DEFAULT MODE
    ]

    # Prepare subprocess arguments based on platform
    log = log_file.open("w")
    kwargs = {
        "stdout": log,
        "stderr": subprocess.STDOUT,
    }

    if hasattr(os, "setsid"):
        # Unix/Linux/macOS
        kwargs["preexec_fn"] = os.setsid
    elif sys.platform == "win32":
        # Windows - create new process group
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    process = subprocess.Popen(cmd, **kwargs)

    # Wait for server to start
    time.sleep(2)

    # Check if server is running
    if process.poll() is not None:
        log.close()
        with log_file.open() as f:
            print(f"Server failed to start. Log:\n{f.read()}")
        raise RuntimeError("Failed to start pys3local server")

    print(f"  ✓ Server started in DEFAULT MODE (PID: {process.pid})")
    print("  ✓ Using virtual 'default' bucket (no bucket directories)")
    return process


def create_s3_client(config: BenchmarkConfig):
    """Create a boto3 S3 client configured for local server.

    Args:
        config: Benchmark configuration

    Returns:
        Boto3 S3 client
    """
    endpoint_url = f"http://{config.server_host}:{config.server_port}"

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=config.access_key,
        aws_secret_access_key=config.secret_key,
        region_name="us-east-1",
    )


def run_benchmark(config: BenchmarkConfig | None = None) -> BenchmarkResult:
    """Run the complete benchmark.

    Args:
        config: Benchmark configuration (uses default if None)

    Returns:
        Benchmark results
    """
    if config is None:
        config = BenchmarkConfig()

    print_header("PYS3LOCAL DEFAULT MODE BENCHMARK (LOCAL BACKEND)")

    # Create temporary directories
    temp_base = Path(tempfile.mkdtemp(prefix="pys3local_default_benchmark_"))
    source_dir = temp_base / "source"
    download_dir = temp_base / "download"
    server_data_dir = temp_base / "server_data"
    log_file = temp_base / "server.log"

    source_dir.mkdir()
    download_dir.mkdir()
    server_data_dir.mkdir()

    server_process = None
    s3_client = None
    bucket_create_time = 0.0
    upload_time = 0.0
    download_time = 0.0
    comparison_success = False
    error_msg = None
    file_count = 0
    total_size = 0

    try:
        # Create test files
        file_count, total_size = create_test_files(
            source_dir,
            config.num_files,
            config.min_file_size,
            config.max_file_size,
            config.num_subdirs,
        )

        # Start server in DEFAULT MODE
        server_process = start_server(config, server_data_dir, log_file)

        # Create S3 client
        s3_client = create_s3_client(config)

        # NOTE: We do NOT create a bucket - 'default' bucket is auto-created
        print_step("Using virtual 'default' bucket (auto-created)...")
        print("  ✓ 'default' bucket is virtual (no directory created)")
        bucket_create_time = 0.0  # Instant, as it's virtual

        # Upload files to 'default' bucket
        if config.parallel:
            success, upload_time, error = upload_files_to_s3_parallel(
                s3_client, config.bucket_name, source_dir, config.parallel_workers
            )
        else:
            success, upload_time, error = upload_files_to_s3(
                s3_client, config.bucket_name, source_dir
            )
        if not success:
            error_msg = f"Upload failed: {error}"
            raise RuntimeError(error_msg)

        # Download files from 'default' bucket
        if config.parallel:
            success, download_time, error = download_files_from_s3_parallel(
                s3_client, config.bucket_name, download_dir, config.parallel_workers
            )
        else:
            success, download_time, error = download_files_from_s3(
                s3_client, config.bucket_name, download_dir
            )
        if not success:
            error_msg = f"Download failed: {error}"
            raise RuntimeError(error_msg)

        # Compare directories
        comparison_success, differences = compare_directories(source_dir, download_dir)

    except Exception as e:
        error_msg = str(e)
        print(f"\n✗ Benchmark failed: {e}")

    finally:
        # NOTE: In default mode, we don't cleanup the bucket as it's virtual
        # The bucket directory will be cleaned up with server_data_dir

        # Stop server
        if server_process:
            stop_server(server_process)

        # Create result
        result = BenchmarkResult(
            total_files=file_count,
            total_size=total_size,
            bucket_create_time=bucket_create_time,
            upload_time=upload_time,
            download_time=download_time,
            comparison_success=comparison_success,
            backend_type="Local (Default Mode)",
            config_summary={
                "Files": config.num_files,
                "File size range": f"{format_bytes(config.min_file_size)} - "
                f"{format_bytes(config.max_file_size)}",
                "Subdirectories": config.num_subdirs,
                "Server": f"{config.server_host}:{config.server_port}",
                "Backend": "Local",
                "Bucket Mode": "DEFAULT (virtual 'default' bucket)",
                "Parallel mode": "Enabled" if config.parallel else "Disabled",
                "Workers": config.parallel_workers if config.parallel else "N/A",
            },
            error=error_msg,
        )

        # Print report
        print_report(result)

        # Cleanup local directories
        cleanup_local_dirs([temp_base])

    return result


def main() -> int:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Benchmark pys3local in DEFAULT MODE (virtual bucket)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--files",
        type=int,
        default=100,
        help="Number of files to create",
    )
    parser.add_argument(
        "--min-size",
        type=int,
        default=1024,
        help="Minimum file size in bytes",
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=1024 * 1024,
        help="Maximum file size in bytes",
    )
    parser.add_argument(
        "--subdirs",
        type=int,
        default=5,
        help="Number of subdirectories",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=10001,
        help="Server port",
    )
    parser.add_argument(
        "--parallel",
        "-p",
        action="store_true",
        help="Enable parallel uploads/downloads",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Number of parallel workers",
    )

    args = parser.parse_args()

    config = BenchmarkConfig(
        num_files=args.files,
        min_file_size=args.min_size,
        max_file_size=args.max_size,
        num_subdirs=args.subdirs,
        server_port=args.port,
        parallel=args.parallel,
        parallel_workers=args.workers,
    )

    result = run_benchmark(config)

    return 0 if result.comparison_success and result.error is None else 1


if __name__ == "__main__":
    sys.exit(main())
