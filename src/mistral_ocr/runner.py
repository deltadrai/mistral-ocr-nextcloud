"""Background consumer that drains the JobQueue through the OcrService."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import typing

from .jobs import JobQueue
from .ocr_service import OcrService

logger = logging.getLogger("mistral_ocr.runner")


class JobRunner:
    def __init__(
        self,
        queue: JobQueue,
        nc_factory: typing.Callable[[], typing.Any],
        service_factory: typing.Callable[[typing.Any], OcrService],
        poll_interval: float = 1.0,
    ):
        self._queue = queue
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
                job = await asyncio.wait_for(self._queue.get(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            try:
                nc = self._nc_factory()
                service = self._service_factory(nc)
                outcome = await service.process(job)
                await self._queue.mark_done(
                    job,
                    error=outcome.error.user_message if outcome.error else None,
                    result_path=outcome.sidecar_path,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("Job %s crashed", job.id)
                await self._queue.mark_done(job, error=str(exc))
