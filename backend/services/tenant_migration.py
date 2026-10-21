"""Additive tenant ownership migration; existing records belong to internal tenant."""
from db import get_app_conn, get_biz_conn
from core.isolation import OWNED_TABLES


def run():
    from config import get_settings
    from services.platform_authorization import ensure_table
    ensure_table()
    for table in sorted(OWNED_TABLES):
        is_biz = table in ('biz_ad_accounts', 'tiktok_material_uploads')
        if is_biz and not get_settings().biz_mysql_database:
            continue
        factory = get_biz_conn if is_biz else get_app_conn
        with factory() as conn:
            cur = conn.cursor()
            cur.execute('SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s', (table,))
            columns = {r['COLUMN_NAME']: r['DATA_TYPE'] for r in cur.fetchall()}
            if not columns:
                raise RuntimeError(f'Missing tenant-owned table: {table}')
            if 'tenant_id' not in columns:
                cur.execute(f'ALTER TABLE {table} ADD COLUMN tenant_id BIGINT NOT NULL DEFAULT 1, ADD INDEX idx_tenant_owner (tenant_id)')
            if table == 'biz_ad_accounts' and 'application_id' not in columns:
                cur.execute('ALTER TABLE biz_ad_accounts ADD COLUMN application_id BIGINT NULL, ADD INDEX idx_application_owner (application_id)')
            if table == 'biz_ad_accounts' and columns.get('app_secret') != 'text':
                cur.execute('ALTER TABLE biz_ad_accounts MODIFY COLUMN app_secret TEXT NOT NULL')
            conn.commit()
