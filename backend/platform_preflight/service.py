"""Validate frozen READY snapshots and create non-executable dry-run plans."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from ad_creation import repository as draft_repository
from core.isolation import require_scope
from repositories import oauth_credential_repository
from . import repository


CONTRACT = "ad_creation_execution_snapshot.v1"
PLAN_CONTRACT = "ad_platform_dry_run_plan.v1"


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _reason(code: str, message: str, **context) -> dict:
    return {"code": code, "message": message, **context}


class AccountMappingInput(BaseModel):
    platform: str = Field(min_length=1, max_length=32)
    account_id: str = Field(min_length=1, max_length=128)
    external_account_id: str = Field(min_length=1, max_length=128)
    credential_external_id: str = Field(min_length=1, max_length=128)
    status: str = "ACTIVE"

    @field_validator("platform")
    @classmethod
    def normalize_platform(cls, value: str) -> str:
        clean = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9_-]+", clean):
            raise ValueError("平台标识格式无效")
        return clean

    @field_validator("account_id", "external_account_id", "credential_external_id")
    @classmethod
    def clean_identifier(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("映射标识不能为空")
        return clean

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        clean = value.strip().upper()
        if clean not in {"ACTIVE", "DISABLED"}:
            raise ValueError("映射状态必须是 ACTIVE 或 DISABLED")
        return clean


class MaterialMappingInput(BaseModel):
    platform: str = Field(min_length=1, max_length=32)
    account_id: str = Field(min_length=1, max_length=128)
    material_id: int = Field(gt=0)
    version_id: int = Field(gt=0)
    platform_asset_id: str = Field(min_length=1, max_length=255)
    upload_status: str = "uploaded"

    @field_validator("platform")
    @classmethod
    def normalize_platform(cls, value: str) -> str:
        return AccountMappingInput.normalize_platform(value)

    @field_validator("account_id", "platform_asset_id")
    @classmethod
    def clean_identifier(cls, value: str) -> str:
        return AccountMappingInput.clean_identifier(value)

    @field_validator("upload_status")
    @classmethod
    def validate_upload_status(cls, value: str) -> str:
        clean = value.strip().lower()
        if clean not in {"uploaded", "pending_upload", "uploading", "failed"}:
            raise ValueError("素材上传状态无效")
        return clean


class PreflightInput(BaseModel):
    request_key: str
    external_write_authorized: bool = False

    @field_validator("request_key")
    @classmethod
    def validate_request_key(cls, value: str) -> str:
        try:
            return str(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("预检请求编号必须是 UUID") from exc

    @field_validator("external_write_authorized")
    @classmethod
    def reject_external_write(cls, value: bool) -> bool:
        if value:
            raise ValueError("本阶段不接受任何外部平台写入授权")
        return False


def save_account_mapping(data: AccountMappingInput, username: str) -> dict:
    return repository.upsert_account_mapping(data.model_dump(), username)


def save_material_mapping(data: MaterialMappingInput, username: str) -> dict:
    return repository.upsert_material_mapping(data.model_dump(), username)


def _validate_snapshot(draft: dict) -> tuple[dict, list[dict]]:
    blockers: list[dict] = []
    snapshot = draft.get("execution_snapshot")
    expected_hash = str(draft.get("execution_snapshot_hash") or "")
    if draft.get("status") != "READY":
        return {}, [_reason("draft_not_ready", "仅 READY 广告草稿可以进入平台预检")]
    if not isinstance(snapshot, dict):
        return {}, [_reason("snapshot_missing", "READY 草稿缺少执行快照")]
    if snapshot.get("contract") != CONTRACT:
        blockers.append(_reason("snapshot_contract_invalid", "执行快照契约不是 ad_creation_execution_snapshot.v1"))
    actual_hash = _sha256(snapshot)
    if not expected_hash or not re.fullmatch(r"[0-9a-f]{64}", expected_hash) or actual_hash != expected_hash:
        blockers.append(_reason("snapshot_hash_mismatch", "执行快照哈希缺失或不匹配", expected=expected_hash, actual=actual_hash))
    scope = require_scope(application=True)
    if snapshot.get("tenant_id") != scope.tenant_id or snapshot.get("application_id") != scope.application_id:
        blockers.append(_reason("snapshot_scope_mismatch", "执行快照不属于当前租户/应用"))
    if snapshot.get("draft_id") != draft.get("id"):
        blockers.append(_reason("snapshot_draft_mismatch", "执行快照的草稿标识不匹配"))
    if snapshot.get("external_write_authorized") is not False:
        blockers.append(_reason("snapshot_external_write_not_denied", "执行快照必须明确 external_write_authorized=false"))
    for field in ("accounts", "name_previews"):
        if not isinstance(snapshot.get(field), list) or not snapshot.get(field):
            blockers.append(_reason("snapshot_incomplete", f"执行快照缺少 {field}", field=field))
    creative = snapshot.get("creative_group")
    if not isinstance(creative, dict) or not isinstance(creative.get("materials"), list) or not creative.get("materials"):
        blockers.append(_reason("snapshot_incomplete", "执行快照缺少创意素材", field="creative_group.materials"))
    return snapshot, blockers


def _credential_state(mapping: dict, platform: str) -> tuple[str, dict | None]:
    scope = require_scope()
    credential = oauth_credential_repository.get_meta(scope.tenant_id, platform, mapping["credential_external_id"])
    if not credential:
        return "missing", None
    expires_at = credential.get("expires_at")
    if expires_at:
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            return "expired", credential
    return "valid", credential


def _validate_name(value: object, field: str, account: dict) -> list[dict]:
    if not isinstance(value, str) or not value.strip():
        return [_reason("name_missing", f"{field} 不能为空", field=field, platform=account["platform"], account_id=account["account_id"])]
    if len(value) > 255:
        return [_reason("name_too_long", f"{field} 超过 255 字符", field=field, platform=account["platform"], account_id=account["account_id"])]
    if any(ord(char) < 32 for char in value):
        return [_reason("name_contains_control_character", f"{field} 包含控制字符", field=field, platform=account["platform"], account_id=account["account_id"])]
    return []


def _evaluate(snapshot: dict) -> tuple[list[dict], list[dict]]:
    blockers: list[dict] = []
    operations: list[dict] = []
    accounts = snapshot.get("accounts") if isinstance(snapshot.get("accounts"), list) else []
    materials = (snapshot.get("creative_group") or {}).get("materials") or []
    previews = {
        (str(item.get("platform") or "").lower(), str(item.get("account_id") or "")): item
        for item in snapshot.get("name_previews") or [] if isinstance(item, dict)
    }
    seen_accounts: set[tuple[str, str]] = set()
    for account in accounts:
        if not isinstance(account, dict):
            blockers.append(_reason("snapshot_account_invalid", "执行快照包含无效账户项"))
            continue
        platform = str(account.get("platform") or "").lower()
        account_id = str(account.get("account_id") or "")
        key = (platform, account_id)
        if not platform or not account_id:
            blockers.append(_reason("snapshot_account_invalid", "执行快照账户缺少 platform/account_id"))
            continue
        if key in seen_accounts:
            blockers.append(_reason("snapshot_account_duplicate", "执行快照包含重复账户", platform=platform, account_id=account_id))
            continue
        seen_accounts.add(key)
        mapping = repository.get_account_mapping(platform, account_id)
        if not mapping:
            blockers.append(_reason("account_mapping_missing", "当前应用缺少平台账户映射", platform=platform, account_id=account_id))
            continue
        if mapping.get("status") != "ACTIVE":
            blockers.append(_reason("account_mapping_inactive", "平台账户映射不是 ACTIVE", platform=platform, account_id=account_id))
        credential_state, _ = _credential_state(mapping, platform)
        if credential_state == "missing":
            blockers.append(_reason("credential_missing", "平台账户映射缺少可用凭证", platform=platform, account_id=account_id))
        elif credential_state == "expired":
            blockers.append(_reason("credential_expired", "平台账户凭证已过期", platform=platform, account_id=account_id))
        preview = previews.get(key)
        if not preview:
            blockers.append(_reason("name_preview_missing", "账户缺少冻结名称预览", platform=platform, account_id=account_id))
        else:
            for field in ("campaign_name", "adgroup_name", "creative_name"):
                blockers.extend(_validate_name(preview.get(field), field, account))
        mapped_materials = []
        for material in materials:
            material_id = material.get("material_id") if isinstance(material, dict) else None
            version_id = material.get("effective_version_id") if isinstance(material, dict) else None
            if not material_id or not version_id:
                blockers.append(_reason("snapshot_material_incomplete", "冻结素材缺少 material_id/effective_version_id", material_id=material_id))
                continue
            if material.get("upload_status") != "uploaded":
                blockers.append(_reason("snapshot_material_not_uploaded", "冻结快照中的素材不是 uploaded 状态", material_id=material_id, version_id=version_id))
            material_mapping = repository.get_material_mapping(platform, account_id, int(material_id), int(version_id))
            if not material_mapping:
                blockers.append(_reason("material_mapping_missing", "账户缺少平台素材映射", platform=platform, account_id=account_id, material_id=material_id, version_id=version_id))
                continue
            if material_mapping.get("upload_status") != "uploaded":
                blockers.append(_reason("platform_material_not_uploaded", "平台素材映射不是 uploaded 状态", platform=platform, account_id=account_id, material_id=material_id, version_id=version_id))
            mapped_materials.append({"material_id": material_id, "version_id": version_id, "platform_asset_id": material_mapping["platform_asset_id"]})
        operations.append({
            "platform": platform,
            "account_id": account_id,
            "external_account_id": mapping["external_account_id"],
            "names": preview or {},
            "materials": mapped_materials,
            "would_create": ["campaign", "ad_group", "creative", "ad"],
        })
    return blockers, operations


def run(draft_id: str, data: PreflightInput, username: str) -> dict:
    if data.external_write_authorized:
        raise HTTPException(400, "本阶段不接受任何外部平台写入授权")
    existing = repository.get_run_by_request(data.request_key)
    draft = draft_repository.get(draft_id)
    if not draft:
        raise HTTPException(404, "广告草稿不存在")
    snapshot, blockers = _validate_snapshot(draft)
    snapshot_hash = str(draft.get("execution_snapshot_hash") or _sha256(snapshot))
    if existing:
        if existing["draft_id"] != draft_id or existing["snapshot_hash"] != snapshot_hash:
            raise HTTPException(409, "同一预检请求编号不能用于不同的草稿或快照")
        return existing
    operations: list[dict] = []
    if snapshot:
        more_blockers, operations = _evaluate(snapshot)
        blockers.extend(more_blockers)
    scope = require_scope(application=True)
    execution_key = hashlib.sha256(
        f"platform-preflight.v1|{scope.tenant_id}|{scope.application_id}|{snapshot_hash}|{data.request_key}".encode()
    ).hexdigest()
    plan = {
        "contract": PLAN_CONTRACT,
        "draft_id": draft_id,
        "snapshot_hash": snapshot_hash,
        "dry_run": True,
        "external_write_authorized": False,
        "executable": False,
        "preflight_passed": not blockers,
        "operations": operations if not blockers else [],
        "notice": "This plan is audit-only and cannot be promoted to a real platform execution.",
    }
    plan_hash = _sha256(plan)
    row, inserted = repository.create_run(
        draft_id=draft_id, request_key=data.request_key, snapshot_hash=snapshot_hash,
        status="PASSED" if not blockers else "BLOCKED", blockers=blockers,
        plan=plan, plan_hash=plan_hash, execution_key=execution_key, created_by=username,
    )
    if not inserted and (row["draft_id"] != draft_id or row["snapshot_hash"] != snapshot_hash):
        raise HTTPException(409, "预检幂等键冲突")
    return row


def refuse_execute(run_id: str, username: str) -> None:
    if not repository.get_run(run_id):
        raise HTTPException(404, "预检记录不存在")
    repository.append_audit(
        run_id, "execution.denied",
        {"reason": "dry_run_only", "external_write_authorized": False}, username,
    )
    raise HTTPException(409, "平台预检仅生成不可执行 dry-run 计划；external_write_authorized=false")
