"""Validation and use cases for the tenant drama catalog."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from urllib.parse import urlparse

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from . import repository


def _clean_list(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = " ".join(value.strip().split())
        key = unicodedata.normalize("NFKC", clean).casefold()
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return result


def normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).strip()).casefold()


def _validate_cover(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("封面地址必须是有效的 HTTP(S) URL")
    return value


class MasterInput(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    original_language: str = Field(default="", max_length=32)
    region: str = Field(default="", max_length=64)
    genres: list[str] = Field(default_factory=list, max_length=20)
    synopsis: str = Field(default="", max_length=5000)
    cover_url: str = Field(default="", max_length=1024)

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str) -> str:
        clean = " ".join(value.strip().split())
        if not clean:
            raise ValueError("剧名不能为空")
        return clean

    @field_validator("aliases", "genres")
    @classmethod
    def clean_lists(cls, value: list[str]) -> list[str]:
        return _clean_list(value)

    @field_validator("cover_url")
    @classmethod
    def valid_cover(cls, value: str) -> str:
        return _validate_cover(value)

    @field_validator("original_language", "region", "synopsis")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()


class MasterUpdate(MasterInput):
    revision: int = Field(ge=1)


class ReferenceInput(BaseModel):
    drama_id: int = Field(gt=0)
    display_title: str = Field(default="", max_length=255)
    status: str = Field(default="active", pattern="^(active|paused)$")
    notes: str = Field(default="", max_length=2000)

    @field_validator("display_title", "notes")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()


class ReferenceUpdate(BaseModel):
    display_title: str = Field(default="", max_length=255)
    status: str = Field(default="active", pattern="^(active|paused)$")
    notes: str = Field(default="", max_length=2000)

    @field_validator("display_title", "notes")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()


def _master_values(data: MasterInput, username: str = "") -> dict:
    normalized = normalize_title(data.title)
    fingerprint_payload = {
        "title": normalized,
        "aliases": sorted(normalize_title(x) for x in data.aliases),
        "original_language": data.original_language.casefold(),
    }
    return {
        **data.model_dump(),
        "normalized_title": normalized,
        "content_fingerprint": hashlib.sha256(
            json.dumps(fingerprint_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "created_by": username,
    }


def create_master(data: MasterInput, username: str) -> dict:
    values = _master_values(data, username)
    if repository.find_duplicate(values["normalized_title"], values["content_fingerprint"]):
        raise HTTPException(409, "当前租户已存在相同剧目")
    try:
        return repository.create_master(values)
    except Exception as exc:
        # The database unique keys close the race between the duplicate check and INSERT.
        if getattr(exc, "args", [None])[0] == 1062:
            raise HTTPException(409, "当前租户已存在相同剧目") from exc
        raise


def update_master(master_id: int, data: MasterUpdate) -> dict:
    if not repository.get_master(master_id):
        raise HTTPException(404, "剧目不存在")
    values = _master_values(data)
    if repository.find_duplicate(values["normalized_title"], values["content_fingerprint"], exclude_id=master_id):
        raise HTTPException(409, "当前租户已存在相同剧目")
    try:
        row = repository.update_master(master_id, values, data.revision)
    except Exception as exc:
        if getattr(exc, "args", [None])[0] == 1062:
            raise HTTPException(409, "当前租户已存在相同剧目") from exc
        raise
    if not row:
        raise HTTPException(409, "剧目已被其他人更新，请刷新后重试")
    return row


def delete_master(master_id: int) -> None:
    if not repository.get_master(master_id):
        raise HTTPException(404, "剧目不存在")
    if repository.master_has_references(master_id):
        raise HTTPException(409, "剧目仍被应用引用，请先解除引用")
    if not repository.delete_master(master_id):
        raise HTTPException(404, "剧目不存在")


def attach(data: ReferenceInput, username: str) -> dict:
    if not repository.get_master(data.drama_id):
        raise HTTPException(404, "剧目不存在")
    values = {**data.model_dump(exclude={"drama_id"}), "created_by": username}
    try:
        row = repository.attach(data.drama_id, values)
    except Exception as exc:
        if getattr(exc, "args", [None])[0] == 1062:
            raise HTTPException(409, "当前应用已引用该剧目") from exc
        raise
    if not row:
        raise HTTPException(404, "剧目不存在")
    return row


def update_reference(master_id: int, data: ReferenceUpdate) -> dict:
    row = repository.update_reference(master_id, data.model_dump())
    if not row:
        raise HTTPException(404, "应用剧目引用不存在")
    return row


def detach(master_id: int) -> None:
    if not repository.detach(master_id):
        raise HTTPException(404, "应用剧目引用不存在")
