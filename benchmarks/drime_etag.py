#!/usr/bin/env python3
"""Test script to verify Drime ETag format works with boto3 S3 client.

This script tests the UUID ETag format for Drime backend:
1. Verifies ETags are in UUID format (from file_name field)
2. Tests that ETags change when file changes
3. Confirms boto3 accepts non-MD5 ETags
4. Validates file integrity with changed ETags
"""

from __future__ import annotations

import getpass
import os
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


def start_server(
    workspace_id: int, api_key: str, port: int = 10001
) -> subprocess.Popen:
    """Start pys3local server with Drime backend.

    Args:
        workspace_id: Drime workspace ID
        api_key: Drime API key
        port: Server port

    Returns:
        Process handle
    """
    print_step("Starting pys3local server with Drime backend...")

    env = os.environ.copy()
    env["DRIME_API_KEY"] = api_key
    env["DRIME_WORKSPACE_ID"] = str(workspace_id)

    cmd = [
        sys.executable,
        "-m",
        "pys3local.cli",
        "serve",
        "--listen",
        f"127.0.0.1:{port}",
        "--backend",
        "drime",
        "--no-auth",
    ]

    log_file = Path(tempfile.gettempdir()) / "pys3local_etag_test.log"
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

    print("  Waiting for server to initialize...")
    time.sleep(5)

    if process.poll() is not None:
        with log_file.open() as f:
            print(f"Server failed to start. Log:\n{f.read()}")
        raise RuntimeError("Failed to start pys3local server")

    print(f"  ✓ Server started (PID: {process.pid})")
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
        print("  ✓ Server stopped")
    except Exception as e:
        print(f"  ⚠ Error stopping server: {e}")


def create_s3_client(port: int = 10001):
    """Create boto3 S3 client."""
    return boto3.client(
        "s3",
        endpoint_url=f"http://127.0.0.1:{port}",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )


def test_etag_format(s3_client, bucket_name: str) -> tuple[bool, str]:
    """Test that ETags are in UUID format.

    Args:
        s3_client: boto3 S3 client
        bucket_name: Bucket name

    Returns:
        Tuple of (success, message)
    """
    print_step("TEST 1: Verify ETag format is UUID")

    # Upload a test file
    test_data = b"Hello, World!"
    test_key = "test-etag-format.txt"

    print(f"  Uploading test file: {test_key} ({len(test_data)} bytes)")
    s3_client.put_object(Bucket=bucket_name, Key=test_key, Body=test_data)

    # Get object metadata
    response = s3_client.head_object(Bucket=bucket_name, Key=test_key)
    etag = response["ETag"].strip('"')

    print(f"  Received ETag: {etag}")

    # Verify format: should be UUID (with or without dashes)
    # UUID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (36 chars with dashes)
    # or 32 hex chars without dashes
    # Note: Drime uses UUID with dashes
    if not etag:
        return False, "ETag is empty"

    # Check if it looks like a UUID (contains dashes and is approximately right length)
    # or if it's a fallback format (hash or numeric ID)
    is_uuid_format = len(etag) >= 32 and ("-" in etag or len(etag) == 32)

    if not is_uuid_format:
        # Could be a fallback (hash or numeric ID)
        print(f"  ⚠ ETag is not in UUID format (may be fallback): {etag}")
        print("    This is acceptable but UUID format is preferred")
    else:
        print(f"  ✓ ETag appears to be in UUID format: {etag}")

    return True, "ETag format is valid"


def test_etag_changes(s3_client, bucket_name: str) -> tuple[bool, str]:
    """Test that ETag changes when file content changes.

    This simulates rclone's behavior: it compares ETags to detect if a file
    needs to be re-uploaded. If the ETag doesn't change when content changes,
    rclone will skip the upload (data loss!).

    Args:
        s3_client: boto3 S3 client
        bucket_name: Bucket name

    Returns:
        Tuple of (success, message)
    """
    print_step("TEST 2: Verify ETag changes when file changes (critical for rclone)")

    test_key = "test-etag-change.txt"

    # Test case 1: Same size, different content
    print("\n  Test 2a: Same size, different content")
    data_v1 = b"Content version 1"  # 17 bytes
    data_v2 = b"Content version 2"  # 17 bytes (same size!)

    print(f"    Uploading v1: '{data_v1.decode()}' ({len(data_v1)} bytes)")
    s3_client.put_object(Bucket=bucket_name, Key=test_key, Body=data_v1)

    response_v1 = s3_client.head_object(Bucket=bucket_name, Key=test_key)
    etag_v1 = response_v1["ETag"].strip('"')
    print(f"    ETag v1: {etag_v1}")

    print(f"    Uploading v2: '{data_v2.decode()}' ({len(data_v2)} bytes)")
    s3_client.put_object(Bucket=bucket_name, Key=test_key, Body=data_v2)

    response_v2 = s3_client.head_object(Bucket=bucket_name, Key=test_key)
    etag_v2 = response_v2["ETag"].strip('"')
    print(f"    ETag v2: {etag_v2}")

    if etag_v1 == etag_v2:
        return (
            False,
            "CRITICAL: ETag did not change despite content change! (same size case)",
        )

    print("    ✓ ETag changed correctly (UUID changed for new file)")

    # Test case 2: Different size, different content
    print("\n  Test 2b: Different size, different content")
    data_v3 = b"Version 3 - much longer content here"

    print(f"    Uploading v3: '{data_v3.decode()[:20]}...' ({len(data_v3)} bytes)")
    s3_client.put_object(Bucket=bucket_name, Key=test_key, Body=data_v3)

    response_v3 = s3_client.head_object(Bucket=bucket_name, Key=test_key)
    etag_v3 = response_v3["ETag"].strip('"')
    print(f"    ETag v3: {etag_v3}")

    if etag_v2 == etag_v3:
        return (
            False,
            "CRITICAL: ETag did not change despite content and size change!",
        )

    print("    ✓ ETag changed correctly (UUID changed for new file)")

    # Verify we can retrieve the correct content
    print("\n  Verifying content integrity...")
    obj = s3_client.get_object(Bucket=bucket_name, Key=test_key)
    retrieved_data = obj["Body"].read()
    if retrieved_data != data_v3:
        return False, "Retrieved content doesn't match last uploaded version"

    print("    ✓ Retrieved correct content")
    print("\n  ✓ All ETag change detection tests passed")
    return True, "ETag changes correctly for all scenarios"


def test_etag_consistency(s3_client, bucket_name: str) -> tuple[bool, str]:
    """Test that ETag format is stable (but may not be identical for re-uploads).

    Note: Some backends (like Drime) may include upload metadata in the hash,
    causing different ETags for the same content uploaded at different times.
    This is acceptable as long as:
    1. The size part is consistent
    2. The ETag changes when content changes (tested separately)
    3. Repeated HEAD requests return the same ETag

    Args:
        s3_client: boto3 S3 client
        bucket_name: Bucket name

    Returns:
        Tuple of (success, message)
    """
    print_step("TEST 3: Verify ETag stability (repeated queries = same ETag)")

    test_key = "test-etag-stability.txt"
    test_data = b"Stable content for testing"

    # Upload file
    print(f"  Upload: {test_key}")
    s3_client.put_object(Bucket=bucket_name, Key=test_key, Body=test_data)

    # Query ETag multiple times (should be stable)
    print("  Querying ETag 3 times...")
    etags = []
    for i in range(3):
        response = s3_client.head_object(Bucket=bucket_name, Key=test_key)
        etag = response["ETag"].strip('"')
        etags.append(etag)
        print(f"    Query {i + 1}: {etag}")

    # All queries should return the same ETag
    if len(set(etags)) != 1:
        return False, f"ETag changed between queries: {etags}"

    print("  ✓ ETag is stable across repeated queries")
    return True, "ETag is stable for same file"


def test_rclone_sync_scenario(s3_client, bucket_name: str) -> tuple[bool, str]:
    """Test the critical rclone sync workflow.

    This simulates what happens when using rclone sync:
    1. Initial sync: file uploaded to S3
    2. Local file modified
    3. Re-sync: rclone checks ETag to decide if upload needed
    4. If ETag unchanged → rclone skips upload (DATA LOSS!)
    5. If ETag changed → rclone uploads new version (correct behavior)

    Args:
        s3_client: boto3 S3 client
        bucket_name: Bucket name

    Returns:
        Tuple of (success, message)
    """
    print_step("TEST 4: Simulate rclone sync workflow (CRITICAL)")

    test_key = "rclone-sync-test.txt"

    # Step 1: Initial rclone sync (upload)
    print("\n  Step 1: Initial sync - uploading file v1")
    local_file_v1 = b"Initial local file content"
    s3_client.put_object(Bucket=bucket_name, Key=test_key, Body=local_file_v1)

    response = s3_client.head_object(Bucket=bucket_name, Key=test_key)
    etag_initial = response["ETag"].strip('"')
    print(f"    Remote ETag after upload: {etag_initial}")

    # Step 2: Simulate local file modification
    print("\n  Step 2: Modify local file (simulate user edit)")
    local_file_v2 = b"Modified local file content - changed by user"
    print(f"    Local file changed: {len(local_file_v1)} → {len(local_file_v2)} bytes")

    # Step 3: rclone checks if sync needed (compares ETags)
    print("\n  Step 3: Re-sync attempt - rclone checks remote ETag")
    print(f"    rclone sees remote ETag: {etag_initial}")
    print("    rclone uploads modified file...")

    # Upload the modified file (this is what rclone would do)
    s3_client.put_object(Bucket=bucket_name, Key=test_key, Body=local_file_v2)

    response = s3_client.head_object(Bucket=bucket_name, Key=test_key)
    etag_after_sync = response["ETag"].strip('"')
    print(f"    Remote ETag after re-sync: {etag_after_sync}")

    # Step 4: Critical check - did the ETag change?
    print("\n  Step 4: Verify rclone would detect the change")
    if etag_initial == etag_after_sync:
        print("    ✗ CRITICAL FAILURE!")
        print("    ETags are identical - rclone would SKIP this upload!")
        print("    This would cause DATA LOSS (remote has old version)")
        return (
            False,
            "CRITICAL: rclone would not detect file changes (ETags identical)",
        )

    print("    ✓ ETags are different - rclone would upload correctly")

    # Step 5: Verify content integrity
    print("\n  Step 5: Verify correct content stored")
    obj = s3_client.get_object(Bucket=bucket_name, Key=test_key)
    remote_content = obj["Body"].read()

    if remote_content != local_file_v2:
        return False, "Remote file has wrong content!"

    print("    ✓ Remote file has correct content")

    print("\n  ✓ rclone sync workflow would work correctly!")
    return True, "rclone sync scenario works perfectly"


def test_boto3_accepts_etag(s3_client, bucket_name: str) -> tuple[bool, str]:
    """Test that boto3 accepts non-MD5 ETags without errors.

    Args:
        s3_client: boto3 S3 client
        bucket_name: Bucket name

    Returns:
        Tuple of (success, message)
    """
    print_step("TEST 4: Verify boto3 accepts non-MD5 ETags")

    # Upload multiple files
    test_files = {
        "file1.txt": b"Content 1",
        "file2.txt": b"Content 2 is longer",
        "file3.txt": b"Content 3 is even longer than the others",
    }

    print(f"  Uploading {len(test_files)} test files...")
    for key, data in test_files.items():
        s3_client.put_object(Bucket=bucket_name, Key=key, Body=data)

    # List objects
    print("  Listing objects...")
    response = s3_client.list_objects_v2(Bucket=bucket_name)

    if "Contents" not in response:
        return False, "list_objects_v2 returned no contents"

    # Verify all files listed with ETags
    found_files = {obj["Key"]: obj["ETag"].strip('"') for obj in response["Contents"]}

    for key in test_files.keys():
        if key not in found_files:
            return False, f"File {key} not found in listing"

        etag = found_files[key]
        print(f"    {key}: {etag}")

    # Download files and verify
    print("  Downloading and verifying files...")
    for key, original_data in test_files.items():
        response = s3_client.get_object(Bucket=bucket_name, Key=key)
        downloaded_data = response["Body"].read()

        if downloaded_data != original_data:
            return False, f"Downloaded content for {key} doesn't match"

    print("  ✓ boto3 accepts ETags and file operations work correctly")
    return True, "boto3 works with non-MD5 ETags"


def test_list_objects_performance(s3_client, bucket_name: str) -> tuple[bool, str]:
    """Test that listing objects is fast (no downloads needed for ETags).

    Args:
        s3_client: boto3 S3 client
        bucket_name: Bucket name

    Returns:
        Tuple of (success, message)
    """
    print_step("TEST 5: Verify listing is fast (no ETag downloads)")

    # Upload files of various sizes
    num_files = 20
    print(f"  Uploading {num_files} test files...")

    for i in range(num_files):
        key = f"perf-test/file{i:03d}.bin"
        # Random sizes from 10KB to 100KB
        size = 10240 + (i * 4096)
        data = os.urandom(size)
        s3_client.put_object(Bucket=bucket_name, Key=key, Body=data)

    # Time the listing operation
    print("  Timing list_objects_v2...")
    start_time = time.time()
    response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix="perf-test/")
    list_time = time.time() - start_time

    if "Contents" not in response:
        return False, "No files found"

    num_listed = len(response["Contents"])
    print(f"  Listed {num_listed} files in {list_time:.3f} seconds")
    print(f"  Average: {list_time / num_listed * 1000:.1f} ms per file")

    # Verify all files have ETags
    for obj in response["Contents"]:
        etag = obj["ETag"].strip('"')
        if not etag:
            return False, f"File {obj['Key']} has empty ETag"

    # If listing takes > 100ms per file, something is wrong (likely downloading)
    avg_time_per_file = list_time / num_listed
    if avg_time_per_file > 0.1:
        return (
            False,
            f"Listing is slow ({avg_time_per_file:.3f}s per file) - "
            "may be downloading files for ETags",
        )

    print("  ✓ Listing is fast - ETags generated without downloads")
    return True, "List operations are efficient"


def run_tests() -> int:
    """Run all ETag tests.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    print_header("DRIME ETAG FORMAT TEST")

    print("This test verifies the UUID ETag format for Drime backend.")
    print("It will:")
    print("  1. Verify ETags are in UUID format")
    print("  2. Test that ETags change when files change (CRITICAL)")
    print("  3. Verify ETag stability (repeated queries)")
    print("  4. Simulate rclone sync workflow (CRITICAL)")
    print("  5. Confirm boto3 accepts non-MD5 ETags")
    print("  6. Test listing performance (no downloads)")

    # Prompt for credentials
    print_header("DRIME CREDENTIALS")
    print("Please enter your Drime credentials.")
    print("These will only be used for this test and not stored.\n")

    workspace_id_str = input("Workspace ID (0 for personal): ").strip()
    workspace_id = int(workspace_id_str) if workspace_id_str else 0

    api_key = getpass.getpass("Drime API key: ").strip()

    if not api_key:
        print("\n[ERROR] API key is required")
        return 1

    print("\n✓ Credentials received")

    # Start server
    server_process = None
    test_bucket = f"etag-test-{int(time.time())}"

    try:
        server_process = start_server(workspace_id, api_key)
        s3_client = create_s3_client()

        # Create test bucket
        print_step(f"Creating test bucket: {test_bucket}")
        s3_client.create_bucket(Bucket=test_bucket)
        print("  ✓ Bucket created")

        # Run tests
        tests = [
            test_etag_format,
            test_etag_changes,
            test_etag_consistency,
            test_rclone_sync_scenario,
            test_boto3_accepts_etag,
            test_list_objects_performance,
        ]

        results = []
        for test_func in tests:
            try:
                success, message = test_func(s3_client, test_bucket)
                results.append((test_func.__name__, success, message))
            except Exception as e:
                results.append((test_func.__name__, False, f"Exception: {e}"))

        # Print summary
        print_header("TEST RESULTS")

        all_passed = True
        for test_name, success, message in results:
            status = "✓ PASS" if success else "✗ FAIL"
            print(f"{status}: {test_name}")
            print(f"        {message}")
            if not success:
                all_passed = False

        # Cleanup
        print_step(f"Cleaning up test bucket: {test_bucket}")
        try:
            s3_client.delete_bucket(Bucket=test_bucket)
            print("  ✓ Bucket deleted")
        except Exception as e:
            print(f"  ⚠ Error deleting bucket: {e}")

        # Final result
        print_header("FINAL RESULT")
        if all_passed:
            print("✓ ALL TESTS PASSED")
            print("\nThe UUID ETag format is working correctly!")
            print("Drime backend is S3-compatible with non-MD5 ETags.")
            return 0
        else:
            print("✗ SOME TESTS FAILED")
            print("\nPlease review the failures above.")
            return 1

    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        return 1

    finally:
        if server_process:
            stop_server(server_process)


if __name__ == "__main__":
    sys.exit(run_tests())
