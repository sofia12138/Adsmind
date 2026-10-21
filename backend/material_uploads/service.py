"""Validation and state transitions for verified material uploads."""
from __future__ import annotations

import hashlib
import math
import re
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import PurePath
from typing import BinaryIO, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from config import get_settings
from . import repository
from .storage import get_storage


class PrepareInput(BaseModel):
    material_id: int = Field(gt=0)
    version_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=128)
    mode: Literal["auto", "direct", "multipart"] = "auto"

    @field_validator("idempotency_key")
    @classmethod
    def safe_key(cls, value: str) -> str:
        clean = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9._:-]+", clean):
            raise ValueError("幂等键只能包含字母、数字和 ._:-")
        return clean


class CompleteInput(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)


def _future() -> datetime:
    return datetime.now() + timedelta(seconds=get_settings().material_upload_session_ttl_seconds)


def _expired(row: dict) -> bool:
    value = row["expires_at"]
    return value <= datetime.now() if isinstance(value, datetime) else datetime.fromisoformat(str(value)) <= datetime.now()


def _public(row: dict) -> dict:
    result = dict(row)
    result.pop("storage_key", None)
    result["progress"] = 100 if row["status"] == "uploaded" else min(99, round(100 * int(row.get("received_size_bytes") or 0) / max(1, int(row["expected_size_bytes"]))))
    result["upload"] = {
        "method": "PUT",
        "direct_url": f"/api/material-uploads/{row['id']}/content" if row["upload_mode"] == "direct" else None,
        "part_url_template": f"/api/material-uploads/{row['id']}/parts/{{part_number}}" if row["upload_mode"] == "multipart" else None,
        "complete_url": f"/api/material-uploads/{row['id']}/complete",
        "expires_at": row["expires_at"],
    }
    return result


def prepare(data: PrepareInput, username: str) -> dict:
    existing = repository.find_by_idempotency(data.idempotency_key)
    if existing:
        if existing["material_id"] != data.material_id or existing["version_id"] != data.version_id:
            raise HTTPException(409, "幂等键已用于另一素材版本")
        return _public(existing)
    version = repository.get_version_for_upload(data.material_id, data.version_id)
    if not version:
        raise HTTPException(404, "素材版本不存在")
    if version["upload_status"] == "uploaded":
        raise HTTPException(409, "素材版本已经上传并验证")
    checksum = (version.get("checksum_sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise HTTPException(422, "上传前必须登记有效的 SHA-256")
    settings = get_settings()
    size = int(version["size_bytes"])
    if size > settings.material_storage_max_bytes:
        raise HTTPException(413, "文件大小超过允许上限")
    part_size = max(1024 * 1024, settings.material_upload_part_size_bytes)
    mode = data.mode
    if mode == "auto":
        mode = "multipart" if size > part_size else "direct"
    parts = math.ceil(size / part_size) if mode == "multipart" else 0
    storage = get_storage()
    if not storage.writable:
        raise HTTPException(503, "云存储适配器仅完成配置接口，当前未启用远程写入")
    upload_id = str(uuid.uuid4())
    key = storage.object_key(
        tenant_id=int(version["tenant_id"]), application_id=_scope_application_id(),
        material_id=data.material_id, version_id=data.version_id, upload_id=upload_id,
        extension=str(version.get("file_extension") or PurePath(version["source_filename"]).suffix),
    )
    row = repository.create_upload({
        "id": upload_id, "material_id": data.material_id, "version_id": data.version_id,
        "idempotency_key": data.idempotency_key, "upload_mode": mode,
        "storage_backend": storage.name, "storage_key": key,
        "expected_size_bytes": size, "expected_mime_type": version["mime_type"],
        "expected_checksum_sha256": checksum, "part_size_bytes": part_size if parts else None,
        "created_by": username, "expires_at": _future(),
    }, parts)
    return _public(row)


def _scope_application_id() -> int:
    from core.isolation import require_scope
    return require_scope(application=True).application_id  # type: ignore[return-value]


def get(upload_id: str) -> dict:
    row = repository.get_upload(upload_id)
    if not row:
        raise HTTPException(404, "上传会话不存在")
    if row["status"] in {"prepared", "uploading", "verifying"} and _expired(row):
        row = repository.mark_expired(upload_id) or row
    result = _public(row)
    if row["upload_mode"] == "multipart":
        result["parts"] = repository.list_parts(upload_id)
        result["received_size_bytes"] = sum(int(part["size_bytes"]) for part in result["parts"] if part["status"] == "uploaded")
        result["progress"] = min(99, round(100 * result["received_size_bytes"] / max(1, int(row["expected_size_bytes"]))))
    return result


def list_uploads(material_id: int | None = None) -> list[dict]:
    return [_public(row) for row in repository.list_uploads(material_id)]


def _require_writable(upload_id: str, mode: str) -> dict:
    row = repository.get_upload(upload_id)
    if not row:
        raise HTTPException(404, "上传会话不存在")
    if row["upload_mode"] != mode:
        raise HTTPException(409, "上传模式不匹配")
    if row["status"] not in {"prepared", "uploading"}:
        raise HTTPException(409, f"当前状态不允许上传：{row['status']}")
    if _expired(row):
        repository.mark_expired(upload_id)
        raise HTTPException(410, "上传会话已过期")
    return row


def upload_direct(upload_id: str, stream: BinaryIO, username: str) -> dict:
    row = _require_writable(upload_id, "direct")
    expected = int(row["expected_size_bytes"])
    with tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024) as buffered:
        size = 0
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > expected:
                repository.mark_failed(upload_id, "size_mismatch", "实际文件大于登记大小", username)
                raise HTTPException(422, "实际文件大小与登记值不一致")
            buffered.write(chunk)
        buffered.seek(0)
        get_storage().write_direct(row["storage_key"], buffered)
    if not repository.mark_direct_received(upload_id, size, username):
        raise HTTPException(409, "上传会话状态已变化")
    return get(upload_id)


def upload_part(upload_id: str, part_number: int, stream: BinaryIO, username: str) -> dict:
    row = _require_writable(upload_id, "multipart")
    if part_number < 1 or part_number > int(row["part_count"]):
        raise HTTPException(404, "分片不存在")
    expected = int(row["part_size_bytes"])
    with tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024) as buffered:
        digest = hashlib.sha256(); size = 0
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk); size += len(chunk); buffered.write(chunk)
            if size > expected:
                raise HTTPException(422, "分片大小不符合会话约定")
        last = part_number == int(row["part_count"])
        if size <= 0 or size > expected or (not last and size != expected):
            raise HTTPException(422, "分片大小不符合会话约定")
        buffered.seek(0)
        get_storage().write_part(row["storage_key"], part_number, buffered)
    if not repository.record_part(upload_id, part_number, size, digest.hexdigest(), username):
        raise HTTPException(409, "上传会话状态已变化")
    return get(upload_id)


def complete(upload_id: str, data: CompleteInput, username: str) -> dict:
    row = repository.get_upload(upload_id)
    if not row:
        raise HTTPException(404, "上传会话不存在")
    if row["idempotency_key"] != data.idempotency_key:
        raise HTTPException(409, "完成回调幂等键不匹配")
    if row["status"] == "uploaded":
        return _public(row)
    if row["status"] not in {"prepared", "uploading", "verifying"}:
        raise HTTPException(409, f"当前状态不允许完成：{row['status']}")
    if _expired(row):
        repository.mark_expired(upload_id)
        raise HTTPException(410, "上传会话已过期")
    storage = get_storage()
    if row["upload_mode"] == "multipart":
        parts = repository.list_parts(upload_id)
        if len(parts) != int(row["part_count"]) or any(part["status"] != "uploaded" for part in parts):
            raise HTTPException(409, "仍有分片未上传")
        storage.assemble(row["storage_key"], int(row["part_count"]))
    try:
        actual = storage.inspect(row["storage_key"], _version_filename(row))
    except FileNotFoundError:
        repository.mark_failed(upload_id, "object_missing", "未找到上传对象", username)
        raise HTTPException(422, "未找到上传对象") from None
    error = None
    if actual.size_bytes != int(row["expected_size_bytes"]):
        error = "文件大小校验失败"
    elif actual.checksum_sha256 != row["expected_checksum_sha256"]:
        error = "SHA-256 校验失败"
    elif actual.detected_mime_type != row["expected_mime_type"]:
        error = f"MIME 校验失败：检测为 {actual.detected_mime_type}"
    if error:
        repository.mark_failed(upload_id, "verification_failed", error, username)
        raise HTTPException(422, error)
    finalized = repository.finalize(upload_id, size=actual.size_bytes, checksum=actual.checksum_sha256, backend=row["storage_backend"], storage_key=row["storage_key"], username=username)
    if not finalized:
        raise HTTPException(409, "素材版本状态已变化")
    return _public(finalized)


def _version_filename(row: dict) -> str:
    version = repository.get_version_for_upload(int(row["material_id"]), int(row["version_id"]))
    if not version:
        raise HTTPException(404, "素材版本不存在")
    return str(version["source_filename"])


def retry(upload_id: str, username: str) -> dict:
    row = repository.retry(upload_id, _future(), username)
    if not row:
        raise HTTPException(409, "只有失败或过期会话可以重试")
    return _public(row)
