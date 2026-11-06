"""Async job queue for OCR work.

Jobs are enqueued from HTTP endpoints (manual file action, flow events) and
the Task Processing worker. The queue is persisted to disk so pending jobs
survive an app/Nextcloud restart; completed jobs are idempotent thanks to the
fingerprint guard.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import typing
import uuid
from dataclasses import asdict, dataclass, field

from .config import OUTPUT_MODE_SIDECAR

logger = logging.getLogger("mistral_ocr.jobs")

DEFAULT_QUEUE_PATH = os.path.join(
    os.getenv("APP_PERSISTENT_STORAGE", os.path.join(os.getcwd(), ".data")),
    "ocr_queue.json",
)

TRIGGER_MANUAL = "manual"
TRIGGER_FLOW = "flow"
TRIGGER_TASK = "task"


@dataclass
class OcrJob:
    file_id: int
    user_id: str
    trigger: str = TRIGGER_MANUAL
    output_mode: str = OUTPUT_MODE_SIDECAR
    force: bool = False
    pages: list[int] | None = None
    task_id: int | None = None
    tags_on_success: list[str] = field(default_factory=list)
    tags_on_failure: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    status: str = "pending"
    error: str | None = None

    def to_dict(self) -> dict[str, typing.Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, typing.Any]) -> "OcrJob":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


class JobQueue:
    """asyncio.Queue backed job queue with JSON persistence of pending jobs."""

    def __init__(self, path: str = DEFAULT_QUEUE_PATH):
        self._path = path
        self._queue: asyncio.Queue[OcrJob] = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._jobs: dict[str, OcrJob] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as fp:
                raw = json.load(fp)
            for item in raw.get("pending", []):
                job = OcrJob.from_dict(item)
                job.status = "pending"
                self._jobs[job.id] = job
                self._queue.put_nowait(job)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            logger.warning("Could not read job queue %s: %s", self._path, exc)

    async def _persist(self) -> None:
        pending = [j.to_dict() for j in self._jobs.values() if j.status == "pending"]
        tmp_path = f"{self._path}.tmp"
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as fp:
                json.dump({"pending": pending}, fp)
            os.replace(tmp_path, self._path)
        except OSError as exc:
            logger.warning("Could not persist job queue: %s", exc)

    async def enqueue(self, job: OcrJob) -> OcrJob:
        async with self._lock:
            job.status = "pending"
            self._jobs[job.id] = job
            self._queue.put_nowait(job)
            await self._persist()
        return job

    async def get(self) -> OcrJob:
        return await self._queue.get()

    async def mark_done(self, job: OcrJob, error: str | None = None) -> None:
        async with self._lock:
            job.status = "failed" if error else "done"
            job.error = error
            await self._persist()

    def get_job(self, job_id: str) -> OcrJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[OcrJob]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
