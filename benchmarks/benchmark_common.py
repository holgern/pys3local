"""Common utilities and functions for S3 benchmark scripts.

This module contains shared components used by both local and Drime
benchmark scripts for testing pys3local with boto3 S3 client.
"""

from __future__ import annotations

import hashlib
import os
import random
import signal
import string
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BenchmarkResult:
    """Results from a benchmark run."""

    total_files: int
    total_size: int
    bucket_create_time: float
    upload_time: float
    download_time: float
    comparison_success: bool
    backend_type: str
    config_summary: dict[str, str | int]
    error: str | None = None


def print_header(text: str) -> None:
    """Print a formatted header."""
    print(f"\n{'=' * 70}")
    print(f"  {text}")
    print(f"{'=' * 70}\n")


def print_step(text: str) -> None:
    """Print a step description."""
    print(f"→ {text}")


def format_bytes(size: int) -> str:
    """Format bytes to human-readable string."""
    size_float = float(size)
    for unit in ["B", "KB", "MB", "GB"]:
        if size_float < 1024:
            return f"{size_float:.2f} {unit}"
        size_float /= 1024
    return f"{size_float:.2f} TB"


def format_time(seconds: float) -> str:
    """Format time to human-readable string."""
    if seconds < 1:
        return f"{seconds * 1000:.2f} ms"
    elif seconds < 60:
        return f"{seconds:.2f} s"
    else:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"


def generate_random_content(size: int) -> bytes:
    """Generate random binary content of specified size."""
    # Use a mix of random bytes and compressible patterns
    if random.random() > 0.5:
        # Compressible pattern (repeated characters)
        char = random.choice(string.ascii_letters).encode()
        return char * size
    else:
        # Random bytes (less compressible)
        return os.urandom(size)


def create_test_files(
    base_dir: Path,
    num_files: int,
    min_file_size: int,
    max_file_size: int,
    num_subdirs: int,
) -> tuple[int, int]:
    """Create random test files in the specified directory.

    Args:
        base_dir: Base directory to create files in
        num_files: Number of files to create
        min_file_size: Minimum file size in bytes
        max_file_size: Maximum file size in bytes
        num_subdirs: Number of subdirectories to create

    Returns:
        Tuple of (file_count, total_size)
    """
    print_step(f"Creating {num_files} test files...")

    # Create subdirectories
    subdirs = [base_dir]
    for i in range(num_subdirs):
        subdir = base_dir / f"subdir_{i}"
        subdir.mkdir(exist_ok=True)
        subdirs.append(subdir)

    total_size = 0
    file_count = 0

    for i in range(num_files):
        # Choose random directory
        target_dir = random.choice(subdirs)

        # Generate random file
        size = random.randint(min_file_size, max_file_size)
        content = generate_random_content(size)

        # Random filename
        name = f"file_{i}_{random.randint(1000, 9999)}.dat"
        file_path = target_dir / name

        file_path.write_bytes(content)
        total_size += size
        file_count += 1

        if (i + 1) % 20 == 0:
            print(f"  Created {i + 1}/{num_files} files...")

    print(f"  ✓ Created {file_count} files ({format_bytes(total_size)})")
    return file_count, total_size


def stop_server(process: subprocess.Popen) -> None:
    """Stop the server process.

    Args:
        process: Server process handle
    """
    print_step("Stopping server...")

    try:
        # Try graceful shutdown first
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        else:
            process.terminate()

        # Wait up to 5 seconds
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Force kill if needed
            if hasattr(os, "killpg"):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            else:
                process.kill()
            process.wait()

        print("  ✓ Server stopped")
    except Exception as e:
        print(f"  ⚠ Error stopping server: {e}")


def create_s3_bucket(s3_client, bucket_name: str) -> tuple[bool, float, str]:
    """Create an S3 bucket.

    Args:
        s3_client: Boto3 S3 client
        bucket_name: Name of bucket to create

    Returns:
        Tuple of (success, elapsed_time, error_message)
    """
    print_step(f"Creating S3 bucket '{bucket_name}'...")

    start_time = time.time()

    try:
        s3_client.create_bucket(Bucket=bucket_name)
        elapsed = time.time() - start_time
        print(f"  ✓ Bucket created ({format_time(elapsed)})")
        return True, elapsed, ""
    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = str(e)
        print(f"  ✗ Bucket creation failed: {error_msg}")
        return False, elapsed, error_msg


def upload_files_to_s3(
    s3_client, bucket_name: str, source_dir: Path
) -> tuple[bool, float, str]:
    """Upload all files from a directory to S3.

    Args:
        s3_client: Boto3 S3 client
        bucket_name: Name of bucket to upload to
        source_dir: Directory containing files to upload

    Returns:
        Tuple of (success, elapsed_time, error_message)
    """
    print_step("Uploading files to S3...")

    start_time = time.time()

    try:
        # Get all files
        files = list(source_dir.rglob("*"))
        files = [f for f in files if f.is_file()]

        uploaded = 0
        for file_path in files:
            # Use relative path as S3 key
            key = str(file_path.relative_to(source_dir))
            # Normalize path separators for S3
            key = key.replace("\\", "/")

            with file_path.open("rb") as f:
                s3_client.put_object(Bucket=bucket_name, Key=key, Body=f.read())

            uploaded += 1
            if uploaded % 20 == 0:
                print(f"  Uploaded {uploaded}/{len(files)} files...")

        elapsed = time.time() - start_time
        print(f"  ✓ Uploaded {uploaded} files ({format_time(elapsed)})")
        return True, elapsed, ""

    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = str(e)
        print(f"  ✗ Upload failed: {error_msg}")
        return False, elapsed, error_msg


def upload_files_to_s3_parallel(
    s3_client, bucket_name: str, source_dir: Path, workers: int = 5
) -> tuple[bool, float, str]:
    """Upload all files from a directory to S3 in parallel.

    Args:
        s3_client: Boto3 S3 client
        bucket_name: Name of bucket to upload to
        source_dir: Directory containing files to upload
        workers: Number of parallel workers (default: 5)

    Returns:
        Tuple of (success, elapsed_time, error_message)
    """
    print_step(f"Uploading files to S3 (parallel with {workers} workers)...")

    start_time = time.time()

    try:
        # Get all files
        files = list(source_dir.rglob("*"))
        files = [f for f in files if f.is_file()]

        uploaded = 0
        upload_lock = threading.Lock()

        def upload_file(file_path: Path) -> bool:
            """Upload a single file."""
            nonlocal uploaded
            try:
                # Use relative path as S3 key
                key = str(file_path.relative_to(source_dir))
                # Normalize path separators for S3
                key = key.replace("\\", "/")

                with file_path.open("rb") as f:
                    s3_client.put_object(Bucket=bucket_name, Key=key, Body=f.read())

                with upload_lock:
                    uploaded += 1
                    if uploaded % 20 == 0:
                        print(f"  Uploaded {uploaded}/{len(files)} files...")
                return True
            except Exception as e:
                print(f"  ✗ Failed to upload {file_path.name}: {e}")
                return False

        # Upload files in parallel
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(upload_file, f) for f in files]
            results = [f.result() for f in as_completed(futures)]

        if not all(results):
            raise RuntimeError("Some uploads failed")

        elapsed = time.time() - start_time
        print(f"  ✓ Uploaded {uploaded} files ({format_time(elapsed)})")
        return True, elapsed, ""

    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = str(e)
        print(f"  ✗ Upload failed: {error_msg}")
        return False, elapsed, error_msg


def download_files_from_s3(
    s3_client, bucket_name: str, dest_dir: Path
) -> tuple[bool, float, str]:
    """Download all files from S3 bucket to a directory.

    Args:
        s3_client: Boto3 S3 client
        bucket_name: Name of bucket to download from
        dest_dir: Directory to download files to

    Returns:
        Tuple of (success, elapsed_time, error_message)
    """
    print_step("Downloading files from S3...")

    start_time = time.time()

    try:
        # List all objects
        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket_name)

        downloaded = 0
        for page in pages:
            if "Contents" not in page:
                continue

            for obj in page["Contents"]:
                key = obj["Key"]

                # Create local file path
                file_path = dest_dir / key
                file_path.parent.mkdir(parents=True, exist_ok=True)

                # Download object
                response = s3_client.get_object(Bucket=bucket_name, Key=key)
                file_path.write_bytes(response["Body"].read())

                downloaded += 1
                if downloaded % 20 == 0:
                    print(f"  Downloaded {downloaded} files...")

        elapsed = time.time() - start_time
        print(f"  ✓ Downloaded {downloaded} files ({format_time(elapsed)})")
        return True, elapsed, ""

    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = str(e)
        print(f"  ✗ Download failed: {error_msg}")
        return False, elapsed, error_msg


def download_files_from_s3_parallel(
    s3_client, bucket_name: str, dest_dir: Path, workers: int = 5
) -> tuple[bool, float, str]:
    """Download all files from S3 bucket to a directory in parallel.

    Args:
        s3_client: Boto3 S3 client
        bucket_name: Name of bucket to download from
        dest_dir: Directory to download files to
        workers: Number of parallel workers (default: 5)

    Returns:
        Tuple of (success, elapsed_time, error_message)
    """
    print_step(f"Downloading files from S3 (parallel with {workers} workers)...")

    start_time = time.time()

    try:
        # List all objects first
        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket_name)

        keys = []
        for page in pages:
            if "Contents" not in page:
                continue
            keys.extend([obj["Key"] for obj in page["Contents"]])

        downloaded = 0
        download_lock = threading.Lock()

        def download_file(key: str) -> bool:
            """Download a single file."""
            nonlocal downloaded
            try:
                # Create local file path
                file_path = dest_dir / key
                file_path.parent.mkdir(parents=True, exist_ok=True)

                # Download object
                response = s3_client.get_object(Bucket=bucket_name, Key=key)
                file_path.write_bytes(response["Body"].read())

                with download_lock:
                    downloaded += 1
                    if downloaded % 20 == 0:
                        print(f"  Downloaded {downloaded}/{len(keys)} files...")
                return True
            except Exception as e:
                print(f"  ✗ Failed to download {key}: {e}")
                return False

        # Download files in parallel
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(download_file, key) for key in keys]
            results = [f.result() for f in as_completed(futures)]

        if not all(results):
            raise RuntimeError("Some downloads failed")

        elapsed = time.time() - start_time
        print(f"  ✓ Downloaded {downloaded} files ({format_time(elapsed)})")
        return True, elapsed, ""

    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = str(e)
        print(f"  ✗ Download failed: {error_msg}")
        return False, elapsed, error_msg


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def compare_directories(dir1: Path, dir2: Path) -> tuple[bool, list[str]]:
    """Compare two directories recursively.

    Args:
        dir1: First directory
        dir2: Second directory

    Returns:
        Tuple of (match, differences)
    """
    print_step("Comparing directories...")

    differences = []

    # Get all files in both directories
    files1 = {p.relative_to(dir1): p for p in dir1.rglob("*") if p.is_file()}
    files2 = {p.relative_to(dir2): p for p in dir2.rglob("*") if p.is_file()}

    # Check for missing files
    only_in_1 = set(files1.keys()) - set(files2.keys())
    only_in_2 = set(files2.keys()) - set(files1.keys())

    if only_in_1:
        differences.append(f"Files only in original: {only_in_1}")
    if only_in_2:
        differences.append(f"Files only in downloaded: {only_in_2}")

    # Compare common files
    common_files = set(files1.keys()) & set(files2.keys())
    for rel_path in common_files:
        file1 = files1[rel_path]
        file2 = files2[rel_path]

        # Compare sizes
        if file1.stat().st_size != file2.stat().st_size:
            differences.append(
                f"Size mismatch for {rel_path}: "
                f"{file1.stat().st_size} vs {file2.stat().st_size}"
            )
            continue

        # Compare content (hash)
        hash1 = compute_file_hash(file1)
        hash2 = compute_file_hash(file2)

        if hash1 != hash2:
            differences.append(f"Content mismatch for {rel_path}")

    if not differences:
        print(f"  ✓ Directories match perfectly ({len(common_files)} files)")
        return True, []
    else:
        print(f"  ✗ Found {len(differences)} differences")
        for diff in differences[:5]:  # Show first 5
            print(f"    - {diff}")
        if len(differences) > 5:
            print(f"    ... and {len(differences) - 5} more")
        return False, differences


def cleanup_s3_bucket(s3_client, bucket_name: str) -> None:
    """Delete all objects in a bucket and the bucket itself.

    Args:
        s3_client: Boto3 S3 client
        bucket_name: Name of bucket to delete
    """
    print_step(f"Cleaning up S3 bucket '{bucket_name}'...")

    try:
        # Delete all objects
        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket_name)

        for page in pages:
            if "Contents" not in page:
                continue

            objects = [{"Key": obj["Key"]} for obj in page["Contents"]]
            if objects:
                s3_client.delete_objects(
                    Bucket=bucket_name, Delete={"Objects": objects}
                )

        # Delete bucket
        s3_client.delete_bucket(Bucket=bucket_name)
        print(f"  ✓ Bucket '{bucket_name}' deleted")

    except Exception as e:
        print(f"  ⚠ Error cleaning up bucket: {e}")


def cleanup_local_dirs(paths: list[Path]) -> None:
    """Clean up local directories.

    Args:
        paths: List of paths to remove
    """
    print_step("Cleaning up local directories...")

    import shutil

    for path in paths:
        try:
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                print(f"  ✓ Removed {path}")
        except Exception as e:
            print(f"  ⚠ Failed to remove {path}: {e}")


def print_report(result: BenchmarkResult) -> None:
    """Print benchmark report.

    Args:
        result: Benchmark results
    """
    print_header("BENCHMARK REPORT")

    print("Configuration:")
    for key, value in result.config_summary.items():
        print(f"  {key}: {value}")

    print("\nTest Data:")
    print(f"  Total files:     {result.total_files}")
    print(f"  Total size:      {format_bytes(result.total_size)}")

    print("\nPerformance:")
    print(f"  Bucket create:   {format_time(result.bucket_create_time)}")
    print(f"  Upload time:     {format_time(result.upload_time)}")
    print(f"  Download time:   {format_time(result.download_time)}")
    total_time = result.bucket_create_time + result.upload_time + result.download_time
    print(f"  Total time:      {format_time(total_time)}")

    if result.upload_time > 0:
        throughput = result.total_size / result.upload_time
        print(f"  Upload rate:     {format_bytes(int(throughput))}/s")

    if result.download_time > 0:
        throughput = result.total_size / result.download_time
        print(f"  Download rate:   {format_bytes(int(throughput))}/s")

    print("\nVerification:")
    if result.comparison_success:
        print("  ✓ Upload and download successful - all files match!")
    else:
        print("  ✗ Verification failed - files don't match")

    if result.error:
        print(f"\nError: {result.error}")

    print(f"\n{'=' * 70}\n")
