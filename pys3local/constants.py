"""Constants for pys3local."""

from __future__ import annotations

# Server defaults
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 10001
DEFAULT_REGION = "us-east-1"

# Authentication defaults
DEFAULT_ACCESS_KEY = "test"
DEFAULT_SECRET_KEY = "test"

# S3 API constants
MAX_KEYS_DEFAULT = 1000
MAX_KEYS_LIMIT = 1000

# Content types
DEFAULT_CONTENT_TYPE = "application/octet-stream"
XML_CONTENT_TYPE = "application/xml"

# Default bucket (virtual bucket in default mode)
DEFAULT_BUCKET = "default"
