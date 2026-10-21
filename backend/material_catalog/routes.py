"""Material catalog HTTP API."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import User, get_current_user
from core.application import ApplicationCtx, get_current_application
from services import oplog_service, panel_service
from . import repository, service


router = APIRouter(prefix="/material-catalog", tags=["素材库"])


def reader(user: User = Depends(get_current_user)) -> User:
    if "creatives" not in panel_service.resolve_allowed_panels(user.username, user.role):
        raise HTTPException(403, "无素材库访问权限")
    return user


def writer(user: User = Depends(reader)) -> User:
    if user.role not in ("super_admin", "admin", "optimizer", "designer"):
        raise HTTPException(403, "无素材库编辑权限")
    return user


def _audit(user: User, action: str, target: int, after: dict | None = None) -> None:
    safe_after = json.loads(json.dumps(after, default=str)) if after is not None else None
    oplog_service.log_operation(username=user.username, action=action, target_type="material", target_id=str(target), after_data=safe_after)


@router.get("/masters")
def list_masters(query: str = Query("", max_length=255), status: str = Query("", pattern="^(|active|archived)$"), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), _: User = Depends(reader)):
    return repository.list_masters(query.strip(), status, page, page_size)


@router.post("/masters", status_code=201)
def create_master(data: service.MasterInput, user: User = Depends(writer)):
    row = service.create_master(data, user.username); _audit(user, "创建素材主档", row["id"], row); return row


@router.get("/masters/{material_id}")
def get_master(material_id: int, _: User = Depends(reader)):
    row = repository.get_master(material_id)
    if not row: raise HTTPException(404, "素材不存在")
    versions = repository.list_versions(material_id) or []
    return {**row, "versions": versions}


@router.put("/masters/{material_id}")
def update_master(material_id: int, data: service.MasterUpdate, user: User = Depends(writer)):
    row = service.update_master(material_id, data); _audit(user, "更新素材主档", material_id, row); return row


@router.get("/masters/{material_id}/versions")
def list_versions(material_id: int, _: User = Depends(reader)):
    rows = repository.list_versions(material_id)
    if rows is None: raise HTTPException(404, "素材不存在")
    return {"items": rows}


@router.post("/masters/{material_id}/versions", status_code=201)
def register_version(material_id: int, data: service.VersionInput, user: User = Depends(writer)):
    row = service.register_version(material_id, data, user.username); _audit(user, "登记素材版本", row["id"], {"material_id": material_id, "upload_status": row["upload_status"]}); return row


@router.get("/references")
def list_references(page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=100), _: User = Depends(reader), __: ApplicationCtx = Depends(get_current_application)):
    return repository.list_references(page, page_size)


@router.post("/references", status_code=201)
def attach(data: service.ReferenceInput, user: User = Depends(writer), _: ApplicationCtx = Depends(get_current_application)):
    row = service.attach(data, user.username); _audit(user, "选择应用素材", data.material_id, row); return row


@router.patch("/references/{material_id}")
def update_reference(material_id: int, data: service.ReferenceUpdate, user: User = Depends(writer), _: ApplicationCtx = Depends(get_current_application)):
    row = service.update_reference(material_id, data); _audit(user, "更新应用素材选择", material_id, row); return row


@router.delete("/references/{material_id}")
def detach(material_id: int, user: User = Depends(writer), _: ApplicationCtx = Depends(get_current_application)):
    service.detach(material_id); _audit(user, "移除应用素材选择", material_id); return {"ok": True}
