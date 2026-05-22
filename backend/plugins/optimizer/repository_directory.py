"""优化师名单数据访问层 — optimizer_directory CRUD + 未识别样本查询"""
from __future__ import annotations

from typing import Optional

from db import get_biz_conn


# ---------------------------------------------------------------------------
# 名单查询
# ---------------------------------------------------------------------------

def get_all(*, keyword: Optional[str] = None, is_active: Optional[int] = None) -> list[dict]:
    clauses = ["1=1"]
    params: list = []
    if keyword:
        clauses.append("(optimizer_name LIKE %s OR optimizer_code LIKE %s OR aliases LIKE %s)")
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw])
    if is_active is not None:
        clauses.append("is_active = %s")
        params.append(is_active)

    where = " AND ".join(clauses)
    sql = f"""
        SELECT id, optimizer_name, optimizer_code, aliases, is_active,
               remark, created_at, updated_at
        FROM optimizer_directory
        WHERE {where}
        ORDER BY is_active DESC, optimizer_name ASC
    """
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()


def get_by_id(oid: int) -> Optional[dict]:
    sql = "SELECT * FROM optimizer_directory WHERE id = %s"
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (oid,))
        return cur.fetchone()


def get_active_directory() -> list[dict]:
    """获取所有启用的优化师名单（用于匹配引擎）"""
    sql = """
        SELECT id, optimizer_name, optimizer_code, aliases
        FROM optimizer_directory
        WHERE is_active = 1
    """
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# 创建 / 更新 / 删除
# ---------------------------------------------------------------------------

def create(data: dict) -> int:
    sql = """
        INSERT INTO optimizer_directory
          (optimizer_name, optimizer_code, aliases, is_active, remark)
        VALUES (%s, %s, %s, %s, %s)
    """
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (
            data["optimizer_name"],
            data["optimizer_code"],
            data.get("aliases", ""),
            data.get("is_active", 1),
            data.get("remark", ""),
        ))
        conn.commit()
        return cur.lastrowid


def update(oid: int, data: dict) -> int:
    fields = []
    params = []
    for key in ("optimizer_name", "optimizer_code", "aliases", "is_active", "remark"):
        if key in data:
            fields.append(f"{key} = %s")
            params.append(data[key])
    if not fields:
        return 0
    params.append(oid)
    sql = f"UPDATE optimizer_directory SET {', '.join(fields)} WHERE id = %s"
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.rowcount


def toggle_status(oid: int, is_active: int) -> int:
    sql = "UPDATE optimizer_directory SET is_active = %s WHERE id = %s"
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (is_active, oid))
        conn.commit()
        return cur.rowcount


def delete(oid: int) -> int:
    sql = "DELETE FROM optimizer_directory WHERE id = %s"
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (oid,))
        conn.commit()
        return cur.rowcount


def code_exists(code: str, exclude_id: Optional[int] = None) -> bool:
    if exclude_id:
        sql = "SELECT COUNT(*) AS cnt FROM optimizer_directory WHERE optimizer_code = %s AND id != %s"
        params = (code, exclude_id)
    else:
        sql = "SELECT COUNT(*) AS cnt FROM optimizer_directory WHERE optimizer_code = %s"
        params = (code,)
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        return (row["cnt"] if row else 0) > 0


# ---------------------------------------------------------------------------
# 未识别样本查询
# ---------------------------------------------------------------------------

def get_unassigned_samples(limit: int = 200) -> list[dict]:
    """查询 campaign_optimizer_mapping 中未识别的原始值样本"""
    sql = """
        SELECT
            m.optimizer_name_raw,
            COUNT(*)                          AS occurrence_count,
            SUM(COALESCE(f.spend, 0))         AS total_spend,
            MAX(m.updated_at)                 AS last_seen_at
        FROM campaign_optimizer_mapping m
        LEFT JOIN (
            SELECT campaign_id, platform, account_id, SUM(spend) AS spend
            FROM biz_campaign_daily_normalized
            WHERE stat_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY campaign_id, platform, account_id
        ) f ON f.campaign_id = m.campaign_id
           AND f.platform    = m.platform
           AND f.account_id  = m.account_id
        WHERE m.optimizer_name_normalized = '未识别'
        GROUP BY m.optimizer_name_raw
        ORDER BY total_spend DESC
        LIMIT %s
    """
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (limit,))
        return cur.fetchall()


def assign_sample(optimizer_name_raw: str, optimizer_id: int) -> int:
    """将未识别样本匹配到指定优化师，更新所有对应映射记录"""
    opt = get_by_id(optimizer_id)
    if not opt:
        return 0
    normalized = opt["optimizer_name"]
    sql = """
        UPDATE campaign_optimizer_mapping
        SET optimizer_name_normalized = %s,
            optimizer_match_source    = 'manual_assign',
            optimizer_match_confidence = 1.00,
            parse_status              = 'ok'
        WHERE optimizer_name_raw = %s
          AND optimizer_name_normalized = '未识别'
    """
    with get_biz_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (normalized, optimizer_name_raw))
        conn.commit()
        return cur.rowcount
