"""任务 #49：验证码服务端限流、隐私返回与 IM 轮询日志回归。"""

import os
import sys
import threading
from contextlib import contextmanager

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret-for-hardening")

import app as app_module  # noqa: E402
import db as root_db  # noqa: E402
import mailer  # noqa: E402

app = app_module.app
app.config["TESTING"] = True
REAL_LOG_ACCESS = app_module._log_access


@pytest.fixture(autouse=True)
def isolate_state(monkeypatch):
    monkeypatch.setattr(app_module, "_log_access", lambda status: None)
    app_module._captcha_store.clear()
    app_module._captcha_expiry.clear()
    app_module._captcha_ip_issues.clear()
    app_module._captcha_ip_expiry.clear()
    app_module._captcha_global_issues.clear()
    app_module._rate.clear()
    yield
    app_module._captcha_store.clear()
    app_module._captcha_expiry.clear()
    app_module._captcha_ip_issues.clear()
    app_module._captcha_ip_expiry.clear()
    app_module._captcha_global_issues.clear()
    app_module._rate.clear()


def login(client, uid=1):
    with client.session_transaction() as sess:
        sess["uid"] = uid
        sess["_csrf"] = "csrf-token"


def pending(client, challenge=41):
    with client.session_transaction() as sess:
        sess["_csrf"] = "csrf-token"
        sess["pending"] = {
            "student_no": "20261101", "real_name": "测试同学", "nickname": "小鲸",
            "email": "student@mail.bnu.edu.cn", "pw_hash": "hash",
            "challenge": challenge, "ts": int(app_module.time.time()),
        }


def test_captcha_ip_and_global_limits(monkeypatch):
    monkeypatch.setattr(app_module, "CAPTCHA_IP_LIMIT", 2)
    monkeypatch.setattr(app_module, "CAPTCHA_GLOBAL_LIMIT", 3)
    monkeypatch.setattr(app_module, "CAPTCHA_MAX_ACTIVE", 10)
    monkeypatch.setattr(app_module.captcha, "generate", lambda: (b"png", "ABCD"))

    first = app.test_client()
    for _ in range(2):
        assert first.get("/captcha.png", environ_overrides={"REMOTE_ADDR": "203.0.113.1"}).status_code == 200
    assert first.get("/captcha.png", environ_overrides={"REMOTE_ADDR": "203.0.113.1"}).status_code == 429

    second = app.test_client()
    assert second.get("/captcha.png", environ_overrides={"REMOTE_ADDR": "203.0.113.2"}).status_code == 200
    limited = second.get("/captcha.png", environ_overrides={"REMOTE_ADDR": "203.0.113.3"})
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"


def test_captcha_ip_limit_canonicalizes_ipv6(monkeypatch):
    monkeypatch.setattr(app_module, "CAPTCHA_IP_LIMIT", 1)
    monkeypatch.setattr(app_module, "CAPTCHA_GLOBAL_LIMIT", 100)
    monkeypatch.setattr(app_module.captcha, "generate", lambda: (b"png", "ABCD"))
    client = app.test_client()
    assert client.get("/captcha.png", environ_overrides={"REMOTE_ADDR": "2001:db8::1"}).status_code == 200
    assert client.get("/captcha.png", environ_overrides={"REMOTE_ADDR": "2001:0db8:0:0:0:0:0:1"}).status_code == 429


def test_captcha_global_capacity_counts_unconsumed(monkeypatch):
    monkeypatch.setattr(app_module, "CAPTCHA_IP_LIMIT", 100)
    monkeypatch.setattr(app_module, "CAPTCHA_GLOBAL_LIMIT", 100)
    monkeypatch.setattr(app_module, "CAPTCHA_MAX_ACTIVE", 1)
    monkeypatch.setattr(app_module.captcha, "generate", lambda: (b"png", "ABCD"))
    client = app.test_client()
    assert client.get("/captcha.png").status_code == 200
    assert client.get("/captcha.png").status_code == 429
    assert len(app_module._captcha_store) == 1


def test_captcha_cleanup_is_incremental(monkeypatch):
    class NoScanDict(dict):
        def items(self):
            raise AssertionError("不应遍历全量验证码")

    monkeypatch.setattr(app_module, "_captcha_store", NoScanDict({
        "expired": ("old", 1.0), "live": ("new", 995.0),
    }))
    monkeypatch.setattr(app_module, "_captcha_expiry", [(1.0, "expired"), (995.0, "live")])
    monkeypatch.setattr(app_module, "_captcha_ip_issues", {"old-ip": [1.0], "live-ip": [995.0]})
    monkeypatch.setattr(app_module, "_captcha_ip_expiry", [(1.0, "old-ip"), (995.0, "live-ip")])
    app_module._captcha_global_issues.extend([1.0, 995.0])
    with app_module._captcha_lock:
        app_module._sweep_captcha(1000.0)
    assert set(app_module._captcha_store) == {"live"}
    assert set(app_module._captcha_ip_issues) == {"live-ip"}
    assert list(app_module._captcha_global_issues) == [995.0]


def test_captcha_concurrent_replay_only_one_success(monkeypatch):
    monkeypatch.setattr(app_module.captcha, "generate", lambda: (b"png", "ABCD"))
    client = app.test_client()
    assert client.get("/captcha.png").status_code == 200
    with client.session_transaction() as sess:
        token = sess["cap_tok"]

    barrier = threading.Barrier(3)
    results = []

    def consume():
        with app.test_request_context("/"):
            app_module.session["cap_tok"] = token
            barrier.wait()
            results.append(app_module._check_captcha("abcd"))

    threads = [threading.Thread(target=consume) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert results.count(True) == 1
    assert results.count(False) == 1


def test_verify_ignores_client_cookie_and_uses_server_challenge(monkeypatch):
    calls = []

    def verify(email, code, challenge, ip):
        calls.append((email, code, challenge, ip))
        return None, 4, "mismatch"

    monkeypatch.setattr(root_db, "verify_code", verify)
    client = app.test_client()
    pending(client)
    with client.session_transaction() as sess:
        sess["code_tries"] = 99
    response = client.post("/verify", data={"csrf": "csrf-token", "code": "000000"})
    assert response.status_code == 200
    assert "验证码错误或已过期" in response.get_data(as_text=True)
    assert calls == [("student@mail.bnu.edu.cn", "000000", 41, "127.0.0.1")]
    with client.session_transaction() as sess:
        assert "code_tries" not in sess
        assert sess["pending"]["challenge"] == 41


def test_verify_keeps_csrf_and_malformed_code_errors(monkeypatch):
    monkeypatch.setattr(root_db, "verify_code",
                        lambda *args: pytest.fail("CSRF/格式失败不应触达验证码"))
    client = app.test_client()
    pending(client)
    assert client.post("/verify", data={"code": "123456"}).status_code == 400
    response = client.post("/verify", data={"csrf": "csrf-token", "code": "abc"})
    assert response.status_code == 200
    assert "请输入 6 位数字验证码" in response.get_data(as_text=True)


def test_verify_server_limit_clears_pending(monkeypatch):
    monkeypatch.setattr(root_db, "verify_code", lambda *args: (None, 0, "limited"))
    client = app.test_client()
    pending(client)
    response = client.post("/verify", data={"csrf": "csrf-token", "code": "000000"})
    assert response.status_code == 302
    assert response.location.endswith("/register")
    with client.session_transaction() as sess:
        assert "pending" not in sess


def test_verify_success_does_not_use_separate_consume(monkeypatch):
    monkeypatch.setattr(root_db, "verify_code", lambda *args: (41, 4, "ok"))
    monkeypatch.setattr(root_db, "create_user", lambda *args: 7)
    monkeypatch.setattr(root_db, "consume_code", lambda *args: pytest.fail("重复消费"))
    client = app.test_client()
    pending(client)
    response = client.post("/verify", data={"csrf": "csrf-token", "code": "123456"})
    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert sess["uid"] == 7
        assert "pending" not in sess


def test_verify_create_failure_returns_claimed_code(monkeypatch):
    released = []
    monkeypatch.setattr(root_db, "verify_code", lambda *args: (41, 4, "ok"))
    monkeypatch.setattr(root_db, "create_user", lambda *args: (_ for _ in ()).throw(RuntimeError("db")))
    monkeypatch.setattr(root_db, "release_code", lambda cid: released.append(cid) or True)
    client = app.test_client()
    pending(client)
    response = client.post("/verify", data={"csrf": "csrf-token", "code": "123456"})
    assert response.status_code == 200
    assert "账号创建失败，请稍后重试" in response.get_data(as_text=True)
    assert released == [41]


def test_resend_rotates_server_challenge(monkeypatch):
    monkeypatch.setattr(root_db, "last_code_age", lambda email: None)
    monkeypatch.setattr(root_db, "recent_code_count", lambda email: 0)
    monkeypatch.setattr(root_db, "save_code", lambda *args: 42)
    monkeypatch.setattr(mailer, "send_code", lambda *args: None)
    client = app.test_client()
    pending(client)
    response = client.post("/api/resend", headers={"X-CSRF-Token": "csrf-token"})
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert sess["pending"]["challenge"] == 42


def test_user_search_omits_real_name(monkeypatch):
    monkeypatch.setattr(root_db, "get_user", lambda uid: {"id": uid, "status": "active"})
    monkeypatch.setattr(root_db, "search_user_by_no", lambda *args: {
        "id": 2, "student_no": "20261102", "nickname": "同学", "real_name": "敏感姓名",
    })
    monkeypatch.setattr(root_db, "is_friend", lambda *args: False)
    client = app.test_client()
    login(client)
    payload = client.get("/api/users/search?no=20261102").get_json()
    assert payload["found"] is True
    assert "real_name" not in payload["user"]
    assert payload["user"]["nickname"] == "同学"


def test_im_polling_gets_do_not_write_access_log(monkeypatch):
    writes = []

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, *args): writes.append(args)
        def commit(self): pass

    class Conn:
        def cursor(self): return Cursor()
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def commit(self): pass

    @contextmanager
    def connect():
        yield Conn()

    monkeypatch.setattr(root_db, "connect", connect)
    monkeypatch.setattr(app_module, "_log_access", REAL_LOG_ACCESS)
    for path in ("/api/conversations", "/api/friends", "/api/friends/requests", "/api/messages"):
        with app.test_request_context(path, method="GET"):
            app_module._log_access(200)
    assert writes == []
    with app.test_request_context("/api/messages", method="POST"):
        app_module._log_access(200)
    assert len(writes) == 1


class FakeCursor:
    def __init__(self, current=None, counts=(0, 0, 0), update_rows=1):
        self.current = current
        self.counts = list(counts)
        self.update_rows = update_rows
        self.rowcount = update_rows
        self.calls = []

    def __enter__(self): return self
    def __exit__(self, *args): return False

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if sql.startswith("SELECT COUNT"):
            self._next = {"c": self.counts.pop(0)}
        elif sql.startswith("SELECT id, code"):
            self._next = self.current
        elif sql.startswith("SELECT GET_LOCK"):
            self._next = {"locked": 1}
        elif sql.startswith("SELECT RELEASE_LOCK"):
            self._next = {"released": 1}

    def fetchone(self):
        return self._next


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0

    def cursor(self): return self._cursor
    def commit(self): self.commits += 1
    def rollback(self): pass
    def __enter__(self): return self
    def __exit__(self, *args): return False


def test_verify_code_counts_three_scopes_and_claims_atomically(monkeypatch):
    cursor = FakeCursor(current={"id": 41, "code": "123456", "expires_at": object()})
    monkeypatch.setattr(root_db, "connect", lambda: FakeConn(cursor))
    assert root_db.verify_code("student@mail.bnu.edu.cn", "123456", 41, "203.0.113.1") == (41, 4, "ok")
    inserts = [params for sql, params in cursor.calls if sql.startswith("INSERT INTO email_code")]
    assert len(inserts) == 3
    assert len({params[0] for params in inserts}) == 3
    assert all(params[0].startswith(("c:", "e:", "i:")) for params in inserts)
    updates = [sql for sql, _ in cursor.calls if sql.startswith("UPDATE email_code SET used=1")]
    assert len(updates) == 1 and "used=0" in updates[0] and "expires_at > NOW()" in updates[0]
    locks = [params[0] for sql, params in cursor.calls if sql.startswith("SELECT GET_LOCK")]
    assert locks[0] == root_db._attempt_lock_name(root_db._attempt_key("i", "203.0.113.1"))


def test_verify_code_stops_at_five_without_claim(monkeypatch):
    cursor = FakeCursor(current={"id": 41, "code": "123456", "expires_at": object()},
                        counts=(5, 0, 0))
    monkeypatch.setattr(root_db, "connect", lambda: FakeConn(cursor))
    assert root_db.verify_code("student@mail.bnu.edu.cn", "123456", 41, "203.0.113.1") == (None, 0, "limited")
    assert not any(sql.startswith("INSERT") for sql, _ in cursor.calls)
    assert not any(sql.startswith("UPDATE") for sql, _ in cursor.calls)


def test_verify_code_mismatch_records_attempt_without_claim(monkeypatch):
    cursor = FakeCursor(current={"id": 41, "code": "123456", "expires_at": object()})
    monkeypatch.setattr(root_db, "connect", lambda: FakeConn(cursor))
    assert root_db.verify_code("student@mail.bnu.edu.cn", "000000", 41, "203.0.113.1") == (None, 4, "mismatch")
    assert sum(sql.startswith("INSERT") for sql, _ in cursor.calls) == 3
    assert not any(sql.startswith("UPDATE") for sql, _ in cursor.calls)


def test_verify_code_accepts_legacy_pending_without_challenge(monkeypatch):
    cursor = FakeCursor(current={"id": 41, "code": "123456", "expires_at": object()})
    monkeypatch.setattr(root_db, "connect", lambda: FakeConn(cursor))
    assert root_db.verify_code("student@mail.bnu.edu.cn", "123456", None, "203.0.113.1") == (41, 4, "ok")
    locks = [params[0] for sql, params in cursor.calls if sql.startswith("SELECT GET_LOCK")]
    assert len(locks) == 2
    assert sum(sql.startswith("INSERT") for sql, _ in cursor.calls) == 3


def test_recent_code_count_excludes_attempt_events(monkeypatch):
    cursor = FakeCursor(counts=(0,))
    monkeypatch.setattr(root_db, "connect", lambda: FakeConn(cursor))
    assert root_db.recent_code_count("student@mail.bnu.edu.cn") == 0
    sql, params = cursor.calls[-1]
    assert "purpose='register'" in sql
    assert params[0] == "student@mail.bnu.edu.cn"
