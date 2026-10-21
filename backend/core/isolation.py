"""Verified tenant/application scope and tenant-owned CRUD boundaries.

The scope in this module is the only scope trusted by repositories, credentials,
background jobs, caches and file helpers.  It is populated after JWT, tenant
membership and application ownership have all been verified.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
import re
import tempfile
from typing import Iterator
from fastapi import HTTPException, Request
from starlette.responses import JSONResponse


@dataclass(frozen=True)
class Scope:
    tenant_id: int
    application_id: int | None = None

    def __post_init__(self):
        if int(self.tenant_id) <= 0:
            raise ValueError('tenant_id 必须是正整数')
        if self.application_id is not None and int(self.application_id) <= 0:
            raise ValueError('application_id 必须是正整数')


current_scope = ContextVar('verified_tenant_scope', default=None)


class ScopeNotBoundError(RuntimeError):
    """Raised when tenant-owned work runs without an explicitly verified scope."""


def require_scope(*, application: bool = False) -> Scope:
    scope = current_scope.get()
    if not isinstance(scope, Scope):
        raise ScopeNotBoundError('缺少已验证的租户作用域')
    if application and scope.application_id is None:
        raise ScopeNotBoundError('缺少已验证的应用作用域')
    return scope


def tenant_id():
    return require_scope().tenant_id


def application_id():
    return require_scope(application=True).application_id


@contextmanager
def bound_scope(scope: Scope) -> Iterator[Scope]:
    """Bind an already-authorized scope for scripts and background jobs."""
    token = current_scope.set(scope)
    try:
        yield scope
    finally:
        current_scope.reset(token)


def scope_cache_key(namespace: str, *parts: object, level: str = 'application') -> str:
    """Build a non-colliding key for tenant/application caches and task locks."""
    scope = require_scope(application=level == 'application')
    if level not in ('tenant', 'application'):
        raise ValueError('level 必须是 tenant 或 application')
    components = [namespace, f'tenant:{scope.tenant_id}']
    if level == 'application':
        components.append(f'application:{scope.application_id}')
    components.extend(str(part) for part in parts)
    return ':'.join(components)


def scoped_object_path(namespace: str, *parts: str, level: str = 'application') -> str:
    """Return a safe relative object path with mandatory ownership prefixes."""
    scope = require_scope(application=level == 'application')
    clean = [_safe_path_part(namespace)]
    clean.extend(('tenants', str(scope.tenant_id)))
    if level == 'application':
        clean.extend(('applications', str(scope.application_id)))
    clean.extend(_safe_path_part(part) for part in parts)
    return '/'.join(clean)


def scoped_temp_dir(namespace: str) -> Path:
    """Create/return a process-local temporary directory scoped to the app."""
    relative = scoped_object_path(namespace)
    path = Path(tempfile.gettempdir()) / 'adsmind' / relative
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _safe_path_part(value: object) -> str:
    text = str(value).strip()
    if not text or text in ('.', '..') or '/' in text or '\\' in text:
        raise ValueError('对象路径包含非法片段')
    return text


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
    'asset_region_groups', 'tiktok_material_uploads',
}

# Tables whose records are never meaningful outside one verified application.
# Keep this list deliberately small: using a tenant-only cursor for one of these
# tables would make same-tenant, cross-application access possible.
APPLICATION_OWNED_TABLES = {
    'biz_ad_accounts',
    'app_account_groups',
    'app_creative_groups',
    'app_naming_rules',
    'app_execution_records',
    'app_launch_drafts',
    'app_ad_creation_drafts',
    'app_distribution_channels',
    'app_distribution_drafts',
}

ACCOUNT_TABLES = {'biz_campaigns', 'biz_adgroups', 'biz_ads'}


def account_clause():
    scope = require_scope(application=True)
    return (
        '(platform, account_id) IN '
        '(SELECT platform, account_id FROM biz_ad_accounts '
        f'WHERE tenant_id = {int(scope.tenant_id)} '
        f'AND application_id = {int(scope.application_id)})'
    )


def require_owned_accounts(conn, rows) -> None:
    """Reject account-backed writes unless every row belongs to this app.

    Sync repositories use platform responses as input, but repository methods
    remain a security boundary and cannot trust a caller-provided account id.
    """
    scope = require_scope(application=True)
    requested = {
        (str(row.get('platform') or ''), str(row.get('account_id') or ''))
        for row in rows
    }
    if not requested or any(not platform or not account_id for platform, account_id in requested):
        raise ScopeNotBoundError('业务记录缺少广告账户作用域')
    placeholders = ','.join(['(%s,%s)'] * len(requested))
    params = []
    for platform, account_id in sorted(requested):
        params.extend((platform, account_id))
    params.extend((scope.tenant_id, scope.application_id))
    cur = conn.cursor()
    cur.execute(
        'SELECT platform, account_id FROM biz_ad_accounts '
        f'WHERE (platform, account_id) IN ({placeholders}) '
        'AND tenant_id=%s AND application_id=%s',
        params,
    )
    owned = {(str(row['platform']), str(row['account_id'])) for row in cur.fetchall()}
    if owned != requested:
        raise ScopeNotBoundError('广告账户不属于当前应用')


def scoped_sql(sql, table):
    """Only simple, single-table CRUD. Unsupported shapes fail closed.

    Tenant values come exclusively from verified context, never user input.
    Parameters retain their original positions. This is not a general SQL parser.
    """
    if table not in OWNED_TABLES | APPLICATION_OWNED_TABLES | ACCOUNT_TABLES:
        raise ValueError('Unsupported tenant table')
    sql = sql.strip()
    if ';' in sql or re.search(r'\b(JOIN|UNION|SELECT.*SELECT)\b', sql, re.I | re.S):
        raise ValueError('Tenant CRUD does not support compound queries')
    tid = int(tenant_id())
    if re.match(r'^INSERT\s+INTO\s+'+table+r'\s*\(', sql, re.I):
        if table in ACCOUNT_TABLES:
            return sql  # structure writes only follow authenticated platform reads
        columns = f'tenant_id, application_id, ' if table in APPLICATION_OWNED_TABLES else 'tenant_id, '
        values = f'{tid}, {int(application_id())}, ' if table in APPLICATION_OWNED_TABLES else f'{tid}, '
        sql = re.sub(r'^(INSERT\s+INTO\s+'+table+r'\s*\()', rf'\1{columns}', sql, count=1, flags=re.I)
        return re.sub(r'\bVALUES\s*\(', f'VALUES ({values}', sql, count=1, flags=re.I)
    if not re.match(r'^(SELECT\s+.+\s+FROM|UPDATE|DELETE\s+FROM)\s+'+table+r'\b', sql, re.I | re.S):
        raise ValueError('Unsupported tenant CRUD statement')
    match = re.search(r'\b(ORDER\s+BY|LIMIT|FOR\s+UPDATE)\b', sql, re.I)
    head, tail = (sql[:match.start()], sql[match.start():]) if match else (sql, '')
    where = re.search(r'\bWHERE\b', head, re.I)
    if table in ACCOUNT_TABLES:
        condition = account_clause()
    elif table in APPLICATION_OWNED_TABLES:
        condition = f'tenant_id = {tid} AND application_id = {int(application_id())}'
    else:
        condition = f'tenant_id = {tid}'
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
        hide_material_scope = scope['path'].startswith('/api/material-catalog')
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
                raise HTTPException(
                    404 if hide_material_scope else 403,
                    '资源不存在' if hide_material_scope else '应用不存在、已停用或不属于当前租户',
                )
            # Tenant owners/admins administer every application in their tenant.
            # Ordinary tenant members must be explicitly assigned to the selected
            # application; merely knowing an application id never grants access.
            if member.get('role') not in ('owner', 'admin'):
                from repositories import application_repository
                if application_repository.get_member_role(app.id, row['id']) is None:
                    raise HTTPException(
                        404 if hide_material_scope else 403,
                        '资源不存在' if hide_material_scope else '当前用户无权访问此应用',
                    )
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
