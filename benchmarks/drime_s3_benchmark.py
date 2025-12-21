#!/usr/bin/env python3
"""Benchmark script for pys3local with Drime backend and boto3 S3 client.

This script:
1. Prompts for Drime credentials (workspace_id, api_key)
2. Starts pys3local server in the background with Drime backend
3. Creates a directory with random test files
4. Creates an S3 bucket
5. Uploads all files to the bucket
6. Downloads all files to a different directory
7. Compares both directories
8. Generates a performance report
9. Cleans up all test data
"""

from __future__ import annotations

import getpass
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
        create_s3_bucket,
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
        create_s3_bucket,
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

    # Drime settings
    workspace_id: int = 0
    drime_api_key: str = ""

    # Bucket settings
    bucket_name: str = "benchmark-bucket"

    # Debug settings
    verbose: bool = False

    # Performance settings
    parallel: bool = False
    parallel_workers: int = 5


def start_server(config: BenchmarkConfig, log_file: Path) -> subprocess.Popen:
    """Start pys3local server with Drime backend in the background.

    Args:
        config: Benchmark configuration
        log_file: Path to log file

    Returns:
        Process handle
    """
    print_step("Starting pys3local server with Drime backend...")

    listen_addr = f"{config.server_host}:{config.server_port}"

    cmd = [
        sys.executable,
        "-m",
        "pys3local.cli",
        "serve",
        "--listen",
        listen_addr,
        "--backend",
        "drime",
        "--no-auth",  # Disable auth for benchmark
        "--allow-bucket-creation",  # Allow custom buckets for benchmark
    ]

    # Add debug flag if verbose mode enabled
    if config.verbose:
        cmd.append("--debug")

    # Set environment variables for Drime
    env = os.environ.copy()
    env["DRIME_API_KEY"] = config.drime_api_key
    env["DRIME_WORKSPACE_ID"] = str(config.workspace_id)

    # Prepare subprocess arguments based on platform
    kwargs: dict = {"env": env}

    # In verbose mode, show server output directly; otherwise log to file
    if config.verbose:
        print("  (Server output will be shown below)")
        kwargs["stdout"] = None  # Inherit stdout
        kwargs["stderr"] = None  # Inherit stderr
    else:
        log = log_file.open("w")
        kwargs["stdout"] = log
        kwargs["stderr"] = subprocess.STDOUT

    if hasattr(os, "setsid"):
        # Unix/Linux/macOS
        kwargs["preexec_fn"] = os.setsid
    elif sys.platform == "win32":
        # Windows - create new process group
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    process = subprocess.Popen(cmd, **kwargs)

    # Wait for server to start
    print("  Waiting for server to initialize...")
    time.sleep(5)

    # Check if server is running
    if process.poll() is not None:
        if not config.verbose:
            with log_file.open() as f:
                print(f"Server failed to start. Log:\n{f.read()}")
        raise RuntimeError("Failed to start pys3local server")

    print(f"  ✓ Server started (PID: {process.pid})")
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


def prompt_drime_credentials() -> tuple[int, str]:
    """Prompt user for Drime credentials.

    Returns:
        Tuple of (workspace_id, api_key)
    """
    print_header("DRIME CREDENTIALS")

    print("Please enter your Drime credentials.")
    print("These will only be used for this benchmark and not stored.\n")

    workspace_id_str = input("Workspace ID (0 for personal workspace): ").strip()
    workspace_id = int(workspace_id_str) if workspace_id_str else 0

    api_key = getpass.getpass("Drime API key: ").strip()

    if not api_key:
        print("\n[ERROR] API key is required")
        sys.exit(1)

    print("\n✓ Credentials received")

    return workspace_id, api_key


def run_benchmark(config: BenchmarkConfig | None = None) -> BenchmarkResult:
    """Run the complete benchmark.

    Args:
        config: Benchmark configuration (uses default if None)

    Returns:
        Benchmark results
    """
    if config is None:
        config = BenchmarkConfig()

    print_header("PYS3LOCAL + DRIME + BOTO3 S3 BENCHMARK")

    # Create temporary directories
    temp_base = Path(tempfile.mkdtemp(prefix="pys3local_drime_benchmark_"))
    source_dir = temp_base / "source"
    download_dir = temp_base / "download"
    log_file = temp_base / "server.log"

    source_dir.mkdir()
    download_dir.mkdir()

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

        # Start server
        server_process = start_server(config, log_file)

        # Create S3 client
        s3_client = create_s3_client(config)

        # Create bucket
        success, bucket_create_time, error = create_s3_bucket(
            s3_client, config.bucket_name
        )
        if not success:
            error_msg = f"Bucket creation failed: {error}"
            raise RuntimeError(error_msg)

        # Upload files
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

        # Download files
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
        # Cleanup S3 bucket
        # Note: The pys3local server now automatically uses force=True for
        # Drime backend, which makes deletion fast (recursive folder delete)
        if s3_client and config.bucket_name:
            try:
                print_step(f"Cleaning up S3 bucket '{config.bucket_name}'...")
                # Delete bucket - server handles it efficiently for Drime
                s3_client.delete_bucket(Bucket=config.bucket_name)
                print(f"  ✓ Bucket '{config.bucket_name}' deleted")
            except Exception as e:
                print(f"  ⚠ Error cleaning up bucket: {e}")

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
            backend_type="Drime Cloud",
            config_summary={
                "Files": config.num_files,
                "File size range": f"{format_bytes(config.min_file_size)} - "
                f"{format_bytes(config.max_file_size)}",
                "Subdirectories": config.num_subdirs,
                "Server": f"{config.server_host}:{config.server_port}",
                "Backend": "Drime Cloud",
                "Workspace ID": config.workspace_id,
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
        description="Benchmark pys3local with Drime backend and boto3 S3 client",
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
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose debug logging (shows detailed API operations and timing)",
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

    # Prompt for Drime credentials
    workspace_id, api_key = prompt_drime_credentials()

    config = BenchmarkConfig(
        num_files=args.files,
        min_file_size=args.min_size,
        max_file_size=args.max_size,
        num_subdirs=args.subdirs,
        server_port=args.port,
        workspace_id=workspace_id,
        drime_api_key=api_key,
        verbose=args.verbose,
        parallel=args.parallel,
        parallel_workers=args.workers,
    )

    result = run_benchmark(config)

    return 0 if result.comparison_success and result.error is None else 1


if __name__ == "__main__":
    sys.exit(main())
