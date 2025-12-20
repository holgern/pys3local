"""AWS authentication handlers for S3 API."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import urllib.parse
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def sign(key: bytes, msg: str) -> bytes:
    """Sign a message with a key using HMAC-SHA256.

    Args:
        key: Signing key
        msg: Message to sign

    Returns:
        Signature bytes
    """
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def get_signature_key(key: str, date_stamp: str, region: str, service: str) -> bytes:
    """Derive AWS signing key from secret key.

    Args:
        key: AWS secret access key
        date_stamp: Date stamp (YYYYMMDD)
        region: AWS region
        service: AWS service name

    Returns:
        Signing key bytes
    """
    k_date = sign(("AWS4" + key).encode("utf-8"), date_stamp)
    k_region = sign(k_date, region)
    k_service = sign(k_region, service)
    k_signing = sign(k_service, "aws4_request")
    return k_signing


def verify_signature_v2(
    access_key: str,
    secret_key: str,
    signature: str,
    string_to_sign: str,
) -> bool:
    """Verify AWS Signature Version 2.

    Args:
        access_key: AWS access key ID
        secret_key: AWS secret access key
        signature: Provided signature
        string_to_sign: String that was signed

    Returns:
        True if signature is valid
    """
    calculated = base64.b64encode(
        hmac.new(
            secret_key.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("utf-8")

    return hmac.compare_digest(calculated, signature)


def verify_signature_v4(
    access_key: str,
    secret_key: str,
    region: str,
    request_method: str,
    request_path: str,
    query_params: dict[str, str],
    headers: dict[str, str],
    payload_hash: str,
    authorization_header: str,
) -> bool:
    """Verify AWS Signature Version 4 header authentication.

    Args:
        access_key: AWS access key ID
        secret_key: AWS secret access key
        region: AWS region
        request_method: HTTP method
        request_path: Request path
        query_params: Query parameters
        headers: Request headers (lowercase keys)
        payload_hash: SHA256 hash of request payload
        authorization_header: Authorization header value

    Returns:
        True if signature is valid
    """
    try:
        # Parse authorization header
        if not authorization_header.startswith("AWS4-HMAC-SHA256 "):
            logger.debug(
                "SigV4: Authorization header doesn't start with AWS4-HMAC-SHA256"
            )
            return False

        logger.debug(f"SigV4: Full authorization header: {authorization_header}")

        auth_parts = {}
        # Split by ", " but be careful with spaces
        parts_str = authorization_header[17:]  # Remove "AWS4-HMAC-SHA256 "
        logger.debug(f"SigV4: Parsing parts from: {parts_str}")

        # Try different splitting strategies
        # Format can be: "Credential=xxx, SignedHeaders=yyy, Signature=zzz"
        # Or with spaces: "Credential = xxx, SignedHeaders = yyy, Signature = zzz"
        for part in parts_str.split(","):
            part = part.strip()  # Remove leading/trailing spaces
            if "=" in part:
                key, value = part.split("=", 1)
                key = key.strip()
                value = value.strip()
                auth_parts[key] = value
                logger.debug(f"SigV4: Found auth part: {key}={value[:50]}...")

        credential = auth_parts.get("Credential")
        signature = auth_parts.get("Signature")
        signed_headers_str = auth_parts.get("SignedHeaders", "")

        if not all([credential, signature, signed_headers_str]):
            logger.debug(
                f"SigV4: Missing auth parts - Credential: {bool(credential)}, "
                f"Signature: {bool(signature)}, "
                f"SignedHeaders: {bool(signed_headers_str)}"
            )
            return False

        # Type narrowing - all values are now non-None
        assert credential is not None
        assert signature is not None
        assert signed_headers_str is not None

        # Parse credential
        cred_parts = credential.split("/")
        if len(cred_parts) != 5:
            logger.debug(f"SigV4: Invalid credential format: {credential}")
            return False

        cred_access_key, datestamp, cred_region, service, aws_request = cred_parts

        # Verify access key
        if cred_access_key != access_key:
            logger.debug(
                f"SigV4: Access key mismatch: {cred_access_key} != {access_key}"
            )
            return False

        # Get required headers
        amz_date = headers.get("x-amz-date")
        if not amz_date:
            logger.debug("SigV4: Missing x-amz-date header")
            return False

        # Create canonical request
        canonical_uri = urllib.parse.quote(request_path, safe="/~")

        # Sort and encode query parameters
        canonical_querystring = "&".join(
            f"{urllib.parse.quote(k, safe='~')}={urllib.parse.quote(v, safe='~')}"
            for k, v in sorted(query_params.items())
        )

        # Create canonical headers
        signed_headers = sorted(signed_headers_str.split(";"))
        logger.debug(f"SigV4: Signed headers list: {signed_headers}")
        logger.debug(f"SigV4: Available headers: {list(headers.keys())}")

        canonical_headers = "".join(
            f"{header}:{headers.get(header, '').strip()}\n" for header in signed_headers
        )

        # Debug: show which headers are missing
        for header in signed_headers:
            if header not in headers:
                logger.warning(
                    f"SigV4: Signed header '{header}' not found in request headers!"
                )
            else:
                logger.debug(f"SigV4: Header '{header}' = '{headers[header][:50]}...'")

        # Build canonical request
        canonical_request = "\n".join(
            [
                request_method,
                canonical_uri,
                canonical_querystring,
                canonical_headers,
                signed_headers_str,
                payload_hash,
            ]
        )

        logger.debug(f"SigV4 canonical request:\n{canonical_request}")

        # Create string to sign
        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{datestamp}/{cred_region}/{service}/aws4_request"
        canonical_request_hash = hashlib.sha256(
            canonical_request.encode("utf-8")
        ).hexdigest()
        string_to_sign = "\n".join(
            [
                algorithm,
                amz_date,
                credential_scope,
                canonical_request_hash,
            ]
        )

        logger.debug(f"SigV4 string to sign:\n{string_to_sign}")

        # Calculate signature
        signing_key = get_signature_key(secret_key, datestamp, cred_region, service)
        calculated_signature = hmac.new(
            signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        logger.debug(f"SigV4 calculated signature: {calculated_signature}")
        logger.debug(f"SigV4 provided signature: {signature}")

        # Compare signatures
        is_valid = hmac.compare_digest(calculated_signature, signature)
        if not is_valid:
            logger.debug("SigV4: Signature mismatch")
        return is_valid

    except Exception as e:
        logger.error(f"Error verifying SigV4: {e}", exc_info=True)
        return False


def verify_presigned_url_v4(
    access_key: str,
    secret_key: str,
    region: str,
    request_method: str,
    request_path: str,
    query_params: dict[str, str],
) -> bool:
    """Verify AWS Signature Version 4 presigned URL.

    Args:
        access_key: AWS access key ID
        secret_key: AWS secret access key
        region: AWS region
        request_method: HTTP method
        request_path: Request path
        query_params: Query parameters (including X-Amz-* params)

    Returns:
        True if signature is valid
    """
    try:
        # Check for required parameters
        algorithm = query_params.get("X-Amz-Algorithm")
        credential = query_params.get("X-Amz-Credential")
        date_str = query_params.get("X-Amz-Date")
        expires_str = query_params.get("X-Amz-Expires")
        signed_headers_str = query_params.get("X-Amz-SignedHeaders", "")
        signature = query_params.get("X-Amz-Signature")

        if not all([algorithm, credential, date_str, expires_str, signature]):
            return False

        # Type narrowing - all values are now non-None
        assert credential is not None
        assert date_str is not None
        assert expires_str is not None
        assert signature is not None

        # Check algorithm
        if algorithm != "AWS4-HMAC-SHA256":
            return False

        # Check expiration
        try:
            request_time = datetime.strptime(date_str, "%Y%m%dT%H%M%SZ")
            expires = int(expires_str)
            expiration_time = request_time + timedelta(seconds=expires)
            if datetime.utcnow() > expiration_time:
                logger.warning("Presigned URL has expired")
                return False
        except (ValueError, TypeError) as e:
            logger.error(f"Error parsing expiration: {e}")
            return False

        # Parse credential
        cred_parts = credential.split("/")
        if len(cred_parts) != 5:
            return False

        cred_access_key, datestamp, cred_region, service, aws_request = cred_parts

        # Verify access key
        if cred_access_key != access_key:
            return False

        # Build canonical request (presigned URLs use UNSIGNED-PAYLOAD)
        canonical_uri = urllib.parse.quote(request_path, safe="/~")

        # Build canonical query string (exclude X-Amz-Signature)
        canonical_params = {
            k: v for k, v in query_params.items() if k != "X-Amz-Signature"
        }
        canonical_querystring = "&".join(
            f"{urllib.parse.quote(k, safe='~')}={urllib.parse.quote(v, safe='~')}"
            for k, v in sorted(canonical_params.items())
        )

        # For presigned URLs, use signed headers from query parameter
        signed_headers = (
            sorted(signed_headers_str.split(";")) if signed_headers_str else []
        )
        canonical_headers = "".join(f"{header}:\n" for header in signed_headers)

        payload_hash = "UNSIGNED-PAYLOAD"

        canonical_request = "\n".join(
            [
                request_method,
                canonical_uri,
                canonical_querystring,
                canonical_headers,
                signed_headers_str,
                payload_hash,
            ]
        )

        # Create string to sign
        algorithm_str = "AWS4-HMAC-SHA256"
        credential_scope = f"{datestamp}/{cred_region}/{service}/aws4_request"
        string_to_sign = "\n".join(
            [
                algorithm_str,
                date_str,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )

        # Calculate signature
        signing_key = get_signature_key(secret_key, datestamp, cred_region, service)
        calculated_signature = hmac.new(
            signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        # Compare signatures
        return hmac.compare_digest(calculated_signature, signature)

    except Exception as e:
        logger.error(f"Error verifying presigned URL: {e}")
        return False
