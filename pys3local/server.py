"""FastAPI-based S3-compatible server.

This module provides a FastAPI application implementing the AWS S3 API.
"""

from __future__ import annotations

import hashlib
import logging
import urllib.parse
from typing import Any

import defusedxml.ElementTree as ET
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from pys3local import auth, xml_templates
from pys3local.constants import DEFAULT_REGION, MAX_KEYS_DEFAULT, XML_CONTENT_TYPE
from pys3local.errors import (
    AccessDenied,
    BucketNotEmpty,
    NoSuchBucket,
    NoSuchKey,
    S3Error,
)
from pys3local.provider import StorageProvider

logger = logging.getLogger(__name__)

# Global server configuration
_server_config: dict[str, Any] = {
    "access_key": "test",
    "secret_key": "test",
    "region": DEFAULT_REGION,
    "provider": None,
    "no_auth": False,
}


def create_s3_app(
    provider: StorageProvider,
    access_key: str = "test",
    secret_key: str = "test",
    region: str = DEFAULT_REGION,
    no_auth: bool = False,
) -> FastAPI:
    """Create FastAPI S3 application.

    Args:
        provider: Storage provider instance
        access_key: AWS access key ID
        secret_key: AWS secret access key
        region: AWS region
        no_auth: Disable authentication

    Returns:
        FastAPI application instance
    """
    app = FastAPI(
        title="pys3local",
        description="Local S3-compatible server for backup software",
    )

    # Store configuration in app state
    app.state.provider = provider
    app.state.access_key = access_key
    app.state.secret_key = secret_key
    app.state.region = region
    app.state.no_auth = no_auth

    # Add global exception handler for S3 errors
    @app.exception_handler(S3Error)
    async def s3_error_handler(request: Request, exc: S3Error) -> Response:
        """Handle S3 errors and convert to XML response."""
        xml = xml_templates.format_error_xml(exc.code, exc.message)
        return Response(
            content=xml, media_type=XML_CONTENT_TYPE, status_code=exc.status_code
        )

    # Setup routes
    _setup_routes(app)

    return app


def _parse_path(path: str, host: str, hostname: str) -> tuple[str | None, str | None]:
    """Parse bucket and key from request path.

    Args:
        path: Request path
        host: Host header value
        hostname: Configured hostname

    Returns:
        Tuple of (bucket_name, key)
    """
    # Virtual host style: bucket.hostname
    if host != hostname and hostname in host:
        idx = host.index(hostname)
        bucket_name_vhost: str | None = host[: idx - 1]
        key_vhost: str | None = urllib.parse.unquote(path.strip("/")) or None
        return bucket_name_vhost, key_vhost

    # Path style: /bucket/key
    parts = path.strip("/").split("/", 1)
    bucket_name: str | None = urllib.parse.unquote(parts[0]) if parts[0] else None
    key: str | None = urllib.parse.unquote(parts[1]) if len(parts) > 1 else None

    return bucket_name, key


async def _verify_auth(request: Request) -> bool:
    """Verify request authentication.

    Args:
        request: FastAPI request

    Returns:
        True if authenticated

    Raises:
        AccessDenied: If authentication fails
    """
    # Skip auth if disabled
    if request.app.state.no_auth:
        return True

    access_key = request.app.state.access_key
    secret_key = request.app.state.secret_key
    region = request.app.state.region

    auth_header = request.headers.get("authorization", "")

    # Check for presigned URL
    query_params = dict(request.query_params)
    if "X-Amz-Algorithm" in query_params:
        # Presigned URL
        is_valid = auth.verify_presigned_url_v4(
            access_key=access_key,
            secret_key=secret_key,
            region=region,
            request_method=request.method,
            request_path=request.url.path,
            query_params=query_params,
        )
        if not is_valid:
            raise AccessDenied()
        return True

    # Check for Signature V4
    if auth_header.startswith("AWS4-HMAC-SHA256"):
        # Convert headers to lowercase dict
        headers = {k.lower(): v for k, v in request.headers.items()}

        # Get payload hash
        payload_hash = headers.get("x-amz-content-sha256", "UNSIGNED-PAYLOAD")

        is_valid = auth.verify_signature_v4(
            access_key=access_key,
            secret_key=secret_key,
            region=region,
            request_method=request.method,
            request_path=request.url.path,
            query_params=query_params,
            headers=headers,
            payload_hash=payload_hash,
            authorization_header=auth_header,
        )
        if not is_valid:
            raise AccessDenied()
        return True

    # Check for Signature V2 (older AWS signature format)
    if auth_header.startswith("AWS "):
        logger.debug("Detected AWS Signature V2 authentication")
        # Parse: "AWS AccessKeyId:Signature"
        try:
            _, auth_data = auth_header.split(" ", 1)
            provided_access_key, signature = auth_data.split(":", 1)

            # Verify access key
            if provided_access_key != access_key:
                logger.warning(
                    f"Access key mismatch: {provided_access_key} != {access_key}"
                )
                raise AccessDenied()

            # Build string to sign for V2
            # Format: HTTP-Verb\nContent-MD5\nContent-Type\nDate\n
            #         CanonicalizedAmzHeaders\nCanonicalizedResource
            content_md5 = request.headers.get("content-md5", "")
            content_type = request.headers.get("content-type", "")
            date = request.headers.get("date", "")

            # Get x-amz-* headers (sorted)
            amz_headers = []
            for key, value in sorted(request.headers.items()):
                if key.lower().startswith("x-amz-"):
                    amz_headers.append(f"{key.lower()}:{value.strip()}")
            canonical_amz_headers = "\n".join(amz_headers)
            if canonical_amz_headers:
                canonical_amz_headers += "\n"

            # Canonicalized resource: bucket and key
            canonical_resource = request.url.path

            string_to_sign = "\n".join(
                [
                    request.method,
                    content_md5,
                    content_type,
                    date,
                    canonical_amz_headers + canonical_resource,
                ]
            )

            logger.debug(f"SigV2 string to sign: {repr(string_to_sign)}")

            is_valid = auth.verify_signature_v2(
                access_key=access_key,
                secret_key=secret_key,
                signature=signature,
                string_to_sign=string_to_sign,
            )

            if not is_valid:
                logger.warning("Signature V2 verification failed")
                raise AccessDenied()

            logger.debug("Signature V2 verified successfully")
            return True

        except (ValueError, IndexError) as e:
            logger.error(f"Failed to parse Signature V2 header: {e}")
            raise AccessDenied() from e

    # No authentication provided
    if not request.app.state.no_auth:
        logger.warning(
            f"No valid authentication provided. Auth header: {auth_header[:50]}"
        )
        raise AccessDenied()

    return True


async def _decode_chunked_stream(request: Request) -> tuple[bytes, str]:
    """Decode AWS chunked encoded stream.

    AWS SDK v4 uses a specific chunked encoding format:
    <chunk-size-hex>;chunk-signature=<signature>\r\n
    <chunk-data>\r\n
    0;chunk-signature=<signature>\r\n
    \r\n

    Args:
        request: FastAPI request with chunked body

    Returns:
        Tuple of (decoded_data, md5_hash)

    Raises:
        ValueError: If chunk format is invalid
    """
    body_stream = request.stream()
    decoded_data = bytearray()
    md5_hasher = hashlib.md5()

    try:
        async for chunk in body_stream:
            if not chunk:
                continue

            # Process chunk data
            data = chunk if isinstance(chunk, bytes) else chunk.encode()
            idx = 0

            while idx < len(data):
                # Find the chunk size line (ends with \r\n)
                line_end = data.find(b"\r\n", idx)
                if line_end == -1:
                    break

                # Parse chunk size
                size_line = data[idx:line_end].decode("ascii")
                try:
                    # Extract hex size (before semicolon)
                    hex_size = size_line.split(";")[0].strip()
                    chunk_size = int(hex_size, 16)
                except (ValueError, IndexError) as e:
                    logger.warning(f"Failed to parse chunk size '{size_line}': {e}")
                    break

                # Move past the size line
                idx = line_end + 2  # Skip \r\n

                if chunk_size == 0:
                    # Last chunk
                    break

                # Extract chunk data
                chunk_data = data[idx : idx + chunk_size]
                decoded_data.extend(chunk_data)
                md5_hasher.update(chunk_data)

                # Move past chunk data and trailing \\r\\n
                idx += chunk_size + 2

    except Exception as e:
        logger.error(f"Error decoding chunked stream: {e}")
        raise ValueError(f"Failed to decode chunked stream: {e}") from e

    md5_hash = md5_hasher.hexdigest()
    logger.debug(f"Decoded chunked stream: {len(decoded_data)} bytes, MD5: {md5_hash}")

    return bytes(decoded_data), md5_hash


def _setup_routes(app: FastAPI) -> None:
    """Setup FastAPI routes.

    Args:
        app: FastAPI application
    """

    @app.get("/")
    async def list_buckets(request: Request) -> Response:
        """List all buckets."""
        await _verify_auth(request)
        provider: StorageProvider = request.app.state.provider

        try:
            buckets = provider.list_buckets()
            xml = xml_templates.format_list_buckets_xml(buckets)
            return Response(content=xml, media_type=XML_CONTENT_TYPE)
        except S3Error as e:
            xml = xml_templates.format_error_xml(e.code, e.message)
            return Response(
                content=xml, media_type=XML_CONTENT_TYPE, status_code=e.status_code
            )
        except Exception as e:
            logger.exception("Error listing buckets")
            xml = xml_templates.format_error_xml("InternalError", str(e))
            return Response(content=xml, media_type=XML_CONTENT_TYPE, status_code=500)

    @app.get("/{path:path}")
    async def get_handler(request: Request, path: str) -> Response:
        """Handle GET requests."""
        await _verify_auth(request)
        provider: StorageProvider = request.app.state.provider
        hostname = "localhost"  # TODO: Get from config

        bucket_name, key = _parse_path(path, request.headers.get("host", ""), hostname)

        if not bucket_name:
            # List buckets
            return await list_buckets(request)

        query_params = dict(request.query_params)

        try:
            if not key:
                # List objects
                prefix = query_params.get("prefix", "")
                marker = query_params.get("marker", "")
                max_keys = int(query_params.get("max-keys", str(MAX_KEYS_DEFAULT)))
                delimiter = query_params.get("delimiter", "")

                result = provider.list_objects(
                    bucket_name, prefix, marker, max_keys, delimiter
                )

                xml = xml_templates.format_list_objects_xml(
                    bucket_name=bucket_name,
                    prefix=prefix,
                    marker=marker,
                    max_keys=max_keys,
                    is_truncated=result["is_truncated"],
                    delimiter=delimiter,
                    contents=result["contents"],
                    common_prefixes=result["common_prefixes"],
                    next_marker=result.get("next_marker", ""),
                )

                return Response(content=xml, media_type=XML_CONTENT_TYPE)

            # Get object
            obj = provider.get_object(bucket_name, key)

            if obj.data is None:
                raise NoSuchKey(key)

            headers = {
                "ETag": f'"{obj.etag}"',
                "Last-Modified": obj.last_modified.strftime(
                    "%a, %d %b %Y %H:%M:%S GMT"
                ),
                "Content-Type": obj.content_type,
                "Content-Length": str(obj.size),
            }

            return StreamingResponse(
                iter([obj.data]),
                status_code=200,
                headers=headers,
                media_type=obj.content_type,
            )

        except S3Error as e:
            xml = xml_templates.format_error_xml(e.code, e.message)
            return Response(
                content=xml, media_type=XML_CONTENT_TYPE, status_code=e.status_code
            )
        except Exception as e:
            logger.exception("Error in GET handler")
            xml = xml_templates.format_error_xml("InternalError", str(e))
            return Response(content=xml, media_type=XML_CONTENT_TYPE, status_code=500)

    @app.head("/{path:path}")
    async def head_handler(request: Request, path: str) -> Response:
        """Handle HEAD requests."""
        await _verify_auth(request)
        provider: StorageProvider = request.app.state.provider
        hostname = "localhost"

        bucket_name, key = _parse_path(path, request.headers.get("host", ""), hostname)

        if not bucket_name:
            return Response(status_code=400)

        try:
            if not key:
                # Check bucket existence
                if provider.bucket_exists(bucket_name):
                    return Response(status_code=200)
                else:
                    return Response(status_code=404)

            # Check object
            obj = provider.head_object(bucket_name, key)

            headers = {
                "ETag": f'"{obj.etag}"',
                "Last-Modified": obj.last_modified.strftime(
                    "%a, %d %b %Y %H:%M:%S GMT"
                ),
                "Content-Type": obj.content_type,
                "Content-Length": str(obj.size),
            }

            return Response(status_code=200, headers=headers)

        except (NoSuchBucket, NoSuchKey):
            return Response(status_code=404)
        except S3Error as e:
            return Response(status_code=e.status_code)
        except Exception:
            logger.exception("Error in HEAD handler")
            return Response(status_code=500)

    @app.put("/{path:path}")
    async def put_handler(request: Request, path: str) -> Response:
        """Handle PUT requests."""
        await _verify_auth(request)
        provider: StorageProvider = request.app.state.provider
        hostname = "localhost"

        bucket_name, key = _parse_path(path, request.headers.get("host", ""), hostname)

        if not bucket_name:
            return Response(status_code=400)

        try:
            if not key:
                # Create bucket
                provider.create_bucket(bucket_name)
                return Response(status_code=200)

            # Check for copy operation
            copy_source = request.headers.get("x-amz-copy-source")
            if copy_source:
                # Copy object
                src_bucket, _, src_key = copy_source.partition("/")
                obj = provider.copy_object(src_bucket, src_key, bucket_name, key)

                xml = xml_templates.format_copy_object_xml(
                    last_modified=obj.last_modified.isoformat() + "Z",
                    etag=obj.etag,
                )

                return Response(
                    content=xml, media_type=XML_CONTENT_TYPE, status_code=200
                )

            # Put object
            # Check if this is a chunked upload (AWS SDK v4)
            content_sha256 = request.headers.get("x-amz-content-sha256", "")
            is_chunked = content_sha256 == "STREAMING-AWS4-HMAC-SHA256-PAYLOAD"

            if is_chunked:
                logger.debug("Detected AWS chunked upload")
                body, md5_hash = await _decode_chunked_stream(request)
            else:
                body = await request.body()
                md5_hash = None  # Provider will calculate

            content_type = request.headers.get(
                "content-type", "application/octet-stream"
            )

            obj = provider.put_object(
                bucket_name, key, body, content_type, md5_hash=md5_hash
            )

            headers = {"ETag": f'"{obj.etag}"'}

            return Response(status_code=200, headers=headers)

        except S3Error as e:
            xml = xml_templates.format_error_xml(e.code, e.message)
            return Response(
                content=xml, media_type=XML_CONTENT_TYPE, status_code=e.status_code
            )
        except Exception as e:
            logger.exception("Error in PUT handler")
            xml = xml_templates.format_error_xml("InternalError", str(e))
            return Response(content=xml, media_type=XML_CONTENT_TYPE, status_code=500)

    @app.delete("/{path:path}")
    async def delete_handler(request: Request, path: str) -> Response:
        """Handle DELETE requests."""
        await _verify_auth(request)
        provider: StorageProvider = request.app.state.provider
        hostname = "localhost"

        bucket_name, key = _parse_path(path, request.headers.get("host", ""), hostname)

        if not bucket_name:
            return Response(status_code=400)

        try:
            if not key:
                # Delete bucket
                # For Drime provider, use force=True for fast recursive deletion
                # Check if delete_bucket accepts force parameter
                import inspect

                sig = inspect.signature(provider.delete_bucket)
                if "force" in sig.parameters:
                    provider.delete_bucket(bucket_name, force=True)  # type: ignore[call-arg]
                else:
                    provider.delete_bucket(bucket_name)
                return Response(status_code=204)

            # Delete object
            provider.delete_object(bucket_name, key)
            return Response(status_code=204)

        except BucketNotEmpty as e:
            xml = xml_templates.format_error_xml(e.code, e.message)
            return Response(
                content=xml, media_type=XML_CONTENT_TYPE, status_code=e.status_code
            )
        except S3Error as e:
            xml = xml_templates.format_error_xml(e.code, e.message)
            return Response(
                content=xml, media_type=XML_CONTENT_TYPE, status_code=e.status_code
            )
        except Exception as e:
            logger.exception("Error in DELETE handler")
            xml = xml_templates.format_error_xml("InternalError", str(e))
            return Response(content=xml, media_type=XML_CONTENT_TYPE, status_code=500)

    @app.post("/{path:path}")
    async def post_handler(request: Request, path: str) -> Response:
        """Handle POST requests."""
        await _verify_auth(request)
        provider: StorageProvider = request.app.state.provider
        hostname = "localhost"

        bucket_name, key = _parse_path(path, request.headers.get("host", ""), hostname)

        query_params = dict(request.query_params)

        if "delete" in query_params:
            # Multi-delete
            try:
                body = await request.body()
                root = ET.fromstring(body)

                keys = []
                for key_elem in root.findall(".//{*}Key"):
                    if key_elem is not None and key_elem.text is not None:
                        keys.append(key_elem.text)

                result = provider.delete_objects(bucket_name or "", keys)

                xml = xml_templates.format_delete_objects_xml(
                    deleted=result["deleted"],
                    errors=result["errors"],
                )

                return Response(
                    content=xml, media_type=XML_CONTENT_TYPE, status_code=200
                )

            except S3Error as e:
                xml = xml_templates.format_error_xml(e.code, e.message)
                return Response(
                    content=xml, media_type=XML_CONTENT_TYPE, status_code=e.status_code
                )
            except Exception as e:
                logger.exception("Error in multi-delete")
                xml = xml_templates.format_error_xml("InternalError", str(e))
                return Response(
                    content=xml, media_type=XML_CONTENT_TYPE, status_code=500
                )

        return Response(status_code=400)
