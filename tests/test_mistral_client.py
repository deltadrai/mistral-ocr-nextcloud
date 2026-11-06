import base64
import json

import httpx
import pytest

from mistral_ocr.errors import (
    ApiServerError,
    ApiTimeoutError,
    InvalidApiKeyError,
    InvalidBaseUrlError,
    QuotaExceededError,
    TooManyPagesError,
    UnsupportedFileError,
)
from mistral_ocr.mistral_client import (
    MistralOcrClient,
    OcrResult,
    build_document_payload,
    encode_data_uri,
    validate_base_url,
)

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

OCR_OK_BODY = {
    "pages": [
        {"index": 0, "markdown": "# Hello", "images": []},
        {"index": 1, "markdown": "World", "images": [{"image_base64": "abc"}]},
    ],
    "model": "mistral-ocr-4-1",
}


def make_client(handler, **kwargs) -> MistralOcrClient:
    transport = httpx.MockTransport(handler)
    kwargs.setdefault("backoff_base", 0)
    return MistralOcrClient(api_key="test-key", transport=transport, **kwargs)


def ok_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/v1/ocr"
    assert request.headers["Authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "mistral-ocr-4-1"
    return httpx.Response(200, json=OCR_OK_BODY)


async def test_ocr_success_parses_pages():
    client = make_client(ok_handler)
    result = await client.ocr_file("image/png", PNG_BYTES)
    assert isinstance(result, OcrResult)
    assert len(result.pages) == 2
    assert result.pages[0].markdown == "# Hello"
    assert result.pages[1].images == ["abc"]
    assert "# Hello" in result.markdown
    assert "## Page 2" in result.markdown


async def test_request_body_uses_data_uri_not_public_url():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=OCR_OK_BODY)

    client = make_client(handler)
    await client.ocr_file("application/pdf", b"%PDF-1.4 fake")
    doc = seen["document"]
    assert doc["type"] == "document_url"
    assert doc["document_url"].startswith("data:application/pdf;base64,")
    assert seen["include_image_base64"] is False


async def test_pages_parameter_forwarded():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=OCR_OK_BODY)

    client = make_client(handler)
    await client.ocr_file("image/png", PNG_BYTES, pages=[1, 3])
    assert seen["pages"] == [1, 3]


async def test_invalid_api_key_maps_to_typed_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthorized"})

    client = make_client(handler)
    with pytest.raises(InvalidApiKeyError) as exc_info:
        await client.ocr_file("image/png", PNG_BYTES)
    assert "key" in exc_info.value.user_message.lower()


async def test_429_retries_then_quota_error():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, json={"message": "rate limited"})

    client = make_client(handler, max_retries=3)
    with pytest.raises(QuotaExceededError):
        await client.ocr_file("image/png", PNG_BYTES)
    assert calls["n"] == 4


async def test_500_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"message": "unavailable"})
        return httpx.Response(200, json=OCR_OK_BODY)

    client = make_client(handler, max_retries=3)
    result = await client.ocr_file("image/png", PNG_BYTES)
    assert calls["n"] == 3
    assert len(result.pages) == 2


async def test_500_exhausts_retries_to_server_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "boom"})

    client = make_client(handler, max_retries=2)
    with pytest.raises(ApiServerError):
        await client.ocr_file("image/png", PNG_BYTES)


async def test_413_maps_to_too_many_pages():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(413, json={"message": "payload too large"})

    client = make_client(handler)
    with pytest.raises(TooManyPagesError):
        await client.ocr_file("application/pdf", b"x" * 10)


async def test_422_maps_to_unsupported_file():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "bad document"})

    client = make_client(handler)
    with pytest.raises(UnsupportedFileError):
        await client.ocr_file("image/png", PNG_BYTES)


async def test_timeout_maps_to_timeout_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    client = make_client(handler, max_retries=1)
    with pytest.raises(ApiTimeoutError):
        await client.ocr_file("image/png", PNG_BYTES)


async def test_malformed_response_raises_api_response_error():
    from mistral_ocr.errors import ApiResponseError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    client = make_client(handler)
    with pytest.raises(ApiResponseError):
        await client.ocr_file("image/png", PNG_BYTES)


async def test_list_models():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "mistral-ocr-4-1"}, {"id": "other"}]})

    client = make_client(handler)
    models = await client.list_models()
    assert models == ["mistral-ocr-4-1", "other"]


def test_validate_base_url_rejects_http():
    with pytest.raises(InvalidBaseUrlError):
        validate_base_url("http://api.mistral.ai")


def test_validate_base_url_rejects_empty():
    with pytest.raises(InvalidBaseUrlError):
        validate_base_url("")


def test_validate_base_url_normalizes_trailing_slash():
    assert validate_base_url("https://api.eu.mistral.ai/") == "https://api.eu.mistral.ai"


def test_encode_data_uri():
    assert encode_data_uri("image/png", b"\x89PNG") == "data:image/png;base64,iVBORw=="


def test_build_document_payload_image():
    payload = build_document_payload("image/jpeg", b"jpeg")
    assert payload["type"] == "image_url"
    assert payload["image_url"].startswith("data:image/jpeg;base64,")


def test_build_document_payload_rejects_unknown_mime():
    from mistral_ocr.errors import UnsupportedFileError as UFE

    with pytest.raises(UFE):
        build_document_payload("text/plain", b"hello")


def test_empty_api_key_rejected():
    with pytest.raises(InvalidApiKeyError):
        MistralOcrClient(api_key="")
