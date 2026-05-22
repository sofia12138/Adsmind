"""运营数据面板 service 层

把 biz_ops_daily 的多行（os_type=0/1/2）合并成前端 DailyOpsRow 一行的扁平结构。

约定：
- 输入 [start_date, end_date] 闭区间，区间内每个 ds 都返回一行
  （即使该 ds 在库里没有任何记录，也补全零行 — 让前端图表 X 轴对齐）
- 金额字段单位 USD（已在同步层从美分换算，DECIMAL → float）
- 日期字段统一 'YYYY-MM-DD' 字符串
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from repositories import biz_attribution_ad_intraday_repository as intraday_repo
from repositories import biz_daily_report_repository as norm_repo
from repositories import biz_ops_daily_intraday_repository as ops_intraday_repo
from repositories import biz_ops_daily_repository as repo
from repositories import biz_ops_daily_shadow_repository as shadow_repo
from repositories import recharge_order_repository as recharge_repo

_LA_TZ = ZoneInfo("America/Los_Angeles")


def _ds_to_str(ds) -> str:
    if isinstance(ds, (date, datetime)):
        return ds.strftime("%Y-%m-%d")
    return str(ds)[:10]


def _empty_row(ds: str) -> dict:
    return {
        "date": ds,
        # 用户侧
        "new_register_uv": 0,
        "new_active_uv": 0,
        "active_uv": 0,
        "d1_retained_uv": 0,
        "d7_retained_uv": 0,
        "d30_retained_uv": 0,
        "total_payer_uv": 0,
        # 投放侧（全量平台合计，单位 USD）
        "ad_spend": 0.0,
        # iOS
        "ios_subscribe_revenue": 0.0,
        "ios_onetime_revenue": 0.0,
        "ios_first_sub_orders": 0,
        "ios_repeat_sub_orders": 0,
        "ios_first_iap_orders": 0,
        "ios_repeat_iap_orders": 0,
        "ios_payer_uv": 0,
        # Android
        "android_subscribe_revenue": 0.0,
        "android_onetime_revenue": 0.0,
        "android_first_sub_orders": 0,
        "android_repeat_sub_orders": 0,
        "android_first_iap_orders": 0,
        "android_repeat_iap_orders": 0,
        "android_payer_uv": 0,
        # 数据来源标记 (前端可据此提示)
        "revenue_source": "platform",  # 'platform' = MC 全量真值；'intraday_fallback' = CK 归因兜底（偏低）
    }


def _merge_user_row(out: dict, raw: dict) -> None:
    """把 os_type=0 的用户侧行（+投放）合并到目标 dict"""
    out["new_register_uv"] = int(raw.get("new_register_uv") or 0)
    out["new_active_uv"]   = int(raw.get("new_active_uv") or 0)
    out["active_uv"]       = int(raw.get("active_uv") or 0)
    out["d1_retained_uv"]  = int(raw.get("d1_retained_uv") or 0)
    out["d7_retained_uv"]  = int(raw.get("d7_retained_uv") or 0)
    out["d30_retained_uv"] = int(raw.get("d30_retained_uv") or 0)
    out["total_payer_uv"]  = int(raw.get("total_payer_uv") or 0)
    out["ad_spend"]        = float(raw.get("ad_spend_usd") or 0)


def _merge_pay_row(out: dict, raw: dict, prefix: str) -> None:
    """把 os_type=1/2 的付费行合并到目标 dict（prefix 'ios_' 或 'android_'）"""
    out[f"{prefix}subscribe_revenue"]   = float(raw.get("subscribe_revenue_usd") or 0)
    out[f"{prefix}onetime_revenue"]     = float(raw.get("onetime_revenue_usd") or 0)
    out[f"{prefix}first_sub_orders"]    = int(raw.get("first_sub_orders") or 0)
    out[f"{prefix}repeat_sub_orders"]   = int(raw.get("repeat_sub_orders") or 0)
    out[f"{prefix}first_iap_orders"]    = int(raw.get("first_iap_orders") or 0)
    out[f"{prefix}repeat_iap_orders"]   = int(raw.get("repeat_iap_orders") or 0)
    out[f"{prefix}payer_uv"]            = int(raw.get("payer_uv") or 0)


def query_daily_ops(start_date: str, end_date: str, *, source: str = "auto") -> list[dict]:
    """读取运营面板日报。

    返回升序日期数组，区间内每天一行。
    某天如果在库里没记录，会补全零行（图表 X 轴需要对齐）。

    source 参数控制付费侧数据源（不影响用户侧 / 投放侧）：
      - auto    今日/昨日 LA 走 biz_ops_daily_intraday，其余走 biz_ops_daily (dwd)
      - dwd     全部走 biz_ops_daily (老行为)
      - polardb 历史走 biz_ops_daily_polardb_shadow，今日/昨日仍走 intraday
    """
    # 主源（dwd 路径）— 提供用户侧 (os_type=0)、付费侧 (os_type=1/2)、ad_spend
    raw_rows = repo.query_range(start_date, end_date)

    # 先按 (ds_str → empty_row) 建桩，保证每个 ds 都有一行
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    by_ds: dict[str, dict] = {}
    cur = start
    while cur <= end:
        ds_str = cur.strftime("%Y-%m-%d")
        by_ds[ds_str] = _empty_row(ds_str)
        cur += timedelta(days=1)

    # 决定付费侧哪些 ds 走 dwd（默认全部），哪些走 polardb 影子表
    pay_overrides: dict[str, dict] = {}
    if source in ("polardb", "auto"):
        pay_overrides = _resolve_pay_overrides(start_date, end_date, source)

    # 合并 dwd 主源各行（注意：付费侧后面可能被覆盖）
    for raw in raw_rows:
        ds_str = _ds_to_str(raw.get("ds"))
        if ds_str not in by_ds:
            continue
        os_type = int(raw.get("os_type") or 0)
        if os_type == 0:
            _merge_user_row(by_ds[ds_str], raw)
        elif os_type == 1:  # Android
            # 仅当该 ds 不在 polardb 覆盖列表里时才用 dwd 付费侧
            if ds_str not in pay_overrides:
                _merge_pay_row(by_ds[ds_str], raw, "android_")
        elif os_type == 2:  # iOS
            if ds_str not in pay_overrides:
                _merge_pay_row(by_ds[ds_str], raw, "ios_")

    # 应用 polardb / intraday 付费侧覆盖
    for ds_str, ds_overrides in pay_overrides.items():
        if ds_str not in by_ds:
            continue
        for os_type, raw in ds_overrides.items():
            if not isinstance(os_type, int):
                continue  # 跳过 "_label" 等元信息键
            prefix = "android_" if os_type == 1 else "ios_"
            _merge_pay_row(by_ds[ds_str], raw, prefix)
        # 标记数据源，便于前端展示与排障
        by_ds[ds_str]["revenue_source"] = ds_overrides.get("_label", "polardb")

    # ad_spend 数据源切换说明：
    #   主源：biz_campaign_daily_normalized — 直接来自 Meta/TikTok 平台 API，
    #         跟 AdsMind Meta 操作台 / 平台后台账单 1:1 同源（口径最准）。
    #   fallback：biz_attribution_ad_intraday — 仅在主源对某天没有任何分区时兜底，
    #         避免主源同步任务中断导致面板完全空白。
    # 不再使用 biz_ops_daily.ad_spend_usd（其上游 biz_attribution_ad_daily 是归因
    # cohort 口径，TikTok 归因数据缺失会导致系统性偏低，与平台后台不符）。
    _override_ad_spend_from_normalized(by_ds, start_date, end_date)

    # 收入兜底：sync_ops_daily / sync_ops_pay_intraday 都没拉到付费侧时（如 DMS
    # AccessKey 失效），从 biz_attribution_ad_intraday 取 first_sub/first_iap 实时
    # 归因金额作为最后兜底。注意这是「投放归因流水」口径，比 dwd_recharge_order_df
    # 全量真值偏低（漏自然流量、漏未归因、漏二次充值），仅作为应急展示。
    _fill_revenue_from_intraday(by_ds, start_date, end_date)

    return [by_ds[k] for k in sorted(by_ds.keys())]


def _resolve_pay_overrides(start_date: str, end_date: str,
                           source: str) -> dict[str, dict]:
    """根据 source 决定哪些 ds 用 polardb 数据覆盖付费侧。

    返回结构：
        { ds_str: { 1: row_android, 2: row_ios, "_label": "intraday"|"polardb" } }

    优先级（source=auto）：
        1. 今日/昨日 LA → biz_ops_daily_intraday（实时层，最新）
        2. 其余日期 → 不覆盖（保留 dwd 主源）

    优先级（source=polardb）：
        1. 今日/昨日 LA → biz_ops_daily_intraday
        2. 其余日期 → biz_ops_daily_polardb_shadow
    """
    out: dict[str, dict] = {}
    today_la = datetime.now(_LA_TZ).date()
    yesterday_la = today_la - timedelta(days=1)
    realtime_dates = {today_la.strftime("%Y-%m-%d"),
                      yesterday_la.strftime("%Y-%m-%d")}

    # ── 实时层（今日+昨日 LA）── 适用于 auto 和 polardb 两种模式
    try:
        intraday_rows = ops_intraday_repo.query_range(start_date, end_date)
    except Exception:
        intraday_rows = []
    for r in intraday_rows:
        ds_str = _ds_to_str(r.get("ds"))
        if ds_str not in realtime_dates:
            continue  # intraday 表只保留 2 天，但保险起见再过滤
        os_type = int(r.get("os_type") or 0)
        if os_type not in (1, 2):
            continue
        out.setdefault(ds_str, {"_label": "intraday"})[os_type] = r

    # ── shadow 历史层（仅 source=polardb 启用）──
    if source == "polardb":
        try:
            shadow_rows = shadow_repo.query_range(start_date, end_date)
        except Exception:
            shadow_rows = []
        for r in shadow_rows:
            ds_str = _ds_to_str(r.get("ds"))
            if ds_str in realtime_dates:
                continue  # 已被 intraday 覆盖，不重复
            os_type = int(r.get("os_type") or 0)
            if os_type not in (1, 2):
                continue
            out.setdefault(ds_str, {"_label": "polardb"})[os_type] = r

    return out


def _override_ad_spend_from_normalized(by_ds: dict[str, dict],
                                       start_date: str, end_date: str) -> None:
    """用 biz_campaign_daily_normalized 的 SUM(spend) 覆盖每天的 ad_spend。

    主源命中的日期：直接覆盖（无论原值是 0 还是非 0），保证跟操作台口径一致。
    主源未命中的日期：兜底到 biz_attribution_ad_intraday；都没有则保持原值（通常为 0）。
    """
    try:
        norm_spend = norm_repo.sum_spend_by_stat_date(start_date, end_date)
    except Exception:
        norm_spend = {}

    missing_days: list[str] = []
    for ds in by_ds.keys():
        v = norm_spend.get(ds)
        if v is not None:
            by_ds[ds]["ad_spend"] = float(v)
        elif not by_ds[ds].get("ad_spend"):
            missing_days.append(ds)

    if not missing_days:
        return
    try:
        intraday_spend = intraday_repo.sum_spend_by_ds_la(start_date, end_date)
    except Exception:
        return
    for ds in missing_days:
        v = intraday_spend.get(ds)
        if v and v > 0:
            by_ds[ds]["ad_spend"] = float(v)


def _fill_revenue_from_intraday(by_ds: dict[str, dict],
                                start_date: str, end_date: str) -> None:
    """对 daily 付费侧完全为空的日期，从 biz_attribution_ad_intraday 取归因流水兜底。

    判定条件：iOS / Android 的订阅 + 内购 4 项金额全为 0 且 4 项订单数全为 0。
    满足时，该天有可能是 sync_ops_daily / sync_ops_pay_intraday 都没拉到的应急情况。
    口径警示：CK intraday 是「按 ad_id 归因」的投放流水，比 MC 全量订单流水偏低，
    仅作为兜底展示，待 MC 同步任务恢复后会被覆盖回真值。
    """
    def _is_pay_empty(row: dict) -> bool:
        for prefix in ("ios_", "android_"):
            for k in ("subscribe_revenue", "onetime_revenue",
                      "first_sub_orders", "first_iap_orders",
                      "repeat_sub_orders", "repeat_iap_orders"):
                if row.get(f"{prefix}{k}"):
                    return False
        return True

    empty_days = [ds for ds, row in by_ds.items() if _is_pay_empty(row)]
    if not empty_days:
        return
    try:
        from db import get_biz_conn
        intraday_rev: dict[str, dict] = {}
        with get_biz_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT ds_la, "
                "       SUM(first_sub_amount)  AS first_sub_amount, "
                "       SUM(first_iap_amount)  AS first_iap_amount, "
                "       SUM(first_sub_count)   AS first_sub_count, "
                "       SUM(first_iap_count)   AS first_iap_count "
                "FROM biz_attribution_ad_intraday "
                "WHERE ds_la BETWEEN %s AND %s "
                "GROUP BY ds_la",
                (start_date, end_date),
            )
            for r in cur.fetchall():
                ds = r.get("ds_la")
                ds_str = ds.strftime("%Y-%m-%d") if hasattr(ds, "strftime") else str(ds)[:10]
                intraday_rev[ds_str] = r
    except Exception:
        return

    for ds in empty_days:
        rec = intraday_rev.get(ds)
        if not rec:
            continue
        sub_amt = float(rec.get("first_sub_amount") or 0)
        iap_amt = float(rec.get("first_iap_amount") or 0)
        sub_cnt = int(rec.get("first_sub_count") or 0)
        iap_cnt = int(rec.get("first_iap_count") or 0)
        if sub_amt + iap_amt <= 0 and sub_cnt + iap_cnt <= 0:
            continue
        # CK intraday 表无 os_type 维度，兜底时把总量统一塞到 iOS 字段（不拆平台）。
        # KPI 卡总收入 = iOS+Android 仍然正确；按平台拆分会显示在 iOS 一侧偏高，
        # 这是有意为之的「警示性失真」 — 配合 revenue_source 标记前端会提示。
        # 真值口径恢复后会被 MC 全量数据覆盖。
        by_ds[ds]["ios_subscribe_revenue"]    = round(sub_amt, 4)
        by_ds[ds]["ios_onetime_revenue"]      = round(iap_amt, 4)
        by_ds[ds]["ios_first_sub_orders"]     = sub_cnt
        by_ds[ds]["ios_first_iap_orders"]     = iap_cnt
        by_ds[ds]["revenue_source"]           = "intraday_fallback"


# ─────────────────────────────────────────────────────────────
#  分时段（LA 小时）充值趋势
# ─────────────────────────────────────────────────────────────

def query_hourly_revenue(start_date: str, end_date: str) -> dict:
    """从 PolarDB 拉取 [start_date, end_date] 区间每日 × 每小时（LA）的充值数据。

    返回结构（前端友好）：
      {
        "days": ["2026-05-06", "2026-05-07", ...],         # 升序日期
        "series": [
          { "ds": "2026-05-06", "hours": [{h, orders, payer_uv,
            total_usd, android_usd, ios_usd, sub_usd, iap_usd}, ...24 项] },
          ...
        ]
      }
    每天 24 小时全部补齐（无数据时各指标为 0），便于前端按 X 轴 0~23 直接画线。
    """
    rows = recharge_repo.fetch_hourly_by_la_day(start_date, end_date)

    by_day: dict[str, dict[int, dict]] = {}
    for r in rows:
        ds = _ds_to_str(r["ds"])
        h = int(r["h"])
        by_day.setdefault(ds, {})[h] = {
            "h": h,
            "orders":      int(r.get("orders") or 0),
            "payer_uv":    int(r.get("payer_uv") or 0),
            "total_usd":   float(r.get("total_usd") or 0),
            "android_usd": float(r.get("android_usd") or 0),
            "ios_usd":     float(r.get("ios_usd") or 0),
            "sub_usd":     float(r.get("sub_usd") or 0),
            "iap_usd":     float(r.get("iap_usd") or 0),
        }

    days: list[str] = []
    cur = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    while cur <= end:
        days.append(cur.strftime("%Y-%m-%d"))
        cur = cur + timedelta(days=1)

    def _empty_hour(h: int) -> dict:
        return {
            "h": h, "orders": 0, "payer_uv": 0,
            "total_usd": 0.0, "android_usd": 0.0, "ios_usd": 0.0,
            "sub_usd": 0.0, "iap_usd": 0.0,
        }

    series = []
    for ds in days:
        hrs = by_day.get(ds, {})
        series.append({
            "ds": ds,
            "hours": [hrs.get(h) or _empty_hour(h) for h in range(24)],
        })
    return {"days": days, "series": series}
