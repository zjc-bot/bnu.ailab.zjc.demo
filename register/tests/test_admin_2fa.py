"""管理后台二次认证与会话撤销回归测试。"""

import os
import sys
import time

import pytest
from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret-for-admin-2fa")

import admin as admin_module  # noqa: E402
from app import app as flask_app


@pytest.fixture(autouse=True)
def clean_state():
    admin_module._a2fa_challenges.clear()
    admin_module._a2fa_sends.clear()
    admin_module._admin_sessions.clear()
    admin_module._fails.clear()
    yield
    admin_module._a2fa_challenges.clear()
    admin_module._a2fa_sends.clear()
    admin_module._admin_sessions.clear()
    admin_module._fails.clear()


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def _admin_session(client, aid=1, name="测试管理员"):
    sid = "session-" + str(aid)
    admin_module._admin_sessions[sid] = {"aid": aid, "expires": time.time() + 3600}
    with client.session_transaction() as s:
        s["aid"] = aid
        s["aname"] = name
        s["a_sid"] = sid
        s["a2fa"] = True
        s["_acsrf"] = "tok"
    return "tok"


def _challenge(client, purpose="login", aid=7, name="测试管理员", target="admin@example.com"):
    token, code = admin_module._create_challenge(
        aid, purpose, target, name, "127.0.0.1",
    )
    with client.session_transaction() as s:
        s["a2fa_challenge"] = token
        s["_acsrf"] = "tok"
    return token, code


def _login_row():
    return {
        "id": 7,
        "username": "admin",
        "password_hash": generate_password_hash("correct-password"),
        "display_name": "测试管理员",
    }


def _fake_summary():
    return {
        "span": {"from": "2026-01-01", "to": "2026-01-02"},
        "pv": 0, "uv": 0, "pv_today": 0,
        "by_major": [], "by_dorm": [], "hours": [],
        "ai_today": 0, "ai_total": 0, "ai_people": 0, "byok": 0,
        "trend": [], "today": 0, "week": 0, "total": 0,
    }


def test_admin_required_blocks_stale_cookie(client):
    with client.session_transaction() as s:
        s["aid"] = 1
        s["a2fa"] = True
    resp = client.get("/admin/")
    assert resp.status_code == 302
    assert "/admin/login" in resp.headers["Location"]
    with client.session_transaction() as s:
        assert not s.get("aid")
        assert not s.get("a_sid")


def test_admin_required_allows_server_session(client, monkeypatch):
    monkeypatch.setattr(admin_module, "q_one", lambda *a, **k: {"email": "a@b.cn"})
    monkeypatch.setattr(admin_module, "summary", lambda *a, **k: _fake_summary())
    _admin_session(client)
    assert client.get("/admin/").status_code == 200


def test_server_session_can_be_revoked(client, monkeypatch):
    monkeypatch.setattr(admin_module, "q_one", lambda *a, **k: {"email": "a@b.cn"})
    monkeypatch.setattr(admin_module, "summary", lambda *a, **k: _fake_summary())
    _admin_session(client)
    admin_module._admin_sessions.clear()
    resp = client.get("/admin/")
    assert resp.status_code == 302
    with client.session_transaction() as s:
        assert not s.get("aid")


def test_login_does_not_put_code_in_cookie(client, monkeypatch):
    sent = {}

    def fake_q_one(sql, params=()):
        if "password_hash" in sql:
            return _login_row()
        return {"email": "admin@example.com"}

    monkeypatch.setattr(admin_module, "q_one", fake_q_one)
    monkeypatch.setattr(admin_module.mailer, "send_code", lambda to, code, **kw: sent.update(to=to, code=code))
    page = client.get("/admin/login")
    csrf = _csrf_from_page(page)
    resp = client.post("/admin/login", data={"csrf": csrf, "username": "admin", "password": "correct-password"})
    assert resp.status_code == 302
    assert "/admin/verify" in resp.headers["Location"]
    assert sent["to"] == "admin@example.com"
    with client.session_transaction() as s:
        assert s.get("a2fa_challenge")
        assert "a2fa_code" not in s
        assert "a2fa_pending" not in s
        assert "a2fa_exp" not in s
        assert not s.get("aid")


def test_login_fails_closed_without_email(client, monkeypatch):
    def fake_q_one(sql, params=()):
        return _login_row() if "password_hash" in sql else {"email": ""}

    monkeypatch.setattr(admin_module, "q_one", fake_q_one)
    csrf = _csrf_from_page(client.get("/admin/login"))
    resp = client.post("/admin/login", data={"csrf": csrf, "username": "admin", "password": "correct-password"})
    assert resp.status_code == 200
    assert "尚未配置二次认证邮箱" in resp.get_data(as_text=True)
    with client.session_transaction() as s:
        assert not s.get("aid")
        assert not s.get("a2fa_challenge")


def test_login_fails_closed_on_email_query_error(client, monkeypatch):
    def fake_q_one(sql, params=()):
        if "password_hash" in sql:
            return _login_row()
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(admin_module, "q_one", fake_q_one)
    csrf = _csrf_from_page(client.get("/admin/login"))
    resp = client.post("/admin/login", data={"csrf": csrf, "username": "admin", "password": "correct-password"})
    assert resp.status_code == 200
    assert "二次认证暂不可用" in resp.get_data(as_text=True)
    with client.session_transaction() as s:
        assert not s.get("aid")


def test_login_fails_closed_on_mail_error(client, monkeypatch):
    def fake_q_one(sql, params=()):
        return _login_row() if "password_hash" in sql else {"email": "admin@example.com"}

    def fail_mail(*a, **k):
        raise RuntimeError("smtp unavailable")

    monkeypatch.setattr(admin_module, "q_one", fake_q_one)
    monkeypatch.setattr(admin_module.mailer, "send_code", fail_mail)
    csrf = _csrf_from_page(client.get("/admin/login"))
    resp = client.post("/admin/login", data={"csrf": csrf, "username": "admin", "password": "correct-password"})
    assert resp.status_code == 200
    assert "邮件发送失败" in resp.get_data(as_text=True)
    with client.session_transaction() as s:
        assert not s.get("aid")
        assert not s.get("a2fa_challenge")


def test_verify_rejects_wrong_code(client):
    _, code = _challenge(client)
    wrong = "000000" if code != "000000" else "111111"
    resp = client.post("/admin/verify", data={"csrf": "tok", "code": wrong})
    assert resp.status_code == 200
    assert "验证码不正确" in resp.get_data(as_text=True)
    with client.session_transaction() as s:
        assert not s.get("aid")


def test_verify_locks_after_five_wrong_codes(client):
    token, code = _challenge(client)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(admin_module.TOTP_ATTEMPT_LIMIT):
        resp = client.post("/admin/verify", data={"csrf": "tok", "code": wrong})
    assert "错误次数过多" in resp.get_data(as_text=True)
    assert token not in admin_module._a2fa_challenges
    with client.session_transaction() as s:
        assert not s.get("a2fa_challenge")


def test_verify_rejects_expired_code(client):
    token, code = _challenge(client)
    admin_module._a2fa_challenges[token]["expires"] = time.time() - 1
    resp = client.post("/admin/verify", data={"csrf": "tok", "code": code})
    assert resp.status_code == 200
    assert "已过期" in resp.get_data(as_text=True)
    assert token not in admin_module._a2fa_challenges


def test_verify_accepts_correct_code_once(client, monkeypatch):
    monkeypatch.setattr(admin_module, "db", _FakeDB())
    token, code = _challenge(client)
    resp = client.post("/admin/verify", data={"csrf": "tok", "code": code})
    assert resp.status_code == 302
    assert "/admin/" in resp.headers["Location"]
    assert token not in admin_module._a2fa_challenges
    with client.session_transaction() as s:
        assert s.get("aid") == 7
        assert s.get("a2fa") is True
        assert s.get("a_sid") in admin_module._admin_sessions
        assert "a2fa_code" not in s


def test_verify_requires_csrf(client):
    _challenge(client)
    resp = client.post("/admin/verify", data={"csrf": "wrong", "code": "123456"})
    assert resp.status_code == 400


def test_email_change_requires_new_email_confirmation(client, monkeypatch):
    sent = {}
    fake_db = _FakeDB()
    password_hash = generate_password_hash("correct-password")

    monkeypatch.setattr(admin_module, "q_one", lambda *a, **k: {"password_hash": password_hash})
    monkeypatch.setattr(admin_module.mailer, "send_code", lambda to, code, **kw: sent.update(to=to, code=code))
    monkeypatch.setattr(admin_module, "db", fake_db)
    _admin_session(client, aid=7)
    resp = client.post("/admin/account/email", data={
        "csrf": "tok", "password": "correct-password", "email": "new@example.com",
    })
    assert resp.status_code == 302
    assert "/admin/verify" in resp.headers["Location"]
    assert sent["to"] == "new@example.com"
    assert not any("SET email" in sql for sql, _ in fake_db.queries)

    with client.session_transaction() as s:
        token = s["a2fa_challenge"]
        csrf = s["_acsrf"]
    assert admin_module._a2fa_challenges[token]["purpose"] == "email"
    resp = client.post("/admin/verify", data={"csrf": csrf, "code": sent["code"]})
    assert resp.status_code == 302
    assert "/admin/account" in resp.headers["Location"]
    assert any("SET email=%s" in sql and params == ("new@example.com", 7)
               for sql, params in fake_db.queries)


def test_password_change_revokes_sessions_and_pending_challenges(client, monkeypatch):
    fake_db = _FakeDB()
    fake_db.row = {"password_hash": generate_password_hash("correct-password")}
    monkeypatch.setattr(admin_module, "q_one", lambda *a, **k: fake_db.row)
    monkeypatch.setattr(admin_module, "db", fake_db)
    _admin_session(client, aid=7)
    own_token, _ = _challenge(client, aid=7)
    other_token, _ = _challenge(client, aid=8)

    resp = client.post("/admin/account/password", data={
        "csrf": "tok", "old": "correct-password",
        "new": "new-password-123", "new2": "new-password-123",
    })
    assert resp.status_code == 302
    assert "/admin/login" in resp.headers["Location"]
    assert own_token not in admin_module._a2fa_challenges
    assert other_token in admin_module._a2fa_challenges
    assert not any(rec["aid"] == 7 for rec in admin_module._admin_sessions.values())


def test_stale_session_no_redirect_loop(client):
    with client.session_transaction() as s:
        s["aid"] = 1
        s["aname"] = "旧管理员"
        s["a2fa"] = True
        s["_acsrf"] = "tok"

    visited = []
    r = client.get("/admin/login", follow_redirects=False)
    for _ in range(8):
        loc = r.headers.get("Location", "")
        visited.append((r.status_code, loc))
        if r.status_code not in (301, 302) or not loc:
            break
        r = client.get(loc, follow_redirects=False)
    assert len(visited) < 8, f"疑似重定向循环: {visited}"
    assert r.status_code == 200
    with client.session_transaction() as s:
        assert not s.get("aid")
        assert not s.get("a2fa")


def test_completed_session_goes_straight_to_dash(client):
    _admin_session(client)
    r = client.get("/admin/login", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/admin/")


def test_verify_page_for_completed_session_no_loop(client):
    _admin_session(client)
    r = client.get("/admin/verify", follow_redirects=False)
    assert r.status_code == 302
    assert "login" not in r.headers["Location"]


def _csrf_from_page(resp):
    text = resp.get_data(as_text=True)
    marker = 'name="csrf" value="'
    start = text.index(marker) + len(marker)
    return text[start:text.index('"', start)]


class _FakeDB:
    def __init__(self):
        self.queries = []
        self.row = None

    class _Ctx:
        def __init__(self, owner):
            self.owner = owner

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return self

        def execute(self, sql, params=()):
            self.owner.queries.append((sql, params))

        def commit(self):
            pass

        def fetchone(self):
            return self.owner.row

    def connect(self):
        return self._Ctx(self)
