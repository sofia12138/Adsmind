"""Application creative-group API."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from auth import User, get_current_user
from core.application import ApplicationCtx, require_application_role
from services.oplog_service import log_operation
from . import service


router = APIRouter(prefix="/creative-groups", tags=["创意组"])
read_application = require_application_role("owner", "admin", "editor", "viewer")
write_application = require_application_role("owner", "admin", "editor")


@router.get("")
def list_groups(_: ApplicationCtx = Depends(read_application)):
    return {"data": service.list_groups()}


@router.get("/{group_id}")
def get_group(group_id: int, _: ApplicationCtx = Depends(read_application)):
    return {"data": service.get_group(group_id)}


@router.post("", status_code=201)
def create_group(
    body: service.CreativeGroupInput,
    user: User = Depends(get_current_user),
    _: ApplicationCtx = Depends(write_application),
):
    row = service.create_group(body, user.username)
    log_operation(
        username=user.username, action="创建创意组", target_type="creative_group",
        target_id=str(row["id"]), after_data={"name": row["name"], "materials": row["asset_refs"]},
    )
    return {"data": row}


@router.put("/{group_id}")
def update_group(
    group_id: int,
    body: service.CreativeGroupInput,
    user: User = Depends(get_current_user),
    _: ApplicationCtx = Depends(write_application),
):
    before = service.get_group(group_id)
    row = service.update_group(group_id, body)
    log_operation(
        username=user.username, action="更新创意组", target_type="creative_group",
        target_id=str(group_id), before_data={"name": before["name"], "materials": before["asset_refs"]},
        after_data={"name": row["name"], "materials": row["asset_refs"]},
    )
    return {"data": row}


@router.delete("/{group_id}")
def delete_group(
    group_id: int,
    user: User = Depends(get_current_user),
    _: ApplicationCtx = Depends(write_application),
):
    before = service.get_group(group_id)
    service.delete_group(group_id)
    log_operation(
        username=user.username, action="删除创意组", target_type="creative_group",
        target_id=str(group_id), before_data={"name": before["name"], "materials": before["asset_refs"]},
    )
    return {"ok": True}
