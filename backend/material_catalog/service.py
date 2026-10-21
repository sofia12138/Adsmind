"""Validation and business rules for material masters, versions and references."""
from __future__ import annotations

import re
from pathlib import PurePath
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from pymysql.err import IntegrityError

from . import repository
from .storage import get_storage


def _tags(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = " ".join(value.strip().split())
        key = clean.casefold()
        if clean and key not in seen:
            seen.add(key); result.append(clean)
    return result


class MasterInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    material_type: Literal["video", "image", "audio", "other"]
    drama_id: int | None = Field(default=None, gt=0)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    status: Literal["active", "archived"] = "active"

    @field_validator("name", "description")
    @classmethod
    def trim(cls, value: str) -> str:
        return " ".join(value.strip().split()) if "\n" not in value else value.strip()

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value: list[str]) -> list[str]:
        return _tags(value)


class MasterUpdate(MasterInput):
    revision: int = Field(ge=1)


class VersionInput(BaseModel):
    source_filename: str = Field(min_length=1, max_length=512)
    mime_type: str = Field(min_length=1, max_length=127)
    size_bytes: int = Field(gt=0)
    checksum_sha256: str | None = None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    duration_ms: int | None = Field(default=None, gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=1000)

    @field_validator("source_filename")
    @classmethod
    def filename_only(cls, value: str) -> str:
        value = value.strip()
        if PurePath(value).name != value or value in (".", "..") or "\\" in value:
            raise ValueError("文件名不能包含路径")
        return value

    @field_validator("mime_type")
    @classmethod
    def clean_mime(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("checksum_sha256")
    @classmethod
    def checksum(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        clean = value.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", clean):
            raise ValueError("SHA-256 必须是 64 位十六进制")
        return clean

    @model_validator(mode="after")
    def dimensions_match_type(self):
        return self


class ReferenceInput(BaseModel):
    material_id: int = Field(gt=0)
    selected_version_id: int | None = Field(default=None, gt=0)
    selection_mode: Literal["latest", "pinned"] = "latest"
    status: Literal["selected", "paused"] = "selected"
    notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def pinned_requires_version(self):
        if self.selection_mode == "pinned" and self.selected_version_id is None:
            raise ValueError("固定版本模式必须选择版本")
        if self.selection_mode == "latest" and self.selected_version_id is not None:
            raise ValueError("跟随最新版本时不能指定版本")
        return self


class ReferenceUpdate(BaseModel):
    selected_version_id: int | None = Field(default=None, gt=0)
    selection_mode: Literal["latest", "pinned"] = "latest"
    status: Literal["selected", "paused"] = "selected"
    notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def pinned_requires_version(self):
        ReferenceInput(material_id=1, **self.model_dump())
        return self


def _validate_drama(drama_id: int | None) -> None:
    if drama_id is not None and not repository.get_drama(drama_id):
        raise HTTPException(404, "剧目不存在")


def create_master(data: MasterInput, username: str) -> dict:
    _validate_drama(data.drama_id)
    return repository.create_master({**data.model_dump(), "created_by": username})


def update_master(material_id: int, data: MasterUpdate) -> dict:
    if not repository.get_master(material_id):
        raise HTTPException(404, "素材不存在")
    _validate_drama(data.drama_id)
    row = repository.update_master(material_id, data.model_dump(exclude={"revision"}), data.revision)
    if not row:
        raise HTTPException(409, "素材已被其他人更新，请刷新后重试")
    return row


def register_version(material_id: int, data: VersionInput, username: str) -> dict:
    values = data.model_dump()
    values["file_extension"] = PurePath(data.source_filename).suffix.lower().lstrip(".")[:32]
    values["metadata_json"] = values.pop("metadata")
    values["created_by"] = username
    row = repository.create_version(material_id, values)
    if not row:
        raise HTTPException(404, "素材不存在")
    reservation = get_storage().reserve(tenant_id=row["tenant_id"], material_id=material_id, version_id=row["id"], filename=data.source_filename)
    return {**row, "upload": reservation.as_dict()}


def attach(data: ReferenceInput, username: str) -> dict:
    if not repository.get_master(data.material_id):
        raise HTTPException(404, "素材不存在")
    try:
        row = repository.attach(data.material_id, {**data.model_dump(exclude={"material_id"}), "created_by": username})
    except Exception as exc:
        if getattr(exc, "args", [None])[0] == 1062:
            raise HTTPException(409, "当前应用已选择该素材") from exc
        raise
    if not row:
        raise HTTPException(404, "素材或版本不存在")
    return row


def update_reference(material_id: int, data: ReferenceUpdate) -> dict:
    row = repository.update_reference(material_id, data.model_dump())
    if not row:
        raise HTTPException(404, "应用素材引用不存在")
    return row


def detach(material_id: int) -> None:
    try:
        removed = repository.detach(material_id)
    except IntegrityError as exc:
        if exc.args and exc.args[0] == 1451:
            raise HTTPException(409, "素材仍被创意组引用，请先从创意组移除") from exc
        raise
    if not removed:
        raise HTTPException(404, "应用素材引用不存在")
