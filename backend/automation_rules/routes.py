"""API for review-only automation rules and dry-run evaluations."""
from fastapi import APIRouter, Depends, HTTPException

from auth import User, get_current_user
from core.application import ApplicationCtx, require_application_role
from services.oplog_service import log_operation
from . import repository, service


router = APIRouter(prefix="/automation-rules", tags=["自动化规则"])
read_application = require_application_role("owner", "admin", "editor", "viewer")
write_application = require_application_role("owner", "admin", "editor")


@router.get("")
def list_rules(_: ApplicationCtx = Depends(read_application)):
    return {"data": repository.list_rules()}


@router.post("", status_code=201)
def create_rule(body: service.RuleCreate, user: User = Depends(get_current_user),
                _: ApplicationCtx = Depends(write_application)):
    row = service.create_rule(body, user.username)
    log_operation(username=user.username, action="创建自动化规则", target_type="automation_rule",
                  target_id=row["id"], after_data={"version": 1, "status": row["status"], "dry_run_only": True})
    return {"data": row}


@router.get("/{rule_id}")
def get_rule(rule_id: str, _: ApplicationCtx = Depends(read_application)):
    row = repository.get_rule(rule_id)
    if not row:
        raise HTTPException(404, "自动化规则不存在")
    return {"data": row, "versions": repository.list_versions(rule_id),
            "audit": repository.list_audit("rule", rule_id)}


@router.put("/{rule_id}")
def update_rule(rule_id: str, body: service.RuleUpdate, user: User = Depends(get_current_user),
                _: ApplicationCtx = Depends(write_application)):
    row = service.update_rule(rule_id, body, user.username)
    log_operation(username=user.username, action="创建自动化规则版本", target_type="automation_rule",
                  target_id=rule_id, after_data={"version": row["current_version"], "status": row["status"], "dry_run_only": True})
    return {"data": row}


@router.get("/{rule_id}/evaluations")
def list_evaluations(rule_id: str, _: ApplicationCtx = Depends(read_application)):
    if not repository.get_rule(rule_id):
        raise HTTPException(404, "自动化规则不存在")
    return {"data": repository.list_evaluations(rule_id)}


@router.post("/{rule_id}/evaluations", status_code=201)
def evaluate(rule_id: str, body: service.EvaluationInput, version: int | None = None,
             user: User = Depends(get_current_user),
             _: ApplicationCtx = Depends(write_application)):
    row = service.evaluate(rule_id, version, body, user.username)
    log_operation(username=user.username, action="试跑自动化规则", target_type="automation_rule_evaluation",
                  target_id=row["id"], after_data={"status": row["status"], "input_snapshot_hash": row["input_snapshot_hash"],
                  "dry_run": True, "external_write_authorized": False})
    return {"data": row}


@router.get("/evaluations/{evaluation_id}/detail")
def evaluation_detail(evaluation_id: str, _: ApplicationCtx = Depends(read_application)):
    row = repository.get_evaluation(evaluation_id)
    if not row:
        raise HTTPException(404, "规则评估记录不存在")
    return {"data": row, "audit": repository.list_audit("evaluation", evaluation_id)}
