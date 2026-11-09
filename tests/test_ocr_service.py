from mistral_ocr.config import OUTPUT_MODE_SIDECAR, OUTPUT_MODE_TASK_RESULT, AppSettings
from mistral_ocr.errors import (
    FileTooLargeError,
    MimeTypeNotAllowedError,
    MissingApiKeyError,
    MistralOcrError,
    SidecarLockedError,
    SidecarWriteError,
)
from mistral_ocr.fingerprints import MemoryFingerprintStore
from mistral_ocr.jobs import TRIGGER_FLOW, TRIGGER_MANUAL, OcrJob
from mistral_ocr.mistral_client import OcrResult, PageResult
from mistral_ocr.ocr_service import OcrService


class FakeNode:
    def __init__(
        self, file_id=42, name="scan.pdf", path="/docs/scan.pdf", mime_type="application/pdf", size=1024, etag="abc123"
    ):
        self.file_id = file_id
        self.name = name
        self.path = path
        self.mime_type = mime_type
        self.size = size
        self.etag = etag


class FakeFiles:
    def __init__(self, node, content=b"pdf-bytes", upload_error=None):
        self.node = node
        self.content = content
        self.uploads = []
        self.upload_error = upload_error

    async def by_id(self, file_id):
        return self.node if self.node and self.node.file_id == file_id else None

    async def download(self, node):
        return self.content

    async def upload(self, path, content):
        if self.upload_error is not None:
            raise self.upload_error
        self.uploads.append((path, content))


class FakeNotifications:
    def __init__(self):
        self.sent = []

    async def create(self, subject, message="", **kwargs):
        self.sent.append((subject, message))
        return "1"


class FakeNc:
    def __init__(self, node, content=b"pdf-bytes", upload_error=None):
        self.files = FakeFiles(node, content, upload_error)
        self.notifications = FakeNotifications()
        self.user = "alice"
        self.logs = []

    async def set_user(self, user_id):
        self.user = user_id

    def log(self, lvl, content, fast_send=False):
        self.logs.append(content)

    async def ocs(self, *args, **kwargs):
        return {}


class FakeClient:
    def __init__(self, result=None, error=None):
        self.calls = []
        self._result = result or OcrResult(
            model="mistral-ocr-4-1",
            pages=[PageResult(index=0, markdown="# Page one", images=[])],
        )
        self._error = error

    async def ocr_file(self, mime_type, content, model, pages=None, include_image_base64=False):
        self.calls.append({"mime": mime_type, "model": model, "pages": pages})
        if self._error:
            raise self._error
        return self._result


def make_service(nc, settings=None, api_key="key", client=None, fingerprints=None):
    settings = settings or AppSettings()
    client = client or FakeClient()
    return (
        OcrService(
            settings_provider=lambda: settings,
            api_key_provider=lambda: api_key,
            client_factory=lambda s, k: client,
            nc=nc,
            fingerprints=fingerprints or MemoryFingerprintStore(),
        ),
        client,
    )


async def test_sidecar_written_next_to_file():
    nc = FakeNc(FakeNode())
    service, client = make_service(nc)
    job = OcrJob(file_id=42, user_id="alice", trigger=TRIGGER_MANUAL, output_mode=OUTPUT_MODE_SIDECAR)
    outcome = await service.process(job)
    assert outcome.error is None
    assert outcome.sidecar_path == "/docs/scan.md"
    assert nc.files.uploads[0][0] == "/docs/scan.md"
    assert b"# Page one" in nc.files.uploads[0][1]
    assert client.calls[0]["mime"] == "application/pdf"


async def test_task_result_mode_writes_no_sidecar():
    nc = FakeNc(FakeNode(name="photo.png", path="/img/photo.png", mime_type="image/png"))
    service, _ = make_service(nc)
    job = OcrJob(file_id=42, user_id="alice", trigger=TRIGGER_MANUAL, output_mode=OUTPUT_MODE_TASK_RESULT)
    outcome = await service.process(job)
    assert outcome.error is None
    assert outcome.result is not None
    assert nc.files.uploads == []


async def test_flow_skips_already_processed_file():
    fp = MemoryFingerprintStore()
    nc = FakeNc(FakeNode())
    service, client = make_service(nc, fingerprints=fp)
    job = OcrJob(file_id=42, user_id="alice", trigger=TRIGGER_FLOW)
    first = await service.process(job)
    assert not first.skipped
    second = await service.process(job)
    assert second.skipped
    assert len(client.calls) == 1


async def test_manual_force_reprocesses():
    fp = MemoryFingerprintStore()
    nc = FakeNc(FakeNode())
    service, client = make_service(nc, fingerprints=fp)
    await service.process(OcrJob(file_id=42, user_id="alice", trigger=TRIGGER_FLOW))
    forced = await service.process(OcrJob(file_id=42, user_id="alice", trigger=TRIGGER_MANUAL, force=True))
    assert not forced.skipped
    assert len(client.calls) == 2


async def test_flow_reprocesses_when_etag_changes():
    fp = MemoryFingerprintStore()
    node = FakeNode()
    nc = FakeNc(node)
    service, client = make_service(nc, fingerprints=fp)
    await service.process(OcrJob(file_id=42, user_id="alice", trigger=TRIGGER_FLOW))
    node.etag = "def456"
    again = await service.process(OcrJob(file_id=42, user_id="alice", trigger=TRIGGER_FLOW))
    assert not again.skipped
    assert len(client.calls) == 2


async def test_disallowed_mime_rejected_and_notifies():
    nc = FakeNc(FakeNode(mime_type="text/plain"))
    service, client = make_service(nc)
    job = OcrJob(file_id=42, user_id="alice", trigger=TRIGGER_MANUAL)
    outcome = await service.process(job)
    assert isinstance(outcome.error, MimeTypeNotAllowedError)
    assert client.calls == []
    assert any("failed" in s.lower() for s, _ in nc.notifications.sent)


async def test_oversize_file_rejected():
    settings = AppSettings(max_file_size_mb=1)
    nc = FakeNc(FakeNode(size=2 * 1024 * 1024))
    service, client = make_service(nc, settings=settings)
    outcome = await service.process(OcrJob(file_id=42, user_id="alice", trigger=TRIGGER_MANUAL))
    assert isinstance(outcome.error, FileTooLargeError)
    assert client.calls == []


async def test_missing_api_key_fails_cleanly():
    nc = FakeNc(FakeNode())
    service, client = make_service(nc, api_key="")
    outcome = await service.process(OcrJob(file_id=42, user_id="alice", trigger=TRIGGER_MANUAL))
    assert isinstance(outcome.error, MissingApiKeyError)
    assert client.calls == []
    assert any("key" in m.lower() for _, m in nc.notifications.sent)


async def test_unknown_file_id():
    from mistral_ocr.errors import FileNotFoundError_

    nc = FakeNc(None)
    service, _ = make_service(nc)
    outcome = await service.process(OcrJob(file_id=999, user_id="alice", trigger=TRIGGER_MANUAL))
    assert isinstance(outcome.error, FileNotFoundError_)


async def test_page_range_forwarded():
    nc = FakeNc(FakeNode())
    service, client = make_service(nc)
    job = OcrJob(file_id=42, user_id="alice", trigger=TRIGGER_MANUAL, pages=[1, 2])
    await service.process(job)
    assert client.calls[0]["pages"] == [1, 2]


async def test_api_error_propagates_as_typed_error():
    from mistral_ocr.errors import QuotaExceededError

    nc = FakeNc(FakeNode())
    service, _ = make_service(nc, client=FakeClient(error=QuotaExceededError("quota")))
    outcome = await service.process(OcrJob(file_id=42, user_id="alice", trigger=TRIGGER_MANUAL))
    assert isinstance(outcome.error, QuotaExceededError)
    assert any("quota" in m.lower() or "rate" in m.lower() for _, m in nc.notifications.sent)


class StatusError(Exception):
    """Stands in for nc_py_api's NextcloudException, which carries status_code."""

    def __init__(self, status_code, text=""):
        super().__init__(text)
        self.status_code = status_code


async def test_locked_sidecar_reports_a_user_facing_error():
    """The Text editor locks .md files with no TTL, so re-OCR'ing must say so."""
    nc = FakeNc(
        FakeNode(),
        upload_error=Exception("[423] Locked <upload: user=admin, path=/docs/scan.md, size=135>"),
    )
    fingerprints = MemoryFingerprintStore()
    service, _ = make_service(nc, fingerprints=fingerprints)
    outcome = await service.process(OcrJob(file_id=42, user_id="alice", trigger=TRIGGER_MANUAL))

    assert isinstance(outcome.error, SidecarLockedError)
    assert "[423]" not in outcome.error.user_message
    assert "Text editor" in outcome.error.user_message
    # The notification carries the friendly message, not the raw DAV error.
    assert any("locked" in m.lower() for _, m in nc.notifications.sent)
    # Not marked processed: the job must be retryable once the file is closed.
    assert not fingerprints.is_processed(42, "abc123", AppSettings().model)


async def test_locked_sidecar_detected_by_status_code():
    nc = FakeNc(FakeNode(), upload_error=StatusError(423, "Locked"))
    service, _ = make_service(nc)
    outcome = await service.process(OcrJob(file_id=42, user_id="alice", trigger=TRIGGER_MANUAL))
    assert isinstance(outcome.error, SidecarLockedError)


async def test_other_sidecar_failure_reports_a_write_error():
    nc = FakeNc(FakeNode(), upload_error=StatusError(403, "Forbidden"))
    service, _ = make_service(nc)
    outcome = await service.process(OcrJob(file_id=42, user_id="alice", trigger=TRIGGER_MANUAL))
    assert isinstance(outcome.error, SidecarWriteError)
    assert isinstance(outcome.error, MistralOcrError)
    assert any("saved" in m.lower() for _, m in nc.notifications.sent)
