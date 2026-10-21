"""HTTP API for preparation-only platform preflight."""
from fastapi import APIRouter, Depends, HTTPException

from auth import User, get_current_user
from core.application import ApplicationCtx, require_application_role
from services.oplog_service import log_operation
from . import repository, service


router = APIRouter(prefix="/platform-preflight", tags=["平台执行预检"])
read_application = require_application_role("owner", "admin", "editor", "viewer")
write_application = require_application_role("owner", "admin", "editor")


@router.get("/mappings/accounts")
def list_account_mappings(_: ApplicationCtx = Depends(read_application)):
    return {"data": repository.list_account_mappings()}


@router.put("/mappings/accounts")
def save_account_mapping(body: service.AccountMappingInput, user: User = Depends(get_current_user),
                         _: ApplicationCtx = Depends(write_application)):
    row = service.save_account_mapping(body, user.username)
    log_operation(username=user.username, action="保存平台账户映射", target_type="platform_account_mapping",
                  target_id=str(row["id"]), after_data={"platform": row["platform"], "account_id": row["account_id"], "status": row["status"]})
    return {"data": row}


@router.get("/mappings/materials")
def list_material_mappings(_: ApplicationCtx = Depends(read_application)):
    return {"data": repository.list_material_mappings()}


@router.put("/mappings/materials")
def save_material_mapping(body: service.MaterialMappingInput, user: User = Depends(get_current_user),
                          _: ApplicationCtx = Depends(write_application)):
    row = service.save_material_mapping(body, user.username)
    log_operation(username=user.username, action="保存平台素材映射", target_type="platform_material_mapping",
                  target_id=str(row["id"]), after_data={"platform": row["platform"], "account_id": row["account_id"], "material_id": row["material_id"], "version_id": row["version_id"], "upload_status": row["upload_status"]})
    return {"data": row}


@router.get("/runs")
def list_runs(draft_id: str | None = None, _: ApplicationCtx = Depends(read_application)):
    return {"data": repository.list_runs(draft_id)}


@router.get("/runs/{run_id}")
def get_run(run_id: str, _: ApplicationCtx = Depends(read_application)):
    row = repository.get_run(run_id)
    if not row:
        raise HTTPException(404, "预检记录不存在")
    return {"data": row, "audit": repository.list_audit(run_id)}


@router.post("/drafts/{draft_id}/runs", status_code=201)
def run_preflight(draft_id: str, body: service.PreflightInput,
                  user: User = Depends(get_current_user),
                  _: ApplicationCtx = Depends(write_application)):
    row = service.run(draft_id, body, user.username)
    log_operation(username=user.username, action="运行平台 dry-run 预检", target_type="platform_preflight",
                  target_id=row["id"], after_data={"status": row["status"], "snapshot_hash": row["snapshot_hash"],
                  "plan_hash": row["plan_hash"], "external_write_authorized": False})
    return {"data": row}


@router.post("/runs/{run_id}/execute")
def execute_is_disabled(run_id: str, user: User = Depends(get_current_user),
                        _: ApplicationCtx = Depends(write_application)):
    service.refuse_execute(run_id, user.username)
