"""Conservative, traceable material/drama aggregation semantics."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from core.isolation import require_scope
from . import repository


Dimension = Literal["material", "drama"]


class AnalysisFilters(BaseModel):
    dimension: Dimension = "material"
    date_from: dt.date
    date_to: dt.date
    platform: str | None = Field(default=None, max_length=32)
    account_id: str | None = Field(default=None, max_length=128)
    coverage_status: str | None = Field(default=None, max_length=40)
    query: str = Field(default="", max_length=255)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def valid_range(self):
        if self.date_from > self.date_to:
            raise ValueError("开始日期不能晚于结束日期")
        if (self.date_to - self.date_from).days > 366:
            raise ValueError("单次分析范围不能超过 367 天")
        return self


def _dec(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def _amount(value: Decimal | None) -> str | None:
    return None if value is None else format(value.quantize(Decimal("0.0001")), "f")


def _ratio(numerator: Decimal, denominator: Decimal) -> str | None:
    return None if not denominator else format((numerator / denominator).quantize(Decimal("0.000001")), "f")


def _time(value: Any) -> str | None:
    return str(value) if value is not None else None


def _metric_seed() -> dict:
    return {"spend": Decimal(0), "revenue": Decimal(0), "impressions": 0,
            "clicks": 0, "installs": 0, "conversions": 0, "rows": 0,
            "dates": set(), "accounts": set(), "ads": set(), "cutoffs": []}


def _add_metric(target: dict, fact: dict) -> None:
    target["spend"] += _dec(fact.get("spend"))
    target["revenue"] += _dec(fact.get("revenue"))
    for field in ("impressions", "clicks", "installs", "conversions"):
        target[field] += int(fact.get(field) or 0)
    target["rows"] += 1
    target["dates"].add(str(fact.get("stat_date")))
    target["accounts"].add((str(fact.get("platform") or ""), str(fact.get("account_id") or "")))
    target["ads"].add(str(fact.get("ad_id") or ""))
    cutoff = fact.get("upstream_updated_at") or fact.get("synced_at")
    if cutoff is not None:
        target["cutoffs"].append(str(cutoff))


def _coverage(material: dict, mappings: list[dict], matched_mapping_ids: set[int]) -> tuple[str, list[dict]]:
    reasons = []
    if material.get("version_id") is None:
        return "missing_version", [{"code": "missing_version", "message": "当前应用选择的素材版本不存在"}]
    if material.get("upload_status") != "uploaded":
        reasons.append({"code": "not_uploaded", "message": "素材版本尚未完成本地上传", "value": material.get("upload_status")})
    effective = [m for m in mappings if int(m.get("version_id") or 0) == int(material["version_id"])]
    if not effective:
        reasons.append({"code": "unmapped", "message": "当前版本没有平台素材映射"})
        return ("not_uploaded" if material.get("upload_status") != "uploaded" else "unmapped"), reasons
    ready = [m for m in effective if m.get("upload_status") == "uploaded" and m.get("platform_asset_id")]
    if len(ready) != len(effective):
        reasons.append({"code": "platform_upload_incomplete", "message": "部分平台映射尚未完成上传"})
    if material.get("upload_status") != "uploaded" or not ready:
        return "not_uploaded", reasons
    matched = sum(int(m["id"]) in matched_mapping_ids for m in ready)
    if matched == 0:
        reasons.append({"code": "no_platform_data", "message": "已有映射但所选日期内没有可关联的平台日报"})
        return "no_platform_data", reasons
    if matched < len(ready):
        reasons.append({"code": "partial_platform_data", "message": "只有部分平台映射关联到日报"})
        return "partial", reasons
    if len(ready) != len(effective):
        return "partial", reasons
    return "complete", reasons


def _metric_payload(metric: dict, *, roi_allowed: bool, reason: str | None) -> dict:
    spend, revenue = metric["spend"], metric["revenue"]
    roi = _ratio(revenue, spend) if roi_allowed else None
    has_rows = metric["rows"] > 0
    return {
        "currency": "USD", "spend": _amount(spend) if has_rows else None,
        "revenue_attributed": _amount(revenue) if has_rows else None,
        "impressions": metric["impressions"] if has_rows else None,
        "clicks": metric["clicks"] if has_rows else None,
        "installs": metric["installs"] if has_rows else None,
        "conversions": metric["conversions"] if has_rows else None,
        "ctr": _ratio(Decimal(metric["clicks"]), Decimal(metric["impressions"])) if has_rows else None,
        "roi": roi, "roi_reason": None if roi is not None else reason,
        "fact_rows": metric["rows"], "account_count": len(metric["accounts"]),
        "ad_count": len(metric["ads"]), "data_cutoff_at": max(metric["cutoffs"]) if metric["cutoffs"] else None,
    }


def _load(filters: AnalysisFilters) -> dict:
    scope = require_scope(application=True)
    materials = repository.list_materials()
    mappings = repository.list_material_mappings()
    accounts = repository.list_accounts()
    groups = repository.list_creative_groups()
    drafts = repository.list_draft_snapshots()
    facts = repository.list_facts(filters.date_from.isoformat(), filters.date_to.isoformat(),
                                  platform=filters.platform, account_id=filters.account_id)
    account_index = {(str(a["platform"]), str(a["account_id"])): a for a in accounts}
    filtered_mappings = [m for m in mappings
                         if (not filters.platform or m.get("platform") == filters.platform)
                         and (not filters.account_id or str(m.get("account_id")) == filters.account_id)]
    asset_index: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for mapping in filtered_mappings:
        key = (str(mapping.get("platform") or ""), str(mapping.get("account_id") or ""), str(mapping.get("platform_asset_id") or ""))
        if key[2]:
            asset_index[key].append(mapping)
    matched_mapping_ids: set[int] = set()
    facts_by_material: dict[int, dict] = defaultdict(_metric_seed)
    trend_by_material: dict[tuple[int, str], dict] = defaultdict(_metric_seed)
    unmatched_facts = 0
    ambiguous_facts = 0
    for fact in facts:
        candidates = []
        for asset in {str(fact.get("video_id") or ""), str(fact.get("creative_id") or "")} - {""}:
            candidates.extend(asset_index.get((str(fact.get("platform") or ""), str(fact.get("account_id") or ""), asset), []))
        unique = {int(item["id"]): item for item in candidates}
        material_ids = {int(item["material_id"]) for item in unique.values()}
        if len(material_ids) != 1:
            unmatched_facts += len(material_ids) == 0
            ambiguous_facts += len(material_ids) > 1
            continue
        material_id = next(iter(material_ids))
        matched_mapping_ids.update(unique)
        _add_metric(facts_by_material[material_id], fact)
        _add_metric(trend_by_material[(material_id, str(fact.get("stat_date")))], fact)
    mappings_by_material: dict[int, list[dict]] = defaultdict(list)
    for mapping in filtered_mappings:
        mappings_by_material[int(mapping["material_id"])].append(mapping)
    groups_by_material: dict[int, list[dict]] = defaultdict(list)
    for group in groups:
        groups_by_material[int(group["material_id"])].append(group)
    drafts_by_group: dict[int, list[dict]] = defaultdict(list)
    for draft in drafts:
        drafts_by_group[int(draft.get("creative_group_id") or 0)].append(draft)

    items = []
    for material in materials:
        material_id = int(material["material_id"])
        selected_mappings = mappings_by_material[material_id]
        status, reasons = _coverage(material, selected_mappings, matched_mapping_ids)
        metric = facts_by_material[material_id]
        cutoff_ok = bool(metric["dates"]) and max(metric["dates"]) >= filters.date_to.isoformat()
        if status == "complete" and not cutoff_ok:
            status = "delayed"
            reasons.append({"code": "source_delayed", "message": "平台日报尚未覆盖所选结束日期"})
        roi_allowed = status == "complete" and cutoff_ok and metric["rows"] > 0 and metric["spend"] > 0
        roi_reason = None if roi_allowed else ("no_spend" if metric["rows"] and not metric["spend"] else f"coverage_{status}")
        material_groups = groups_by_material[material_id]
        related_drafts = [draft for group in material_groups for draft in drafts_by_group[int(group["creative_group_id"])]]
        items.append({
            "entity_type": "material", "entity_id": str(material_id), "name": material.get("name") or f"素材 {material_id}",
            "drama_id": str(material["drama_id"]) if material.get("drama_id") is not None else None,
            "drama_title": material.get("drama_title"), "coverage_status": status, "coverage_reasons": reasons,
            "source_filename": material.get("source_filename"), "version_id": material.get("version_id"),
            "version_number": material.get("version_number"), "upload_status": material.get("upload_status"),
            "mapping_count": len(selected_mappings), "matched_mapping_count": sum(int(m["id"]) in matched_mapping_ids for m in selected_mappings),
            "platforms": sorted({str(m["platform"]) for m in selected_mappings}),
            "account_currencies": sorted({str(account_index.get((str(m["platform"]), str(m["account_id"])), {}).get("currency") or "未知") for m in selected_mappings}),
            "account_timezones": sorted({str(account_index.get((str(m["platform"]), str(m["account_id"])), {}).get("timezone") or "未知") for m in selected_mappings}),
            "metrics": _metric_payload(metric, roi_allowed=roi_allowed, reason=roi_reason),
            "creative_groups": [{"id": str(g["creative_group_id"]), "name": g.get("creative_group_name"), "status": g.get("creative_group_status")} for g in material_groups],
            "drafts": [{"id": str(d["id"]), "title": d.get("title"), "status": d.get("status"), "snapshot": "execution" if d.get("execution_snapshot") else "draft"} for d in related_drafts],
        })
    return {"scope": {"tenant_id": scope.tenant_id, "application_id": scope.application_id}, "materials": items,
            "trend_by_material": trend_by_material, "facts": facts, "accounts": accounts,
            "matched_mapping_ids": matched_mapping_ids, "unmatched_facts": unmatched_facts,
            "ambiguous_facts": ambiguous_facts, "mapping_total": len(filtered_mappings)}


def _drama_items(loaded: dict, filters: AnalysisFilters) -> list[dict]:
    buckets: dict[str, dict] = {}
    for item in loaded["materials"]:
        key = item["drama_id"] or "unassigned"
        bucket = buckets.setdefault(key, {"entity_type": "drama", "entity_id": key,
            "name": item["drama_title"] or "未关联剧目", "materials": [], "metric": _metric_seed()})
        bucket["materials"].append(item)
        metric = item["metrics"]
        # Aggregate only already-linked fact totals; coverage is evaluated independently below.
        bucket["metric"]["spend"] += _dec(metric["spend"])
        bucket["metric"]["revenue"] += _dec(metric["revenue_attributed"])
        for field in ("impressions", "clicks", "installs", "conversions"):
            bucket["metric"][field] += int(metric[field] or 0)
        bucket["metric"]["rows"] += int(metric["fact_rows"] or 0)
        bucket["metric"]["cutoffs"].extend([metric["data_cutoff_at"]] if metric["data_cutoff_at"] else [])
    result = []
    for bucket in buckets.values():
        statuses = {item["coverage_status"] for item in bucket["materials"]}
        status = "complete" if statuses == {"complete"} else (next(iter(statuses)) if len(statuses) == 1 else "partial")
        roi_allowed = status == "complete" and bucket["metric"]["spend"] > 0
        result.append({
            "entity_type": "drama", "entity_id": bucket["entity_id"], "name": bucket["name"],
            "drama_id": None if bucket["entity_id"] == "unassigned" else bucket["entity_id"], "drama_title": bucket["name"],
            "coverage_status": status,
            "coverage_reasons": [] if status == "complete" else [{"code": "material_coverage_incomplete", "message": "剧目下至少一个素材的来源覆盖不完整"}],
            "material_count": len(bucket["materials"]), "complete_material_count": sum(i["coverage_status"] == "complete" for i in bucket["materials"]),
            "mapping_count": sum(i["mapping_count"] for i in bucket["materials"]),
            "matched_mapping_count": sum(i["matched_mapping_count"] for i in bucket["materials"]),
            "platforms": sorted({p for i in bucket["materials"] for p in i["platforms"]}),
            "account_currencies": sorted({c for i in bucket["materials"] for c in i["account_currencies"]}),
            "account_timezones": sorted({z for i in bucket["materials"] for z in i["account_timezones"]}),
            "metrics": _metric_payload(bucket["metric"], roi_allowed=roi_allowed, reason=None if roi_allowed else f"coverage_{status}"),
            "materials": [{"id": i["entity_id"], "name": i["name"], "coverage_status": i["coverage_status"], "spend": i["metrics"]["spend"]} for i in bucket["materials"]],
        })
    return result


def report(filters: AnalysisFilters) -> dict:
    loaded = _load(filters)
    items = loaded["materials"] if filters.dimension == "material" else _drama_items(loaded, filters)
    query = filters.query.strip().casefold()
    if filters.coverage_status:
        items = [item for item in items if item["coverage_status"] == filters.coverage_status]
    if query:
        items = [item for item in items if query in " ".join(str(item.get(k) or "") for k in ("name", "entity_id", "drama_title", "source_filename")).casefold()]
    items.sort(key=lambda item: (-_dec(item["metrics"]["spend"]), item["name"], item["entity_id"]))
    total = len(items)
    start = (filters.page - 1) * filters.page_size
    coverage_counts: dict[str, int] = defaultdict(int)
    for item in items:
        coverage_counts[item["coverage_status"]] += 1
    selected_material_ids = ({int(item["entity_id"]) for item in items}
        if filters.dimension == "material"
        else {int(material["id"]) for item in items for material in item.get("materials", [])})
    trend: dict[str, dict] = defaultdict(_metric_seed)
    for (material_id, day), metric in loaded["trend_by_material"].items():
        if material_id in selected_material_ids:
            trend[day]["spend"] += metric["spend"]
            trend[day]["revenue"] += metric["revenue"]
            for field in ("impressions", "clicks", "installs", "conversions", "rows"):
                trend[day][field] += metric[field]
    mapped_facts = sum(item["metrics"]["fact_rows"] for item in loaded["materials"])
    return {
        "contract": "asset_analysis.v1", "scope": loaded["scope"], "read_only": True,
        "dimension": filters.dimension, "date_from": filters.date_from.isoformat(), "date_to": filters.date_to.isoformat(),
        "currency_policy": "USD attribution facts only; currencies are never combined or converted by this analysis.",
        "items": items[start:start + filters.page_size], "total": total, "page": filters.page, "page_size": filters.page_size,
        "trend": [{"date": day, **_metric_payload(metric, roi_allowed=False, reason="aggregate_coverage_not_proven")} for day, metric in sorted(trend.items())],
        "coverage": {
            "states": dict(sorted(coverage_counts.items())), "material_total": len(loaded["materials"]),
            "mapping_total": loaded["mapping_total"], "matched_mapping_total": len(loaded["matched_mapping_ids"]),
            "fact_rows_total": len(loaded["facts"]), "mapped_fact_rows": mapped_facts,
            "unmapped_fact_rows": loaded["unmatched_facts"], "ambiguous_fact_rows": loaded["ambiguous_facts"],
            "data_cutoff_at": max((value for f in loaded["facts"] if (value := _time(f.get("upstream_updated_at") or f.get("synced_at"))) is not None), default=None),
            "sources": ["APP: material/drama/version/reference/creative-group/draft/platform-mapping", "BIZ: biz_attribution_ad_daily"],
            "notes": ["缺失、延迟、未映射、未上传和无平台数据分别统计，不视为 0。", "仅 platform + account + platform_asset_id 与 video_id/creative_id 精确一致时归集。", "ROI 仅在对象映射和结束日期覆盖完整且消耗大于 0 时返回。"],
        },
    }
