"""Private storage boundary for material uploads.

Only the local adapter writes bytes. The S3-compatible adapter deliberately
exposes configuration/capability metadata without importing a cloud SDK or
contacting a remote account.
"""
from __future__ import annotations

import hashlib
import mimetypes
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from config import get_settings


CHUNK = 1024 * 1024


@dataclass(frozen=True)
class StoredObject:
    size_bytes: int
    checksum_sha256: str
    detected_mime_type: str


class StorageAdapter(Protocol):
    name: str
    writable: bool

    def object_key(self, *, tenant_id: int, application_id: int, material_id: int, version_id: int, upload_id: str, extension: str) -> str: ...
    def write_direct(self, key: str, stream: BinaryIO) -> int: ...
    def write_part(self, key: str, part_number: int, stream: BinaryIO) -> int: ...
    def assemble(self, key: str, part_count: int) -> None: ...
    def inspect(self, key: str, filename: str) -> StoredObject: ...


def _suffix(value: str) -> str:
    clean = value.strip().lower().lstrip(".")
    return clean[:16] if re.fullmatch(r"[a-z0-9]{0,16}", clean) else ""


class LocalStorage:
    name = "local"
    writable = True

    def __init__(self, root: str | Path | None = None):
        configured = Path(root or get_settings().material_storage_local_root)
        self.root = (configured if configured.is_absolute() else Path.cwd() / configured).resolve()

    def object_key(self, *, tenant_id: int, application_id: int, material_id: int, version_id: int, upload_id: str, extension: str) -> str:
        suffix = _suffix(extension)
        filename = f"{upload_id}.{suffix}" if suffix else upload_id
        return f"tenants/{tenant_id}/applications/{application_id}/materials/{material_id}/versions/{version_id}/{filename}"

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root != path and self.root not in path.parents:
            raise ValueError("storage key escapes local root")
        return path

    def _copy(self, destination: Path, stream: BinaryIO) -> int:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".uploading")
        total = 0
        with temporary.open("wb") as output:
            while chunk := stream.read(CHUNK):
                total += len(chunk)
                output.write(chunk)
        os.replace(temporary, destination)
        return total

    def write_direct(self, key: str, stream: BinaryIO) -> int:
        return self._copy(self._path(key), stream)

    def write_part(self, key: str, part_number: int, stream: BinaryIO) -> int:
        if part_number < 1:
            raise ValueError("part number must be positive")
        return self._copy(self._path(f"{key}.parts/{part_number:08d}"), stream)

    def assemble(self, key: str, part_count: int) -> None:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".assembling")
        with temporary.open("wb") as output:
            for number in range(1, part_count + 1):
                part = self._path(f"{key}.parts/{number:08d}")
                with part.open("rb") as incoming:
                    while chunk := incoming.read(CHUNK):
                        output.write(chunk)
        os.replace(temporary, destination)
        for number in range(1, part_count + 1):
            self._path(f"{key}.parts/{number:08d}").unlink(missing_ok=True)
        try:
            self._path(f"{key}.parts").rmdir()
        except OSError:
            pass

    def inspect(self, key: str, filename: str) -> StoredObject:
        digest = hashlib.sha256()
        size = 0
        path = self._path(key)
        signature = b""
        with path.open("rb") as incoming:
            while chunk := incoming.read(CHUNK):
                if not signature:
                    signature = chunk[:32]
                digest.update(chunk)
                size += len(chunk)
        mime = _detect_mime(signature, filename)
        return StoredObject(size, digest.hexdigest(), mime)


class S3CompatibleStorage:
    """Configuration contract only; no remote writes are performed here."""

    name = "s3-compatible"
    writable = False

    @property
    def configured(self) -> bool:
        settings = get_settings()
        return bool(settings.material_storage_endpoint and settings.material_storage_bucket and settings.material_storage_region)

    def object_key(self, **values: object) -> str:
        return LocalStorage("/tmp/adsmind-object-key-only").object_key(**values)  # pure key formatting; no write

    def write_direct(self, key: str, stream: BinaryIO) -> int:
        raise RuntimeError("S3-compatible adapter is configuration-only")

    write_part = write_direct

    def assemble(self, key: str, part_count: int) -> None:
        raise RuntimeError("S3-compatible adapter is configuration-only")

    def inspect(self, key: str, filename: str) -> StoredObject:
        raise RuntimeError("S3-compatible adapter is configuration-only")


def get_storage() -> StorageAdapter:
    backend = get_settings().material_storage_backend.strip().lower()
    if backend == "local":
        return LocalStorage()
    if backend in {"s3", "s3-compatible", "oss"}:
        return S3CompatibleStorage()
    raise RuntimeError(f"unsupported material storage backend: {backend}")


def _detect_mime(signature: bytes, filename: str) -> str:
    """Small deterministic detector for the catalog's common media types."""
    if signature.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if signature.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if signature.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if signature.startswith(b"RIFF") and signature[8:12] == b"WEBP":
        return "image/webp"
    if len(signature) >= 12 and signature[4:8] == b"ftyp":
        return "video/mp4"
    if signature.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    if signature.startswith(b"ID3") or signature.startswith(b"\xff\xfb"):
        return "audio/mpeg"
    if signature.startswith(b"%PDF-"):
        return "application/pdf"
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"
