"""Orchestration of one OCR job: fetch file -> guards -> Mistral API -> outputs.

The Nextcloud side is accessed through a minimal structural interface
(``files`` with ``by_id``/``download``/``upload`` and ``notifications`` with
``create``) so the service is fully unit-testable with fakes.
"""

from __future__ import annotations

import logging
import os
import typing

from .config import OUTPUT_MODE_DESCRIPTION, OUTPUT_MODE_SIDECAR, AppSettings
from .errors import (
    FileNotFoundError_,
    FileTooLargeError,
    MimeTypeNotAllowedError,
    MissingApiKeyError,
    MistralOcrError,
)
from .fingerprints import FingerprintStore, MemoryFingerprintStore
from .jobs import TRIGGER_FLOW, OcrJob
from .mistral_client import MistralOcrClient, OcrResult

logger = logging.getLogger("mistral_ocr.service")

APP_ID = "mistral_ocr"
EVENT_OCR_COMPLETED = f"{APP_ID}:ocr_completed"
EVENT_OCR_FAILED = f"{APP_ID}:ocr_failed"


class OcrOutcome(typing.NamedTuple):
    job: OcrJob
    result: OcrResult | None
    sidecar_path: str | None
    skipped: bool
    error: MistralOcrError | None


class OcrService:
    def __init__(
        self,
        settings_provider: typing.Callable[[], AppSettings],
        api_key_provider: typing.Callable[[], str],
        client_factory: typing.Callable[[AppSettings, str], MistralOcrClient],
        nc: typing.Any,
        fingerprints: FingerprintStore | MemoryFingerprintStore,
    ):
        self._settings_provider = settings_provider
        self._api_key_provider = api_key_provider
        self._client_factory = client_factory
        self._nc = nc
        self._fingerprints = fingerprints

    async def process(self, job: OcrJob) -> OcrOutcome:
        settings = self._settings_provider()
        api_key = self._api_key_provider()
        if not api_key:
            err = MissingApiKeyError()
            await self._notify_failure(job, err)
            return OcrOutcome(job, None, None, False, err)
        try:
            node = await self._nc.files.by_id(job.file_id)
            if node is None:
                raise FileNotFoundError_(f"File id {job.file_id} not found")
            mime_type = getattr(node, "mime_type", None) or getattr(node, "mimetype", "") or ""
            if not mime_type:
                # nc_py_api's files.by_id uses a WebDAV SEARCH whose response often
                # omits d:getcontenttype; fall back to the file name extension.
                import mimetypes

                name = getattr(node, "name", "") or ""
                mime_type = mimetypes.guess_type(name)[0] or ""
            if not settings.is_mime_allowed(mime_type):
                raise MimeTypeNotAllowedError(f"MIME type {mime_type} is not allowed")
            size = int(getattr(node, "size", 0) or 0)
            if size > settings.max_file_size_mb * 1024 * 1024:
                raise FileTooLargeError(f"File size {size} exceeds limit {settings.max_file_size_mb} MB")
            etag = str(getattr(node, "etag", "") or "")
            if job.trigger == TRIGGER_FLOW and not job.force:
                if self._fingerprints.is_processed(job.file_id, etag, settings.model):
                    logger.info("Skipping already-processed file id=%s", job.file_id)
                    return OcrOutcome(job, None, None, True, None)
            content = await self._nc.files.download(node)
            client = self._client_factory(settings, api_key)
            pages = job.pages
            if pages and len(pages) > settings.max_pages:
                from .errors import TooManyPagesError

                raise TooManyPagesError(f"Requested {len(pages)} pages, limit is {settings.max_pages}")
            result = await client.ocr_file(
                mime_type,
                content,
                model=settings.model,
                pages=pages,
                include_image_base64=settings.include_image_base64,
            )
            sidecar_path = None
            output_mode = job.output_mode or settings.default_output_mode
            if output_mode == OUTPUT_MODE_SIDECAR:
                sidecar_path = await self._write_sidecar(node, result)
            elif output_mode == OUTPUT_MODE_DESCRIPTION:
                await self._append_description(node, result)
            self._fingerprints.mark_processed(job.file_id, etag, settings.model)
            if settings.notify_on_success:
                await self._notify_success(job, node, sidecar_path)
            self._emit_event(EVENT_OCR_COMPLETED, job, node)
            return OcrOutcome(job, result, sidecar_path, False, None)
        except MistralOcrError as exc:
            logger.warning("OCR job %s failed: %s", job.id, exc)
            await self._notify_failure(job, exc)
            self._emit_event(EVENT_OCR_FAILED, job, None, exc)
            return OcrOutcome(job, None, None, False, exc)

    async def _write_sidecar(self, node: typing.Any, result: OcrResult) -> str:
        name = getattr(node, "name", "file")
        parent = os.path.dirname(getattr(node, "path", "") or f"/{name}")
        sidecar_name = f"{os.path.splitext(name)[0]}.md"
        target = f"{parent.rstrip('/')}/{sidecar_name}" if parent else f"/{sidecar_name}"
        await self._nc.files.upload(target, result.markdown.encode("utf-8"))
        logger.info("Wrote sidecar %s for file %s", target, getattr(node, "file_id", "?"))
        return target

    async def _append_description(self, node: typing.Any, result: OcrResult) -> None:
        text = result.markdown.strip()
        preview = text[:2000]
        try:
            await self._nc.ocs(
                "PUT",
                f"/ocs/v2.php/apps/files/api/v1/files/{node.file_id}",
                json={"description": preview},
            )
        except Exception as exc:  # noqa: BLE001 - experimental output mode, must not fail the job
            logger.warning("Could not append description to file %s: %s", node.file_id, exc)

    async def _notify_success(self, job: OcrJob, node: typing.Any, sidecar_path: str | None) -> None:
        subject = "Mistral OCR finished"
        message = f"Text was extracted from {getattr(node, 'name', 'file')}"
        if sidecar_path:
            message += f" and saved as {sidecar_path}"
        try:
            await self._nc.set_user(job.user_id)
            await self._nc.notifications.create(subject=subject, message=message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not send success notification: %s", exc)

    async def _notify_failure(self, job: OcrJob, err: MistralOcrError) -> None:
        try:
            await self._nc.set_user(job.user_id)
            await self._nc.notifications.create(
                subject="Mistral OCR failed",
                message=err.user_message,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not send failure notification: %s", exc)

    def _emit_event(
        self,
        event_name: str,
        job: OcrJob,
        node: typing.Any,
        error: MistralOcrError | None = None,
    ) -> None:
        payload = {
            "event": event_name,
            "fileId": job.file_id,
            "trigger": job.trigger,
            "fileName": getattr(node, "name", None) if node else None,
            "error": error.user_message if error else None,
        }
        try:
            self._nc.log(1, f"event {json_dumps_safe(payload)}")
        except Exception:  # noqa: BLE001
            logger.info("event %s", payload)


def json_dumps_safe(payload: dict[str, typing.Any]) -> str:
    import json

    return json.dumps(payload, default=str)
