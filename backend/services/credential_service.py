"""统一凭证解析服务（阶段 2 — 接入加密表）。

三级降级策略，保证迁移期/未配置密钥的环境向后兼容：

  1. `app_oauth_credentials`（AES-GCM 加密表，OAuth 流程写入）
  2. `biz_ad_accounts.access_token`（旧明文字段；002 迁移后清空）
  3. `settings.{platform}_access_token`（.env 默认值，本地开发兜底）

所有业务模块（TikTokClient / MetaClient / routes / services / tasks）都应通过
`resolve_access_token()` 取 token，而非自行读 settings 或 biz_account_repository。

详见 docs/saas-transformation.md §20.6。
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

from core.tenant import INTERNAL_TENANT_ID


# ── 内部工具 ──────────────────────────────────────────────────────

def _from_oauth_credentials(tenant_id: int, platform: str, account_id: Optional[str]) -> Optional[str]:
    """从加密凭证表读取。account_id=None 时取该平台下任意一条（升序第一个）。"""
    try:
        from repositories import oauth_credential_repository as cred_repo
    except Exception as e:
        logger.debug(f"credential_service: oauth_credential_repository 不可用：{e}")
        return None

    try:
        if account_id:
            token = cred_repo.get_access_token(tenant_id, platform, str(account_id))
            if token:
                return token
        # account_id 缺省：取该 tenant + platform 下任意一条凭证
        rows = cred_repo.list_by_tenant(tenant_id, platform=platform)
        for row in rows:
            ext_id = row.get("external_id")
            if not ext_id:
                continue
            token = cred_repo.get_access_token(tenant_id, platform, str(ext_id))
            if token:
                return token
    except Exception as e:
        logger.debug(f"credential_service: 加密表读取失败 tenant={tenant_id} {platform}:{account_id} → {e}")
    return None


def _from_legacy_biz_accounts(platform: str, account_id: Optional[str]) -> Optional[str]:
    """从旧的明文 `biz_ad_accounts.access_token` 字段读取（兼容路径）。"""
    try:
        from repositories import biz_account_repository
    except Exception:
        return None
    try:
        if account_id:
            row = biz_account_repository.get_by_platform_account(platform, str(account_id))
            if row and row.get("access_token"):
                return str(row["access_token"])
            return None
        rows = biz_account_repository.list_by_platform(platform)
        # 优先 is_default=1 的
        rows_sorted = sorted(rows, key=lambda r: -int(r.get("is_default") or 0))
        for r in rows_sorted:
            if r.get("access_token"):
                return str(r["access_token"])
    except Exception as e:
        logger.debug(f"credential_service: biz_ad_accounts 读取失败 {platform}:{account_id} → {e}")
    return None


def _from_settings_default(platform: str) -> Optional[str]:
    """从 .env 全局默认 token 读取（最后兜底，仅本地/单租户）。"""
    try:
        from config import get_settings
        settings = get_settings()
    except Exception:
        return None
    if platform == "tiktok":
        token = settings.tiktok_access_token or ""
    elif platform == "meta":
        token = settings.meta_access_token or ""
    else:
        token = ""
    return token or None


# ── 公共 API ──────────────────────────────────────────────────────

def resolve_access_token(
    platform: str,
    account_id: Optional[str] = None,
    tenant_id: Optional[int] = None,
) -> Optional[str]:
    """统一入口：按 `加密表 → 明文兼容 → .env` 优先级解析 access_token。

    参数:
      platform:   "tiktok" / "meta" / "google" / "oceanengine" / "snapchat"
      account_id: 平台侧账号 id（可选；缺省时取默认账户）
      tenant_id:  租户 id；None 时默认 internal tenant (id=1)，保留旧行为

    返回:
      明文 access_token；全部级别都找不到时返回 None。
    """
    tid = int(tenant_id) if tenant_id else INTERNAL_TENANT_ID

    # Layer 1：加密表
    token = _from_oauth_credentials(tid, platform, account_id)
    if token:
        return token

    # Layer 2：旧明文字段（迁移期兼容）
    token = _from_legacy_biz_accounts(platform, account_id)
    if token:
        return token

    # Layer 3：.env 默认 token
    return _from_settings_default(platform)


def resolve_token_source(
    platform: str,
    account_id: Optional[str] = None,
    tenant_id: Optional[int] = None,
) -> tuple[Optional[str], str]:
    """与 `resolve_access_token` 相同，但同时返回来源标签，便于日志/审计。

    返回 (token, source) 之一：
      - ("xxx", "oauth_credentials")  ← 加密表（推荐）
      - ("xxx", "biz_ad_accounts")    ← 旧明文（兼容）
      - ("xxx", "settings_env")       ← .env 兜底
      - (None,  "none")               ← 没找到
    """
    tid = int(tenant_id) if tenant_id else INTERNAL_TENANT_ID

    token = _from_oauth_credentials(tid, platform, account_id)
    if token:
        return token, "oauth_credentials"

    token = _from_legacy_biz_accounts(platform, account_id)
    if token:
        return token, "biz_ad_accounts"

    token = _from_settings_default(platform)
    if token:
        return token, "settings_env"

    return None, "none"
