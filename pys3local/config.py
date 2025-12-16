"""Backend configuration management using vaultconfig.

This module provides configuration management for pys3local backend configurations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from vaultconfig import (  # type: ignore[import-not-found]
    ConfigManager,
    create_obscurer_from_hex,
)

# Backend types specific to pys3local
BackendType = Literal["local", "drime"]

# Configuration paths
CONFIG_DIR = Path.home() / ".config" / "pys3local"
BACKENDS_FILE = CONFIG_DIR / "backends.toml"

# Custom obscurer for pys3local using a random cipher key
# Generated with: secrets.token_bytes(32).hex()
_PYS3LOCAL_CIPHER_KEY = (
    "1f45e72a93b84d6fc08a29de67f3b2a8e94c5d6f0a1b2c3d4e5f6a7b8c9d0e1f"
)
_PYS3LOCAL_OBSCURER = create_obscurer_from_hex(_PYS3LOCAL_CIPHER_KEY)


class BackendConfig:
    """Adapter for vaultconfig ConfigEntry."""

    def __init__(self, name: str, backend_type: BackendType, config: dict[str, Any]):
        """Initialize backend config.

        Args:
            name: Backend name
            backend_type: Backend type
            config: Configuration dict
        """
        self.name = name
        self.backend_type = backend_type
        self._config = config

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value.

        Args:
            key: Configuration key
            default: Default value

        Returns:
            Configuration value (with passwords revealed if obscured)
        """
        value = self._config.get(key, default)

        # Reveal obscured passwords
        if isinstance(value, str) and key in (
            "password",
            "api_key",
            "secret_access_key",
        ):
            try:
                return _PYS3LOCAL_OBSCURER.reveal(value)
            except ValueError:
                return value

        return value

    def get_all(self) -> dict[str, Any]:
        """Get all config values with passwords revealed.

        Returns:
            Dictionary of all configuration values
        """
        result = {}
        for key, value in self._config.items():
            if isinstance(value, str) and key in (
                "password",
                "api_key",
                "secret_access_key",
            ):
                try:
                    result[key] = _PYS3LOCAL_OBSCURER.reveal(value)
                except ValueError:
                    result[key] = value
            else:
                result[key] = value
        return result


class Pys3localConfigManager:
    """Configuration manager for pys3local backends."""

    def __init__(self, config_file: Path = BACKENDS_FILE):
        """Initialize config manager.

        Args:
            config_file: Path to config file
        """
        self.config_file = config_file
        self._config_dir = config_file.parent

        # Use vaultconfig ConfigManager
        self._manager = ConfigManager(
            config_dir=self._config_dir,
            format="toml",
            password=None,
            obscurer=_PYS3LOCAL_OBSCURER,
        )

    def list_backends(self) -> list[str]:
        """List all backend names.

        Returns:
            List of backend names
        """
        result: list[str] = self._manager.list_configs()
        return result

    def get_backend(self, name: str) -> BackendConfig | None:
        """Get backend configuration.

        Args:
            name: Backend name

        Returns:
            BackendConfig or None if not found
        """
        config_entry = self._manager.get_config(name)
        if not config_entry:
            return None

        # Extract backend type and config
        data = config_entry.get_all(reveal_secrets=False)
        backend_type = data.pop("type", "local")

        return BackendConfig(name, backend_type, data)

    def has_backend(self, name: str) -> bool:
        """Check if backend exists.

        Args:
            name: Backend name

        Returns:
            True if backend exists
        """
        result: bool = self._manager.has_config(name)
        return result

    def add_backend(
        self,
        name: str,
        backend_type: BackendType,
        config: dict[str, Any],
        obscure_passwords: bool = True,
    ) -> None:
        """Add or update backend.

        Args:
            name: Backend name
            backend_type: Backend type
            config: Configuration dict
            obscure_passwords: Whether to obscure passwords
        """
        # Add type to config
        full_config = {"type": backend_type, **config}

        # Manually obscure passwords
        if obscure_passwords:
            full_config = full_config.copy()
            for key in ("password", "api_key", "secret_access_key"):
                if key in full_config and isinstance(full_config[key], str):
                    if not _PYS3LOCAL_OBSCURER.is_obscured(full_config[key]):
                        full_config[key] = _PYS3LOCAL_OBSCURER.obscure(full_config[key])

        self._manager.add_config(name, full_config, obscure_passwords=False)

    def remove_backend(self, name: str) -> bool:
        """Remove backend.

        Args:
            name: Backend name

        Returns:
            True if removed
        """
        result: bool = self._manager.remove_config(name)
        return result

    def get_backend_names_by_type(self, backend_type: BackendType) -> list[str]:
        """Get backend names by type.

        Args:
            backend_type: Backend type to filter

        Returns:
            List of backend names
        """
        result = []
        for name in self.list_backends():
            backend = self.get_backend(name)
            if backend and backend.backend_type == backend_type:
                result.append(name)
        return result


# Global config manager instance
_config_manager: Pys3localConfigManager | None = None


def get_config_manager() -> Pys3localConfigManager:
    """Get global config manager instance.

    Returns:
        Pys3localConfigManager instance
    """
    global _config_manager
    if _config_manager is None:
        _config_manager = Pys3localConfigManager()
    return _config_manager
