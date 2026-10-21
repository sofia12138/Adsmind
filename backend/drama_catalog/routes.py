"""HTTP API for tenant drama masters and application references."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import User, get_current_user
from core.application import ApplicationCtx, get_current_application
from services import panel_service
from . import repository, service


router = APIRouter(prefix="/drama-catalog", tags=["剧目库"])


def reader(user: User = Depends(get_current_user)) -> User:
    if "creatives" not in panel_service.resolve_allowed_panels(user.username, user.role):
        raise HTTPException(403, "无剧目库访问权限")
    return user


def writer(user: User = Depends(reader)) -> User:
    if user.role not in ("super_admin", "admin", "optimizer", "designer"):
        raise HTTPException(403, "无剧目库编辑权限")
    return user


@router.get("/masters")
def search_masters(
    query: str = Query(default="", max_length=255), page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100), _: User = Depends(reader),
):
    return repository.search_masters(query.strip(), page, page_size)


@router.post("/masters", status_code=201)
def create_master(data: service.MasterInput, user: User = Depends(writer)):
    return service.create_master(data, user.username)


@router.get("/masters/{master_id}")
def get_master(master_id: int, _: User = Depends(reader)):
    row = repository.get_master(master_id)
    if not row:
        raise HTTPException(404, "剧目不存在")
    return row


@router.put("/masters/{master_id}")
def update_master(master_id: int, data: service.MasterUpdate, _: User = Depends(writer)):
    return service.update_master(master_id, data)


@router.delete("/masters/{master_id}")
def delete_master(master_id: int, _: User = Depends(writer)):
    service.delete_master(master_id)
    return {"ok": True}


@router.get("/references")
def list_references(
    query: str = Query(default="", max_length=255), page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100), _: User = Depends(reader),
    __: ApplicationCtx = Depends(get_current_application),
):
    return repository.list_references(query.strip(), page, page_size)


@router.post("/references", status_code=201)
def attach_drama(
    data: service.ReferenceInput, user: User = Depends(writer),
    _: ApplicationCtx = Depends(get_current_application),
):
    return service.attach(data, user.username)


@router.patch("/references/{master_id}")
def update_reference(
    master_id: int, data: service.ReferenceUpdate, _: User = Depends(writer),
    __: ApplicationCtx = Depends(get_current_application),
):
    return service.update_reference(master_id, data)


@router.delete("/references/{master_id}")
def detach_drama(
    master_id: int, _: User = Depends(writer),
    __: ApplicationCtx = Depends(get_current_application),
):
    service.detach(master_id)
    return {"ok": True}
