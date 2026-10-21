"""HTTP endpoints for local verified material uploads."""
from __future__ import annotations

import tempfile

from fastapi import APIRouter, Depends, Query, Request

from auth import User
from core.application import ApplicationCtx, get_current_application
from material_catalog.routes import reader, writer
from . import service


router = APIRouter(prefix="/material-uploads", tags=["素材上传"])


async def _body(request: Request):
    temporary = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
    async for chunk in request.stream():
        temporary.write(chunk)
    temporary.seek(0)
    return temporary


@router.post("/prepare", status_code=201)
def prepare(data: service.PrepareInput, user: User = Depends(writer), _: ApplicationCtx = Depends(get_current_application)):
    return service.prepare(data, user.username)


@router.get("")
def list_uploads(material_id: int | None = Query(None, gt=0), _: User = Depends(reader), __: ApplicationCtx = Depends(get_current_application)):
    return {"items": service.list_uploads(material_id)}


@router.get("/{upload_id}")
def get_upload(upload_id: str, _: User = Depends(reader), __: ApplicationCtx = Depends(get_current_application)):
    return service.get(upload_id)


@router.put("/{upload_id}/content")
async def upload_content(upload_id: str, request: Request, user: User = Depends(writer), _: ApplicationCtx = Depends(get_current_application)):
    body = await _body(request)
    try:
        return service.upload_direct(upload_id, body, user.username)
    finally:
        body.close()


@router.put("/{upload_id}/parts/{part_number}")
async def upload_part(upload_id: str, part_number: int, request: Request, user: User = Depends(writer), _: ApplicationCtx = Depends(get_current_application)):
    body = await _body(request)
    try:
        return service.upload_part(upload_id, part_number, body, user.username)
    finally:
        body.close()


@router.post("/{upload_id}/complete")
def complete(upload_id: str, data: service.CompleteInput, user: User = Depends(writer), _: ApplicationCtx = Depends(get_current_application)):
    return service.complete(upload_id, data, user.username)


@router.post("/{upload_id}/retry")
def retry(upload_id: str, user: User = Depends(writer), _: ApplicationCtx = Depends(get_current_application)):
    return service.retry(upload_id, user.username)
