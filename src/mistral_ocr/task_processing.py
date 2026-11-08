"""Task Processing provider for `core:image2text:ocr`.

Registers the provider on enable and runs a background worker that polls
Nextcloud for queued tasks, processes them through the OCR service and
reports the extracted Markdown back via the Task Processing API.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import typing

from nc_py_api.ex_app.providers.task_processing import (
    ShapeDescriptor,
    ShapeType,
    TaskProcessingProvider,
)

from .jobs import TRIGGER_TASK, OcrJob
from .ocr_service import OcrService

logger = logging.getLogger("mistral_ocr.task_processing")

TASK_TYPE_OCR = "core:image2text:ocr"
PROVIDER_ID = "mistral_ocr_image2text_ocr"


def build_provider() -> TaskProcessingProvider:
    return TaskProcessingProvider(
        id=PROVIDER_ID,
        name="Mistral OCR",
        task_type=TASK_TYPE_OCR,
        expected_runtime=120,
        optional_input_shape=[
            ShapeDescriptor(
                name="pages",
                description="Optional 1-based page range to process, e.g. [1, 2, 3]",
                shape_type=ShapeType.LIST_OF_NUMBERS,
            ),
        ],
        optional_output_shape=[],
    )


async def register_provider(nc: typing.Any) -> None:
    await nc.providers.task_processing.register(build_provider())
    logger.info("Registered Task Processing provider %s for %s", PROVIDER_ID, TASK_TYPE_OCR)


async def unregister_provider(nc: typing.Any) -> None:
    with contextlib.suppress(Exception):
        await nc.providers.task_processing.unregister(PROVIDER_ID)


def _extract_file_id(task: dict[str, typing.Any]) -> int | None:
    """Extract the Nextcloud file ID from a task input payload."""
    inp = task.get("input") or {}
    if isinstance(inp, dict):
        for key in ("input", "fileId", "file_id", "id"):
            value = inp.get(key)
            if isinstance(value, list) and value:
                value = value[0]  # core:image2text:ocr sends ListOfFiles under "input"
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
            if isinstance(value, dict):
                fid = value.get("fileId") or value.get("id")
                if isinstance(fid, int):
                    return fid
                if isinstance(fid, str) and fid.isdigit():
                    return int(fid)
    return None


def _extract_pages(task: dict[str, typing.Any]) -> list[int] | None:
    inp = task.get("input") or {}
    if isinstance(inp, dict):
        pages = inp.get("pages")
        if isinstance(pages, list) and all(isinstance(p, int) for p in pages):
            return pages
    return None


class TaskProcessingWorker:
    """Polls Nextcloud for OCR tasks and runs them through the OcrService."""

    def __init__(
        self,
        nc_factory: typing.Callable[[], typing.Any],
        service_factory: typing.Callable[[typing.Any], OcrService],
        poll_interval: float = 5.0,
    ):
        self._nc_factory = nc_factory
        self._service_factory = service_factory
        self._poll_interval = poll_interval
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - keep the worker alive
                logger.exception("Task processing poll failed")
            await asyncio.sleep(self._poll_interval)

    async def _poll_once(self) -> None:
        nc = self._nc_factory()
        response = await nc.providers.task_processing.next_task(provider_ids=[PROVIDER_ID], task_types=[TASK_TYPE_OCR])
        if not response:
            return
        task = response.get("task", response)
        task_id = task.get("id")
        if task_id is None:
            return
        user_id = task.get("userId") or task.get("user_id") or "admin"
        await nc.set_user(user_id)
        file_id = _extract_file_id(task)
        if file_id is None:
            await nc.providers.task_processing.report_result(task_id, error_message="No file id in task input")
            return
        await nc.providers.task_processing.set_progress(task_id, 10.0)
        service = self._service_factory(nc)
        job = OcrJob(
            file_id=file_id,
            user_id=user_id,
            trigger=TRIGGER_TASK,
            task_id=task_id,
            pages=_extract_pages(task),
        )
        outcome = await service.process(job)
        await nc.providers.task_processing.set_progress(task_id, 90.0)
        if outcome.error is not None:
            await nc.providers.task_processing.report_result(
                task_id,
                error_message=str(outcome.error),
                user_facing_error_message=outcome.error.user_message,
            )
        else:
            await nc.providers.task_processing.report_result(
                task_id, output={"output": [outcome.result.markdown] if outcome.result else []}
            )
