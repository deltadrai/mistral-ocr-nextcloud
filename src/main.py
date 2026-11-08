"""FastAPI entrypoint of the Mistral OCR ExApp.

Lifecycle endpoints (`/heartbeat`, `/init`, `/enabled`) are provided by
``nc_py_api.ex_app.integration_fastapi.set_handlers``. On top of that this
module exposes:

- ``GET  /api/v1/status``                 health/status for the AppAPI admin UI
- ``GET|POST /api/v1/admin/settings``     admin settings (API key stored encrypted)
- ``POST /api/v1/admin/test-connection``  "Test API key & model" setup check
- ``POST /api/v1/ocr``                    manual trigger from the Files context menu
- ``POST /api/v1/flow/event``             workflow engine (Flow) event endpoint
- ``GET  /api/v1/jobs``                   job list (admin/debug)
- ``GET  /admin``                         minimal admin settings page
"""

from __future__ import annotations

import logging
import os
import typing

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from nc_py_api import AsyncNextcloudApp
from nc_py_api.ex_app.integration_fastapi import anc_app, set_handlers
from pydantic import BaseModel, Field

from .mistral_ocr import __version__
from .mistral_ocr.config import (
    AppApiSettingsStore,
    AppSettings,
    MemorySettingsStore,
    SettingsStore,
)
from .mistral_ocr.errors import MissingApiKeyError, MistralOcrError
from .mistral_ocr.fingerprints import FingerprintStore
from .mistral_ocr.jobs import TRIGGER_FLOW, TRIGGER_MANUAL, JobQueue, OcrJob
from .mistral_ocr.mistral_client import MistralOcrClient
from .mistral_ocr.ocr_service import OcrService
from .mistral_ocr.runner import JobRunner
from .mistral_ocr.task_processing import (
    PROVIDER_ID,
    TASK_TYPE_OCR,
    TaskProcessingWorker,
    register_provider,
    unregister_provider,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger("mistral_ocr.main")

APP_ID = "mistral_ocr"
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "js")

app = FastAPI(title="Mistral OCR ExApp", version=__version__)

_store: SettingsStore | None = None
_queue: JobQueue | None = None
_worker: TaskProcessingWorker | None = None
_runner: JobRunner | None = None


def get_store(nc: typing.Any) -> SettingsStore:
    global _store
    if _store is None:
        _store = AppApiSettingsStore(nc)
    return _store


def get_queue() -> JobQueue:
    global _queue
    if _queue is None:
        _queue = JobQueue()
    return _queue


def make_client(settings: AppSettings, api_key: str) -> MistralOcrClient:
    return MistralOcrClient(
        api_key=api_key,
        base_url=settings.base_url,
        timeout=settings.timeout_seconds,
    )


def make_service(nc: typing.Any, store: SettingsStore) -> OcrService:
    return OcrService(
        settings_provider=store.load_settings,
        api_key_provider=store.get_api_key,
        client_factory=make_client,
        nc=nc,
        fingerprints=FingerprintStore(),
    )


def get_worker() -> TaskProcessingWorker:
    global _worker
    if _worker is None:
        _worker = TaskProcessingWorker(
            nc_factory=lambda: AsyncNextcloudApp(),
            service_factory=lambda nc: make_service(nc, _store or MemorySettingsStore()),
        )
    return _worker


def get_runner() -> JobRunner:
    global _runner
    if _runner is None:
        _runner = JobRunner(
            queue=get_queue(),
            nc_factory=lambda: AsyncNextcloudApp(),
            service_factory=lambda nc: make_service(nc, _store or MemorySettingsStore()),
        )
    return _runner


FILE_ACTION_NAME = "mistral_ocr_recognize_text"


async def enabled_handler(enabled: bool, nc: AsyncNextcloudApp) -> str:
    get_store(nc)
    if enabled:
        await register_provider(nc)
        # Files context-menu entry; NC's app_api-filesplugin calls
        # /apps/app_api/proxy/mistral_ocr/<action_handler> when it is clicked.
        await nc.ui.files_dropdown_menu.register_ex(
            FILE_ACTION_NAME,
            "Recognize text with Mistral OCR",
            "api/v1/ocr",
            # The Files plugin matches mime entries as substrings of the node mime
            # ("image/png".includes("image/")); "file" never matches a real file mime.
            mime="image/,application/pdf",
        )
        await get_worker().start()
        return ""
    await nc.ui.files_dropdown_menu.unregister(FILE_ACTION_NAME)
    await unregister_provider(nc)
    await get_worker().stop()
    await get_runner().stop()
    return ""


async def trigger_handler(provider_id: str) -> None:
    if provider_id == PROVIDER_ID:
        logger.info("Trigger received for provider %s", provider_id)


set_handlers(app, enabled_handler, trigger_handler=trigger_handler)


@app.on_event("startup")
async def _startup() -> None:
    await get_worker().start()
    await get_runner().start()


class SettingsUpdate(BaseModel):
    api_key: str | None = Field(default=None, description="Omit to keep the current key")
    base_url: str | None = None
    model: str | None = None
    max_file_size_mb: int | None = None
    max_pages: int | None = None
    allowed_mime_types: list[str] | None = None
    default_output_mode: str | None = None
    include_image_base64: bool | None = None
    timeout_seconds: float | None = None
    notify_on_success: bool | None = None


class OcrRequest(BaseModel):
    fileId: int
    force: bool = False
    pages: list[int] | None = None
    output_mode: str | None = None


class FlowEvent(BaseModel):
    event: str
    file_id: int = Field(alias="fileId")
    user_id: str = Field(default="admin", alias="userId")
    tags_on_success: list[str] = Field(default_factory=list)
    tags_on_failure: list[str] = Field(default_factory=list)
    output_mode: str | None = None
    model_config = {"populate_by_name": True}


@app.get("/api/v1/status")
async def status(nc: typing.Annotated[AsyncNextcloudApp, Depends(anc_app)]):
    store = get_store(nc)
    settings = await store.load_settings()
    return {
        "app": APP_ID,
        "version": __version__,
        "provider": PROVIDER_ID,
        "taskType": TASK_TYPE_OCR,
        "configured": bool(await store.get_api_key()),
        "model": settings.model,
        "baseUrl": settings.base_url,
        "pendingJobs": len([j for j in get_queue().list_jobs() if j.status == "pending"]),
    }


@app.get("/api/v1/admin/settings")
async def get_settings(nc: typing.Annotated[AsyncNextcloudApp, Depends(anc_app)]):
    store = get_store(nc)
    settings = await store.load_settings()
    return {"settings": settings.to_public_dict(), "apiKeyConfigured": bool(await store.get_api_key())}


@app.post("/api/v1/admin/settings")
async def update_settings(payload: SettingsUpdate, nc: typing.Annotated[AsyncNextcloudApp, Depends(anc_app)]):
    store = get_store(nc)
    current = await store.load_settings()
    updates = payload.model_dump(exclude_unset=True)
    api_key = updates.pop("api_key", None)
    try:
        new_settings = AppSettings.from_dict({**current.to_public_dict(), **updates})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await store.save_settings(new_settings)
    if api_key is not None:
        await store.set_api_key(api_key.strip())
    return {"settings": new_settings.to_public_dict(), "apiKeyConfigured": bool(await store.get_api_key())}


@app.post("/api/v1/admin/test-connection")
async def test_connection(nc: typing.Annotated[AsyncNextcloudApp, Depends(anc_app)]):
    store = get_store(nc)
    settings = await store.load_settings()
    api_key = await store.get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail=MissingApiKeyError().user_message)
    client = make_client(settings, api_key)
    try:
        models = await client.list_models()
    except MistralOcrError as exc:
        raise HTTPException(status_code=502, detail=exc.user_message) from exc
    model_ok = settings.model in models or any(settings.model in m for m in models)
    return {"ok": True, "modelAvailable": model_ok, "models": models[:50]}


@app.post("/api/v1/ocr", status_code=202)
async def manual_ocr(payload: OcrRequest, nc: typing.Annotated[AsyncNextcloudApp, Depends(anc_app)]):
    store = get_store(nc)
    settings = await store.load_settings()
    job = OcrJob(
        file_id=payload.fileId,
        user_id=await nc.user,  # async SDK: nc.user is a coroutine
        trigger=TRIGGER_MANUAL,
        output_mode=payload.output_mode or settings.default_output_mode,
        force=payload.force,
        pages=payload.pages,
    )
    await get_queue().enqueue(job)
    return {"jobId": job.id, "status": "queued"}


@app.post("/api/v1/flow/event", status_code=202)
async def flow_event(event: FlowEvent, nc: typing.Annotated[AsyncNextcloudApp, Depends(anc_app)]):
    store = get_store(nc)
    settings = await store.load_settings()
    job = OcrJob(
        file_id=event.file_id,
        user_id=event.user_id,
        trigger=TRIGGER_FLOW,
        output_mode=event.output_mode or settings.default_output_mode,
        tags_on_success=event.tags_on_success,
        tags_on_failure=event.tags_on_failure,
    )
    await get_queue().enqueue(job)
    return {"jobId": job.id, "status": "queued"}


@app.get("/api/v1/jobs")
async def list_jobs(nc: typing.Annotated[AsyncNextcloudApp, Depends(anc_app)]):
    return {"jobs": [j.to_dict() for j in get_queue().list_jobs()]}


@app.get("/admin")
async def admin_page():
    index = os.path.join(STATIC_DIR, "admin.html")
    if os.path.exists(index):
        return FileResponse(index)
    return JSONResponse({"detail": "admin page not found"}, status_code=404)


@app.get("/api/v1/health")
async def health():
    return {"status": "ok"}
