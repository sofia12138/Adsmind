"""Verified request identity and tenant-owned CRUD boundaries."""
from contextvars import ContextVar
from dataclasses import dataclass
import re
from fastapi import HTTPException, Request
from starlette.responses import JSONResponse


@dataclass(frozen=True)
class Scope:
    tenant_id: int
    application_id: int | None = None


current_scope = ContextVar('verified_tenant_scope', default=None)


def tenant_id():
    scope = current_scope.get()
    return scope.tenant_id if scope else 1  # maintenance / internal scheduler


def application_id():
    scope = current_scope.get()
    return scope.application_id if scope else None


def default_account_id(platform):
    from repositories import biz_account_repository
    rows = biz_account_repository.list_active(application_id=application_id())
    return next((str(r['account_id']) for r in rows if r['platform'] == platform), '')


def check_entity(platform, level, entity_id):
    tables = {'campaign': ('biz_campaigns', 'campaign_id'), 'adgroup': ('biz_adgroups', 'adgroup_id'), 'ad': ('biz_ads', 'ad_id')}
    if level not in tables:
        raise HTTPException(400, '对象类型无效')
    table, column = tables[level]
    from db import get_biz_conn
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(f'SELECT account_id FROM {table} WHERE platform=%s AND {column}=%s', (platform, str(entity_id)))
        row = cur.fetchone()
    if not row:
        raise HTTPException(403, '对象不属于当前租户或尚未同步')
    from services.credential_service import _check_account_scope
    _check_account_scope(tenant_id(), platform, row['account_id'])


OWNED_TABLES = {
    'app_templates', 'app_oplog', 'asset_landing_pages', 'asset_copy_packs',
    'asset_region_groups', 'tiktok_material_uploads', 'biz_ad_accounts',
}

ACCOUNT_TABLES = {'biz_campaigns', 'biz_adgroups', 'biz_ads'}


def account_clause():
    return f'(platform, account_id) IN (SELECT platform, account_id FROM biz_ad_accounts WHERE tenant_id = {int(tenant_id())})'


def scoped_sql(sql, table):
    """Only simple, single-table CRUD. Unsupported shapes fail closed.

    Tenant values come exclusively from verified context, never user input.
    Parameters retain their original positions. This is not a general SQL parser.
    """
    if table not in OWNED_TABLES | ACCOUNT_TABLES:
        raise ValueError('Unsupported tenant table')
    sql = sql.strip()
    if ';' in sql or re.search(r'\b(JOIN|UNION|SELECT.*SELECT)\b', sql, re.I | re.S):
        raise ValueError('Tenant CRUD does not support compound queries')
    tid = int(tenant_id())
    if re.match(r'^INSERT\s+INTO\s+'+table+r'\s*\(', sql, re.I):
        if table in ACCOUNT_TABLES:
            return sql  # structure writes only follow authenticated platform reads
        sql = re.sub(r'^(INSERT\s+INTO\s+'+table+r'\s*\()', r'\1tenant_id, ', sql, count=1, flags=re.I)
        return re.sub(r'\bVALUES\s*\(', f'VALUES ({tid}, ', sql, count=1, flags=re.I)
    if not re.match(r'^(SELECT\s+.+\s+FROM|UPDATE|DELETE\s+FROM)\s+'+table+r'\b', sql, re.I | re.S):
        raise ValueError('Unsupported tenant CRUD statement')
    match = re.search(r'\b(ORDER\s+BY|LIMIT|FOR\s+UPDATE)\b', sql, re.I)
    head, tail = (sql[:match.start()], sql[match.start():]) if match else (sql, '')
    where = re.search(r'\bWHERE\b', head, re.I)
    condition = account_clause() if table in ACCOUNT_TABLES else f'tenant_id = {tid}'
    if where:
        head = head[:where.end()] + f' {condition} AND (' + head[where.end():].strip() + ') '
    else:
        head += f' WHERE {condition} '
    return head + tail


class TenantCursor:
    def __init__(self, cursor, table):
        self.cursor, self.table = cursor, table

    def execute(self, sql, args=None):
        return self.cursor.execute(scoped_sql(sql, self.table), args)

    def __getattr__(self, name):
        return getattr(self.cursor, name)


def tenant_cursor(conn, table):
    return TenantCursor(conn.cursor(), table)


PUBLIC = {
    ('POST', '/api/auth/reset-password'),
    ('POST', '/api/users/login'), ('POST', '/api/auth/register'),
    ('POST', '/api/auth/check-availability'),
}


def is_public(method, path):
    if (method, path.rstrip('/')) in PUBLIC:
        return True
    return bool(re.fullmatch(r'/api/auth/(verify-email|invitation)/[^/]+(?:/accept)?', path)) or bool(
        method == 'GET' and re.fullmatch(r'/api/integrations/(tiktok|meta)/oauth/(callback|mock-callback)', path))


class IsolationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and re.fullmatch(r'/api/integrations/(tiktok|meta)/oauth/(callback|mock-callback)', scope['path']):
            from integrations.oauth_base import verify_state, OAuthError
            try:
                request = Request(scope)
                payload = verify_state(request.query_params.get('state', ''))
                from core.tenant import get_tenant_by_id
                from core.application import get_application_by_id
                tenant = get_tenant_by_id(int(payload['t']))
                aid = (payload.get('x') or {}).get('a')
                app = get_application_by_id(int(aid)) if aid is not None else None
                if not tenant or tenant.status != 'active' or not app or app.tenant_id != tenant.id or not app.is_active:
                    raise OAuthError('授权目标租户或应用不可用')
            except (OAuthError, ValueError, KeyError, TypeError):
                return await JSONResponse({'detail': '授权状态无效或目标不可用'}, status_code=400)(scope, receive, send)
            token = current_scope.set(Scope(tenant.id, app.id))
            try:
                return await self.app(scope, receive, send)
            finally:
                current_scope.reset(token)
        if scope['type'] != 'http' or not scope['path'].startswith('/api/') or scope['method'] == 'OPTIONS' or is_public(scope['method'], scope['path']):
            return await self.app(scope, receive, send)
        request = Request(scope)
        try:
            from auth import decode_token, get_user
            from core.tenant import get_tenant_by_id
            from core.application import get_application_by_id, get_default_application_for_tenant
            from repositories import user_repository, tenant_member_repository
            header = request.headers.get('authorization', '')
            if not header.startswith('Bearer '):
                raise HTTPException(401, '未登录')
            payload = decode_token(header[7:])
            tid = payload.get('tenant_id')
            if not isinstance(tid, int):
                raise HTTPException(401, '请重新登录以确定所属租户')
            tenant = get_tenant_by_id(tid)
            if not tenant or tenant.status != 'active':
                raise HTTPException(403, '租户不存在或已停用')
            row = user_repository.get_by_username(payload.get('sub', ''))
            member = tenant_member_repository.get(tid, row['id']) if row else None
            if not member:
                raise HTTPException(403, '当前用户不属于此租户')
            aid = request.headers.get('x-application-id') or payload.get('application_id')
            try:
                app = get_application_by_id(int(aid)) if aid is not None else get_default_application_for_tenant(tid)
            except (ValueError, TypeError):
                raise HTTPException(400, '应用编号无效')
            if not app or app.tenant_id != tid or not app.is_active:
                raise HTTPException(403, '应用不存在、已停用或不属于当前租户')
            user = get_user(row['username'])
            if member['role'] in ('owner', 'admin'):
                user.role = 'super_admin' if user.role == 'super_admin' and tenant.is_internal else 'admin'
            elif user.role in ('admin', 'super_admin'):
                user.role = 'optimizer'
            request.state.tenant, request.state.application = tenant, app
            request.state.verified_user = user
            # Internal business sources are not customer-owned SaaS data.
            internal_only = ('/api/bizdata', '/api/ops', '/api/attribution', '/api/optimizer', '/api/drama', '/api/designer', '/api/analysis', '/api/insight')
            if not tenant.is_internal and any(scope['path'].startswith(p) for p in internal_only):
                raise HTTPException(403, '此功能仅供内部租户使用')
            if scope['path'] in ('/api/auth/authorize', '/api/auth/callback'):
                raise HTTPException(404, '请使用集成中心授权')
        except HTTPException as error:
            return await JSONResponse({'detail': error.detail}, status_code=error.status_code)(scope, receive, send)
        token = current_scope.set(Scope(tid, app.id))
        try:
            await self.app(scope, receive, send)
        finally:
            current_scope.reset(token)
