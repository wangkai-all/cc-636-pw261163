"""FastAPI application for the data intake desk."""

from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import storage
from .compiler import (
    CompiledColumn,
    CompiledResult,
    SpecError,
    compile_result,
    parse_spec,
    preview,
    spec_token,
)
from .config import MAX_UPLOAD_BYTES, SAMPLES_DIR, SUPPORTED_SUFFIXES
from .export import build_export, verify
from .exports import EXPORT_FORMATS, FORMAT_LIMITS, FORMAT_NOTES, FORMAT_TITLES
from .reader import ReadResult, UnsupportedFileError, read_file

app = FastAPI(title="数据收件台", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class OverrideIn(BaseModel):
    rule_id: str
    action: str = "missing"
    value: Any = None
    label: Optional[str] = None


class FieldIn(BaseModel):
    name: str
    layers: list[str] = Field(default_factory=lambda: ["raw", "label", "analysis", "state"])
    overrides: list[OverrideIn] = Field(default_factory=list)
    time_mode: str = "interpret"


class SpecIn(BaseModel):
    fields: list[FieldIn]


class ExportIn(BaseModel):
    spec: SpecIn
    format: str
    preview_token: Optional[str] = None


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/formats")
def formats() -> dict[str, Any]:
    return {
        "formats": [
            {
                "id": fmt,
                "title": FORMAT_TITLES[fmt],
                "notes": FORMAT_NOTES[fmt],
                "limits": FORMAT_LIMITS[fmt],
            }
            for fmt in EXPORT_FORMATS
        ]
    }


@app.get("/api/samples")
def samples() -> dict[str, Any]:
    items = []
    for path in sorted(SAMPLES_DIR.glob("*")):
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        items.append(
            {
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "file_type": SUPPORTED_SUFFIXES[path.suffix.lower()],
            }
        )
    return {"samples": items}


@app.post("/api/uploads")
async def create_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的扩展名 {suffix or '(无)'}：仅接受 .sav 和 .dta",
        )
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件超过上传上限")
    return _ingest_bytes(file.filename or f"upload{suffix}", data)


@app.post("/api/uploads/sample/{name}")
def create_sample_upload(name: str) -> dict[str, Any]:
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="非法样例名")
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=400, detail="样例仅支持 .sav/.dta")
    path = SAMPLES_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="样例不存在")
    return _ingest_bytes(name, path.read_bytes())


def _ingest_bytes(name: str, data: bytes) -> dict[str, Any]:
    upload_id = storage.new_upload_id()
    suffix = Path(name).suffix.lower()
    safe_name = Path(name).name
    tmp_dir = storage.upload_root() / f".tmp-{upload_id}"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)
    tmp_path = tmp_dir / f"source{suffix}"
    tmp_path.write_bytes(data)
    try:
        read = read_file(str(tmp_path), safe_name)
    except UnsupportedFileError as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - unexpected parser failure
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=f"读取失败：{exc}") from exc

    # Persist the per-cell interpretation as the immutable record.
    interpretation = _interpretation_payload(read)
    final_dir = storage.upload_dir(upload_id)
    if final_dir.exists():
        shutil.rmtree(final_dir)
    created = time.time()
    record = storage.UploadRecord(
        upload_id=upload_id,
        filename=f"source{suffix}",
        original_name=safe_name,
        file_type=read.file_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        created_at=created,
        path=final_dir / f"source{suffix}",
    )
    (tmp_dir / f"source{suffix}").write_bytes(data)
    storage.write_json(tmp_dir / "upload.json", record.to_dict())
    storage.write_json(tmp_dir / "interpretation.json", interpretation)
    tmp_dir.rename(final_dir)
    return _upload_summary(record, interpretation)


def _interpretation_payload(read: ReadResult) -> dict[str, Any]:
    cell_rows = []
    for row in range(read.row_count):
        row_cells = {"row_id": row}
        for variable in read.variables:
            column = read.columns[variable.name]
            row_cells[variable.name] = {
                "raw": column["raw"][row],
                "label": column["label"][row],
                "analysis": column["analysis"][row],
                "state": column["state"][row],
                "rule": column["rule"][row],
                "ext_code": column["ext_code"][row],
            }
        cell_rows.append(row_cells)
    payload = read.to_metadata()
    payload["cells"] = cell_rows
    payload["schema_version"] = 1
    return payload


def _upload_summary(record: storage.UploadRecord, interpretation: dict[str, Any]) -> dict[str, Any]:
    return {
        "upload": record.to_dict(),
        "interpretation": {
            key: value
            for key, value in interpretation.items()
            if key not in {"cells", "schema_version"}
        },
        "results": storage.list_results(record.upload_id),
    }


@app.get("/api/uploads")
def list_uploads() -> dict[str, Any]:
    return {"uploads": storage.list_uploads()}


@app.get("/api/uploads/{upload_id}")
def get_upload(upload_id: str) -> dict[str, Any]:
    try:
        record = storage.load_upload(upload_id)
        interpretation = storage.load_interpretation(upload_id)
    except storage.StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _upload_summary(record, interpretation)


@app.get("/api/uploads/{upload_id}/cells")
def upload_cells(
    upload_id: str,
    column: str = Query(..., min_length=1),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    try:
        interpretation = storage.load_interpretation(upload_id)
    except storage.StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    variables = {item["name"]: item for item in interpretation.get("variables", [])}
    if column not in variables:
        raise HTTPException(status_code=404, detail="字段不存在")
    cells = interpretation.get("cells", [])
    rows = []
    for cell in cells[offset : offset + limit]:
        data = cell.get(column, {})
        rows.append({"row_id": cell["row_id"], **data})
    return {
        "column": variables[column],
        "rows": rows,
        "total": len(cells),
        "offset": offset,
        "limit": limit,
    }


@app.post("/api/uploads/{upload_id}/preview")
def upload_preview(upload_id: str, spec: SpecIn) -> dict[str, Any]:
    read, record = _load_read(upload_id)
    try:
        result = preview(
            read,
            record.sha256,
            spec.model_dump(),
            available_formats=EXPORT_FORMATS,
        )
    except SpecError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result["formats"] = [
        {
            "id": fmt,
            "title": FORMAT_TITLES[fmt],
            "notes": FORMAT_NOTES[fmt],
            "limits": FORMAT_LIMITS[fmt],
        }
        for fmt in EXPORT_FORMATS
    ]
    result["dataset"] = {
        "row_count": read.row_count,
        "column_count": read.column_count,
        "file_type": read.file_type,
        "file_format": read.file_format,
        "encoding": read.encoding,
    }
    return result


@app.post("/api/uploads/{upload_id}/results")
def create_result(upload_id: str, payload: ExportIn) -> dict[str, Any]:
    if payload.format not in EXPORT_FORMATS:
        raise HTTPException(status_code=422, detail="不支持的导出格式")
    read, record = _load_read(upload_id)
    spec_dict = payload.spec.model_dump()
    token = spec_token(record.sha256, spec_dict)
    if payload.preview_token and payload.preview_token != token:
        raise HTTPException(
            status_code=409,
            detail="预览令牌与当前字段/转换不一致，请重新预览并确认。",
        )
    try:
        fields = parse_spec(read, spec_dict)
        compiled = compile_result(read, fields)
        pv = preview(read, record.sha256, spec_dict, available_formats=EXPORT_FORMATS)
    except SpecError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    result_id, path = storage.create_result_dir(upload_id)
    interpretation = storage.load_interpretation(upload_id)
    manifest = {
        "result_id": result_id,
        "upload_id": upload_id,
        "upload_sha256": record.sha256,
        "created_at": time.time(),
        "format": payload.format,
        "format_title": FORMAT_TITLES[payload.format],
        "spec": spec_dict,
        "preview_token": token,
        "row_count": compiled.row_count,
        "columns": compiled.schema,
        "overrides": compiled.overrides_applied,
        "notes": compiled.notes,
        "scope": pv["scope"],
        "preview": {
            "fields": pv["fields"],
            "warnings": pv["warnings"],
        },
        "exports": [],
        "original": {
            "filename": record.filename,
            "original_name": record.original_name,
            "sha256": record.sha256,
            "unchanged": True,
        },
        "interpretation_ref": "interpretation.json",
    }
    storage.store_manifest(result_id, manifest)

    try:
        export_info = _write_export(
            result_id, upload_id, payload.format, compiled, interpretation, read.file_type
        )
    except Exception as exc:
        manifest["error"] = f"导出失败：{exc}"
        storage.store_manifest(result_id, manifest)
        raise HTTPException(status_code=500, detail=manifest["error"]) from exc

    manifest["exports"] = [export_info]
    storage.store_manifest(result_id, manifest)
    storage.write_json(
        path / "data.json",
        {
            "schema": compiled.schema,
            "rows": compiled.to_rows(limit=compiled.row_count, offset=0),
            "overrides": compiled.overrides_applied,
        },
    )
    return manifest


def _write_export(
    result_id: str,
    upload_id: str,
    fmt: str,
    compiled: CompiledResult,
    interpretation: dict[str, Any],
    source_type: str,
) -> dict[str, Any]:
    target = storage.exports_dir(result_id) / f"result.{fmt}"
    info = build_export(
        fmt,
        target,
        compiled,
        interpretation,
        source_type=source_type,
        target_type=fmt,
    )
    report = verify(target, fmt, compiled)
    info.update(
        {
            "id": fmt,
            "filename": target.name,
            "size_bytes": target.stat().st_size,
            "verification": report,
            "limits": FORMAT_LIMITS.get(fmt, []),
        }
    )
    return info


def _load_read(upload_id: str) -> tuple[ReadResult, storage.UploadRecord]:
    try:
        record = storage.load_upload(upload_id)
    except storage.StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        read = read_file(str(record.path), record.original_name)
    except UnsupportedFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return read, record


@app.get("/api/uploads/{upload_id}/results")
def list_results(upload_id: str) -> dict[str, Any]:
    try:
        return {"results": storage.list_results(upload_id)}
    except storage.StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/results/{result_id}")
def get_result(result_id: str) -> dict[str, Any]:
    try:
        return storage.load_manifest(result_id)
    except storage.StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/results/{result_id}/rows")
def result_rows(
    result_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    q: Optional[str] = None,
) -> dict[str, Any]:
    try:
        manifest = storage.load_manifest(result_id)
        data = storage.read_json(storage.result_dir(result_id) / "data.json")
    except storage.StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    rows = data["rows"]
    if q:
        needle = q.lower()
        rows = [
            row
            for row in rows
            if any(needle in str(value).lower() for key, value in row.items() if key != "row_id")
        ]
    total = len(rows)
    return {
        "schema": data["schema"],
        "rows": rows[offset : offset + limit],
        "total": total,
        "offset": offset,
        "limit": limit,
        "overrides": data.get("overrides", []),
        "manifest": {key: manifest.get(key) for key in ("result_id", "created_at", "format", "row_count", "notes")},
    }


@app.post("/api/results/{result_id}/exports/{fmt}")
def add_export(result_id: str, fmt: str) -> dict[str, Any]:
    """Generate one more export format for an existing result.

    The compiled layers are replayed from ``data.json``; the upload and its
    interpretation are still only read, never rewritten.
    """

    if fmt not in EXPORT_FORMATS:
        raise HTTPException(status_code=422, detail="不支持的导出格式")
    try:
        manifest = storage.load_manifest(result_id)
    except storage.StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    existing = [item for item in manifest.get("exports", []) if item.get("id") == fmt]
    if existing:
        return manifest
    try:
        data = storage.read_json(storage.result_dir(result_id) / "data.json")
        record = storage.load_upload(manifest["upload_id"])
        interpretation = storage.load_interpretation(manifest["upload_id"])
    except (storage.StorageError, OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=f"结果数据缺失：{exc}") from exc
    compiled = _compiled_from_data(data)
    try:
        info = _write_export(
            result_id, manifest["upload_id"], fmt, compiled, interpretation, record.file_type
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"导出失败：{exc}") from exc
    manifest["exports"].append(info)
    storage.store_manifest(result_id, manifest)
    return manifest


@app.get("/api/results/{result_id}/download")
def download_result(result_id: str, fmt: Optional[str] = None) -> FileResponse:
    try:
        manifest = storage.load_manifest(result_id)
    except storage.StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    chosen = fmt or manifest.get("format")
    if chosen not in EXPORT_FORMATS:
        raise HTTPException(status_code=400, detail="不支持的格式")
    path = storage.exports_dir(result_id) / f"result.{chosen}"
    if not path.exists():
        raise HTTPException(status_code=404, detail="导出文件不存在")
    media = {
        "sav": "application/x-spss-sav",
        "dta": "application/x-stata-dta",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }[chosen]
    return FileResponse(path, media_type=media, filename=f"{result_id}.{chosen}")


@app.get("/api/results/{result_id}/verification")
def result_verification(result_id: str) -> dict[str, Any]:
    try:
        manifest = storage.load_manifest(result_id)
    except storage.StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    exports = manifest.get("exports", [])
    if not exports:
        raise HTTPException(status_code=404, detail="尚无导出")
    return {"verifications": [item.get("verification") for item in exports]}


@app.get("/api/results/{result_id}/recheck")
def recheck_result(result_id: str) -> dict[str, Any]:
    """Re-read every export and re-run verification against its manifest."""

    try:
        manifest = storage.load_manifest(result_id)
        data = storage.read_json(storage.result_dir(result_id) / "data.json")
    except storage.StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    compiled = _compiled_from_data(data)
    reports = []
    for item in manifest.get("exports", []):
        fmt = item["id"]
        path = storage.exports_dir(result_id) / f"result.{fmt}"
        if not path.exists():
            reports.append({"format": fmt, "ok": False, "error": "文件缺失"})
            continue
        report = verify(path, fmt, compiled)
        reports.append({**report, "format": fmt, "filename": path.name})
    return {"result_id": result_id, "reports": reports}


def _compiled_from_data(data: dict[str, Any]) -> CompiledResult:
    schema = data["schema"]
    rows = data["rows"]
    columns = []
    for item in schema:
        columns.append(
            CompiledColumn(
                name=item["name"],
                source=item["source"],
                layer=item["layer"],
                dtype=item["dtype"],
                title=item["title"],
                description=item["description"],
                value_labels=item.get("value_labels", []),
                missing_rules=item.get("missing_rules", []),
                time=item.get("time"),
                notes=item.get("notes", []),
                values=[row.get(item["name"]) for row in rows],
            )
        )
    return CompiledResult(
        columns=columns,
        row_count=len(rows),
        overrides_applied=data.get("overrides", []),
        notes=[],
    )
