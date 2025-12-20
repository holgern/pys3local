# Testing rclone Compatibility

## Changes Made

### 1. Updated uvicorn configuration for better HTTP/1.1 compatibility

- Explicitly use `h11` backend instead of default `httptools`
- Disabled Server header (some clients have issues with this)
- Set standard keep-alive timeout (75 seconds)
- Only show access logs in debug mode

### 2. Added uvicorn[standard] dependency

- Includes `httptools`, `uvloop`, `websockets` for better performance
- Provides multiple HTTP backends for compatibility

## Testing with rclone

### 1. Start the server

```bash
# Local backend
pys3local serve --path /tmp/s3store --debug

# Drime backend
pys3local serve --backend drime --backend-config myconfig --debug
```

### 2. Configure rclone

Create or edit `~/.config/rclone/rclone.conf`:

```ini
[pys3local]
type = s3
provider = Other
access_key_id = test
secret_access_key = test
endpoint = http://localhost:8000
region = us-east-1
# Important settings for compatibility
force_path_style = true
disable_checksum = false
# Use v4 signatures (default)
# v2_auth = false
```

### 3. Test rclone commands

```bash
# List buckets
rclone lsd pys3local:

# Create bucket
rclone mkdir pys3local:test-bucket

# Upload file
echo "Hello World" > test.txt
rclone copy test.txt pys3local:test-bucket/

# List objects
rclone ls pys3local:test-bucket

# Download file
rclone copy pys3local:test-bucket/test.txt ./downloaded.txt

# Delete object
rclone delete pys3local:test-bucket/test.txt

# Delete bucket
rclone rmdir pys3local:test-bucket
```

### 4. Verbose debugging

If you still get errors, run with verbose output:

```bash
# rclone with verbose output
rclone -vv lsd pys3local:

# Server with debug logging
pys3local serve --path /tmp/s3store --debug
```

## Common Issues and Solutions

### Issue: "Invalid HTTP request received"

**Causes:**

1. Incompatible HTTP backend (httptools vs h11)
2. Malformed request headers
3. HTTP/2 upgrade attempts

**Solutions:**

- ✅ Now using `h11` backend explicitly (more lenient with protocol violations)
- ✅ Disabled Server header
- ✅ Standard keep-alive timeout

### Issue: "SignatureDoesNotMatch" or "AccessDenied"

**Causes:**

1. Mismatched credentials
2. Wrong signature version
3. Missing required headers

**Solutions:**

1. Verify access_key_id and secret_access_key match
2. Ensure rclone config has matching credentials
3. Use `--debug` on server to see auth details
4. Check for `force_path_style = true` in rclone config

### Issue: "NoSuchBucket" errors

**Causes:**

1. Virtual-host style URLs not properly configured
2. Bucket name in wrong place

**Solutions:**

1. Set `force_path_style = true` in rclone config
2. Use path-style URLs: `http://localhost:8000/bucket/key`

### Issue: Slow performance

**Causes:**

1. Not using uvicorn[standard] with optimized backends
2. Too many keep-alive connections

**Solutions:**

1. Install: `pip install uvicorn[standard]`
2. This provides uvloop and httptools for better performance

## Technical Details

### HTTP Backend Selection

**httptools (default):**

- Faster, written in C
- Stricter HTTP parsing
- May reject some edge-case requests

**h11 (now default for pys3local):**

- Pure Python
- More lenient parsing
- Better compatibility with diverse S3 clients
- Slightly slower but more robust

### Why h11 works better

rclone and other S3 clients may:

- Send headers in non-standard order
- Use HTTP/1.1 pipelining
- Send Expect: 100-continue headers
- Use chunked transfer encoding

The `h11` backend handles these cases more gracefully.

## Verification

After the changes, you should see:

```
Starting S3 server at http://0.0.0.0:8000/
Press Ctrl+C to stop the server
```

And rclone commands should work without "Invalid HTTP request" errors.

## Next Steps

If you still encounter issues:

1. **Capture the error details:**

   ```bash
   pys3local serve --debug 2>&1 | tee server.log
   rclone -vv lsd pys3local: 2>&1 | tee rclone.log
   ```

2. **Share the logs** showing:

   - Exact error message
   - Request headers (from debug output)
   - rclone version: `rclone version`
   - Python version: `python --version`

3. **Try with different settings:**
   ```ini
   # In rclone config, try:
   v2_auth = true  # Use signature v2 instead of v4
   chunk_size = 5M  # Smaller chunks
   upload_concurrency = 1  # Sequential uploads
   ```
