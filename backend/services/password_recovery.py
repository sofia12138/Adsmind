"""One-time recovery links issued by a trusted local administrator."""
import hashlib
import secrets

from db import get_app_conn


def issue(user_id: int, email: str) -> str:
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE app_email_verifications SET expires_at=NOW() WHERE user_id=%s AND purpose='password_reset' AND verified_at IS NULL", (user_id,))
        cur.execute("INSERT INTO app_email_verifications (user_id,email,token,purpose,expires_at) VALUES (%s,%s,%s,'password_reset',NOW()+INTERVAL 30 MINUTE)", (user_id, email, digest))
        conn.commit()
    return token


def consume(token: str, password_hash: str) -> bool:
    digest = hashlib.sha256(token.encode()).hexdigest()
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id,user_id FROM app_email_verifications WHERE token=%s AND purpose='password_reset' AND verified_at IS NULL AND expires_at>NOW() FOR UPDATE", (digest,))
        record = cur.fetchone()
        if not record:
            return False
        cur.execute("UPDATE app_users SET password_hash=%s WHERE id=%s", (password_hash, record['user_id']))
        cur.execute("UPDATE app_email_verifications SET verified_at=NOW() WHERE id=%s", (record['id'],))
        conn.commit()
    return True
