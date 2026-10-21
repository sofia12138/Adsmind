"""Tenant-bound, one-time OAuth sessions; tokens never leave the server."""
import hashlib
import json
import secrets
from dataclasses import asdict
from urllib.parse import urlencode

from fastapi import HTTPException
from config import get_settings
from core import crypto
from core.isolation import tenant_id, application_id
from db import get_app_conn
from integrations.oauth_base import build_state, verify_state, default_redirect_uri
from integrations.tiktok.oauth import TikTokOAuth
from integrations.meta.oauth import MetaOAuth
from repositories import user_repository, tenant_member_repository, oauth_credential_repository
from services import account_service
from core.log_redaction import install

install()


def ensure_table():
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS app_oauth_sessions (
            id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL,
            application_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
            platform VARCHAR(20) NOT NULL DEFAULT 'tiktok',
            state_digest CHAR(64) NOT NULL, status VARCHAR(20) NOT NULL,
            payload_cipher LONGBLOB NULL, frontend_base VARCHAR(512) NOT NULL,
            expires_at DATETIME NOT NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_oauth_expiry(expires_at), INDEX idx_oauth_tenant(tenant_id)
        )''')
        cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='app_oauth_sessions' AND COLUMN_NAME='platform'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE app_oauth_sessions ADD COLUMN platform VARCHAR(20) NOT NULL DEFAULT 'tiktok'")
        # Expired sessions contain no usable credentials, even if metadata is retained.
        cur.execute('UPDATE app_oauth_sessions SET payload_cipher=NULL WHERE expires_at<=NOW() AND payload_cipher IS NOT NULL')
        conn.commit()


def flow(platform):
    if platform not in ('tiktok', 'meta'):
        raise HTTPException(404, '不支持的广告平台')
    return TikTokOAuth() if platform == 'tiktok' else MetaOAuth()


def start(username: str, platform='tiktok'):
    settings = get_settings()
    if platform not in ('tiktok', 'meta'):
        raise HTTPException(404, '不支持的广告平台')
    app_id = getattr(settings, platform+'_app_id')
    app_secret = getattr(settings, platform+'_app_secret')
    if not app_id or not app_secret:
        raise HTTPException(503, '平台授权应用尚未配置，请联系系统管理员')
    user = user_repository.get_by_username(username)
    sid = secrets.token_urlsafe(32)
    redirect = default_redirect_uri(platform)
    state = build_state(tenant_id(), platform, {'a': application_id(), 's': sid, 'r': redirect})
    frontend = (settings.public_base_url or 'http://localhost:4001').rstrip('/')
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute('INSERT INTO app_oauth_sessions (id,tenant_id,application_id,user_id,platform,state_digest,status,frontend_base,expires_at) VALUES (%s,%s,%s,%s,%s,%s,\'PENDING\',%s,NOW()+INTERVAL 10 MINUTE)',
                    (sid, tenant_id(), application_id(), user['id'], platform, hashlib.sha256(state.encode()).hexdigest(), frontend))
        conn.commit()
    oauth = TikTokOAuth(app_id, app_secret) if platform == 'tiktok' else MetaOAuth(app_id, app_secret)
    return {'authorize_url': oauth._build_url(redirect, state), 'state': state,
            'platform': platform, 'mock_mode': False, 'application_id': application_id()}


def transition(sid, before, after, payload=None):
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute('UPDATE app_oauth_sessions SET status=%s,payload_cipher=%s WHERE id=%s AND tenant_id=%s AND application_id=%s AND status=%s AND expires_at>NOW()',
                    (after, payload, sid, tenant_id(), application_id(), before))
        ok = cur.rowcount == 1
        conn.commit()
    return ok


def get(sid, username=None):
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute('SELECT * FROM app_oauth_sessions WHERE id=%s AND tenant_id=%s AND application_id=%s AND expires_at>NOW()', (sid, tenant_id(), application_id()))
        row = cur.fetchone()
    if not row or (username and row['user_id'] != user_repository.get_by_username(username)['id']):
        raise HTTPException(404, '授权会话无效或已过期，请重新连接')
    member = tenant_member_repository.get(row['tenant_id'], row['user_id'])
    if not member or member['role'] not in ('owner', 'admin'):
        raise HTTPException(403, '只有当前团队管理员可以连接账号')
    return row


async def callback(state, code, denied=False, platform='tiktok'):
    signed = verify_state(state)
    sid = (signed.get('x') or {}).get('s')
    row = get(sid)
    if signed['p'] != platform or row['platform'] != platform or row['state_digest'] != hashlib.sha256(state.encode()).hexdigest():
        raise HTTPException(400, '授权状态不匹配')
    if not transition(sid, 'PENDING', 'EXCHANGING'):
        raise HTTPException(409, '此授权回调已处理，请返回集成中心')
    try:
        if denied or not code:
            raise HTTPException(400, '用户取消授权')
        bundle = await flow(platform).exchange_code(code, default_redirect_uri(platform))
        if not bundle.accounts:
            raise HTTPException(422, '没有可连接的广告账号')
        payload = asdict(bundle)
        payload.pop('raw', None)
        if bundle.expires_at:
            payload['expires_at'] = bundle.expires_at.isoformat()
        encrypted = crypto.encrypt(json.dumps(payload), aad=sid.encode())
        if not transition(sid, 'EXCHANGING', 'READY', encrypted):
            raise HTTPException(422, '授权会话已过期')
        outcome = 'ready'
    except Exception:
        transition(sid, 'EXCHANGING', 'FAILED')
        outcome = 'failed'
    return row['frontend_base']+f'/settings/integrations/{platform}/complete?'+urlencode({'session_id': sid, 'result': outcome})


def pending(sid, username, platform):
    row = get(sid, username)
    if row['platform'] != platform:
        raise HTTPException(404, '授权会话不属于当前平台')
    if row['status'] != 'READY' or not row['payload_cipher']:
        raise HTTPException(422, '授权未完成、已取消或已使用，请重新连接')
    payload = json.loads(crypto.decrypt(row['payload_cipher'], aad=sid.encode()))
    return row, payload


def details(sid, username, platform='tiktok'):
    row, payload = pending(sid, username, platform)
    return {'application_id': row['application_id'], 'accounts': payload['accounts']}


def finish(sid, account_id, username, platform='tiktok'):
    row, payload = pending(sid, username, platform)
    account = next((a for a in payload['accounts'] if a['account_id'] == account_id), None)
    if not account:
        raise HTTPException(403, '账号不在本次授权范围内')
    from services.quota_service import enforce_account_quota
    enforce_account_quota(tenant_id(), additional=1, existing_account_id=account_id)
    encrypted = row['payload_cipher']
    if not transition(sid, 'READY', 'SAVING', encrypted):
        raise HTTPException(409, '账号正在保存或授权已使用')
    try:
        account_row = account_service.add_account(platform=platform, account_id=account_id,
            account_name=account['account_name'], access_token=payload['access_token'],
            currency=account['currency'], timezone=account['timezone'], application_id=application_id(),
            status=account.get('status') if account.get('status') in ('ACTIVE', 'DISABLED', 'PAUSED') else 'ACTIVE')
        from datetime import datetime
        expires = datetime.fromisoformat(payload['expires_at']) if payload.get('expires_at') else None
        oauth_credential_repository.upsert(tenant_id=tenant_id(), platform=platform, external_id=account_id,
            access_token=payload['access_token'], refresh_token=payload.get('refresh_token'), expires_at=expires,
            scopes=payload.get('scopes') or None)
        transition(sid, 'SAVING', 'COMPLETED')
        return {'data': account_row}
    except Exception:
        transition(sid, 'SAVING', 'READY', encrypted)
        raise
