"""pys3local - Local S3 server for backup software with pluggable storage backends.

This package provides a Python implementation of an S3-compatible API with support for
multiple storage backends, including local filesystem and Drime Cloud storage.
"""

from __future__ import annotations

__all__ = ["StorageProvider"]

try:
    from pys3local._version import version as __version__
except ImportError:
    __version__ = "unknown"
