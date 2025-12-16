"""Storage providers for pys3local."""

from __future__ import annotations

from pys3local.providers.local import LocalStorageProvider

__all__ = ["LocalStorageProvider"]

try:
    from pys3local.providers.drime import DrimeStorageProvider

    __all__.append("DrimeStorageProvider")
except ImportError:
    pass
