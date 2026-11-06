"""Skip-if-processed guard.

Stores a fingerprint per processed file: sha256(file_id + etag + model).
Automatic (flow) triggers skip files whose fingerprint is unchanged; manual
runs can force re-processing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import typing

logger = logging.getLogger("mistral_ocr.fingerprints")

DEFAULT_STORE_PATH = os.path.join(
    os.getenv("APP_PERSISTENT_STORAGE", os.path.join(os.getcwd(), ".data")),
    "ocr_fingerprints.json",
)


def compute_fingerprint(file_id: int | str, etag: str, model: str) -> str:
    digest = hashlib.sha256(f"{file_id}|{etag}|{model}".encode("utf-8")).hexdigest()
    return digest


class FingerprintStore:
    """JSON-file backed fingerprint store. Survives app restarts."""

    def __init__(self, path: str = DEFAULT_STORE_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as fp:
                raw = json.load(fp)
            if isinstance(raw, dict):
                self._data = {str(k): str(v) for k, v in raw.items()}
        except FileNotFoundError:
            self._data = {}
        except (OSError, ValueError) as exc:
            logger.warning("Could not read fingerprint store %s: %s", self._path, exc)
            self._data = {}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp_path = f"{self._path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fp:
            json.dump(self._data, fp)
        os.replace(tmp_path, self._path)

    def is_processed(self, file_id: int | str, etag: str, model: str) -> bool:
        fingerprint = compute_fingerprint(file_id, etag, model)
        with self._lock:
            return self._data.get(str(file_id)) == fingerprint

    def mark_processed(self, file_id: int | str, etag: str, model: str) -> None:
        fingerprint = compute_fingerprint(file_id, etag, model)
        with self._lock:
            self._data[str(file_id)] = fingerprint
            try:
                self._save()
            except OSError as exc:
                logger.warning("Could not persist fingerprint store: %s", exc)

    def clear(self, file_id: int | str | None = None) -> None:
        with self._lock:
            if file_id is None:
                self._data.clear()
            else:
                self._data.pop(str(file_id), None)
            try:
                self._save()
            except OSError as exc:
                logger.warning("Could not persist fingerprint store: %s", exc)

    def all(self) -> dict[str, str]:
        with self._lock:
            return dict(self._data)


class MemoryFingerprintStore:
    """In-memory variant for tests."""

    def __init__(self):
        self._inner = FingerprintStore.__new__(FingerprintStore)
        self._inner._path = ":memory:"
        self._inner._lock = threading.Lock()
        self._inner._data = {}

    def is_processed(self, file_id: int | str, etag: str, model: str) -> bool:
        return self._inner._data.get(str(file_id)) == compute_fingerprint(file_id, etag, model)

    def mark_processed(self, file_id: int | str, etag: str, model: str) -> None:
        self._inner._data[str(file_id)] = compute_fingerprint(file_id, etag, model)

    def clear(self, file_id: int | str | None = None) -> None:
        if file_id is None:
            self._inner._data.clear()
        else:
            self._inner._data.pop(str(file_id), None)

    def all(self) -> dict[str, str]:
        return dict(self._inner._data)


if typing.TYPE_CHECKING:
    FingerprintProtocol = FingerprintStore
else:
    FingerprintProtocol = typing.Any
