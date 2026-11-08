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

# Nextcloud's admin settings form (declarative settings, registered by the ExApp)
# stores every field as its own ExApp appconfig key. The ids below are therefore
# also the config keys, so the NC admin form and the ExApp's own admin API share
# one store. `mistral_ocr_api_key` is handled separately (sensitive=True).
SETTINGS_FIELDS: dict[str, str] = {
    "mistral_ocr_base_url": "base_url",
    "mistral_ocr_model": "model",
    "mistral_ocr_max_file_size_mb": "max_file_size_mb",
    "mistral_ocr_max_pages": "max_pages",
    "mistral_ocr_default_output_mode": "default_output_mode",
    "mistral_ocr_include_image_base64": "include_image_base64",
    "mistral_ocr_timeout_seconds": "timeout_seconds",
    "mistral_ocr_notify_on_success": "notify_on_success",
}


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


def _coerce(value: typing.Any, default: typing.Any) -> typing.Any:
    """appconfig values are strings; convert them to the default's type."""
    if isinstance(default, bool):
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int) and not isinstance(default, bool):
        return int(float(value))
    if isinstance(default, float):
        return float(value)
    if isinstance(default, list) and isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else default
        except ValueError:
            return default
    return value


def _serialize(value: typing.Any) -> str:
    """Inverse of _coerce: appconfig values are stored as strings."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


class AppApiSettingsStore:
    """Persists settings through the AppAPI app-config endpoints of a Nextcloud connection.

    The API key is written with ``sensitive=True`` (encrypted at rest by AppAPI);
    non-sensitive settings are stored as one JSON blob.
    """

    def __init__(self, nc: typing.Any):
        self._nc = nc

    async def load_settings(self) -> AppSettings:
        data: dict[str, typing.Any] = {}
        # Legacy: settings saved as one JSON blob by older ExApp versions.
        raw = await self._nc.appconfig_ex.get_value(KEY_SETTINGS)
        if raw:
            try:
                data.update(json.loads(raw))
            except (ValueError, TypeError) as exc:
                logger.warning("Stored settings blob is unreadable, ignoring it: %s", exc)
        # Current: one appconfig key per field (written by the NC admin form and by
        # this app's own admin API alike).
        defaults = AppSettings()
        for key, attr in SETTINGS_FIELDS.items():
            value = await self._nc.appconfig_ex.get_value(key)
            if value is None or value == "":
                continue
            data[attr] = _coerce(value, getattr(defaults, attr))
        try:
            return AppSettings.from_dict(data)
        except (ValueError, TypeError) as exc:
            logger.warning("Stored settings are unreadable, falling back to defaults: %s", exc)
            return AppSettings()

    async def save_settings(self, settings: AppSettings) -> None:
        public = settings.to_public_dict()
        for key, attr in SETTINGS_FIELDS.items():
            await self._nc.appconfig_ex.set_value(key, _serialize(public[attr]), sensitive=False)

    async def get_api_key(self) -> str:
        return await self._nc.appconfig_ex.get_value(KEY_API_KEY) or ""

    async def set_api_key(self, api_key: str) -> None:
        await self._nc.appconfig_ex.set_value(KEY_API_KEY, api_key, sensitive=True)
