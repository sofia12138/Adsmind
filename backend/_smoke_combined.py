"""阶段 7 #1+#2+#3+#4 联合冒烟"""
from __future__ import annotations
import json
import sys
import time
import urllib.error
import urllib.request
import urllib.parse

BASE = "http://127.0.0.1:5000"


def _req(method, path, *, headers=None, body=None, expect_ok=True, raw=False):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = resp.read().decode("utf-8", errors="replace")
            if raw:
                return resp.status, payload
            return resp.status, json.loads(payload) if payload else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        if expect_ok:
            print(f"HTTP {e.code} {method} {path}: {body_text[:300]}")
            raise
        try:
            return e.code, json.loads(body_text)
        except Exception:
            return e.code, {"raw": body_text}


def main():
    suffix = int(time.time())
    owner_email = f"combo-{suffix}@example.com"

    print("=" * 72)
    print("  阶段 7 联合冒烟：#3 邮箱验证 + #4 成员 + #2 升级 + #1 OAuth(mock)")
    print("=" * 72)

    # ───────── #3 邮箱验证 ─────────
    print("\n#3 [3.1] 注册 → 返回 verification_url")
    _, r = _req("POST", "/api/auth/register",
                body={"email": owner_email, "password": "ComboPass1",
                      "company_name": f"联合冒烟 {suffix}"})
    token = r["token"]
    tenant_id = r["tenant"]["id"]
    app_id = r["application"]["id"]
    user_id = r["user"]["id"]
    verify_url = r["email_verification"]["verification_url"]
    print(f"    tenant.id={tenant_id} user.id={user_id}")
    print(f"    verify_url={verify_url}")
    assert verify_url

    # 升级 plan 到 pro，方便后续 members/applications 测试
    from db import get_app_conn  # type: ignore
    with get_app_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE app_tenants SET plan_id='pro' WHERE id=%s", (tenant_id,))
        conn.commit()
    print(f"    [setup] tenant {tenant_id} 升级到 pro 套餐")
    auth = {"Authorization": f"Bearer {token}"}

    # 访问验证链接
    print("\n#3 [3.2] 访问验证链接 → 应标记成功")
    verify_token = verify_url.rsplit("/", 1)[-1]
    _, vr = _req("GET", f"/api/auth/verify-email/{verify_token}")
    print(f"    {vr}")
    assert vr["ok"]

    print("\n#3 [3.3] 重复访问 → already_verified")
    _, vr = _req("GET", f"/api/auth/verify-email/{verify_token}")
    assert vr["ok"]
    assert vr.get("already_verified") is True

    print("\n#3 [3.4] 无效 token → 404")
    code, _ = _req("GET", "/api/auth/verify-email/INVALID_TOKEN", expect_ok=False)
    assert code == 404

    print("\n#3 [3.5] resend-verification（未验证邮箱才会生成）")
    _, rs = _req("POST", "/api/auth/resend-verification",
                 body={"email": owner_email})
    print(f"    already_verified={rs.get('already_verified')}")
    assert rs.get("already_verified") is True

    # ───────── #4 成员管理 ─────────
    print("\n#4 [4.1] 给租户拉一个 member 进来（先发邀请 + 接受）")
    member_email = f"combo-m1-{suffix}@example.com"
    _, inv = _req("POST", "/api/tenant/invitations",
                  headers=auth,
                  body={"email": member_email, "role": "member"})
    _, accept = _req("POST", f"/api/auth/invitation/{inv['token']}/accept",
                     body={"password": "MemberPass1"})
    member_user_id = accept["user"]["id"]
    print(f"    member.user_id={member_user_id} role={accept['tenant']['tenant_role']}")

    print("\n#4 [4.2] GET /api/tenant/members → 应有 2 人")
    _, mlist = _req("GET", "/api/tenant/members", headers=auth)
    print(f"    -> {len(mlist)} 人：{[(m['user_id'], m['role']) for m in mlist]}")
    assert len(mlist) == 2

    print("\n#4 [4.3] 提升 member → admin")
    _, mr = _req("PUT", f"/api/tenant/members/{member_user_id}",
                 headers=auth, body={"role": "admin"})
    print(f"    -> role={mr.get('role')}")
    assert mr.get("role") == "admin"

    print("\n#4 [4.4] owner 不能把自己降为 member")
    me_id = user_id
    code, r = _req("PUT", f"/api/tenant/members/{me_id}",
                   headers=auth, body={"role": "member"}, expect_ok=False)
    print(f"    -> HTTP {code} detail={r.get('detail')}")
    assert code == 422

    print("\n#4 [4.5] owner 不能把自己降为 admin（最后一个 owner）")
    code, r = _req("PUT", f"/api/tenant/members/{me_id}",
                   headers=auth, body={"role": "admin"}, expect_ok=False)
    print(f"    -> HTTP {code} detail={r.get('detail')[:60]}")
    assert code == 422

    print("\n#4 [4.6] 移除 member")
    _, dr = _req("DELETE", f"/api/tenant/members/{member_user_id}", headers=auth)
    print(f"    ok={dr.get('ok')}")
    _, mlist = _req("GET", "/api/tenant/members", headers=auth)
    assert len(mlist) == 1

    # ───────── #2 付费升级 ─────────
    print("\n#2 [2.1] 申请升级到 business")
    _, ur = _req("POST", "/api/billing/upgrade-request",
                 headers=auth,
                 body={"to_plan_id": "business",
                       "contact_email": owner_email,
                       "message": "需要更多账号配额"})
    req_id = ur["id"]
    print(f"    request.id={req_id} status={ur['status']} to={ur['to_plan_id']}")
    assert ur["status"] == "pending"

    print("\n#2 [2.2] 重复申请被拒")
    code, r = _req("POST", "/api/billing/upgrade-request",
                   headers=auth,
                   body={"to_plan_id": "starter", "contact_email": owner_email},
                   expect_ok=False)
    print(f"    -> HTTP {code} detail.code={r.get('detail', {}).get('code')}")
    assert code == 422
    assert r["detail"]["code"] == "UPGRADE_REQUEST_PENDING"

    print("\n#2 [2.3] 普通用户访问 /admin/upgrade-requests → 403")
    code, _ = _req("GET", "/api/billing/admin/upgrade-requests",
                   headers=auth, expect_ok=False)
    print(f"    -> HTTP {code}")
    assert code == 403

    print("\n#2 [2.4] 平台 admin 登录 + approve")
    _, sa = _req("POST", "/api/users/login",
                body={"username": "admin", "password": "admin123"})
    sa_auth = {"Authorization": f"Bearer {sa['token']}"}
    print(f"    admin role={sa['user']['role']}")

    _, lst = _req("GET", "/api/billing/admin/upgrade-requests", headers=sa_auth)
    print(f"    super_admin 看到 {len(lst)} 条申请")
    assert len(lst) >= 1

    _, approved = _req("POST", f"/api/billing/admin/upgrade-requests/{req_id}/approve",
                       headers=sa_auth,
                       body={"admin_note": "MVP test approve"})
    print(f"    approved status={approved['status']} to_plan={approved['to_plan_id']}")
    assert approved["status"] == "approved"

    # 验证 tenant.plan_id 确实切换了
    print("\n#2 [2.5] 验证 tenant.plan_id 已切到 business")
    _, q = _req("GET", "/api/quota/me", headers=auth)
    print(f"    -> plan={q['plan_id']} limits.applications={q['limits']['applications']}")
    assert q["plan_id"] == "business"

    # ───────── #1 OAuth Mock ─────────
    print("\n#1 [1.1] 启动 OAuth (tiktok)，force_mock=1（本地冒烟）")
    _, ostart = _req("GET",
                     f"/api/integrations/tiktok/oauth/start"
                     f"?application_id={app_id}&force_mock=1",
                     headers=auth)
    print(f"    mock_mode={ostart.get('mock_mode')}")
    print(f"    authorize_url={ostart['authorize_url'][:80]}...")
    assert ostart.get("mock_mode") is True
    mock_url = ostart["authorize_url"]
    if "force_mock=1" not in mock_url:
        mock_url += ("&" if "?" in mock_url else "?") + "force_mock=1"

    print("\n#1 [1.2] 访问 mock-callback")
    parsed = urllib.parse.urlparse(mock_url)
    path = parsed.path + ("?" + parsed.query if parsed.query else "")
    code, html = _req("GET", path, raw=True)
    print(f"    HTTP {code} html.len={len(html)}")
    assert "演示模式授权完成" in html

    print("\n#1 [1.3] 凭证 + 账号应已落到当前应用")
    _, creds = _req("GET", "/api/integrations/credentials?platform=tiktok",
                    headers=auth)
    print(f"    credentials.count={len(creds.get('items', []))}")
    assert len(creds["items"]) >= 2

    headers_app = {**auth, "X-Application-Id": str(app_id)}
    _, accts = _req("GET", "/api/ad-accounts/", headers=headers_app)
    print(f"    accounts.count={len(accts['data'])}（绑定到 app {app_id}）")
    # 全是 mock_tiktok_*
    mock_accts = [a for a in accts["data"] if a.get("platform") == "tiktok"]
    assert len(mock_accts) >= 2

    print("\n#1 [1.4] 再启 meta（也走 mock）")
    _, ostart2 = _req("GET",
                      f"/api/integrations/meta/oauth/start"
                      f"?application_id={app_id}&force_mock=1",
                      headers=auth)
    assert ostart2.get("mock_mode") is True
    mock_url2 = ostart2["authorize_url"]
    if "force_mock=1" not in mock_url2:
        mock_url2 += ("&" if "?" in mock_url2 else "?") + "force_mock=1"
    parsed2 = urllib.parse.urlparse(mock_url2)
    _req("GET", parsed2.path + ("?" + parsed2.query if parsed2.query else ""), raw=True)
    _, accts2 = _req("GET", "/api/ad-accounts/", headers=headers_app)
    print(f"    accounts.count={len(accts2['data'])}（tiktok + meta mock）")
    assert len(accts2["data"]) >= 4

    print("\n" + "=" * 72)
    print(f"  联合冒烟全 PASS：tenant_id={tenant_id} owner={owner_email}")
    print("=" * 72)


if __name__ == "__main__":
    sys.exit(main() or 0)
