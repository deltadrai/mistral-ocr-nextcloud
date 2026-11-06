"""Async client for the Mistral OCR API (`POST {base_url}/v1/ocr`).

Robustness: configurable timeout, retries with exponential backoff for
429/5xx (max 3 retries), typed errors mapped to user-facing messages.
No document content or API key is ever logged.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import typing

import httpx

from .errors import (
    ApiResponseError,
    ApiServerError,
    ApiTimeoutError,
    InvalidApiKeyError,
    InvalidBaseUrlError,
    QuotaExceededError,
    TooManyPagesError,
    UnsupportedFileError,
)

if typing.TYPE_CHECKING:
    from .errors import MistralOcrError

logger = logging.getLogger("mistral_ocr.client")

DEFAULT_BASE_URL = "https://api.mistral.ai"
EU_BASE_URL = "https://api.eu.mistral.ai"
DEFAULT_MODEL = "mistral-ocr-4-1"
DEFAULT_TIMEOUT = 120.0
MAX_RETRIES = 3
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}

SUPPORTED_IMAGE_MIME_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/tiff",
        "image/webp",
        "image/bmp",
        "image/heic",
        "image/heif",
    }
)
SUPPORTED_DOCUMENT_MIME_TYPES = frozenset({"application/pdf"})
SUPPORTED_MIME_TYPES = SUPPORTED_IMAGE_MIME_TYPES | SUPPORTED_DOCUMENT_MIME_TYPES


def validate_base_url(base_url: str) -> str:
    """Ensure the base URL is a valid HTTPS URL; return it normalized (no trailing slash)."""
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url:
        raise InvalidBaseUrlError("Base URL is empty")
    if not base_url.startswith("https://"):
        raise InvalidBaseUrlError(f"Refusing non-HTTPS base URL: {base_url!r}")
    if "://" not in base_url or "/" in base_url[len("https://") :]:
        raise InvalidBaseUrlError(f"Malformed base URL: {base_url!r}")
    return base_url


def encode_data_uri(mime_type: str, content: bytes) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(content).decode('ascii')}"


def build_document_payload(mime_type: str, content: bytes) -> dict[str, str]:
    """Build the `document` object of the OCR request from raw file bytes.

    Nextcloud files are not publicly reachable, so the bytes are sent inline
    as a base64 data URI instead of a public `document_url`/`image_url`.
    """
    data_uri = encode_data_uri(mime_type, content)
    if mime_type in SUPPORTED_IMAGE_MIME_TYPES:
        return {"type": "image_url", "image_url": data_uri}
    if mime_type in SUPPORTED_DOCUMENT_MIME_TYPES:
        return {"type": "document_url", "document_url": data_uri}
    raise UnsupportedFileError(f"MIME type not supported by client: {mime_type}")


class PageResult(typing.NamedTuple):
    index: int
    markdown: str
    images: list[str]


class OcrResult(typing.NamedTuple):
    model: str
    pages: list[PageResult]

    @property
    def markdown(self) -> str:
        """Full Markdown output, one section per page."""
        parts = []
        for page in self.pages:
            header = f"## Page {page.index + 1}\n\n" if len(self.pages) > 1 else ""
            parts.append(f"{header}{page.markdown}".rstrip())
        return "\n\n---\n\n".join(parts) + "\n"


class MistralOcrClient:
    """Thin async wrapper around the Mistral OCR endpoint."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        backoff_base: float = 1.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not api_key:
            raise InvalidApiKeyError("API key is empty")
        self._api_key = api_key
        self._base_url = validate_base_url(base_url)
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._transport = transport

    @property
    def base_url(self) -> str:
        return self._base_url

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._timeout),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            transport=self._transport,
        )

    async def ocr(
        self,
        document: dict[str, str],
        model: str = DEFAULT_MODEL,
        pages: list[int] | None = None,
        include_image_base64: bool = False,
    ) -> OcrResult:
        """Run OCR on a document payload built by :func:`build_document_payload`."""
        body: dict[str, typing.Any] = {
            "model": model,
            "document": document,
            "include_image_base64": include_image_base64,
        }
        if pages:
            body["pages"] = pages
        response = await self._request_with_retries("POST", "/v1/ocr", json=body)
        return self._parse_response(response.json(), model)

    async def ocr_file(
        self,
        mime_type: str,
        content: bytes,
        model: str = DEFAULT_MODEL,
        pages: list[int] | None = None,
        include_image_base64: bool = False,
    ) -> OcrResult:
        return await self.ocr(
            build_document_payload(mime_type, content),
            model=model,
            pages=pages,
            include_image_base64=include_image_base64,
        )

    async def list_models(self) -> list[str]:
        """Validate the API key and return available model ids (used by the setup check)."""
        response = await self._request_with_retries("GET", "/v1/models")
        data = response.json()
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]

    async def _request_with_retries(self, method: str, path: str, **kwargs: typing.Any) -> httpx.Response:
        last_exc: MistralOcrError | None = None
        async with self._client() as client:
            for attempt in range(self._max_retries + 1):
                try:
                    response = await client.request(method, path, **kwargs)
                except httpx.TimeoutException as exc:
                    last_exc = ApiTimeoutError(f"Timeout calling Mistral API: {exc.__class__.__name__}")
                    if attempt < self._max_retries:
                        await self._sleep(attempt)
                        continue
                    raise last_exc from exc
                if response.status_code in RETRY_STATUS_CODES:
                    if attempt < self._max_retries:
                        await self._sleep(attempt)
                        continue
                    raise self._map_error(response, f"Giving up after {self._max_retries + 1} attempts")
                if response.status_code >= 400:
                    raise self._map_error(response)
                return response
        raise last_exc or ApiServerError("Request failed without a response")

    async def _sleep(self, attempt: int) -> None:
        await asyncio.sleep(self._backoff_base * (2**attempt))

    def _map_error(self, response: httpx.Response, suffix: str = "") -> MistralOcrError:
        status = response.status_code
        detail = ""
        try:
            detail = str(response.json().get("message", ""))[:200]
        except Exception:  # noqa: BLE001 - never leak the raw body into logs
            detail = ""
        tech_msg = f"Mistral API error {status} {detail}".strip() + (f" ({suffix})" if suffix else "")
        if status in (401, 403):
            return InvalidApiKeyError(tech_msg)
        if status == 413:
            return TooManyPagesError(tech_msg)
        if status == 422:
            return UnsupportedFileError(tech_msg)
        if status == 429:
            return QuotaExceededError(tech_msg)
        if status >= 500:
            return ApiServerError(tech_msg)
        return ApiResponseError(tech_msg)

    @staticmethod
    def _parse_response(data: dict[str, typing.Any], model: str) -> OcrResult:
        pages_raw = data.get("pages")
        if not isinstance(pages_raw, list) or not pages_raw:
            raise ApiResponseError("Mistral API response contains no pages")
        pages: list[PageResult] = []
        for i, page in enumerate(pages_raw):
            markdown = page.get("markdown")
            if not isinstance(markdown, str):
                raise ApiResponseError(f"Page {i} has no markdown field")
            images = [img.get("image_base64", "") for img in page.get("images", []) if isinstance(img, dict)]
            pages.append(PageResult(index=i, markdown=markdown, images=images))
        return OcrResult(model=data.get("model", model), pages=pages)
