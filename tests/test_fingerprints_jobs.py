import asyncio

from mistral_ocr.fingerprints import MemoryFingerprintStore, compute_fingerprint
from mistral_ocr.jobs import JobQueue, OcrJob


def test_fingerprint_changes_with_inputs():
    f1 = compute_fingerprint(1, "a", "m1")
    assert f1 != compute_fingerprint(1, "b", "m1")
    assert f1 != compute_fingerprint(2, "a", "m1")
    assert f1 != compute_fingerprint(1, "a", "m2")
    assert f1 == compute_fingerprint(1, "a", "m1")


def test_memory_fingerprint_store():
    store = MemoryFingerprintStore()
    assert not store.is_processed(1, "a", "m")
    store.mark_processed(1, "a", "m")
    assert store.is_processed(1, "a", "m")
    assert not store.is_processed(1, "changed", "m")
    store.clear(1)
    assert not store.is_processed(1, "a", "m")


async def test_job_queue_enqueue_and_done(tmp_path):
    queue = JobQueue(path=str(tmp_path / "q.json"))
    job = OcrJob(file_id=1, user_id="u", trigger="manual")
    await queue.enqueue(job)
    got = await asyncio.wait_for(queue.get(), timeout=1)
    assert got.id == job.id
    await queue.mark_done(got)
    assert queue.get_job(job.id).status == "done"
    pending = [j for j in queue.list_jobs() if j.status == "pending"]
    assert pending == []


async def test_job_queue_persists_pending(tmp_path):
    path = str(tmp_path / "q.json")
    q1 = JobQueue(path=path)
    job = OcrJob(file_id=7, user_id="u")
    await q1.enqueue(job)
    q2 = JobQueue(path=path)
    restored = await asyncio.wait_for(q2.get(), timeout=1)
    assert restored.file_id == 7
