"""Resolve and freeze application ad creation drafts without platform writes."""
from __future__ import annotations

from datetime import date
import hashlib
import json
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from core.isolation import require_scope
from creative_groups import service as creative_group_service
from repositories import account_group_repository, biz_account_repository, naming_rule_repository
from services.naming_rule_service import normalize_rule
from . import repository


class DraftInput(BaseModel):
    request_key: str | None = None
    title: str = Field(min_length=1, max_length=160)
    account_group_id: int = Field(gt=0)
    naming_rule_id: int = Field(gt=0)
    creative_group_id: int = Field(gt=0)
    naming_values: dict[str, str] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if not value:
            raise ValueError("草稿名称不能为空")
        return value

    @field_validator("naming_values")
    @classmethod
    def clean_values(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"product", "country", "language", "campaign", "adgroup", "creative", "date"}
        if set(value) - allowed:
            raise ValueError("命名参数包含不支持的字段")
        result = {}
        for key, raw in value.items():
            clean = str(raw).strip()
            if len(clean) > 120:
                raise ValueError(f"命名参数 {key} 不能超过 120 个字符")
            result[key] = clean
        return result


class DraftUpdate(DraftInput):
    request_key: str | None = Field(default=None, exclude=True)
    revision: int = Field(ge=1)


def _reason(code: str, message: str, **context) -> dict:
    return {"code": code, "message": message, **context}


def _render_names(pattern: str, values: dict[str, str], account: dict) -> dict:
    common = {
        **values,
        "platform": str(account.get("platform") or ""),
        "account": str(account.get("account_name") or account.get("account_id") or ""),
        "date": values.get("date") or date.today().isoformat(),
    }
    return {
        "platform": common["platform"],
        "account_id": str(account["account_id"]),
        "account_name": common["account"],
        "campaign_name": pattern.format_map({**common, "campaign": values.get("campaign", "campaign"), "adgroup": values.get("adgroup", "adgroup"), "creative": values.get("creative", "creative")}),
        "adgroup_name": pattern.format_map({**common, "campaign": values.get("campaign", "campaign"), "adgroup": values.get("adgroup", "adgroup"), "creative": values.get("creative", "creative")}),
        "creative_name": pattern.format_map({**common, "campaign": values.get("campaign", "campaign"), "adgroup": values.get("adgroup", "adgroup"), "creative": values.get("creative", "creative")}),
    }


def resolve(*, account_group_id: int, naming_rule_id: int,
            creative_group_id: int, naming_values: dict[str, str]) -> dict:
    account_group = account_group_repository.get(account_group_id)
    naming_rule = naming_rule_repository.get(naming_rule_id)
    creative_group = creative_group_service.get_group(creative_group_id)
    if not account_group:
        raise HTTPException(404, "账户组不存在于当前应用")
    if not naming_rule:
        raise HTTPException(404, "命名规则不存在于当前应用")

    rule = normalize_rule(naming_rule["rule"])
    refs = account_group.get("account_refs") or []
    current_accounts = {
        (str(row.get("platform") or "").lower(), str(row.get("account_id") or "")): row
        for row in biz_account_repository.list_all()
    }
    accounts = []
    reasons = []
    for ref in refs:
        key = (str(ref.get("platform") or "").lower(), str(ref.get("account_id") or ""))
        row = current_accounts.get(key)
        if not row:
            reasons.append(_reason("account_not_owned", "账户已不属于当前应用", platform=key[0], account_id=key[1]))
            continue
        safe = {name: row.get(name) for name in ("platform", "account_id", "account_name", "currency", "timezone", "status")}
        accounts.append(safe)
        if row.get("status") != "ACTIVE":
            reasons.append(_reason("account_inactive", "账户状态不是 ACTIVE", platform=key[0], account_id=key[1]))
    if not refs:
        reasons.append(_reason("account_group_empty", "账户组没有广告账户"))

    automatic = {"platform", "account", "date", "campaign", "adgroup", "creative"}
    for field in rule["fields"]:
        if field not in automatic and not naming_values.get(field):
            reasons.append(_reason("naming_value_missing", f"命名规则缺少 {field} 参数", field=field))
    previews = []
    if not any(item["code"] == "naming_value_missing" for item in reasons):
        previews = [_render_names(rule["pattern"], naming_values, account) for account in accounts]
    if not creative_group["can_deliver"]:
        reasons.extend(
            _reason("creative_group_blocked", message, creative_group_id=creative_group_id)
            for message in creative_group["blocking_reasons"]
        )

    creative_snapshot = {
        "id": creative_group["id"],
        "name": creative_group["name"],
        "can_deliver": creative_group["can_deliver"],
        "materials": [
            {
                "material_id": item["material_id"],
                "material_name": item["material_name"],
                "selection_mode": item["selection_mode"],
                "selected_version_id": item["selected_version_id"],
                "effective_version_id": item["effective_version_id"],
                "upload_status": item["selected_version_upload_status"],
            }
            for item in creative_group["materials"]
        ],
    }
    return {
        "ready": not reasons,
        "account_group": {"id": account_group["id"], "name": account_group["name"]},
        "naming_rule": {"id": naming_rule["id"], "name": naming_rule["name"], "rule": rule},
        "resolved_accounts": accounts,
        "name_previews": previews,
        "creative_snapshot": creative_snapshot,
        "blocking_reasons": reasons,
    }


def _same_request(row: dict, data: DraftInput) -> bool:
    return all((
        row["title"] == data.title,
        int(row["account_group_id"]) == data.account_group_id,
        int(row["naming_rule_id"]) == data.naming_rule_id,
        int(row["creative_group_id"]) == data.creative_group_id,
        row["naming_values"] == data.naming_values,
    ))


def create(data: DraftInput, username: str) -> dict:
    try:
        request_key = str(uuid.UUID(data.request_key or ""))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(400, "草稿请求编号无效") from exc
    resolution = resolve(
        account_group_id=data.account_group_id,
        naming_rule_id=data.naming_rule_id,
        creative_group_id=data.creative_group_id,
        naming_values=data.naming_values,
    )
    row, inserted = repository.create(
        request_key=request_key, created_by=username, title=data.title,
        account_group_id=data.account_group_id, naming_rule_id=data.naming_rule_id,
        creative_group_id=data.creative_group_id, naming_values=data.naming_values,
        resolution=resolution,
    )
    if not inserted and not _same_request(row, data):
        raise HTTPException(409, "同一请求编号不能用于不同的草稿内容")
    return row


def get(draft_id: str) -> dict:
    row = repository.get(draft_id)
    if not row:
        raise HTTPException(404, "广告草稿不存在")
    return row


def list_all() -> list[dict]:
    return repository.list_all()


def update(draft_id: str, data: DraftUpdate) -> dict:
    row = get(draft_id)
    if row["status"] != "DRAFT":
        raise HTTPException(409, "准备就绪的草稿及执行快照不可修改")
    resolution = resolve(
        account_group_id=data.account_group_id, naming_rule_id=data.naming_rule_id,
        creative_group_id=data.creative_group_id, naming_values=data.naming_values,
    )
    updated = repository.update(
        draft_id, expected_revision=data.revision, title=data.title,
        account_group_id=data.account_group_id, naming_rule_id=data.naming_rule_id,
        creative_group_id=data.creative_group_id, naming_values=data.naming_values,
        resolution=resolution,
    )
    if not updated:
        raise HTTPException(409, "草稿已被更新，请刷新后重试")
    return updated


def check(draft_id: str) -> dict:
    row = get(draft_id)
    if row["status"] == "READY":
        return row
    resolution = resolve(
        account_group_id=row["account_group_id"], naming_rule_id=row["naming_rule_id"],
        creative_group_id=row["creative_group_id"], naming_values=row["naming_values"],
    )
    refreshed = repository.refresh(draft_id, expected_revision=row["revision"], resolution=resolution)
    if not refreshed:
        raise HTTPException(409, "草稿检查期间已发生变更，请刷新后重试")
    return refreshed


def mark_ready(draft_id: str, revision: int) -> dict:
    row = get(draft_id)
    if row["status"] == "READY":
        return row
    resolution = resolve(
        account_group_id=row["account_group_id"], naming_rule_id=row["naming_rule_id"],
        creative_group_id=row["creative_group_id"], naming_values=row["naming_values"],
    )
    if resolution["blocking_reasons"]:
        repository.refresh(draft_id, expected_revision=row["revision"], resolution=resolution)
        raise HTTPException(422, {"message": "草稿尚未准备就绪", "blocking_reasons": resolution["blocking_reasons"]})
    scope = require_scope(application=True)
    snapshot = {
        "contract": "ad_creation_execution_snapshot.v1",
        "draft_id": row["id"],
        "source_revision": row["revision"],
        "tenant_id": scope.tenant_id,
        "application_id": scope.application_id,
        "account_group": resolution["account_group"],
        "accounts": resolution["resolved_accounts"],
        "naming_rule": resolution["naming_rule"],
        "name_previews": resolution["name_previews"],
        "creative_group": resolution["creative_snapshot"],
        "external_write_authorized": False,
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    ready = repository.mark_ready(
        draft_id, expected_revision=revision, resolution=resolution,
        snapshot=snapshot, snapshot_hash=hashlib.sha256(encoded.encode()).hexdigest(),
    )
    if not ready:
        current = get(draft_id)
        if current["status"] == "READY":
            return current
        raise HTTPException(409, "草稿已被更新，请刷新后重试")
    return ready
