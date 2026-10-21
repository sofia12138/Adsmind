"""Safe, explicit and deterministic automation rule evaluation."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from ad_creation import repository as draft_repository
from creative_groups import repository as creative_group_repository
from material_catalog import repository as material_repository
from platform_preflight import repository as preflight_repository
from . import repository


Source = Literal["material", "creative_group", "ad_draft", "platform_preflight"]
Operator = Literal["equals", "not_equals", "in", "not_in", "contains", "exists"]
Outcome = Literal["review_required", "blocking_reason"]

ALLOWED_FIELDS: dict[str, set[str]] = {
    "material": {"material_id", "name", "material_type", "material_status", "reference_status", "selection_mode", "selected_version_id", "selected_version_number", "selected_version_upload_status"},
    "creative_group": {"id", "name", "can_deliver", "blocking_reason_count", "material_count"},
    "ad_draft": {"id", "title", "status", "revision", "blocking_reason_count", "has_execution_snapshot"},
    "platform_preflight": {"id", "draft_id", "status", "blocking_reason_count", "dry_run", "external_write_authorized", "preflight_passed"},
}


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


class Condition(BaseModel):
    source: Source
    field: str
    operator: Operator
    value: Any = None
    quantifier: Literal["any", "all"] = "any"
    outcome: Outcome
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)

    @field_validator("field")
    @classmethod
    def validate_field(cls, value: str, info):
        source = info.data.get("source")
        if source and value not in ALLOWED_FIELDS[source]:
            raise ValueError(f"{source} 不允许读取字段 {value}")
        return value

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        clean = value.strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,79}", clean):
            raise ValueError("原因代码须使用小写字母、数字、点、下划线或连字符")
        return clean


class RuleDefinition(BaseModel):
    conditions: list[Condition] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_codes(self):
        codes = [item.code for item in self.conditions]
        if len(codes) != len(set(codes)):
            raise ValueError("同一规则版本中的原因代码不能重复")
        return self


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    status: Literal["ACTIVE", "DISABLED"] = "ACTIVE"
    definition: RuleDefinition

    @field_validator("name", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class RuleUpdate(RuleCreate):
    expected_version: int = Field(gt=0)


class EvaluationInput(BaseModel):
    material_ids: list[int] = Field(default_factory=list, max_length=100)
    creative_group_ids: list[int] = Field(default_factory=list, max_length=100)
    ad_draft_ids: list[str] = Field(default_factory=list, max_length=100)
    platform_preflight_run_ids: list[str] = Field(default_factory=list, max_length=100)
    external_write_authorized: bool = False

    @field_validator("material_ids", "creative_group_ids")
    @classmethod
    def positive_unique_ids(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("输入编号必须为正整数")
        return sorted(set(values))

    @field_validator("ad_draft_ids", "platform_preflight_run_ids")
    @classmethod
    def clean_unique_ids(cls, values: list[str]) -> list[str]:
        clean = sorted(set(value.strip() for value in values if value.strip()))
        if len(clean) != len(values):
            raise ValueError("输入编号不能为空或重复")
        return clean

    @field_validator("external_write_authorized")
    @classmethod
    def reject_external_write(cls, value: bool) -> bool:
        if value:
            raise ValueError("规则评估不接受任何外部写入授权")
        return False

    @model_validator(mode="after")
    def require_input(self):
        if not (self.material_ids or self.creative_group_ids or self.ad_draft_ids or self.platform_preflight_run_ids):
            raise ValueError("至少选择一个内部状态作为评估输入")
        return self


def create_rule(data: RuleCreate, username: str) -> dict:
    definition = data.definition.model_dump()
    return repository.create_rule(name=data.name, description=data.description, status=data.status,
                                  definition=definition, definition_hash=_hash(definition), created_by=username)


def update_rule(rule_id: str, data: RuleUpdate, username: str) -> dict:
    if not repository.get_rule(rule_id):
        raise HTTPException(404, "自动化规则不存在")
    definition = data.definition.model_dump()
    row = repository.create_version(rule_id, expected_version=data.expected_version, name=data.name,
                                    description=data.description, status=data.status, definition=definition,
                                    definition_hash=_hash(definition), created_by=username)
    if not row:
        raise HTTPException(409, "规则版本已变化，请刷新后重试")
    return row


def _material_snapshot(material_id: int) -> dict:
    row = material_repository.get_reference(material_id)
    if not row:
        raise HTTPException(404, f"素材 {material_id} 不存在于当前应用")
    return {key: row.get(key) for key in sorted(ALLOWED_FIELDS["material"])}


def _creative_group_snapshot(group_id: int) -> dict:
    row = creative_group_repository.get(group_id)
    if not row:
        raise HTTPException(404, f"创意组 {group_id} 不存在于当前应用")
    return {"id": row["id"], "name": row["name"], "can_deliver": bool(row.get("can_deliver")),
            "blocking_reason_count": len(row.get("blocking_reasons") or []),
            "material_count": len(row.get("materials") or [])}


def _draft_snapshot(draft_id: str) -> dict:
    row = draft_repository.get(draft_id)
    if not row:
        raise HTTPException(404, f"广告草稿 {draft_id} 不存在于当前应用")
    return {"id": row["id"], "title": row["title"], "status": row["status"], "revision": row["revision"],
            "blocking_reason_count": len(row.get("blocking_reasons") or []),
            "has_execution_snapshot": isinstance(row.get("execution_snapshot"), dict)}


def _preflight_snapshot(run_id: str) -> dict:
    row = preflight_repository.get_run(run_id)
    if not row:
        raise HTTPException(404, f"平台预检 {run_id} 不存在于当前应用")
    plan = row.get("dry_run_plan") or {}
    return {"id": row["id"], "draft_id": row["draft_id"], "status": row["status"],
            "blocking_reason_count": len(row.get("blocking_reasons") or []), "dry_run": row.get("dry_run") is True,
            "external_write_authorized": row.get("external_write_authorized") is True,
            "preflight_passed": plan.get("preflight_passed") is True}


def build_snapshot(data: EvaluationInput) -> dict:
    return {
        "contract": "automation_rule_input_snapshot.v1",
        "material": [_material_snapshot(item) for item in data.material_ids],
        "creative_group": [_creative_group_snapshot(item) for item in data.creative_group_ids],
        "ad_draft": [_draft_snapshot(item) for item in data.ad_draft_ids],
        "platform_preflight": [_preflight_snapshot(item) for item in data.platform_preflight_run_ids],
        "dry_run": True,
        "external_write_authorized": False,
    }


def _matches(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "exists":
        return (actual is not None) is bool(expected)
    if operator == "equals":
        return actual == expected
    if operator == "not_equals":
        return actual != expected
    if operator in {"in", "not_in"}:
        if not isinstance(expected, list):
            return False
        result = actual in expected
        return result if operator == "in" else not result
    if operator == "contains":
        return isinstance(actual, (str, list)) and expected in actual
    return False


def _evaluate(definition: dict, snapshot: dict) -> tuple[list[dict], list[dict]]:
    blockers: list[dict] = []
    recommendations: list[dict] = []
    for condition in definition["conditions"]:
        records = snapshot[condition["source"]]
        if not records:
            blockers.append({"code": "input_source_missing", "message": f"规则需要 {condition['source']} 输入",
                             "condition_code": condition["code"], "source": condition["source"]})
            continue
        results = [_matches(record.get(condition["field"]), condition["operator"], condition.get("value")) for record in records]
        matched = all(results) if condition["quantifier"] == "all" else any(results)
        if not matched:
            continue
        evidence = {"source": condition["source"], "field": condition["field"], "operator": condition["operator"],
                    "value": condition.get("value"), "quantifier": condition["quantifier"], "matched_records": sum(results)}
        item = {"code": condition["code"], "message": condition["message"], "evidence": evidence}
        if condition["outcome"] == "blocking_reason":
            blockers.append(item)
        else:
            recommendations.append(item)
    return blockers, recommendations


def evaluate(rule_id: str, version: int | None, data: EvaluationInput, username: str) -> dict:
    if data.external_write_authorized:
        raise HTTPException(400, "规则评估不接受任何外部写入授权")
    rule = repository.get_rule(rule_id, version)
    if not rule:
        raise HTTPException(404, "自动化规则或版本不存在")
    if rule["status"] != "ACTIVE":
        raise HTTPException(409, "已停用规则不能试跑")
    if version is not None:
        rule["current_version"] = rule["selected_version"]
    snapshot = build_snapshot(data)
    snapshot_hash = _hash(snapshot)
    evaluation_key = _hash({"contract": "automation_rule_evaluation_key.v1", "rule_version_id": rule["rule_version_id"],
                            "definition_hash": rule["definition_hash"], "input_snapshot_hash": snapshot_hash})
    existing = repository.get_evaluation_by_key(evaluation_key)
    if existing:
        return existing
    blockers, recommendations = _evaluate(rule["definition"], snapshot)
    status = "BLOCKED" if blockers else "REVIEW_REQUIRED" if recommendations else "CLEAR"
    row, _ = repository.create_evaluation(rule=rule, input_snapshot=snapshot, input_snapshot_hash=snapshot_hash,
                                          evaluation_key=evaluation_key, status=status, blockers=blockers,
                                          recommendations=recommendations, created_by=username)
    return row
