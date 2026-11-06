"""Admin settings for the app.

Storage: values are persisted through the AppAPI app-config API
(``nc.appconfig_ex``); the Mistral API key is stored with ``sensitive=True``
so AppAPI encrypts it at rest and never mirrors it into readable config.
A process-local ``MemorySettingsStore`` is used in tests.
"""

from __future__ import annotations

import json
import logging
import typing

from pydantic import BaseModel, Field, field_validator

from .errors import InvalidBaseUrlError
from .mistral_client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    SUPPORTED_MIME_TYPES,
    validate_base_url,
)

logger = logging.getLogger("mistral_ocr.config")

OUTPUT_MODE_SIDECAR = "sidecar"
OUTPUT_MODE_TASK_RESULT = "task_result"
OUTPUT_MODE_DESCRIPTION = "description"
OUTPUT_MODES = (OUTPUT_MODE_SIDECAR, OUTPUT_MODE_TASK_RESULT, OUTPUT_MODE_DESCRIPTION)

CONFIG_PREFIX = "mistral_ocr_"
KEY_API_KEY = f"{CONFIG_PREFIX}api_key"
KEY_SETTINGS = f"{CONFIG_PREFIX}settings"

DEFAULT_ALLOWED_MIME_TYPES = sorted(SUPPORTED_MIME_TYPES)
DEFAULT_MAX_FILE_SIZE_MB = 50
DEFAULT_MAX_PAGES = 100


class AppSettings(BaseModel):
    """User-facing admin settings (the API key itself is stored separately, encrypted)."""

    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    max_file_size_mb: int = DEFAULT_MAX_FILE_SIZE_MB
    max_pages: int = DEFAULT_MAX_PAGES
    allowed_mime_types: list[str] = Field(default_factory=lambda: list(DEFAULT_ALLOWED_MIME_TYPES))
    default_output_mode: str = OUTPUT_MODE_SIDECAR
    include_image_base64: bool = False
    timeout_seconds: float = DEFAULT_TIMEOUT
    notify_on_success: bool = False

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str) -> str:
        try:
            return validate_base_url(value)
        except InvalidBaseUrlError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("default_output_mode")
    @classmethod
    def _check_output_mode(cls, value: str) -> str:
        if value not in OUTPUT_MODES:
            raise ValueError(f"Unknown output mode: {value}")
        return value

    @field_validator("max_file_size_mb", "max_pages")
    @classmethod
    def _check_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Value must be >= 1")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def _check_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Timeout must be > 0")
        return value

    def is_mime_allowed(self, mime_type: str) -> bool:
        return mime_type in self.allowed_mime_types

    def to_public_dict(self) -> dict[str, typing.Any]:
        """Serializable representation safe to return via API (never contains the key)."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, typing.Any]) -> "AppSettings":
        return cls.model_validate(data)


class SettingsStore(typing.Protocol):
    def load_settings(self) -> AppSettings: ...
    def save_settings(self, settings: AppSettings) -> None: ...
    def get_api_key(self) -> str: ...
    def set_api_key(self, api_key: str) -> None: ...


class MemorySettingsStore:
    """In-memory store used by unit tests."""

    def __init__(self, api_key: str = "", settings: AppSettings | None = None):
        self._api_key = api_key
        self._settings = settings or AppSettings()

    def load_settings(self) -> AppSettings:
        return self._settings.model_copy(deep=True)

    def save_settings(self, settings: AppSettings) -> None:
        self._settings = settings.model_copy(deep=True)

    def get_api_key(self) -> str:
        return self._api_key

    def set_api_key(self, api_key: str) -> None:
        self._api_key = api_key


class AppApiSettingsStore:
    """Persists settings through the AppAPI app-config endpoints of a Nextcloud connection.

    The API key is written with ``sensitive=True`` (encrypted at rest by AppAPI);
    non-sensitive settings are stored as one JSON blob.
    """

    def __init__(self, nc: typing.Any):
        self._nc = nc

    def load_settings(self) -> AppSettings:
        raw = self._nc.appconfig_ex.get_value(KEY_SETTINGS)
        if not raw:
            return AppSettings()
        try:
            return AppSettings.from_dict(json.loads(raw))
        except (ValueError, TypeError) as exc:
            logger.warning("Stored settings are unreadable, falling back to defaults: %s", exc)
            return AppSettings()

    def save_settings(self, settings: AppSettings) -> None:
        self._nc.appconfig_ex.set_value(KEY_SETTINGS, json.dumps(settings.to_public_dict()), sensitive=False)

    def get_api_key(self) -> str:
        return self._nc.appconfig_ex.get_value(KEY_API_KEY) or ""

    def set_api_key(self, api_key: str) -> None:
        self._nc.appconfig_ex.set_value(KEY_API_KEY, api_key, sensitive=True)
