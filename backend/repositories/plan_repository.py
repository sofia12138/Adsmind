"""套餐数据访问层 — 封装 app_plans 表的读取。

阶段 7 配额限流 MVP 的基础设施：所有配额校验先调本仓库拿到套餐元数据，
再结合 usage 统计判定是否放行。
"""
from __future__ import annotations

import json
from typing import Optional

from db import get_app_conn
from loguru import logger


_FALLBACK_PLAN_FREE = {
    "id": "free",
    "name": "Free",
    "accounts_limit": 1,
    "api_calls_monthly": 5000,
    "ai_calls_monthly": 0,
    "sync_interval_min": 60,
    "data_retention_days": 30,
    "price_monthly_cents": 0,
    "features": {"plugins": ["core_ads"], "applications_limit": 1, "members_limit": 1},
}


# 表 app_plans 没有 applications_limit / members_limit 列；约定从 features JSON 读，
# 并对每个套餐提供兜底默认值（避免线上 seed 还没补就崩）。
_DEFAULT_APPLICATIONS_LIMIT_BY_PLAN = {
    "internal":   999,
    "free":       1,
    "starter":    3,
    "pro":        10,
    "business":   30,
    "enterprise": 999,
}
_DEFAULT_MEMBERS_LIMIT_BY_PLAN = {
    "internal":   999,
    "free":       1,
    "starter":    5,
    "pro":        20,
    "business":   100,
    "enterprise": 999,
}


def get_by_id(plan_id: str) -> Optional[dict]:
    """读取套餐定义；查不到返回 None。"""
    try:
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT id, name, accounts_limit, api_calls_monthly, ai_calls_monthly,
                          sync_interval_min, data_retention_days, price_monthly_cents, features
                   FROM app_plans WHERE id = %s""",
                (plan_id,),
            )
            row = cur.fetchone()
    except Exception as e:
        logger.warning(f"plan_repository.get_by_id({plan_id}) 查询失败：{e}")
        return None
    if not row:
        return None
    if isinstance(row.get("features"), str):
        try:
            row["features"] = json.loads(row["features"]) or {}
        except Exception:
            row["features"] = {}
    elif row.get("features") is None:
        row["features"] = {}
    return row


def get_quota_for_plan(plan_id: str) -> dict:
    """读取套餐的"配额视图"，归一化各上限字段；查不到则用 free 兜底。

    返回字段：
      - applications_limit / accounts_limit / members_limit
      - api_calls_monthly / ai_calls_monthly
      - sync_interval_min / data_retention_days
      - plan_id / plan_name
    """
    plan = get_by_id(plan_id) or _FALLBACK_PLAN_FREE
    features = plan.get("features") or {}

    return {
        "plan_id": plan["id"],
        "plan_name": plan["name"],
        "applications_limit": int(
            features.get("applications_limit",
                         _DEFAULT_APPLICATIONS_LIMIT_BY_PLAN.get(plan["id"], 1))
        ),
        "accounts_limit": int(plan.get("accounts_limit", 1)),
        "members_limit": int(
            features.get("members_limit",
                         _DEFAULT_MEMBERS_LIMIT_BY_PLAN.get(plan["id"], 1))
        ),
        "api_calls_monthly": int(plan.get("api_calls_monthly", 5000)),
        "ai_calls_monthly": int(plan.get("ai_calls_monthly", 0)),
        "sync_interval_min": int(plan.get("sync_interval_min", 60)),
        "data_retention_days": int(plan.get("data_retention_days", 30)),
        "features": features,
    }
