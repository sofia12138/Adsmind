"""Storage boundary for material files.

This phase intentionally ships without a writable backend. Registration records
verified file metadata and remains pending until an explicitly configured safe
backend can reserve an upload target.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol


@dataclass(frozen=True)
class UploadReservation:
    backend: str
    available: bool
    status: str
    storage_key: str | None = None
    upload_url: str | None = None
    reason: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


class MaterialStorage(Protocol):
    def reserve(self, *, tenant_id: int, material_id: int, version_id: int, filename: str) -> UploadReservation: ...


class UnconfiguredStorage:
    def reserve(self, **_: object) -> UploadReservation:
        return UploadReservation(
            backend="unconfigured", available=False, status="pending_upload",
            reason="尚未配置安全的素材存储，当前仅登记文件元数据",
        )


def get_storage() -> MaterialStorage:
    return UnconfiguredStorage()
