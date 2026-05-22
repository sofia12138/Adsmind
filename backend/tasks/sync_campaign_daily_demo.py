"""
BIZ 落库链路 Demo — 使用 mock 数据演示完整写库流程

用法：
    python -m tasks.sync_campaign_daily_demo

执行后可用以下 SQL 验证：
    USE adpilot_biz;
    SELECT * FROM biz_sync_logs ORDER BY id DESC LIMIT 5;
    SELECT * FROM biz_ad_accounts;
    SELECT * FROM biz_campaigns;
    SELECT * FROM biz_campaign_daily_normalized ORDER BY stat_date;
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from repositories import (
    biz_account_repository,
    biz_campaign_repository,
    biz_daily_report_repository,
    biz_sync_log_repository,
)

MOCK_ACCOUNTS = [
    {
        "platform": "tiktok",
        "account_id": "7602627489392394248",
        "account_name": "AdsMind Demo TikTok",
        "currency": "USD",
        "timezone": "America/Los_Angeles",
        "status": "ACTIVE",
        "raw_json": {"source": "demo", "advertiser_id": "7602627489392394248"},
    },
    {
        "platform": "meta",
        "account_id": "act_1859812594690702",
        "account_name": "AdsMind Demo Meta",
        "currency": "USD",
        "timezone": "America/New_York",
        "status": "ACTIVE",
        "raw_json": {"source": "demo", "ad_account_id": "act_1859812594690702"},
    },
]

MOCK_CAMPAIGNS = [
    {
        "platform": "tiktok",
        "account_id": "7602627489392394248",
        "campaign_id": "tt_camp_001",
        "campaign_name": "[Demo] TikTok 注册拉新",
        "objective": "CONVERSIONS",
        "buying_type": "",
        "status": "ENABLE",
        "is_active": True,
        "raw_json": {"source": "demo"},
    },
    {
        "platform": "tiktok",
        "account_id": "7602627489392394248",
        "campaign_id": "tt_camp_002",
        "campaign_name": "[Demo] TikTok 付费推广",
        "objective": "CONVERSIONS",
        "buying_type": "",
        "status": "ENABLE",
        "is_active": True,
        "raw_json": {"source": "demo"},
    },
    {
        "platform": "meta",
        "account_id": "act_1859812594690702",
        "campaign_id": "meta_camp_001",
        "campaign_name": "[Demo] Meta 拉新投放",
        "objective": "OUTCOME_APP_PROMOTION",
        "buying_type": "AUCTION",
        "status": "ACTIVE",
        "is_active": True,
        "raw_json": {"source": "demo"},
    },
]

MOCK_DAILY_REPORTS = [
    # TikTok campaign 1 — 3天日报
    {"platform": "tiktok", "account_id": "7602627489392394248", "campaign_id": "tt_camp_001",
     "campaign_name": "[Demo] TikTok 注册拉新", "stat_date": "2025-03-28",
     "spend": 520.30, "impressions": 45000, "clicks": 1800, "installs": 320, "conversions": 95, "revenue": 1250.00,
     "raw_json": {"source": "demo"}},
    {"platform": "tiktok", "account_id": "7602627489392394248", "campaign_id": "tt_camp_001",
     "campaign_name": "[Demo] TikTok 注册拉新", "stat_date": "2025-03-29",
     "spend": 480.75, "impressions": 42000, "clicks": 1650, "installs": 290, "conversions": 88, "revenue": 1100.00,
     "raw_json": {"source": "demo"}},
    {"platform": "tiktok", "account_id": "7602627489392394248", "campaign_id": "tt_camp_001",
     "campaign_name": "[Demo] TikTok 注册拉新", "stat_date": "2025-03-30",
     "spend": 550.00, "impressions": 48000, "clicks": 1900, "installs": 340, "conversions": 102, "revenue": 1380.00,
     "raw_json": {"source": "demo"}},
    # TikTok campaign 2 — 3天日报
    {"platform": "tiktok", "account_id": "7602627489392394248", "campaign_id": "tt_camp_002",
     "campaign_name": "[Demo] TikTok 付费推广", "stat_date": "2025-03-28",
     "spend": 310.00, "impressions": 28000, "clicks": 950, "installs": 0, "conversions": 42, "revenue": 890.00,
     "raw_json": {"source": "demo"}},
    {"platform": "tiktok", "account_id": "7602627489392394248", "campaign_id": "tt_camp_002",
     "campaign_name": "[Demo] TikTok 付费推广", "stat_date": "2025-03-29",
     "spend": 295.50, "impressions": 26000, "clicks": 880, "installs": 0, "conversions": 38, "revenue": 820.00,
     "raw_json": {"source": "demo"}},
    {"platform": "tiktok", "account_id": "7602627489392394248", "campaign_id": "tt_camp_002",
     "campaign_name": "[Demo] TikTok 付费推广", "stat_date": "2025-03-30",
     "spend": 330.20, "impressions": 30000, "clicks": 1020, "installs": 0, "conversions": 45, "revenue": 950.00,
     "raw_json": {"source": "demo"}},
    # Meta campaign — 3天日报
    {"platform": "meta", "account_id": "act_1859812594690702", "campaign_id": "meta_camp_001",
     "campaign_name": "[Demo] Meta 拉新投放", "stat_date": "2025-03-28",
     "spend": 420.00, "impressions": 38000, "clicks": 1500, "installs": 210, "conversions": 65, "revenue": 0,
     "raw_json": {"source": "demo"}},
    {"platform": "meta", "account_id": "act_1859812594690702", "campaign_id": "meta_camp_001",
     "campaign_name": "[Demo] Meta 拉新投放", "stat_date": "2025-03-29",
     "spend": 395.80, "impressions": 35000, "clicks": 1400, "installs": 195, "conversions": 60, "revenue": 0,
     "raw_json": {"source": "demo"}},
    {"platform": "meta", "account_id": "act_1859812594690702", "campaign_id": "meta_camp_001",
     "campaign_name": "[Demo] Meta 拉新投放", "stat_date": "2025-03-30",
     "spend": 440.50, "impressions": 40000, "clicks": 1600, "installs": 225, "conversions": 70, "revenue": 0,
     "raw_json": {"source": "demo"}},
]


def run_demo():
    logger.info("===== BIZ 落库 Demo 开始 =====")

    # 1) 创建同步日志 (running)
    log_id = biz_sync_log_repository.create(
        task_name="sync_campaign_daily_demo",
        platform="all",
        account_id="demo",
        sync_date="2025-03-30",
    )
    logger.info(f"同步日志已创建: id={log_id}, status=running")

    try:
        # 2) 写入广告账户
        for acct in MOCK_ACCOUNTS:
            biz_account_repository.upsert(**acct)
        logger.info(f"已写入 {len(MOCK_ACCOUNTS)} 个广告账户")

        # 3) 写入 campaign
        affected = biz_campaign_repository.upsert_batch(MOCK_CAMPAIGNS)
        logger.info(f"已写入 {len(MOCK_CAMPAIGNS)} 个 campaign, affected={affected}")

        # 4) 写入日报
        affected = biz_daily_report_repository.upsert_batch(MOCK_DAILY_REPORTS)
        logger.info(f"已写入 {len(MOCK_DAILY_REPORTS)} 条日报, affected={affected}")

        # 5) 更新同步日志为 success
        total_rows = len(MOCK_ACCOUNTS) + len(MOCK_CAMPAIGNS) + len(MOCK_DAILY_REPORTS)
        biz_sync_log_repository.finish(
            log_id,
            status="success",
            rows_affected=total_rows,
            message=f"demo 完成: {len(MOCK_ACCOUNTS)} 账户, "
                    f"{len(MOCK_CAMPAIGNS)} campaign, "
                    f"{len(MOCK_DAILY_REPORTS)} 条日报",
        )
        logger.info(f"同步日志已更新: id={log_id}, status=success")

    except Exception as e:
        biz_sync_log_repository.finish(
            log_id,
            status="failed",
            message=str(e),
        )
        logger.error(f"同步日志已更新: id={log_id}, status=failed, error={e}")
        raise

    logger.info("===== BIZ 落库 Demo 完成 =====")
    print()
    print("验证 SQL:")
    print("  USE adpilot_biz;")
    print("  SELECT * FROM biz_ad_accounts;")
    print("  SELECT platform, campaign_id, campaign_name, status FROM biz_campaigns;")
    print("  SELECT platform, campaign_id, stat_date, spend, ctr, cpc, roas FROM biz_campaign_daily_normalized ORDER BY platform, campaign_id, stat_date;")
    print("  SELECT id, task_name, status, rows_affected, message FROM biz_sync_logs ORDER BY id DESC LIMIT 5;")


if __name__ == "__main__":
    run_demo()
