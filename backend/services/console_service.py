"""Read-only console queries, retaining the existing report source and account scope."""
import json
from decimal import Decimal
from db import get_biz_conn
from repositories import biz_daily_report_repository, biz_adgroup_daily_repository, biz_ad_daily_repository
from services import biz_blend_service, biz_attribution_service

LEVELS = {
    'campaign': ('biz_campaigns', 'campaign_id', 'campaign_name', biz_daily_report_repository),
    'adgroup': ('biz_adgroups', 'adgroup_id', 'adgroup_name', biz_adgroup_daily_repository),
    'ad': ('biz_ads', 'ad_id', 'ad_name', biz_ad_daily_repository),
}


def attach_metadata(rows, level, platform):
    if not rows:
        return rows
    table, id_key, _, _ = LEVELS[level]
    metadata = {}
    ids = list({str(row[id_key]) for row in rows})
    with get_biz_conn() as conn:
        cur = conn.cursor()
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            placeholders = ','.join(['%s'] * len(chunk))
            cur.execute(f'SELECT account_id, {id_key}, status, raw_json FROM {table} WHERE platform=%s AND {id_key} IN ({placeholders})', [platform, *chunk])
            for item in cur.fetchall():
                metadata[(str(item['account_id']), str(item[id_key]))] = item
    result = []
    for row in rows:
        item = metadata.get((str(row.get('account_id', '')), str(row[id_key])), {})
        raw = item.get('raw_json') or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (ValueError, TypeError):
                raw = {}
        if not isinstance(raw, dict):
            raw = {}
        budget = raw.get('budget', raw.get('daily_budget'))
        result.append({**row, 'status': item.get('status') or 'UNKNOWN',
                       'budget': float(budget) / (100 if platform == 'meta' else 1) if budget is not None else None})
    return result


def select_page(rows, level, q, page, page_size):
    _, id_key, name_key, _ = LEVELS[level]
    needle = q.strip().casefold()
    if needle:
        rows = [r for r in rows if needle in str(r.get(name_key) or '').casefold() or needle in str(r.get(id_key) or '').casefold()]
    total = len(rows)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    return {'list': rows[(page - 1) * page_size:page * page_size], 'total': total, 'page': page, 'page_size': page_size}


def query(level, start_date, end_date, *, platform, account_id, source, order_by, order_dir,
          campaign_id=None, adgroup_id=None, q='', page=1, page_size=50):
    module = {'blend': biz_blend_service, 'attribution': biz_attribution_service}.get(source, LEVELS[level][3])
    kwargs = dict(platform=platform, account_id=account_id, order_by=order_by, order_dir=order_dir)
    if level != 'campaign':
        kwargs['campaign_id'] = campaign_id
    if level == 'ad':
        kwargs['adgroup_id'] = adgroup_id
    rows = getattr(module, f'get_{level}_aggregated')(start_date, end_date, **kwargs)
    # Stable ordering for equal metric values prevents items moving between pages.
    id_key = LEVELS[level][1]
    rows.sort(key=lambda row: (str(row.get('account_id', '')), str(row[id_key])))
    rows.sort(key=lambda row: (row.get(order_by) is not None, row.get(order_by) or 0), reverse=order_dir == 'desc')
    result = select_page(rows, level, q, page, page_size)
    result['list'] = attach_metadata(result['list'], level, platform)
    for row in result['list']:
        for key, value in row.items():
            if isinstance(value, Decimal):
                row[key] = float(value)
    return result
