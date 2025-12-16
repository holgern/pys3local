#!/usr/bin/env python3
"""Test script to verify rclone-like sync workflow with pys3local.

This script simulates the complete rclone sync workflow:
1. Create local files
2. Initial sync (upload to S3)
3. Modify local files
4. Re-sync (should detect changes via ETag)
5. Verify files were re-uploaded with new content

Tests both local and Drime backends to ensure ETag-based change detection works.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import boto3
except ImportError:
    print("Error: boto3 is required for this test")
    print("Install it with: pip install boto3")
    sys.exit(1)


def print_header(text: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70 + "\n")


def print_step(text: str) -> None:
    """Print a formatted step."""
    print(f"\n→ {text}")


def print_substep(text: str) -> None:
    """Print a formatted substep."""
    print(f"  • {text}")


def file_hash(filepath: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def start_server(
    backend: str,
    base_dir: Path | None = None,
    workspace_id: int | None = None,
    api_key: str | None = None,
    port: int = 10001,
) -> subprocess.Popen:
    """Start pys3local server.

    Args:
        backend: Backend type ("local" or "drime")
        base_dir: Base directory for local backend
        workspace_id: Drime workspace ID
        api_key: Drime API key
        port: Server port

    Returns:
        Process handle
    """
    print_step(f"Starting pys3local server ({backend} backend)...")

    env = os.environ.copy()

    cmd = [
        sys.executable,
        "-m",
        "pys3local.cli",
        "serve",
        "--listen",
        f"127.0.0.1:{port}",
        "--backend",
        backend,
        "--no-auth",
    ]

    if backend == "local":
        if base_dir is None:
            raise ValueError("base_dir required for local backend")
        cmd.extend(["--path", str(base_dir)])
    elif backend == "drime":
        if workspace_id is None or api_key is None:
            raise ValueError("workspace_id and api_key required for drime backend")
        env["DRIME_API_KEY"] = api_key
        env["DRIME_WORKSPACE_ID"] = str(workspace_id)

    log_file = Path(tempfile.gettempdir()) / f"pys3local_sync_test_{backend}.log"
    log = log_file.open("w")

    kwargs = {
        "env": env,
        "stdout": log,
        "stderr": subprocess.STDOUT,
    }

    if hasattr(os, "setsid"):
        kwargs["preexec_fn"] = os.setsid
    elif sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    process = subprocess.Popen(cmd, **kwargs)

    print_substep(f"Waiting for server to start (log: {log_file})...")
    time.sleep(5)

    if process.poll() is not None:
        with log_file.open() as f:
            print(f"Server failed to start. Log:\n{f.read()}")
        raise RuntimeError("Failed to start pys3local server")

    print_substep(f"Server started (PID: {process.pid})")
    return process


def stop_server(process: subprocess.Popen) -> None:
    """Stop the server process."""
    print_step("Stopping server...")
    try:
        if sys.platform == "win32":
            process.terminate()
        else:
            os.killpg(os.getpgid(process.pid), 15)
        process.wait(timeout=5)
        print_substep("Server stopped")
    except Exception as e:
        print_substep(f"Warning: Error stopping server: {e}")


def create_s3_client(port: int = 10001):
    """Create boto3 S3 client."""
    return boto3.client(
        "s3",
        endpoint_url=f"http://127.0.0.1:{port}",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )


def create_test_files(base_dir: Path, num_files: int = 5) -> dict[str, str]:
    """Create test files with known content.

    Args:
        base_dir: Directory to create files in
        num_files: Number of files to create

    Returns:
        Dict mapping filename to content hash
    """
    print_step(f"Creating {num_files} test files in {base_dir}...")

    base_dir.mkdir(parents=True, exist_ok=True)
    file_hashes = {}

    for i in range(num_files):
        filename = f"file{i:02d}.txt"
        filepath = base_dir / filename
        content = f"File {i} - Initial content (version 1)\n" * (i + 1)

        filepath.write_text(content)
        file_hashes[filename] = file_hash(filepath)
        hash_preview = file_hashes[filename][:16]
        print_substep(
            f"Created {filename} ({len(content)} bytes, hash: {hash_preview}...)"
        )

    return file_hashes


def modify_test_files(base_dir: Path, filenames: list[str]) -> dict[str, str]:
    """Modify existing test files.

    Args:
        base_dir: Directory containing files
        filenames: List of filenames to modify

    Returns:
        Dict mapping filename to new content hash
    """
    print_step(f"Modifying {len(filenames)} test files...")

    new_hashes = {}

    for i, filename in enumerate(filenames):
        filepath = base_dir / filename
        content = f"File {i} - MODIFIED content (version 2) - CHANGED!\n" * (i + 2)

        filepath.write_text(content)
        new_hashes[filename] = file_hash(filepath)
        hash_preview = new_hashes[filename][:16]
        print_substep(
            f"Modified {filename} ({len(content)} bytes, hash: {hash_preview}...)"
        )

    return new_hashes


def sync_to_s3(
    s3_client, bucket_name: str, local_dir: Path, file_hashes: dict[str, str]
) -> dict[str, str]:
    """Upload files to S3 and return their ETags.

    Args:
        s3_client: boto3 S3 client
        bucket_name: S3 bucket name
        local_dir: Local directory containing files
        file_hashes: Dict of local file hashes

    Returns:
        Dict mapping filename to ETag
    """
    print_step(f"Syncing {len(file_hashes)} files to S3 bucket '{bucket_name}'...")

    etags = {}

    for filename in file_hashes.keys():
        filepath = local_dir / filename
        with open(filepath, "rb") as f:
            s3_client.put_object(Bucket=bucket_name, Key=filename, Body=f)

        response = s3_client.head_object(Bucket=bucket_name, Key=filename)
        etag = response["ETag"].strip('"')
        etags[filename] = etag
        print_substep(f"Uploaded {filename} → ETag: {etag}")

    return etags


def verify_s3_content(
    s3_client, bucket_name: str, expected_hashes: dict[str, str]
) -> tuple[bool, str]:
    """Verify S3 files match expected content.

    Args:
        s3_client: boto3 S3 client
        bucket_name: S3 bucket name
        expected_hashes: Dict mapping filename to expected SHA256 hash

    Returns:
        Tuple of (success, message)
    """
    print_step("Verifying S3 content matches expected hashes...")

    for filename, expected_hash in expected_hashes.items():
        response = s3_client.get_object(Bucket=bucket_name, Key=filename)
        content = response["Body"].read()

        # Calculate hash of downloaded content
        actual_hash = hashlib.sha256(content).hexdigest()

        if actual_hash != expected_hash:
            exp_preview = expected_hash[:16]
            act_preview = actual_hash[:16]
            return (
                False,
                f"Content mismatch for {filename}: "
                f"expected {exp_preview}..., got {act_preview}...",
            )

        print_substep(f"✓ {filename} content verified (hash: {actual_hash[:16]}...)")

    return True, "All files verified"


def test_sync_workflow(
    s3_client, bucket_name: str, local_dir: Path, num_files: int = 5
) -> tuple[bool, str]:
    """Test the complete sync workflow.

    Args:
        s3_client: boto3 S3 client
        bucket_name: S3 bucket name
        local_dir: Local directory for test files
        num_files: Number of files to test with

    Returns:
        Tuple of (success, message)
    """
    print_header("SYNC WORKFLOW TEST")

    # Phase 1: Initial sync
    print_header("PHASE 1: Initial Sync")
    initial_hashes = create_test_files(local_dir, num_files)
    initial_etags = sync_to_s3(s3_client, bucket_name, local_dir, initial_hashes)

    success, message = verify_s3_content(s3_client, bucket_name, initial_hashes)
    if not success:
        return False, f"Initial sync verification failed: {message}"

    print_substep("✓ Initial sync successful")

    # Phase 2: Modify files locally
    print_header("PHASE 2: Modify Local Files")
    filenames = list(initial_hashes.keys())
    modified_hashes = modify_test_files(local_dir, filenames)

    # Verify hashes changed
    for filename in filenames:
        if initial_hashes[filename] == modified_hashes[filename]:
            return False, f"Hash didn't change for {filename} after modification!"

    print_substep("✓ All files modified locally")

    # Phase 3: Re-sync (simulates rclone detecting changes)
    print_header("PHASE 3: Re-Sync (Detect Changes)")
    print_step("Checking if rclone would detect changes (ETag comparison)...")

    # Get current ETags from S3 (this is what rclone does)
    current_s3_etags = {}
    for filename in filenames:
        response = s3_client.head_object(Bucket=bucket_name, Key=filename)
        etag = response["ETag"].strip('"')
        current_s3_etags[filename] = etag
        print_substep(f"{filename}: remote ETag = {etag}")

    # These should still be the initial ETags (content hasn't been uploaded yet)
    for filename in filenames:
        if current_s3_etags[filename] != initial_etags[filename]:
            return (
                False,
                f"S3 ETag changed before re-upload for {filename}! "
                "(should be unchanged)",
            )

    print_substep("✓ Remote ETags unchanged (as expected)")

    # Now upload modified files
    print_step("Uploading modified files...")
    new_etags = sync_to_s3(s3_client, bucket_name, local_dir, modified_hashes)

    # Phase 4: Verify ETags changed (critical for rclone)
    print_header("PHASE 4: Verify ETag Change Detection")

    all_etags_changed = True
    for filename in filenames:
        old_etag = initial_etags[filename]
        new_etag = new_etags[filename]

        if old_etag == new_etag:
            print_substep(f"✗ CRITICAL: {filename} ETag unchanged! ({old_etag})")
            print_substep("  This means rclone would SKIP this file (DATA LOSS!)")
            all_etags_changed = False
        else:
            print_substep(f"✓ {filename} ETag changed: {old_etag} → {new_etag}")

    if not all_etags_changed:
        return (
            False,
            "CRITICAL: Some ETags didn't change! rclone would not detect changes.",
        )

    print_substep("✓ All ETags changed correctly")

    # Phase 5: Verify content
    print_header("PHASE 5: Verify Modified Content")
    success, message = verify_s3_content(s3_client, bucket_name, modified_hashes)
    if not success:
        return False, f"Content verification failed: {message}"

    print_substep("✓ All modified files have correct content in S3")

    return True, "Complete sync workflow test PASSED"


def cleanup_s3(s3_client, bucket_name: str) -> None:
    """Delete all objects and bucket."""
    print_step(f"Cleaning up S3 bucket '{bucket_name}'...")

    try:
        # Delete all objects
        response = s3_client.list_objects_v2(Bucket=bucket_name)
        if "Contents" in response:
            objects = [{"Key": obj["Key"]} for obj in response["Contents"]]
            s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": objects})
            print_substep(f"Deleted {len(objects)} objects")

        # Delete bucket
        s3_client.delete_bucket(Bucket=bucket_name)
        print_substep("Deleted bucket")
    except Exception as e:
        print_substep(f"Warning: Cleanup error: {e}")


def run_local_backend_test(num_files: int = 5) -> tuple[bool, str]:
    """Run sync workflow test with local backend.

    Args:
        num_files: Number of files to test

    Returns:
        Tuple of (success, message)
    """
    print_header("LOCAL BACKEND TEST")

    temp_base = Path(tempfile.mkdtemp(prefix="pys3local_sync_test_"))
    s3_storage_dir = temp_base / "s3_storage"
    local_files_dir = temp_base / "local_files"

    s3_storage_dir.mkdir()
    local_files_dir.mkdir()

    server_process = None
    bucket_name = f"sync-test-{int(time.time())}"

    try:
        # Start server
        server_process = start_server("local", base_dir=s3_storage_dir)
        s3_client = create_s3_client()

        # Create bucket
        print_step(f"Creating bucket '{bucket_name}'...")
        s3_client.create_bucket(Bucket=bucket_name)
        print_substep("Bucket created")

        # Run test
        success, message = test_sync_workflow(
            s3_client, bucket_name, local_files_dir, num_files
        )

        # Cleanup
        cleanup_s3(s3_client, bucket_name)

        return success, message

    except Exception as e:
        import traceback

        return False, f"Exception: {e}\n{traceback.format_exc()}"

    finally:
        if server_process:
            stop_server(server_process)

        # Cleanup temp directory
        print_step("Cleaning up temporary directory...")
        shutil.rmtree(temp_base, ignore_errors=True)
        print_substep(f"Removed {temp_base}")


def run_drime_backend_test(
    workspace_id: int, api_key: str, num_files: int = 5
) -> tuple[bool, str]:
    """Run sync workflow test with Drime backend.

    Args:
        workspace_id: Drime workspace ID
        api_key: Drime API key
        num_files: Number of files to test

    Returns:
        Tuple of (success, message)
    """
    print_header("DRIME BACKEND TEST")

    temp_base = Path(tempfile.mkdtemp(prefix="pys3local_sync_test_drime_"))
    local_files_dir = temp_base / "local_files"
    local_files_dir.mkdir()

    server_process = None
    bucket_name = f"sync-test-{int(time.time())}"

    try:
        # Start server
        server_process = start_server(
            "drime", workspace_id=workspace_id, api_key=api_key
        )
        s3_client = create_s3_client()

        # Create bucket
        print_step(f"Creating bucket '{bucket_name}'...")
        s3_client.create_bucket(Bucket=bucket_name)
        print_substep("Bucket created")

        # Run test
        success, message = test_sync_workflow(
            s3_client, bucket_name, local_files_dir, num_files
        )

        # Cleanup
        cleanup_s3(s3_client, bucket_name)

        return success, message

    except Exception as e:
        import traceback

        return False, f"Exception: {e}\n{traceback.format_exc()}"

    finally:
        if server_process:
            stop_server(server_process)

        # Cleanup temp directory
        print_step("Cleaning up temporary directory...")
        shutil.rmtree(temp_base, ignore_errors=True)
        print_substep(f"Removed {temp_base}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test rclone-like sync workflow with pys3local",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test local backend only
  %(prog)s --backend local --files 5

  # Test Drime backend only
  %(prog)s --backend drime --files 5

  # Test both backends
  %(prog)s --backend both --files 10
        """,
    )

    parser.add_argument(
        "--backend",
        choices=["local", "drime", "both"],
        default="local",
        help="Backend to test (default: local)",
    )

    parser.add_argument(
        "--files",
        type=int,
        default=5,
        help="Number of test files (default: 5)",
    )

    args = parser.parse_args()

    print_header("PYSLOCAL SYNC WORKFLOW TEST")
    print("This test simulates rclone sync workflow:")
    print("  1. Upload files to S3")
    print("  2. Modify files locally")
    print("  3. Re-upload (should detect changes via ETag)")
    print("  4. Verify changes were uploaded")
    print()
    print("This test is CRITICAL for ensuring rclone sync works correctly.")

    results = []

    # Test local backend
    if args.backend in ["local", "both"]:
        success, message = run_local_backend_test(args.files)
        results.append(("Local Backend", success, message))

    # Test Drime backend
    if args.backend in ["drime", "both"]:
        print_header("DRIME CREDENTIALS")
        print("Please enter your Drime credentials.")
        print("These will only be used for this test and not stored.\n")

        workspace_id_str = input("Workspace ID (0 for personal): ").strip()
        workspace_id = int(workspace_id_str) if workspace_id_str else 0

        api_key = getpass.getpass("Drime API key: ").strip()

        if not api_key:
            print("\n[ERROR] API key is required for Drime backend")
            return 1

        print("\n✓ Credentials received")

        success, message = run_drime_backend_test(workspace_id, api_key, args.files)
        results.append(("Drime Backend", success, message))

    # Print results
    print_header("TEST RESULTS")

    all_passed = True
    for backend, success, message in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"\n{status}: {backend}")
        print(f"  {message}")
        if not success:
            all_passed = False

    # Final result
    print_header("FINAL RESULT")
    if all_passed:
        print("✓ ALL TESTS PASSED")
        print()
        print("The sync workflow works correctly!")
        print("Files are properly detected as changed via ETags.")
        print("rclone sync would work correctly with this backend.")
        return 0
    else:
        print("✗ SOME TESTS FAILED")
        print()
        print("Please review the failures above.")
        print("If ETags don't change, rclone will not detect file changes!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
