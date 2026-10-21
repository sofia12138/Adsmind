"""Application-scoped account-group and naming-rule APIs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import User, get_current_user
from core.application import ApplicationCtx, require_application_role
from repositories import application_repository, user_repository
from services import account_group_service, naming_rule_service
from services.oplog_service import log_operation


router = APIRouter(tags=["应用配置"])


class AccountRefIn(BaseModel):
    platform: str = Field(min_length=1, max_length=32)
    account_id: str = Field(min_length=1, max_length=128)


class AccountGroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    account_refs: list[AccountRefIn] = Field(min_length=1)


class NamingRuleValueIn(BaseModel):
    pattern: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=500)


class NamingRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    rule: NamingRuleValueIn


read_application = require_application_role("owner", "admin", "editor", "viewer")
write_application = require_application_role("owner", "admin", "editor")


@router.get("/application-settings/access")
async def get_application_settings_access(
    user: User = Depends(get_current_user),
    application: ApplicationCtx = Depends(read_application),
):
    if user.role in ("super_admin", "admin"):
        role = "admin"
    else:
        row = user_repository.get_by_username(user.username)
        role = application_repository.get_member_role(application.id, int(row["id"])) if row else None
    return {"role": role, "can_write": role in ("owner", "admin", "editor")}


@router.get("/account-groups")
async def list_account_groups(_: ApplicationCtx = Depends(read_application)):
    return {"data": account_group_service.list_groups()}


@router.get("/account-groups/{group_id}")
async def get_account_group(group_id: int, _: ApplicationCtx = Depends(read_application)):
    row = account_group_service.get_group(group_id)
    if not row:
        raise HTTPException(status_code=404, detail="账户组不存在")
    return {"data": row}


@router.post("/account-groups", status_code=201)
async def create_account_group(
    body: AccountGroupIn,
    user: User = Depends(get_current_user),
    _: ApplicationCtx = Depends(write_application),
):
    try:
        row = account_group_service.create_group(
            name=body.name,
            account_refs=[ref.model_dump() for ref in body.account_refs],
            created_by=user.username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log_operation(username=user.username, action="创建账户组", target_type="account_group",
                  target_id=str(row["id"]), after_data={"name": row["name"]})
    return {"data": row}


@router.put("/account-groups/{group_id}")
async def update_account_group(
    group_id: int,
    body: AccountGroupIn,
    user: User = Depends(get_current_user),
    _: ApplicationCtx = Depends(write_application),
):
    try:
        row = account_group_service.update_group(
            group_id, name=body.name,
            account_refs=[ref.model_dump() for ref in body.account_refs],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="账户组不存在")
    log_operation(username=user.username, action="更新账户组", target_type="account_group",
                  target_id=str(group_id), after_data={"name": row["name"]})
    return {"data": row}


@router.delete("/account-groups/{group_id}")
async def delete_account_group(
    group_id: int,
    user: User = Depends(get_current_user),
    _: ApplicationCtx = Depends(write_application),
):
    if not account_group_service.delete_group(group_id):
        raise HTTPException(status_code=404, detail="账户组不存在")
    log_operation(username=user.username, action="删除账户组", target_type="account_group",
                  target_id=str(group_id))
    return {"ok": True}


@router.get("/naming-rules")
async def list_naming_rules(_: ApplicationCtx = Depends(read_application)):
    return {"data": naming_rule_service.list_rules(),
            "allowed_fields": sorted(naming_rule_service.ALLOWED_FIELDS)}


@router.get("/naming-rules/{rule_id}")
async def get_naming_rule(rule_id: int, _: ApplicationCtx = Depends(read_application)):
    row = naming_rule_service.get_rule(rule_id)
    if not row:
        raise HTTPException(status_code=404, detail="命名规则不存在")
    return {"data": row}


@router.post("/naming-rules", status_code=201)
async def create_naming_rule(
    body: NamingRuleIn,
    user: User = Depends(get_current_user),
    _: ApplicationCtx = Depends(write_application),
):
    try:
        row = naming_rule_service.create_rule(
            name=body.name, rule=body.rule.model_dump(), created_by=user.username
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log_operation(username=user.username, action="创建命名规则", target_type="naming_rule",
                  target_id=str(row["id"]), after_data={"name": row["name"]})
    return {"data": row}


@router.put("/naming-rules/{rule_id}")
async def update_naming_rule(
    rule_id: int,
    body: NamingRuleIn,
    user: User = Depends(get_current_user),
    _: ApplicationCtx = Depends(write_application),
):
    try:
        row = naming_rule_service.update_rule(
            rule_id, name=body.name, rule=body.rule.model_dump()
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="命名规则不存在")
    log_operation(username=user.username, action="更新命名规则", target_type="naming_rule",
                  target_id=str(rule_id), after_data={"name": row["name"]})
    return {"data": row}


@router.delete("/naming-rules/{rule_id}")
async def delete_naming_rule(
    rule_id: int,
    user: User = Depends(get_current_user),
    _: ApplicationCtx = Depends(write_application),
):
    if not naming_rule_service.delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="命名规则不存在")
    log_operation(username=user.username, action="删除命名规则", target_type="naming_rule",
                  target_id=str(rule_id))
    return {"ok": True}
