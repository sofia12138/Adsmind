"""Derive auditable readiness summaries without mutating source records."""
from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, Field

from core.isolation import require_scope
from . import repository


EntityType = Literal["material", "creative_group", "draft", "preflight"]
KNOWN_UPLOAD_STATUSES = {"uploaded", "pending_upload", "uploading", "failed"}


class DetailFilters(BaseModel):
    entity_type: EntityType | None = None
    status: str | None = Field(default=None, max_length=64)
    reason_code: str | None = Field(default=None, max_length=128)
    query: str = Field(default="", max_length=255)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


def _reason(code: str, message: str, **context: Any) -> dict:
    return {"code": code, "message": message, **context}


def _reason_list(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return [_reason("unknown_reason", "阻断原因缺失或格式未知")]
    result = []
    for item in raw:
        if isinstance(item, dict):
            result.append({
                **item,
                "code": str(item.get("code") or "unknown_reason"),
                "message": str(item.get("message") or "未提供阻断说明"),
            })
        elif item:
            result.append(_reason("unstructured_reason", str(item)))
    return result


def _material_item(row: dict) -> dict:
    reasons = []
    if row.get("reference_status") != "selected":
        reasons.append(_reason("material_reference_paused", "素材在当前应用中已暂停"))
    if row.get("material_status") != "active":
        reasons.append(_reason("material_archived", "素材主档不是 active 状态"))
    raw_status = row.get("upload_status")
    if row.get("effective_version_id") is None:
        status = "missing"
        reasons.append(_reason("material_version_missing", "素材缺少当前选择模式下的有效版本"))
    elif raw_status in KNOWN_UPLOAD_STATUSES:
        status = str(raw_status)
        if status != "uploaded":
            reasons.append(_reason(f"material_{status}", {
                "pending_upload": "素材版本等待上传",
                "uploading": "素材版本仍在上传",
                "failed": "素材版本上传失败",
            }[status]))
    else:
        status = "unknown"
        reasons.append(_reason("material_upload_status_unknown", "素材版本上传状态未知", raw_status=raw_status))
    if row.get("upload_error"):
        reasons.append(_reason("material_upload_error", str(row["upload_error"])))
    return {
        "entity_type": "material", "entity_id": str(row["material_id"]),
        "name": row.get("material_name") or f"素材 {row['material_id']}",
        "status": status, "status_label": {
            "uploaded": "已上传", "pending_upload": "待上传", "uploading": "上传中",
            "failed": "上传失败", "missing": "缺少版本", "unknown": "状态未知",
        }[status],
        "reasons": reasons, "last_changed_at": row.get("updated_at"),
        "trace_url": f"/creatives?material_id={row['material_id']}",
        "metadata": {
            "reference_id": row.get("reference_id"), "selection_mode": row.get("selection_mode"),
            "effective_version_id": row.get("effective_version_id"),
            "effective_version_number": row.get("effective_version_number"),
            "filename": row.get("effective_filename"), "drama_id": row.get("drama_id"),
            "drama_title": row.get("drama_title"), "reference_status": row.get("reference_status"),
            "material_status": row.get("material_status"),
        },
    }


def _creative_item(row: dict) -> dict:
    raw_reasons = row.get("blocking_reasons")
    reasons = [_reason("creative_group_blocked", str(message)) for message in raw_reasons] if isinstance(raw_reasons, list) else _reason_list(raw_reasons)
    if row.get("can_deliver") is True:
        status, label = "deliverable", "可投放"
    elif row.get("can_deliver") is False:
        status, label = "blocked", "已阻断"
    else:
        status, label = "unknown", "状态未知"
        reasons.append(_reason("creative_group_state_unknown", "创意组可投放状态未知"))
    return {
        "entity_type": "creative_group", "entity_id": str(row["id"]),
        "name": row.get("name") or f"创意组 {row['id']}", "status": status,
        "status_label": label, "reasons": reasons, "last_changed_at": row.get("updated_at"),
        "trace_url": f"/creative-groups?group_id={row['id']}",
        "metadata": {"material_count": len(row.get("materials") or [])},
    }


def _draft_item(row: dict) -> dict:
    raw_reasons = row.get("blocking_reasons")
    reasons = _reason_list(raw_reasons) if raw_reasons is not None else [_reason("draft_readiness_unknown", "草稿没有就绪检查结果")]
    if row.get("status") == "READY":
        status, label = "ready", "READY"
    elif row.get("status") == "DRAFT" and reasons:
        status, label = "blocked", "已阻断"
    elif row.get("status") == "DRAFT":
        status, label = "pending", "待标记就绪"
        reasons = [_reason("draft_not_marked_ready", "当前检查未发现阻断，但草稿尚未标记为 READY")]
    else:
        status, label = "unknown", "状态未知"
        reasons.append(_reason("draft_status_unknown", "广告草稿状态不在已知范围", raw_status=row.get("status")))
    return {
        "entity_type": "draft", "entity_id": str(row["id"]),
        "name": row.get("title") or f"广告草稿 {row['id']}", "status": status,
        "status_label": label, "reasons": reasons, "last_changed_at": row.get("updated_at"),
        "trace_url": f"/ads/app-drafts/{row['id']}",
        "metadata": {"source_status": row.get("status"), "revision": row.get("revision"),
                     "ready_at": row.get("ready_at"), "created_by": row.get("created_by")},
    }


def _preflight_item(row: dict, draft_names: dict[str, str]) -> dict:
    reasons = _reason_list(row.get("blocking_reasons"))
    if row.get("status") == "PASSED":
        status, label = "passed", "已通过"
    elif row.get("status") == "BLOCKED":
        status, label = "blocked", "已阻断"
        if not reasons:
            reasons = [_reason("preflight_blocked_reason_missing", "预检被阻断，但未记录具体原因")]
    else:
        status, label = "unknown", "状态未知"
        reasons.append(_reason("preflight_status_unknown", "预检状态不在已知范围", raw_status=row.get("status")))
    draft_id = str(row.get("draft_id") or "")
    return {
        "entity_type": "preflight", "entity_id": str(row["id"]),
        "name": f"{draft_names.get(draft_id, '广告草稿')} · 预检",
        "status": status, "status_label": label, "reasons": reasons,
        "last_changed_at": row.get("finished_at") or row.get("created_at"),
        "trace_url": f"/ads/platform-preflight?draft_id={draft_id}",
        "metadata": {"draft_id": draft_id, "dry_run": row.get("dry_run"),
                     "external_write_authorized": row.get("external_write_authorized"),
                     "created_by": row.get("created_by")},
    }


def _not_run_item(row: dict) -> dict:
    return {
        "entity_type": "preflight", "entity_id": f"not-run:{row['id']}",
        "name": f"{row.get('title') or '广告草稿'} · 预检",
        "status": "not_run", "status_label": "未运行",
        "reasons": [_reason("preflight_not_run", "READY 草稿尚无平台预检记录")],
        "last_changed_at": row.get("ready_at") or row.get("updated_at"),
        "trace_url": f"/ads/platform-preflight?draft_id={row['id']}",
        "metadata": {"draft_id": str(row["id"]), "synthetic": True},
    }


def _count(items: list[dict], statuses: list[str]) -> dict[str, int]:
    raw = Counter(item["status"] for item in items)
    return {status: raw.get(status, 0) for status in statuses}


def _latest(items: list[dict]) -> str | None:
    values = [str(item["last_changed_at"]) for item in items if item.get("last_changed_at")]
    return max(values) if values else None


def build_snapshot() -> dict:
    scope = require_scope(application=True)
    materials = [_material_item(row) for row in repository.list_material_references()]
    creatives = [_creative_item(row) for row in repository.list_creative_groups()]
    draft_rows = repository.list_drafts()
    drafts = [_draft_item(row) for row in draft_rows]
    draft_names = {str(row["id"]): str(row.get("title") or "广告草稿") for row in draft_rows}
    run_rows = repository.list_preflight_runs()
    actual_preflights = [_preflight_item(row, draft_names) for row in run_rows]
    preflights = list(actual_preflights)
    ran_drafts = {str(row.get("draft_id")) for row in run_rows}
    preflights.extend(_not_run_item(row) for row in draft_rows if row.get("status") == "READY" and str(row["id"]) not in ran_drafts)
    all_items = [*materials, *creatives, *drafts, *preflights]
    reason_counts = Counter(
        str(reason.get("code") or "unknown_reason")
        for item in preflights if item["status"] == "blocked"
        for reason in item["reasons"]
    )
    pending = [item for item in all_items if item["status"] not in {"uploaded", "deliverable", "ready", "passed"}]
    return {
        "contract": "readiness_analytics.v1",
        "scope": {"tenant_id": scope.tenant_id, "application_id": scope.application_id},
        "read_only": True,
        "disclaimer": "准备就绪度分析，不是广告效果、消耗、ROI 或平台投放报表。",
        "summary": {
            "materials": _count(materials, ["uploaded", "pending_upload", "uploading", "failed", "missing", "unknown"]),
            "creative_groups": _count(creatives, ["deliverable", "blocked", "unknown"]),
            "drafts": _count(drafts, ["ready", "blocked", "pending", "unknown"]),
            "preflights": _count(preflights, ["passed", "blocked", "not_run", "unknown"]),
            "preflight_blocking_reasons": [
                {"code": code, "count": count} for code, count in sorted(reason_counts.items(), key=lambda pair: (-pair[1], pair[0]))
            ],
            "pending_total": len(pending), "last_changed_at": _latest(all_items),
        },
        "source_freshness": {
            "materials": _latest(materials), "creative_groups": _latest(creatives),
            "drafts": _latest(drafts), "preflights": _latest(actual_preflights),
        },
        "items": all_items,
    }


def overview() -> dict:
    result = build_snapshot()
    result.pop("items")
    return result


def details(filters: DetailFilters) -> dict:
    snapshot = build_snapshot()
    items = snapshot.pop("items")
    query = filters.query.strip().casefold()
    if filters.entity_type:
        items = [item for item in items if item["entity_type"] == filters.entity_type]
    if filters.status:
        items = [item for item in items if item["status"] == filters.status]
    if filters.reason_code:
        items = [item for item in items if any(reason.get("code") == filters.reason_code for reason in item["reasons"])]
    if query:
        items = [item for item in items if query in " ".join((item["name"], item["entity_id"], *(str(v) for v in item["metadata"].values() if v is not None))).casefold()]
    items.sort(key=lambda item: (str(item.get("last_changed_at") or ""), item["entity_id"]), reverse=True)
    total = len(items)
    start = (filters.page - 1) * filters.page_size
    return {**snapshot, "data": items[start:start + filters.page_size], "total": total,
            "page": filters.page, "page_size": filters.page_size}
