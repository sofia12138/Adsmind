"""Durable template launch drafts. Successful platform writes are replayed locally.

A pending/unknown write is never automatically repeated: the platform may already
have accepted it. This mechanism does not claim platform-wide idempotency.
"""
from contextvars import ContextVar
import copy
import hashlib
import json
import uuid
from fastapi import HTTPException
from db import get_app_conn
from services import template_service

_active = ContextVar('launch_draft', default=None)
_SECRET_KEYS = {'access_token', 'app_secret', 'password', 'cookie', 'secret'}


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if k.lower() not in _SECRET_KEYS}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def init_table():
    with get_app_conn() as conn:
        conn.cursor().execute('''CREATE TABLE IF NOT EXISTS app_launch_drafts (
            id CHAR(36) PRIMARY KEY, tenant_id BIGINT NOT NULL, application_id BIGINT NOT NULL,
            created_by VARCHAR(255) NOT NULL, request_key CHAR(36) NOT NULL,
            name VARCHAR(255) NOT NULL, platform VARCHAR(16) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'DRAFT', revision INT NOT NULL DEFAULT 1,
            payload JSON NOT NULL, template_snapshot JSON NOT NULL, checkpoints JSON NOT NULL,
            result JSON NULL, last_error TEXT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_launch_draft_request (tenant_id, application_id, created_by, request_key),
            KEY idx_launch_draft_scope (tenant_id, application_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        conn.commit()


def decode(row):
    if not row:
        return None
    row = dict(row)
    for key in ('payload', 'template_snapshot', 'checkpoints', 'result'):
        if isinstance(row.get(key), str):
            row[key] = json.loads(row[key])
    for key in ('created_at', 'updated_at'):
        if row.get(key):
            row[key] = str(row[key])
    return row


def load(draft_id, application, user):
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute('SELECT * FROM app_launch_drafts WHERE id=%s AND tenant_id=%s AND application_id=%s AND created_by=%s',
                    (draft_id, application.tenant_id, application.id, user.username))
        row = decode(cur.fetchone())
    if not row:
        raise HTTPException(404, '草稿不存在或无权访问')
    return row


def list_drafts(application, user, page):
    with get_app_conn() as conn:
        cur = conn.cursor()
        args = (application.tenant_id, application.id, user.username)
        where = 'WHERE tenant_id=%s AND application_id=%s AND created_by=%s'
        cur.execute('SELECT COUNT(*) AS total FROM app_launch_drafts '+where, args)
        total = cur.fetchone()['total']
        cur.execute('SELECT * FROM app_launch_drafts '+where+' ORDER BY created_at DESC, id LIMIT 20 OFFSET %s', (*args, (page-1)*20))
        rows = [public(decode(row)) for row in cur.fetchall()]
    return {'list': rows, 'total': total, 'page': page, 'page_size': 20}


def public(row):
    result = {k: v for k, v in row.items() if k not in ('template_snapshot', 'checkpoints', 'created_by', 'request_key', 'tenant_id', 'application_id')}
    result['template_name'] = (row.get('template_snapshot') or {}).get('name', '投放模板')
    template = row.get('template_snapshot') or {}
    result['budget_mode'] = 'CBO' if template.get('template_type') == 'web_to_app_conversion_cbo' or template.get('id') == 'tpl_meta_web_to_app_conv_cbo' else 'ABO'
    return result


def precheck(payload, tpl, application, user):
    from core.biz_filter import resolve_account_filter
    from services import account_service
    platform = tpl.get('platform', 'tiktok')
    account_id = str(payload.get('ad_account_id' if platform == 'meta' else 'advertiser_id') or '')
    checks = []
    def check(code, ok, message):
        checks.append({'code': code, 'ok': bool(ok), 'message': message})
    check('role', user.role in ('admin', 'super_admin', 'optimizer'), '当前账号具有广告创建权限')
    accounts = account_service.list_accounts(platform, application_id=None if application.is_default and application.tenant_id == 1 else application.id)
    account = next((a for a in accounts if str(a['account_id']) == account_id), None)
    check('account', bool(account), '已选择当前应用可用的广告账户')
    if account:
        check('account_status', account.get('status') == 'ACTIVE',
              '广告账户状态正常' if account.get('status') == 'ACTIVE' else '广告账户已停用或状态异常，请先在平台恢复后同步账户')
        from services.launch_budget import budget_checks
        checks.extend(budget_checks(payload, platform, account.get('currency')))
    if account_id:
        try:
            resolve_account_filter(application, account_id)
        except HTTPException:
            check('application_scope', False, '广告账户不属于当前应用')
        if user.role == 'optimizer':
            check('assigned_account', account_id in user.assigned_accounts, '广告账户已分配给当前优化师')
    check('name', bool(str(payload.get('campaign_name') or '').strip()), '广告系列名称已填写')
    try:
        budget = float(payload.get('budget') or 0)
        check('budget', 0 < budget < float('inf'), '日预算必须为正数')
    except (ValueError, TypeError):
        check('budget', False, '日预算必须为正数')
    if platform == 'meta':
        materials = payload.get('materials') or []
        check('materials', bool(materials) and all(m.get('video_id') or m.get('image_hash') for m in materials), '已选择上传完成的广告素材')
        for index, adset in enumerate(payload.get('adsets') or []):
            check(f'adset_materials_{index}', bool(adset.get('material_ids')), f'广告组 {index+1} 已分配素材')
    else:
        check('materials', bool(payload.get('video_id') or payload.get('materials') or payload.get('creatives')), '已选择上传完成的广告素材')
    return {'ok': all(c['ok'] for c in checks), 'checks': checks, 'notice': '这是本地配置预检查；素材审核、余额和平台限制以实际接口结果为准。'}


def create(payload, request_key, application, user):
    try:
        uuid.UUID(request_key)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, '草稿请求编号无效')
    payload = clean(copy.deepcopy(payload))
    tpl = template_service.get_template(payload.get('template_id'))
    if not tpl:
        raise HTTPException(404, '模板不存在')
    tpl = clean(tpl)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    draft_id = str(uuid.uuid4())
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute('''INSERT IGNORE INTO app_launch_drafts
            (id, tenant_id, application_id, created_by, request_key, name, platform, payload, template_snapshot, checkpoints)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (draft_id, application.tenant_id, application.id, user.username, request_key,
                     str(payload.get('campaign_name') or '未命名草稿')[:255], tpl.get('platform', 'tiktok'), encoded, json.dumps(tpl, ensure_ascii=False), '{}'))
        cur.execute('SELECT * FROM app_launch_drafts WHERE tenant_id=%s AND application_id=%s AND created_by=%s AND request_key=%s',
                    (application.tenant_id, application.id, user.username, request_key))
        row = decode(cur.fetchone())
        conn.commit()
    if row['payload'] != payload:
        raise HTTPException(409, '同一请求编号不能用于不同的草稿内容')
    return row


def update(row, changes, revision, application, user):
    from decimal import Decimal, InvalidOperation
    from repositories import biz_account_repository
    if row['status'] != 'DRAFT':
        raise HTTPException(409, '只有尚未执行的草稿可以修改')
    name = str(changes.get('campaign_name') or '').strip()
    if not name or len(name) > 255:
        raise HTTPException(400, '请填写不超过 255 字的广告系列名称')
    def amount(value):
        try:
            value = Decimal(str(value))
            if not value.is_finite() or value <= 0 or value*100 != (value*100).to_integral_value():
                raise ValueError()
            return float(value)
        except (InvalidOperation, ValueError, TypeError):
            raise HTTPException(400, '预算必须为正数，且最多保留两位小数')
    payload = copy.deepcopy(row['payload'])
    payload['campaign_name'] = name
    payload['budget'] = amount(changes.get('budget'))
    platform = row['platform']
    aid = str(payload.get('ad_account_id' if platform == 'meta' else 'advertiser_id') or '')
    account = biz_account_repository.get_by_platform_account(platform, aid)
    currency = (account or {}).get('currency')
    if not currency:
        raise HTTPException(422, '请先连接广告账户并同步币种')
    payload['budget_currency'] = currency
    if platform == 'meta':
        minor = int(Decimal(str(payload['budget']))*100)
        overrides = payload.setdefault('overrides', {})
        is_cbo = row['template_snapshot'].get('template_type') == 'web_to_app_conversion_cbo' or row['template_snapshot'].get('id') == 'tpl_meta_web_to_app_conv_cbo'
        overrides.setdefault('campaign' if is_cbo else 'adset', {})['daily_budget'] = minor
        if not is_cbo and payload.get('adsets'):
            budgets = changes.get('adset_budgets')
            if not isinstance(budgets, list) or len(budgets) != len(payload['adsets']):
                raise HTTPException(400, '请填写每个广告组的日预算')
            for adset, budget in zip(payload['adsets'], budgets):
                adset['daily_budget'] = int(Decimal(str(amount(budget)))*100)
            payload['budget'] = payload['adsets'][0]['daily_budget']/100
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE app_launch_drafts SET name=%s,payload=%s,revision=revision+1 WHERE id=%s AND tenant_id=%s AND application_id=%s AND created_by=%s AND status='DRAFT' AND revision=%s",
                    (name, json.dumps(payload, ensure_ascii=False), row['id'], application.tenant_id, application.id, user.username, revision))
        updated = cur.rowcount
        conn.commit()
    if not updated:
        raise HTTPException(409, '草稿已更新或开始执行，请刷新后重试')
    return load(row['id'], application, user)


class Run:
    def __init__(self, row):
        self.row = row
        self.points = row['checkpoints'] or {}
        self.counts = {}

    def persist(self):
        with get_app_conn() as conn:
            conn.cursor().execute('UPDATE app_launch_drafts SET checkpoints=%s WHERE id=%s',
                                  (json.dumps(self.points, ensure_ascii=False), self.row['id']))
            conn.commit()


async def checkpoint_call(platform, endpoint, payload, send):
    run = _active.get()
    if run is None:
        return await send()
    body = clean(payload or {})
    signature = hashlib.sha256(json.dumps([platform, endpoint, body], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    occurrence = run.counts.get(signature, 0)
    run.counts[signature] = occurrence + 1
    key = f'{signature}:{occurrence}'
    existing = run.points.get(key)
    if existing and existing['status'] == 'SUCCEEDED':
        return copy.deepcopy(existing['result'])
    if existing and existing['status'] in ('PENDING', 'UNKNOWN'):
        raise HTTPException(409, '平台写入结果尚未确认，请先在平台核对；系统不会重复创建此步骤')
    run.points[key] = {'status': 'PENDING', 'endpoint': endpoint}
    run.persist()  # Persist before writing, so a crash cannot silently permit a repeat.
    try:
        result = await send()
    except Exception as error:
        import httpx
        explicit = hasattr(error, 'code') or (isinstance(error, httpx.HTTPStatusError) and 400 <= error.response.status_code < 500 and error.response.status_code != 408)
        run.points[key] = {'status': 'FAILED' if explicit else 'UNKNOWN', 'endpoint': endpoint, 'error': str(error)}
        run.persist()
        raise
    run.points[key] = {'status': 'SUCCEEDED', 'endpoint': endpoint, 'result': clean(result)}
    run.persist()
    return result


def result_status(result, points):
    if any(p['status'] in ('PENDING', 'UNKNOWN') for p in points.values()):
        return 'UNKNOWN'
    if result.get('error'):
        return 'FAILED'
    def steps(value):
        if isinstance(value, dict):
            if 'success' in value:
                yield bool(value['success'])
            for child in value.values():
                yield from steps(child)
        elif isinstance(value, list):
            for child in value:
                yield from steps(child)
    states = list(steps(result.get('data')))
    if states and all(states):
        return 'SUCCEEDED'
    if any(states) or any(p['status'] == 'SUCCEEDED' for p in points.values()):
        return 'PARTIAL'
    return 'FAILED'


async def execute(row, revision, application, user):
    if row['status'] == 'SUCCEEDED':
        return row
    if row['status'] in ('RUNNING', 'UNKNOWN'):
        raise HTTPException(409, '已有创建正在执行或结果尚未确认，请在平台核对，勿重复创建')
    report = precheck(row['payload'], row['template_snapshot'], application, user)
    if not report['ok']:
        raise HTTPException(422, {'message': '创建条件未满足', 'checks': report['checks']})
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE app_launch_drafts SET status='RUNNING', revision=revision+1, last_error=NULL WHERE id=%s AND revision=%s AND status IN ('DRAFT','FAILED','PARTIAL')", (row['id'], revision))
        claimed = cur.rowcount
        conn.commit()
    if not claimed:
        raise HTTPException(409, '草稿已被执行或更新，请刷新后重试')
    run = Run(row)
    token = _active.set(run)
    try:
        from routes.templates import launch_from_template
        result = await launch_from_template(copy.deepcopy(row['payload']), user)
        status = result_status(result, run.points)
        error = result.get('error') or ('部分步骤未完成，可继续失败步骤' if status == 'PARTIAL' else '创建未完成，请查看步骤结果' if status != 'SUCCEEDED' else None)
    except BaseException as exc:
        result = {'error': str(exc)}
        status = 'UNKNOWN' if any(p['status'] in ('PENDING', 'UNKNOWN', 'SUCCEEDED') for p in run.points.values()) else 'FAILED'
        error = '创建被中断，请核对平台结果后处理' if status == 'UNKNOWN' else str(exc)
        if not isinstance(exc, Exception):
            # The checkpoints still block repeats after process cancellation.
            raise
    finally:
        _active.reset(token)
    with get_app_conn() as conn:
        conn.cursor().execute('UPDATE app_launch_drafts SET status=%s, result=%s, last_error=%s WHERE id=%s',
                              (status, json.dumps(clean(result), ensure_ascii=False), error, row['id']))
        conn.commit()
    return load(row['id'], application, user)


def active_template(template_id):
    run = _active.get()
    if run and run.row['template_snapshot'].get('id') == template_id:
        return copy.deepcopy(run.row['template_snapshot'])
    return None
