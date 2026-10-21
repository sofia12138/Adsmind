"""阶段 4 X3-filter Round 2 — 业务查询的应用级账号过滤助手。

设计动机
========
`routes/biz.py` 下的报表/聚合接口本来就接受单值 `account_id` 过滤参数，
直接扩展所有 service / repository 签名为 `account_ids: list[str]` 成本巨大且风险高。

本模块在 **route 层** 做"应用白名单守门"，规则如下：

| 当前应用类型 | 用户是否传了 `account_id` | 应用下绑定账号数 | 行为 |
|---|---|---|---|
| 默认应用（is_default=1） | — | — | 完全不变，透传 `account_id` |
| 非默认应用 | 否 | 0 | `skip_query=True`，前端提示"请先绑定账号" |
| 非默认应用 | 否 | 1 | 自动注入唯一账号 ID |
| 非默认应用 | 否 | ≥ 2 | `skip_query=True`，提示"请指定 account_id" |
| 非默认应用 | 是 | — | 校验账号属于该应用，否则 403 |

副作用
------
- 不动 service / repository 签名，对老代码 0 影响
- 默认应用（含内部租户）行为 100% 不变
- 仅在非默认应用 + 多账号场景下，需要客户端配合传 `account_id`

落地接口
--------
首批接入：`/api/biz/overview`、`/api/biz/campaign-agg`（PoC 验证思路），
后续按需扩展到 `campaign-daily`、`top-campaigns`、`adgroup-*`、`ad-*`。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException

from core.application import ApplicationCtx
from repositories import biz_account_repository


@dataclass
class AccountFilter:
    """业务查询账号过滤结果。

    Attributes:
        account_id: 应注入到下游 service 的 account_id 参数（可能与 requested 相同/不同/None）。
        skip_query: True 表示根据应用上下文判定，应直接返回空，不发起昂贵的报表查询。
        hint: 当 skip_query=True 时给前端展示的提示语。
        bound_account_ids: 该应用绑定的账号 ID 列表（含 0/1/多）。便于上层做"账号选择器"。
    """

    account_id: Optional[str]
    skip_query: bool = False
    hint: Optional[str] = None
    bound_account_ids: tuple[str, ...] = ()


def resolve_account_filter(
    application: ApplicationCtx,
    requested_account_id: Optional[str],
) -> AccountFilter:
    """根据当前应用上下文解析业务查询的 account_id 过滤值。

    详见模块 docstring 的"规则表"。注意：阶段 7 后只有 internal tenant 的
    默认应用享受"全量视角"，外部租户即使在默认应用下也必须按应用过滤。
    """
    from core.tenant import INTERNAL_TENANT_ID
    bound_rows = (biz_account_repository.list_all() if application.is_default and application.tenant_id == INTERNAL_TENANT_ID else biz_account_repository.list_by_application(application.id))
    bound = tuple(
        sorted({str(r.get("account_id")) for r in bound_rows if r.get("account_id")})
    )

    # 用户没传 account_id：按应用绑定数自动决策
    if requested_account_id is None:
        if not bound:
            return AccountFilter(
                account_id=None,
                skip_query=True,
                hint=(
                    f"当前应用「{application.name}」未绑定任何广告账号，"
                    f"请先到应用配置页面绑定账号后再查询。"
                ),
                bound_account_ids=bound,
            )
        if len(bound) == 1:
            return AccountFilter(account_id=bound[0], bound_account_ids=bound)
        return AccountFilter(
            account_id=None,
            skip_query=True,
            hint=(
                f"当前应用「{application.name}」绑定了 {len(bound)} 个广告账号，"
                f"请在查询参数中指定 account_id。"
            ),
            bound_account_ids=bound,
        )

    # 用户传了 account_id：校验是否在应用白名单内
    if requested_account_id not in bound:
        raise HTTPException(
            status_code=403,
            detail=(
                f"账号 {requested_account_id} 不属于当前应用「{application.name}」。"
                f"应用绑定账号: {list(bound) if bound else '(无)'}"
            ),
        )
    return AccountFilter(account_id=requested_account_id, bound_account_ids=bound)


def get_application_account_whitelist(application: ApplicationCtx) -> Optional[set[str]]:
    """阶段 4 X3-filter Round 3：返回当前应用允许访问的 account_id 集合。

    用于 list 型接口（`biz_campaigns` / `biz_adgroups` / `biz_ads`）的后置过滤，
    它们没有暴露 `account_id` 单值参数，无法走 `resolve_account_filter` 的入参收窄逻辑。

    Returns:
        - None：**internal tenant 的默认应用**，跳过过滤，行为不变
        - set[str]：其它情况（含外部租户的默认应用）绑定的全部 account_id；可能为空集
                    （空集意味着应用未绑定任何账号，调用方应直接返回空列表）
    """
    from core.tenant import INTERNAL_TENANT_ID
    bound_rows = (biz_account_repository.list_all() if application.is_default and application.tenant_id == INTERNAL_TENANT_ID else biz_account_repository.list_by_application(application.id))
    return {str(r.get("account_id")) for r in bound_rows if r.get("account_id")}


def filter_rows_by_account_whitelist(
    rows: list[dict],
    whitelist: Optional[set[str]],
    *,
    key: str = "account_id",
) -> list[dict]:
    """根据账号白名单做行级过滤。`whitelist is None` 时不过滤（行为完全不变）。"""
    if whitelist is None:
        return rows
    if not whitelist:
        return []
    return [r for r in rows if str(r.get(key, "")) in whitelist]


__all__ = [
    "AccountFilter",
    "resolve_account_filter",
    "get_application_account_whitelist",
    "filter_rows_by_account_whitelist",
]
