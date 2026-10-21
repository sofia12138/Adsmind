"""HTTP API for internal application ad creation drafts."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import User, get_current_user
from core.application import ApplicationCtx, require_application_role
from services.oplog_service import log_operation
from . import service


router = APIRouter(prefix="/ad-creation-drafts", tags=["应用广告创建草稿"])
read_application = require_application_role("owner", "admin", "editor", "viewer")
write_application = require_application_role("owner", "admin", "editor")


class ReadyInput(BaseModel):
    revision: int = Field(ge=1)


@router.get("")
def list_drafts(_: ApplicationCtx = Depends(read_application)):
    return {"data": service.list_all()}


@router.post("", status_code=201)
def create_draft(body: service.DraftInput, user: User = Depends(get_current_user),
                 _: ApplicationCtx = Depends(write_application)):
    row = service.create(body, user.username)
    log_operation(username=user.username, action="创建应用广告草稿",
                  target_type="ad_creation_draft", target_id=row["id"],
                  after_data={"status": row["status"], "revision": row["revision"]})
    return {"data": row}


@router.get("/{draft_id}")
def get_draft(draft_id: str, _: ApplicationCtx = Depends(read_application)):
    return {"data": service.get(draft_id)}


@router.put("/{draft_id}")
def update_draft(draft_id: str, body: service.DraftUpdate,
                 user: User = Depends(get_current_user),
                 _: ApplicationCtx = Depends(write_application)):
    before = service.get(draft_id)
    row = service.update(draft_id, body)
    log_operation(username=user.username, action="更新应用广告草稿",
                  target_type="ad_creation_draft", target_id=draft_id,
                  before_data={"revision": before["revision"]},
                  after_data={"revision": row["revision"]})
    return {"data": row}


@router.post("/{draft_id}/check")
def check_draft(draft_id: str, _: ApplicationCtx = Depends(read_application)):
    return {"data": service.check(draft_id)}


@router.post("/{draft_id}/ready")
def ready_draft(draft_id: str, body: ReadyInput,
                user: User = Depends(get_current_user),
                _: ApplicationCtx = Depends(write_application)):
    row = service.mark_ready(draft_id, body.revision)
    log_operation(username=user.username, action="标记应用广告草稿准备就绪",
                  target_type="ad_creation_draft", target_id=draft_id,
                  after_data={"revision": row["revision"], "snapshot_hash": row["execution_snapshot_hash"]})
    return {"data": row}


@router.get("/{draft_id}/execution-snapshot")
def execution_snapshot(draft_id: str, _: ApplicationCtx = Depends(read_application)):
    row = service.get(draft_id)
    if row["status"] != "READY" or not row.get("execution_snapshot"):
        raise HTTPException(409, "草稿尚未准备就绪，没有可供平台执行阶段读取的快照")
    return {
        "data": row["execution_snapshot"],
        "sha256": row["execution_snapshot_hash"],
        "immutable": True,
        "external_write_authorized": False,
    }
