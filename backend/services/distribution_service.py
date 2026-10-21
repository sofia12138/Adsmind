"""YouTube distribution preparation. No platform uploads or scheduled jobs yet."""
import json
import uuid
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from db import get_app_conn


class ChannelInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    channel_id: str = Field(pattern=r'^UC[A-Za-z0-9_-]{22}$')
    language: str = Field(min_length=1, max_length=40)
    timezone: str = Field(default='Asia/Shanghai', max_length=80)

    @field_validator('name', 'language')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('不能为空')
        return value.strip()

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('时区无效')
        return value


class DraftInput(BaseModel):
    drama_name: str = Field(min_length=1, max_length=200)
    version: str = Field(default='', max_length=100)
    language: str = Field(default='', max_length=40)
    material_id: str = Field(default='', max_length=200)
    file_name: str = Field(default='', max_length=255)
    channel_id: str = Field(default='', max_length=36)
    title: str = Field(default='', max_length=100)
    description: str = Field(default='', max_length=5000)
    thumbnail_url: str = Field(default='', max_length=2000)
    subtitle_note: str = Field(default='', max_length=500)
    audience: Literal['unset', 'kids', 'general'] = 'unset'
    publish_mode: Literal['immediate', 'scheduled'] = 'immediate'
    scheduled_at: datetime | None = None
    full_drama_confirmed: bool = False
    rights_confirmed: bool = False

    @field_validator('drama_name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('请填写剧名')
        return value.strip()

    @field_validator('thumbnail_url')
    @classmethod
    def valid_url(cls, value):
        from urllib.parse import urlsplit
        if value:
            url = urlsplit(value)
            if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password:
                raise ValueError('封面地址必须是有效的 HTTP/HTTPS 地址')
        return value

    @model_validator(mode='after')
    def schedule(self):
        if self.publish_mode == 'scheduled':
            if not self.scheduled_at or self.scheduled_at.tzinfo is None:
                raise ValueError('定时计划需提供带时区的时间')
            if self.scheduled_at <= datetime.now(timezone.utc):
                raise ValueError('计划时间需晚于当前时间')
        else:
            self.scheduled_at = None
        return self


class DraftUpdate(DraftInput):
    revision: int = Field(ge=1)


def init_tables():
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS app_distribution_channels (
            id CHAR(36) PRIMARY KEY, tenant_id BIGINT NOT NULL, application_id BIGINT NOT NULL,
            name VARCHAR(120) NOT NULL, channel_id VARCHAR(24) NOT NULL,
            language VARCHAR(40) NOT NULL, timezone VARCHAR(80) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_distribution_channel (tenant_id, application_id, channel_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        cur.execute('''CREATE TABLE IF NOT EXISTS app_distribution_drafts (
            id CHAR(36) PRIMARY KEY, tenant_id BIGINT NOT NULL, application_id BIGINT NOT NULL,
            created_by VARCHAR(255) NOT NULL, revision INT NOT NULL DEFAULT 1,
            payload JSON NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            KEY idx_distribution_scope (tenant_id, application_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        conn.commit()


def public(row):
    row = {k: v for k, v in dict(row).items() if k not in ('tenant_id', 'application_id')}
    if isinstance(row.get('payload'), str):
        row['payload'] = json.loads(row['payload'])
    for key in ('created_at', 'updated_at'):
        if row.get(key):
            row[key] = str(row[key])
    if 'payload' in row:
        row['status'] = 'DRAFT'
    else:
        row['authorization_status'] = 'NOT_CONNECTED'
    return row


def channels(app):
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute('SELECT * FROM app_distribution_channels WHERE tenant_id=%s AND application_id=%s ORDER BY created_at DESC', (app.tenant_id, app.id))
        return [public(r) for r in cur.fetchall()]


def create_channel(body, app):
    row_id = str(uuid.uuid4())
    from pymysql.err import IntegrityError
    with get_app_conn() as conn:
        try:
            conn.cursor().execute('INSERT INTO app_distribution_channels (id,tenant_id,application_id,name,channel_id,language,timezone) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                                  (row_id, app.tenant_id, app.id, body.name, body.channel_id, body.language, body.timezone))
            conn.commit()
        except IntegrityError:
            raise HTTPException(409, '该频道已登记')
    return next(c for c in channels(app) if c['id'] == row_id)


def list_drafts(app, page):
    with get_app_conn() as conn:
        cur = conn.cursor()
        args = (app.tenant_id, app.id)
        cur.execute('SELECT COUNT(*) AS total FROM app_distribution_drafts WHERE tenant_id=%s AND application_id=%s', args)
        total = cur.fetchone()['total']
        cur.execute('SELECT * FROM app_distribution_drafts WHERE tenant_id=%s AND application_id=%s ORDER BY created_at DESC, id LIMIT 20 OFFSET %s', (*args, (page-1)*20))
        return {'list': [public(r) for r in cur.fetchall()], 'total': total}


def load(row_id, app):
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute('SELECT * FROM app_distribution_drafts WHERE id=%s AND tenant_id=%s AND application_id=%s', (row_id, app.tenant_id, app.id))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, '发行任务不存在或无权访问')
    return public(row)


def save(body, app, user, row_id=None):
    if body.channel_id and not any(c['id'] == body.channel_id for c in channels(app)):
        raise HTTPException(400, '频道不属于当前应用')
    payload = body.model_dump(mode='json', exclude={'revision'})
    encoded = json.dumps(payload, ensure_ascii=False)
    with get_app_conn() as conn:
        cur = conn.cursor()
        if row_id:
            cur.execute('UPDATE app_distribution_drafts SET payload=%s, revision=revision+1 WHERE id=%s AND tenant_id=%s AND application_id=%s AND revision=%s',
                        (encoded, row_id, app.tenant_id, app.id, body.revision))
            if cur.rowcount != 1:
                raise HTTPException(409, '任务已变更或不存在，请刷新后重试')
        else:
            row_id = str(uuid.uuid4())
            cur.execute('INSERT INTO app_distribution_drafts (id,tenant_id,application_id,created_by,payload) VALUES (%s,%s,%s,%s,%s)',
                        (row_id, app.tenant_id, app.id, user.username, encoded))
        conn.commit()
    return load(row_id, app)


def precheck(row, app):
    p = row['payload']
    channel = next((c for c in channels(app) if c['id'] == p['channel_id']), None)
    checks = [
        ('成片引用已填写', bool(p['material_id'] or p['file_name'])),
        ('已确认是完整剧集成片', p['full_drama_confirmed']),
        ('已选择发行频道', bool(channel)),
        ('已填写成片语言', bool(p['language'].strip())),
        ('已填写发布标题', bool(p['title'].strip())),
        ('已填写简介', bool(p['description'].strip())),
        ('已设置受众', p['audience'] != 'unset'),
        ('已确认发行授权', p['rights_confirmed']),
        ('计划时间有效', p['publish_mode'] == 'immediate' or bool(p['scheduled_at'] and datetime.fromisoformat(p['scheduled_at']) > datetime.now(timezone.utc))),
        ('频道已完成 YouTube 授权', False),
        ('真实上传能力已接入', False),
    ]
    return {'ok': False, 'checks': [{'label': label, 'ok': bool(ok)} for label, ok in checks],
            'notice': '当前仅保存发行准备资料，不上传视频、不自动定时公开。成片引用尚未验证文件可用性。'}
