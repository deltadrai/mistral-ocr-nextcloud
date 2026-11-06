import pytest
from pydantic import ValidationError

from mistral_ocr.config import (
    OUTPUT_MODE_SIDECAR,
    AppSettings,
    MemorySettingsStore,
)


def test_defaults():
    s = AppSettings()
    assert s.model == "mistral-ocr-4-1"
    assert s.base_url == "https://api.mistral.ai"
    assert s.max_file_size_mb == 50
    assert s.max_pages == 100
    assert s.default_output_mode == OUTPUT_MODE_SIDECAR
    assert s.include_image_base64 is False
    assert "application/pdf" in s.allowed_mime_types
    assert "image/png" in s.allowed_mime_types


def test_https_only_base_url():
    with pytest.raises(ValidationError):
        AppSettings(base_url="http://api.mistral.ai")
    s = AppSettings(base_url="https://api.eu.mistral.ai/")
    assert s.base_url == "https://api.eu.mistral.ai"


def test_invalid_output_mode_rejected():
    with pytest.raises(ValidationError):
        AppSettings(default_output_mode="nope")


def test_limits_must_be_positive():
    with pytest.raises(ValidationError):
        AppSettings(max_pages=0)
    with pytest.raises(ValidationError):
        AppSettings(max_file_size_mb=-1)


def test_mime_allowlist():
    s = AppSettings(allowed_mime_types=["application/pdf"])
    assert s.is_mime_allowed("application/pdf")
    assert not s.is_mime_allowed("image/png")


def test_public_dict_never_contains_api_key():
    s = AppSettings()
    dumped = s.to_public_dict()
    assert "api_key" not in dumped
    assert "apiKey" not in dumped


def test_memory_store_roundtrip():
    store = MemorySettingsStore(api_key="secret")
    assert store.get_api_key() == "secret"
    store.set_api_key("new-secret")
    assert store.get_api_key() == "new-secret"
    store.save_settings(AppSettings(model="mistral-ocr-3"))
    assert store.load_settings().model == "mistral-ocr-3"
