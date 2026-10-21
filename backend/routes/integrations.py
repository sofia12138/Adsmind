"""第三方平台集成路由（阶段 2 新增）。

提供：
  - GET  /api/integrations/platforms                      列出可用平台
  - GET  /api/integrations/{platform}/oauth/start         生成授权跳转 URL（前端打开新窗口）
  - GET  /api/integrations/{platform}/oauth/callback      授权码回调（落库凭证 + 同步账户）
  - GET  /api/integrations/credentials                    列出当前 tenant 的凭证元信息（不含密文）
  - DELETE /api/integrations/{platform}/{external_id}     撤销凭证

详见 docs/saas-transformation.md §7.6、§8.1。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger

from auth import User, get_current_user, require_admin
from pydantic import BaseModel, Field
from core.tenant import TenantCtx, get_current_tenant
from integrations.base import get_oauth_flow, supported_oauth_platforms
from integrations.oauth_base import OAuthError, build_state, default_redirect_uri, verify_state
from repositories import oauth_credential_repository as cred_repo
from services import account_service

router = APIRouter(prefix="/integrations", tags=["第三方集成"])


# ── 列表 ──────────────────────────────────────────────────────────

@router.get("/platforms")
async def list_platforms(_: User = Depends(get_current_user)):
    """返回当前已实现 OAuth 接入的平台列表。"""
    return {"platforms": supported_oauth_platforms()}


@router.get("/credentials")
async def list_credentials(
    platform: Optional[str] = Query(None),
    tenant: TenantCtx = Depends(get_current_tenant),
    _: User = Depends(get_current_user),
):
    """列出当前租户的凭证元数据（不含密文 / 不含 token）。"""
    rows = cred_repo.list_by_tenant(tenant.id, platform=platform)
    return {"items": rows}


@router.get("/overview", summary="集成中心总览：平台状态 + 凭证 + 配置情况")
async def integrations_overview(
    request: Request,
    tenant: TenantCtx = Depends(get_current_tenant),
    _: User = Depends(get_current_user),
):
    """聚合接口供前端 /settings/integrations 使用：

    返回每个平台的：
      - 是否配置了真实 OAuth (configured)
      - 当前租户已授权的凭证数 / 即将过期数 / 过期数
      - mock_available（未配置真实凭证时也能演示）
    """
    from datetime import datetime, timedelta

    now = datetime.now()
    soon_threshold = now + timedelta(days=14)
    items: list[dict] = []
    for p in supported_oauth_platforms():
        configured = _platform_credentials_configured(p)
        creds = cred_repo.list_by_tenant(tenant.id, platform=p)
        valid = 0
        expiring = 0
        expired = 0
        for c in creds:
            exp = c.get("expires_at")
            if exp is None:
                valid += 1
                continue
            try:
                if exp < now:
                    expired += 1
                elif exp <= soon_threshold:
                    expiring += 1
                else:
                    valid += 1
            except Exception:
                valid += 1
        items.append({
            "platform": p,
            "configured": configured,
            "mock_available": _mock_mode_allowed(p, request, force_mock=True),
            "credentials": {
                "total": len(creds),
                "valid": valid,
                "expiring": expiring,
                "expired": expired,
            },
        })
    return {
        "tenant_id": tenant.id,
        "items": items,
        "redirect_base": (default_redirect_uri("tiktok")
                          .rsplit("/", 3)[0] if items else None),
    }


# ── OAuth 入口 ────────────────────────────────────────────────────

def _platform_credentials_configured(platform: str) -> bool:
    """检测平台是否配置了真实 OAuth 凭证（app_id+secret）。否则 fallback 到 mock 模式。"""
    from config import get_settings
    s = get_settings()
    if platform == "tiktok":
        return bool(getattr(s, "tiktok_app_id", "") and getattr(s, "tiktok_app_secret", ""))
    if platform == "meta":
        return bool(getattr(s, "meta_app_id", "") and getattr(s, "meta_app_secret", ""))
    return False


def _is_local_request(request: Request | None) -> bool:
    if request is None:
        return False
    host = (request.headers.get("host") or "").split(":")[0].lower()
    client = (request.client.host if request.client else "") or ""
    return host in ("127.0.0.1", "localhost", "::1") or client in ("127.0.0.1", "::1")


def _mock_mode_allowed(platform: str, request: Request | None, force_mock: bool = False) -> bool:
    if platform in ('tiktok', 'meta'):
        return False
    from core.isolation import current_scope
    scope = current_scope.get()
    if scope is None or scope.tenant_id != 1 or not _is_local_request(request):
        return False
    """未配置真实凭证 → mock；或本地冒烟显式 force_mock=1。"""
    if not _platform_credentials_configured(platform):
        return True
    return bool(force_mock and _is_local_request(request))


@router.get("/{platform}/oauth/start")
async def oauth_start(
    platform: str,
    request: Request,
    redirect_uri: Optional[str] = Query(None, description="覆盖默认回调地址（可选）"),
    application_id: Optional[int] = Query(None, description="授权完成后把同步账号绑定到该应用"),
    force_mock: bool = Query(False, description="本地冒烟：强制走 mock（仅 127.0.0.1）"),
    tenant: TenantCtx = Depends(get_current_tenant),
    _: User = Depends(get_current_user),
):
    """生成授权跳转 URL。前端拿到 `authorize_url` 后用新窗口/新标签页打开。

    阶段 7 #1 增强：
      - `application_id` 编码到 state 里，回调时同步的账号自动绑到该应用
      - 平台未配置 app_id/secret 时返回 `mock_authorize_url`，进入演示流程
    """
    from core.application import get_application_by_id

    if platform in ('tiktok', 'meta'):
        require_admin(_)
        from core.isolation import application_id as scoped_application_id
        if application_id is not None and application_id != scoped_application_id():
            raise HTTPException(403, '请选择当前应用进行授权')
        if redirect_uri is not None and redirect_uri != default_redirect_uri(platform):
            raise HTTPException(400, '授权回调地址由服务端配置')
        from services.platform_authorization import start
        return start(_.username, platform)

    final_redirect = redirect_uri or default_redirect_uri(platform)
    extra: dict = {"r": final_redirect}

    # 应用归属校验：传 application_id 时必须属于当前 tenant
    effective_app_id: Optional[int] = None
    if application_id is not None:
        app = get_application_by_id(int(application_id))
        if not app or app.tenant_id != tenant.id:
            raise HTTPException(status_code=404, detail="application_id 不属于本租户")
        effective_app_id = int(application_id)
        extra["a"] = effective_app_id
    else:
        # 兜底：用 request.state 上的当前应用
        rs_app = getattr(request.state, "application", None) if request else None
        if rs_app is not None:
            effective_app_id = int(rs_app.id)
            extra["a"] = effective_app_id

    state = build_state(tenant.id, platform, extra=extra)

    if _mock_mode_allowed(platform, request, force_mock=force_mock):
        # mock 模式：返回后端模拟回调链接，前端打开后直接走完整 callback 流程
        from urllib.parse import urlencode
        mock_url = f"{final_redirect.rstrip('/')}".rsplit("/", 1)[0]  # not actually used
        scheme = "http"
        host = request.headers.get("host", "127.0.0.1:5000") if request else "127.0.0.1:5000"
        if request and getattr(request.url, "scheme", None):
            scheme = request.url.scheme
        q: dict = {"state": state, "mock": "1"}
        if force_mock:
            q["force_mock"] = "1"
        params = urlencode(q)
        mock_authorize_url = f"{scheme}://{host}/api/integrations/{platform}/oauth/mock-callback?{params}"
        return {
            "platform": platform,
            "mock_mode": True,
            "authorize_url": mock_authorize_url,
            "state": state,
            "redirect_uri": final_redirect,
            "application_id": effective_app_id,
            "hint": f"{platform} 平台未配置真实 app_id/secret，正在使用 mock 演示模式",
        }

    if not _platform_credentials_configured(platform):
        raise HTTPException(503, '平台授权应用尚未配置，请联系系统管理员')
    try:
        flow = get_oauth_flow(platform)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    auth_url = flow._build_url(final_redirect, state)
    return {
        "platform": platform,
        "mock_mode": False,
        "authorize_url": auth_url,
        "state": state,
        "redirect_uri": final_redirect,
        "application_id": effective_app_id,
    }


@router.get("/{platform}/oauth/callback")
async def oauth_callback(
    platform: str,
    request: Request,
    code: Optional[str] = Query(None, description="平台返回的授权码"),
    state: str = Query(..., description="start 阶段生成的签名 state"),
    auth_code: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
):
    """OAuth 回调：换 token、加密落库、同步账户列表到 biz_ad_accounts。

    注意此端点**不依赖** `get_current_user`：用户已被重定向到平台站点后跳回，
    身份从 state HMAC 中还原。
    """
    if platform in ('tiktok', 'meta'):
        from services.platform_authorization import callback
        from fastapi.responses import RedirectResponse
        target = await callback(state, (auth_code or code) if platform == 'tiktok' else code, denied=bool(error), platform=platform)
        return RedirectResponse(target, status_code=303, headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})
    try:
        payload = verify_state(state)
    except OAuthError as e:
        raise HTTPException(status_code=400, detail=f"state 校验失败：{e}")

    if payload.get("p") != platform:
        raise HTTPException(status_code=400, detail="state 与 URL platform 不匹配")
    tenant_id = int(payload["t"])
    extra = payload.get("x") or {}
    redirect_uri = extra.get("r") or default_redirect_uri(platform)
    application_id_from_state: Optional[int] = (
        int(extra["a"]) if extra.get("a") is not None else None
    )

    try:
        flow = get_oauth_flow(platform)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        bundle = await flow.exchange_code(code, redirect_uri=redirect_uri)
    except OAuthError as e:
        logger.warning(f"[oauth] {platform} exchange_code 失败 tenant={tenant_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"[oauth] {platform} 异常 tenant={tenant_id}: {e}")
        raise HTTPException(status_code=500, detail="OAuth 处理异常，请稍后重试")

    # 1) 加密落库凭证（按主 external_id 与所有账户分别落一份，便于多账号下发不同 token）
    saved = 0
    external_ids = {bundle.primary_external_id} if bundle.primary_external_id else set()
    for a in bundle.accounts:
        if a.get("account_id"):
            external_ids.add(str(a["account_id"]))
    if not external_ids:
        # 平台未返回账户（极少见），仍写一条占位
        external_ids = {"_default_"}

    for ext_id in external_ids:
        try:
            cred_repo.upsert(
                tenant_id=tenant_id,
                platform=platform,
                external_id=str(ext_id),
                access_token=bundle.access_token,
                refresh_token=bundle.refresh_token,
                expires_at=bundle.expires_at,
                scopes=bundle.scopes or None,
            )
            saved += 1
        except Exception as e:
            logger.error(f"[oauth] 凭证落库失败 tenant={tenant_id} ext={ext_id}: {e}")

    # 2) 同步账户元信息到 biz_ad_accounts（不再写明文 token；token 走 oauth_credentials）
    # 阶段 7 #1：把账号自动绑到 state 里携带的 application_id（外部租户的应用语义）
    upserted = 0
    for a in bundle.accounts:
        try:
            account_service.add_account(
                platform=platform,
                account_id=str(a.get("account_id", "")),
                account_name=a.get("account_name", ""),
                # 兼容层：service 层暂时仍接收 token 字段，但传空避免明文落 biz_ad_accounts
                access_token="",
                app_id="",
                app_secret="",
                currency=a.get("currency", "USD"),
                timezone=a.get("timezone", ""),
                application_id=application_id_from_state,
            )
            upserted += 1
        except Exception as e:
            logger.warning(f"[oauth] account_service.add_account 失败：{e}")

    logger.info(
        f"[oauth] {platform} 完成 tenant={tenant_id} credentials={saved} accounts={upserted}"
    )

    # 3) 返回简单 HTML 提示，前端可监听 window.opener.postMessage 后关闭
    from fastapi.responses import HTMLResponse
    html = f"""
    <!doctype html>
    <html><head><meta charset="utf-8"><title>授权完成</title></head>
    <body style="font-family:system-ui;padding:48px;text-align:center;">
      <h2>授权完成 ✓</h2>
      <p>{platform} · {saved} 份凭证已安全保存，{upserted} 个广告账户已同步。</p>
      <p style="color:#888">本窗口可关闭，返回 AdsMind 查看接入状态。</p>
      <script>
        try {{ window.opener && window.opener.postMessage({{ type: 'oauth_complete', platform: '{platform}', credentials: {saved}, accounts: {upserted} }}, '*'); }} catch(e) {{}}
        setTimeout(function() {{ window.close(); }}, 2000);
      </script>
    </body></html>
    """
    return HTMLResponse(content=html)


class FinishPlatformAuthorization(BaseModel):
    account_id: str = Field(min_length=1, max_length=128)


@router.get('/{platform}/authorization/{session_id}')
async def get_platform_authorization(platform: str, session_id: str, user=Depends(require_admin)):
    from services.platform_authorization import details
    from fastapi.responses import JSONResponse
    return JSONResponse(details(session_id, user.username, platform), headers={'Cache-Control': 'no-store'})


@router.post('/{platform}/authorization/{session_id}')
async def finish_platform_authorization(platform: str, session_id: str, req: FinishPlatformAuthorization, user=Depends(require_admin)):
    from services.platform_authorization import finish
    return finish(session_id, req.account_id, user.username, platform)


# ── Mock 模式（无真实平台凭证时演示用） ──────────────────────────

@router.get("/{platform}/oauth/mock-callback")
async def oauth_mock_callback(
    platform: str,
    request: Request,
    state: str = Query(...),
    force_mock: bool = Query(False, description="本地冒烟：已配置真实凭证时仍允许 mock"),
):
    """阶段 7 #1 演示用：不调真实平台 API，直接生成 1-2 个假账号 + 凭证落库。

    安全：未配置凭证时允许；或 localhost + force_mock=1。state 仍走 HMAC 校验。
    """
    if not _mock_mode_allowed(platform, request, force_mock=force_mock):
        raise HTTPException(
            status_code=400,
            detail=f"{platform} 已配置真实凭证，请走标准 oauth 流程",
        )
    try:
        payload = verify_state(state)
    except OAuthError as e:
        raise HTTPException(status_code=400, detail=f"state 校验失败：{e}")
    if payload.get("p") != platform:
        raise HTTPException(status_code=400, detail="state 与 URL platform 不匹配")
    tenant_id = int(payload["t"])
    extra = payload.get("x") or {}
    application_id_from_state: Optional[int] = (
        int(extra["a"]) if extra.get("a") is not None else None
    )

    import secrets as _secrets
    from datetime import datetime as _dt, timedelta as _td

    # 生成 2 个 mock 账号
    mock_accounts = [
        {
            "account_id": f"mock_{platform}_{_secrets.token_hex(4)}",
            "account_name": f"Mock {platform.upper()} 账号 #1",
            "currency": "USD",
            "timezone": "America/Los_Angeles",
        },
        {
            "account_id": f"mock_{platform}_{_secrets.token_hex(4)}",
            "account_name": f"Mock {platform.upper()} 账号 #2",
            "currency": "EUR",
            "timezone": "Europe/Berlin",
        },
    ]

    # 凭证落库（明文为 mock_*，加密后写入）
    saved = 0
    upserted = 0
    for a in mock_accounts:
        mock_token = f"mock_token_{_secrets.token_hex(16)}"
        try:
            cred_repo.upsert(
                tenant_id=tenant_id,
                platform=platform,
                external_id=a["account_id"],
                access_token=mock_token,
                refresh_token=None,
                expires_at=_dt.now() + _td(days=365),
                scopes=["mock"],
            )
            saved += 1
        except Exception as e:
            logger.warning(f"[oauth mock] 凭证落库失败：{e}")

        # 账号同步到 biz_ad_accounts，自动绑定到 state.a
        try:
            account_service.add_account(
                platform=platform,
                account_id=a["account_id"],
                account_name=a["account_name"],
                access_token=mock_token,
                app_id="",
                app_secret="",
                currency=a["currency"],
                timezone=a["timezone"],
                application_id=application_id_from_state,
            )
            upserted += 1
        except Exception as e:
            logger.warning(f"[oauth mock] add_account 失败：{e}")

    logger.info(
        f"[oauth mock] {platform} tenant={tenant_id} app={application_id_from_state} "
        f"credentials={saved} accounts={upserted}"
    )

    from fastapi.responses import HTMLResponse
    html = f"""
    <!doctype html>
    <html><head><meta charset="utf-8"><title>授权完成（演示模式）</title></head>
    <body style="font-family:system-ui;padding:48px;text-align:center;background:#f8f9fb">
      <div style="display:inline-block;padding:32px 48px;background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.06)">
        <div style="font-size:48px;line-height:1">🎭</div>
        <h2 style="margin:12px 0 4px;color:#111">演示模式授权完成</h2>
        <p style="color:#555;margin:8px 0;font-size:14px">
          已为本租户模拟创建 <b>{saved}</b> 份 {platform.upper()} 凭证，
          <b>{upserted}</b> 个广告账号已自动同步并绑定到所选应用。
        </p>
        <p style="color:#888;margin-top:18px;font-size:12px">
          这是 mock 数据，仅供 SaaS 流程演示。上线时配置真实 {platform} app_id/secret 即可走完整 OAuth。
        </p>
      </div>
      <script>
        try {{
          window.opener && window.opener.postMessage(
            {{ type: 'oauth_complete', platform: '{platform}', credentials: {saved}, accounts: {upserted}, mock: true }},
            '*'
          );
        }} catch(e) {{}}
        setTimeout(function() {{ window.close(); }}, 2500);
      </script>
    </body></html>
    """
    return HTMLResponse(content=html)


# ── 撤销 ──────────────────────────────────────────────────────────

@router.delete("/{platform}/credentials/{external_id}")
async def delete_credential(
    platform: str,
    external_id: str,
    tenant: TenantCtx = Depends(get_current_tenant),
    _: User = Depends(get_current_user),
):
    ok = cred_repo.delete(tenant.id, platform, external_id)
    if not ok:
        raise HTTPException(status_code=404, detail="凭证不存在")
    return {"ok": True}
