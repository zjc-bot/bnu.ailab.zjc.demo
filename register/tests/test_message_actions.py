"""消息交互 API 测试（§9B）：删除 / 转发 / 引用 / 批量上限。

用 mock 隔离数据层，重点验证服务端校验：CSRF、会话归属、上限、跨会话引用。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret-for-message-actions")

import app as app_module  # noqa: E402
import db as root_db  # noqa: E402

app = app_module.app
app.config["TESTING"] = True


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(root_db, "get_user",
                        lambda uid: {"id": uid, "status": "active",
                                     "nickname": "用户" + str(uid)})
    return app.test_client()


def login(c, uid):
    with c.session_transaction() as s:
        s["uid"] = uid
        s["_csrf"] = "tok"
        # login_required 经 get_user（已 mock）；CSRF 头用 _csrf


def test_delete_requires_csrf(client, monkeypatch):
    monkeypatch.setattr(root_db, "get_conversation",
                        lambda cid: {"id": cid, "user_a": 1, "user_b": 2})
    login(client, 1)
    r = client.post("/api/messages/delete", json={"conv": 1, "ids": [5]})
    assert r.status_code == 403


def test_delete_checks_conv_membership(client, monkeypatch):
    monkeypatch.setattr(root_db, "get_conversation",
                        lambda cid: {"id": cid, "user_a": 1, "user_b": 2})
    login(client, 99)   # 非会话成员
    r = client.post("/api/messages/delete",
                    json={"conv": 1, "ids": [5]},
                    headers={"X-CSRF-Token": "tok"})
    assert r.status_code == 404


def test_delete_rejects_over_50(client, monkeypatch):
    monkeypatch.setattr(root_db, "get_conversation",
                        lambda cid: {"id": cid, "user_a": 1, "user_b": 2})
    login(client, 1)
    r = client.post("/api/messages/delete",
                    json={"conv": 1, "ids": list(range(1, 52))},
                    headers={"X-CSRF-Token": "tok"})
    assert r.status_code == 400
    assert "50" in r.get_json()["error"]


def test_delete_rejects_bad_ids(client, monkeypatch):
    monkeypatch.setattr(root_db, "get_conversation",
                        lambda cid: {"id": cid, "user_a": 1, "user_b": 2})
    login(client, 1)
    for bad in ([0], ["5"], [True], "5", []):
        r = client.post("/api/messages/delete",
                        json={"conv": 1, "ids": bad},
                        headers={"X-CSRF-Token": "tok"})
        assert r.status_code == 400, bad


def test_delete_calls_soft_delete(client, monkeypatch):
    monkeypatch.setattr(root_db, "get_conversation",
                        lambda cid: {"id": cid, "user_a": 1, "user_b": 2})
    called = {}
    monkeypatch.setattr(root_db, "soft_delete_messages",
                        lambda conv, uid, ids: (called.update(conv=conv, uid=uid, ids=ids) or 2))
    login(client, 1)
    r = client.post("/api/messages/delete",
                    json={"conv": 1, "ids": [5, 6]},
                    headers={"X-CSRF-Token": "tok"})
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "deleted": 2}
    assert called == {"conv": 1, "uid": 1, "ids": [5, 6]}


def test_forward_rejects_non_friend(client, monkeypatch):
    convs = {1: {"id": 1, "user_a": 1, "user_b": 2},
             2: {"id": 2, "user_a": 1, "user_b": 3}}
    monkeypatch.setattr(root_db, "get_conversation", lambda cid: convs.get(cid))
    monkeypatch.setattr(root_db, "is_friend", lambda a, b: False)
    login(client, 1)
    r = client.post("/api/messages/forward",
                    json={"conv": 1, "to_conv": 2, "ids": [5]},
                    headers={"X-CSRF-Token": "tok"})
    assert r.status_code == 403


def test_forward_sends_text_snapshot(client, monkeypatch):
    convs = {1: {"id": 1, "user_a": 1, "user_b": 2},
             2: {"id": 2, "user_a": 1, "user_b": 3}}
    monkeypatch.setattr(root_db, "get_conversation", lambda cid: convs.get(cid))
    monkeypatch.setattr(root_db, "is_friend", lambda a, b: True)
    monkeypatch.setattr(root_db, "get_messages_by_ids",
                        lambda conv, ids: [{"id": 5, "sender_id": 2, "content": "原文"}])
    sent = []
    monkeypatch.setattr(root_db, "add_im_message",
                        lambda conv, uid, text, **kw: sent.append((conv, uid, text, kw)) or 9)
    login(client, 1)
    r = client.post("/api/messages/forward",
                    json={"conv": 1, "to_conv": 2, "ids": [5]},
                    headers={"X-CSRF-Token": "tok"})
    assert r.status_code == 200 and r.get_json()["forwarded"] == 1
    assert sent[0][0] == 2 and sent[0][1] == 1
    assert "转发自" in sent[0][2] and "原文" in sent[0][2]
    assert sent[0][3].get("forward_from") == 1


def test_send_rejects_cross_conv_quote(client, monkeypatch):
    """跨会话引用按无引用处理，不报错也不写入 quote_id。"""
    monkeypatch.setattr(root_db, "get_conversation",
                        lambda cid: {"id": cid, "user_a": 1, "user_b": 2})
    monkeypatch.setattr(root_db, "is_message_in_conv", lambda mid, cid: False)
    seen = {}
    monkeypatch.setattr(root_db, "add_im_message",
                        lambda conv, uid, content, **kw: seen.update(kw) or 7)
    login(client, 1)
    r = client.post("/api/messages",
                    json={"conv": 1, "content": "回复", "quote_id": 999},
                    headers={"X-CSRF-Token": "tok"})
    assert r.status_code == 200
    assert seen.get("quote_id") is None


def test_soft_delete_uses_current_side(monkeypatch):
    """软删除按 uid 是 user_a 还是 user_b 置对应标志位。"""
    class FakeCursor:
        rowcount = 2

        def __enter__(self): return self
        def __exit__(self, *a): return False

        def fetchone(self):
            return {"user_a": 1, "user_b": 2}

        def execute(self, sql, params):
            if sql.startswith("UPDATE"):
                assert "deleted_by_a=1" in sql
                assert params == (1, 5, 6)

    class FakeConn:
        def cursor(self): return FakeCursor()
        def commit(self): pass

    import contextlib

    @contextlib.contextmanager
    def fake_connect():
        yield FakeConn()

    monkeypatch.setattr(root_db, "connect", fake_connect)
    monkeypatch.setattr(root_db, "get_conversation",
                        lambda cid: {"id": cid, "user_a": 1, "user_b": 2})
    assert root_db.soft_delete_messages(1, 1, [5, 6]) == 2
