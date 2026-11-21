"""Filesystem layout for uploads and compiled results.

The uploaded file and its interpretation are written once and never modified.
Every compilation (including what-if re-runs) gets a new result directory, so
an earlier result and the original interpretation stay reproducible.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import DATA_DIR

UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{12}$")
RESULT_ID_RE = re.compile(r"^[0-9a-f]{16}$")


class StorageError(ValueError):
    pass


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    _atomic_write(path, text.encode("utf-8"))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class UploadRecord:
    upload_id: str
    filename: str
    original_name: str
    file_type: str
    size_bytes: int
    sha256: str
    created_at: float
    path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "upload_id": self.upload_id,
            "filename": self.filename,
            "original_name": self.original_name,
            "file_type": self.file_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "created_at": self.created_at,
        }


def upload_root() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / "uploads"


def new_upload_id() -> str:
    return uuid.uuid4().hex[:12]


def new_result_id() -> str:
    return uuid.uuid4().hex[:16]


def upload_dir(upload_id: str) -> Path:
    if not UPLOAD_ID_RE.match(upload_id):
        raise StorageError("上传 ID 格式不正确")
    return upload_root() / upload_id


def result_dir(result_id: str) -> Path:
    if not RESULT_ID_RE.match(result_id):
        raise StorageError("结果 ID 格式不正确")
    root = upload_root()
    for candidate in root.glob(f"*/results/{result_id}"):
        return candidate
    raise StorageError("结果不存在")


def load_upload(upload_id: str) -> UploadRecord:
    root = upload_dir(upload_id)
    if not root.exists():
        raise StorageError("上传不存在")
    data = read_json(root / "upload.json")
    return UploadRecord(path=root / data["filename"], **{k: data[k] for k in (
        "upload_id",
        "filename",
        "original_name",
        "file_type",
        "size_bytes",
        "sha256",
        "created_at",
    )})


def load_interpretation(upload_id: str) -> dict[str, Any]:
    root = upload_dir(upload_id)
    path = root / "interpretation.json"
    if not path.exists():
        raise StorageError("该上传缺少原解释")
    return read_json(path)


def list_uploads(limit: int = 30) -> list[dict[str, Any]]:
    root = upload_root()
    items: list[dict[str, Any]] = []
    for meta_path in root.glob("*/upload.json"):
        try:
            data = read_json(meta_path)
        except (OSError, ValueError):
            continue
        results = sorted((meta_path.parent / "results").glob("*/manifest.json"))
        data["result_count"] = len(results)
        items.append(data)
    items.sort(key=lambda item: item.get("created_at", 0), reverse=True)
    return items[:limit]


def create_result_dir(upload_id: str) -> tuple[str, Path]:
    result_id = new_result_id()
    path = upload_dir(upload_id) / "results" / result_id
    path.mkdir(parents=True)
    return result_id, path


def result_manifest_path(result_id: str) -> Path:
    return result_dir(result_id) / "manifest.json"


def load_manifest(result_id: str) -> dict[str, Any]:
    path = result_manifest_path(result_id)
    if not path.exists():
        raise StorageError("结果清单不存在")
    return read_json(path)


def store_manifest(result_id: str, manifest: dict[str, Any]) -> None:
    path = result_manifest_path(result_id)
    write_json(path, manifest)


def dataset_path(result_id: str) -> Path:
    return result_dir(result_id) / "data.parquet"


def exports_dir(result_id: str) -> Path:
    path = result_dir(result_id) / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_results(upload_id: str) -> list[dict[str, Any]]:
    root = upload_dir(upload_id) / "results"
    items = []
    for path in sorted(root.glob("*/manifest.json")):
        try:
            items.append(read_json(path))
        except (OSError, ValueError):
            continue
    items.sort(key=lambda item: item.get("created_at", 0), reverse=True)
    return items


def remove_upload(upload_id: str) -> None:
    root = upload_dir(upload_id)
    if root.exists():
        shutil.rmtree(root)


def remove_result(result_id: str) -> None:
    path = result_dir(result_id)
    shutil.rmtree(path, ignore_errors=True)
