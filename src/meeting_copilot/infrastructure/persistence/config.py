"""ConfigStore — reads/writes settings to ``~/.meeting-copilot/config.json``.

The API key is stored separately in the OS keyring for security.
Config writes are atomic (write to ``.tmp``, then rename).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

import keyring

from meeting_copilot.domain.settings import Settings

logger = logging.getLogger(__name__)

_SERVICE_NAME = "meeting-copilot"
_KEYRING_USERNAME = "groq_api_key"

# Fields that are NOT persisted in JSON (stored in keyring instead)
_EXCLUDED_FROM_JSON: frozenset[str] = frozenset()


def _config_dir() -> Path:
    """Return the config directory, creating it if needed."""
    config_dir = Path.home() / ".meeting-copilot"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def _config_path() -> Path:
    return _config_dir() / "config.json"


class ConfigStore:
    """Reads and writes ``Settings`` + API key."""

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self) -> Settings:
        """Load settings from disk.  Missing keys use defaults."""
        path = _config_path()
        data: dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("Corrupt config.json — using defaults")

        # Filter to only known Settings fields
        valid_keys = {f.name for f in fields(Settings)}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        settings = Settings(**filtered)

        # Auto-detect WASAPI loopback on Windows if not set
        if settings.loopback_device_id is None:
            from meeting_copilot.infrastructure.audio.devices import find_wasapi_loopback  # noqa: PLC0415
            loopback = find_wasapi_loopback()
            if loopback:
                logger.info("Auto-detected loopback device: %s (ID: %d)", loopback['name'], loopback['id'])
                settings = Settings(**{**asdict(settings), 'loopback_device_id': loopback['id']})

        return settings

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(self, settings: Settings) -> None:
        """Persist *settings* to JSON atomically."""
        path = _config_path()
        tmp_path = path.with_suffix(".tmp")

        data = asdict(settings)
        # Remove excluded keys
        for key in _EXCLUDED_FROM_JSON:
            data.pop(key, None)

        tmp_path.write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8"
        )
        # Atomic rename (Windows may need replace)
        if os.name == "nt":
            tmp_path.replace(path)
        else:
            os.rename(tmp_path, path)

        logger.info("Settings saved to %s", path)

    # ------------------------------------------------------------------
    # API Key (keyring)
    # ------------------------------------------------------------------

    def get_api_key(self) -> str | None:
        """Retrieve the Groq API key from the OS keyring."""
        try:
            return keyring.get_password(_SERVICE_NAME, _KEYRING_USERNAME)
        except Exception:
            logger.warning("Failed to read API key from keyring")
            return None

    def set_api_key(self, api_key: str) -> None:
        """Store the Groq API key in the OS keyring."""
        try:
            keyring.set_password(_SERVICE_NAME, _KEYRING_USERNAME, api_key)
            logger.info("API key saved to keyring")
        except Exception:
            logger.exception("Failed to save API key to keyring")
            raise

    def delete_api_key(self) -> None:
        """Remove the Groq API key from the OS keyring."""
        try:
            keyring.delete_password(_SERVICE_NAME, _KEYRING_USERNAME)
        except keyring.errors.PasswordDeleteError:
            pass  # Already absent
