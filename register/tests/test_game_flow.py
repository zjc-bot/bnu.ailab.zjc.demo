"""对战全链路集成测试（Flask-SocketIO 客户端，不连数据库）。

mock 掉 db 的好友/会话/归档，验证：
  邀请 → 加入 → 落子 → 五连终局 → 归档调用。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SECRET_KEY", "test-secret-for-game-flow")

import app as app_module  # noqa: E402
import db as root_db  # noqa: E402
from games import events as events_module  # noqa: E402
from games import manager  # noqa: E402

socketio = app_module.socketio
app = app_module.app


@pytest.fixture
def setup(monkeypatch):
    # login_required / current_uid 现在每次校验用户状态，测试需 mock
    monkeypatch.setattr(root_db, "get_user",
                        lambda uid: {"id": uid, "status": "active"})
    monkeypatch.setattr(root_db, "is_friend", lambda a, b: True)
    monkeypatch.setattr(
        root_db, "get_pair_conversation",
        lambda a, b: {"id": 7, "user_a": min(a, b), "user_b": max(a, b)},
    )
    archived = []
    monkeypatch.setattr(
        root_db, "save_game_record",
        lambda **kw: archived.append(kw) or len(archived),
    )
    # 离线邀请持久化在本测试里用内存替身，避免依赖真实 MySQL。
    invite_calls = []
    monkeypatch.setattr(events_module.store, "pending_for", lambda uid, limit=20: [])
    monkeypatch.setattr(
        events_module.store, "create_invite",
        lambda *args: invite_calls.append(args) or len(invite_calls),
    )
    monkeypatch.setattr(events_module.store, "accept_pending", lambda room, uid: True)
    monkeypatch.setattr(events_module.store, "decline_pending", lambda room, uid: None)
    monkeypatch.setattr(events_module.store, "expire_pending", lambda room, uid: None)
    for rid in list(manager._rooms):
        manager.destroy(rid)
    yield archived
    for rid in list(manager._rooms):
        manager.destroy(rid)


def test_full_game_flow(setup):
    archived = setup
    flask_c1 = app.test_client()
    flask_c2 = app.test_client()
    with flask_c1.session_transaction() as s:
        s["uid"] = 10
    with flask_c2.session_transaction() as s:
        s["uid"] = 20

    c1 = socketio.test_client(app, flask_test_client=flask_c1)
    c2 = socketio.test_client(app, flask_test_client=flask_c2)
    try:
        r = c1.emit("game:invite", {"to": 20, "game": "gomoku"}, callback=True)
        assert r["ok"] is True and r["room"] == 7

        assert c1.emit("game:join", {"room": 7}, callback=True)["ok"] is True
        assert c2.emit("game:join", {"room": 7}, callback=True)["ok"] is True

        # P1 在 y=0 连五，P2 在 y=5 陪走
        for i in range(4):
            assert c1.emit("game:move", {"room": 7, "move": {"x": i, "y": 0}}, callback=True)["ok"]
            assert c2.emit("game:move", {"room": 7, "move": {"x": i, "y": 5}}, callback=True)["ok"]
        last = c1.emit("game:move", {"room": 7, "move": {"x": 4, "y": 0}}, callback=True)

        assert last["ok"] is True
        # 终局即销毁房间：同一会话可立即开下一局
        assert manager.get_room(7) is None
        assert archived and archived[-1]["winner"] == 10
        assert archived[-1]["reason"] == "five_in_row"
        assert archived[-1]["steps"] == 9
    finally:
        c1.disconnect()
        c2.disconnect()


def test_wrong_turn_via_socket(setup):
    flask_c1 = app.test_client()
    flask_c2 = app.test_client()
    with flask_c1.session_transaction() as s:
        s["uid"] = 10
    with flask_c2.session_transaction() as s:
        s["uid"] = 20
    c1 = socketio.test_client(app, flask_test_client=flask_c1)
    c2 = socketio.test_client(app, flask_test_client=flask_c2)
    try:
        c1.emit("game:invite", {"to": 20, "game": "gomoku"}, callback=True)
        c2.emit("game:join", {"room": 7}, callback=True)
        # 轮到 P1，P2 抢先落子应被拒
        r = c2.emit("game:move", {"room": 7, "move": {"x": 0, "y": 0}}, callback=True)
        assert r["ok"] is False and "轮到你" in r["error"]
    finally:
        c1.disconnect()
        c2.disconnect()


def test_new_room_after_finished(setup):
    """终局后房间立即释放，同一对好友可立刻开下一局。"""
    archived = setup
    f1, f2 = app.test_client(), app.test_client()
    with f1.session_transaction() as s:
        s["uid"] = 10
    with f2.session_transaction() as s:
        s["uid"] = 20
    c1 = socketio.test_client(app, flask_test_client=f1)
    c2 = socketio.test_client(app, flask_test_client=f2)
    try:
        # 第一局：A 认输结束
        c1.emit("game:invite", {"to": 20, "game": "gomoku"}, callback=True)
        c1.emit("game:join", {"room": 7}, callback=True)
        c2.emit("game:join", {"room": 7}, callback=True)
        r = c1.emit("game:resign", {"room": 7}, callback=True)
        assert r["ok"] is True
        assert manager.get_room(7) is None
        before = len(archived)

        # 第二局：B 发起，应能重建房间，且座位按服务端 players=[B,A]
        r = c2.emit("game:invite", {"to": 10, "game": "gomoku"}, callback=True)
        assert r["ok"] is True and r["room"] == 7
        room = manager.get_room(7)
        assert room is not None and room["status"] == "active"
        assert room["players"] == [20, 10]

        j1 = c1.emit("game:join", {"room": 7}, callback=True)
        j2 = c2.emit("game:join", {"room": 7}, callback=True)
        assert j1["seat"] == 2 and j2["seat"] == 1   # 服务端结算座位，不按谁先点
        assert len(archived) == before               # 未终局不重复归档
    finally:
        c1.disconnect()
        c2.disconnect()


def test_resign_after_finished_rejected(setup):
    """已终局棋局再认输应被拒，不覆盖结果、不重复归档。"""
    archived = setup
    f1, f2 = app.test_client(), app.test_client()
    with f1.session_transaction() as s:
        s["uid"] = 10
    with f2.session_transaction() as s:
        s["uid"] = 20
    c1 = socketio.test_client(app, flask_test_client=f1)
    c2 = socketio.test_client(app, flask_test_client=f2)
    try:
        c1.emit("game:invite", {"to": 20, "game": "gomoku"}, callback=True)
        c1.emit("game:join", {"room": 7}, callback=True)
        c2.emit("game:join", {"room": 7}, callback=True)
        # 双方落一步，房间仍 active
        c1.emit("game:move", {"room": 7, "move": {"x": 0, "y": 0}}, callback=True)
        c2.emit("game:move", {"room": 7, "move": {"x": 1, "y": 0}}, callback=True)
        # A 认输终局
        c1.emit("game:resign", {"room": 7}, callback=True)
        n = len(archived)
        winner = archived[-1]["winner"]
        # 房间已销毁，再认输应报无权/不存在（而非覆盖结果）
        r = c2.emit("game:resign", {"room": 7}, callback=True)
        assert r["ok"] is False
        assert len(archived) == n
        assert archived[-1]["winner"] == winner
    finally:
        c1.disconnect()
        c2.disconnect()


def test_malformed_payloads_rejected(setup):
    """join/move/resign 载荷非 dict 时返回错误，不抛异常。"""
    f1 = app.test_client()
    with f1.session_transaction() as s:
        s["uid"] = 10
    c1 = socketio.test_client(app, flask_test_client=f1)
    try:
        for evt in ("game:join", "game:move", "game:resign",
                    "game:invite:decline", "game:ai:start"):
            r = c1.emit(evt, "not-a-dict", callback=True)
            assert r and r.get("ok") is False, evt
    finally:
        c1.disconnect()


def test_invite_is_persisted_before_delivery(setup, monkeypatch):
    """好友离线时也要先把邀请落库，不能只做内存推送。"""
    calls = []
    monkeypatch.setattr(
        events_module.store, "create_invite",
        lambda *args: calls.append(args) or 1,
    )
    f1 = app.test_client()
    with f1.session_transaction() as s:
        s["uid"] = 10
    c1 = socketio.test_client(app, flask_test_client=f1)
    try:
        r = c1.emit("game:invite", {"to": 20, "game": "gomoku"}, callback=True)
        assert r["ok"] is True
        assert calls == [(7, "gomoku", 10, 20)]
    finally:
        c1.disconnect()


def test_pending_invites_delivered_on_connect(setup, monkeypatch):
    """接收方上线后能拿到 1 小时内仍有效的持久化邀请。"""
    row = {
        "id": 3, "conv_id": 7, "game": "gomoku", "from_id": 10,
        "to_id": 20, "created_at": None, "from_name": "好友甲",
    }
    monkeypatch.setattr(
        events_module.store, "pending_for",
        lambda uid, limit=20: [row] if uid == 20 else [],
    )
    f2 = app.test_client()
    with f2.session_transaction() as s:
        s["uid"] = 20
    c2 = socketio.test_client(app, flask_test_client=f2)
    try:
        packets = c2.get_received()
        invites = [p for p in packets if p["name"] == "game:invites"]
        assert invites
        assert invites[-1]["args"][0]["items"][0]["conv_id"] == 7
    finally:
        c2.disconnect()


def test_pve_ai_replies_through_server_rules(setup):
    """PvE：真人落子后，AI 自动走一步，且棋盘仍由服务端派生。"""
    f1 = app.test_client()
    with f1.session_transaction() as s:
        s["uid"] = 10
    c1 = socketio.test_client(app, flask_test_client=f1)
    try:
        r = c1.emit(
            "game:ai:start",
            {"game": "gomoku", "difficulty": "easy"},
            callback=True,
        )
        assert r["ok"] is True and r["room"] == -10
        j = c1.emit("game:join", {"room": r["room"]}, callback=True)
        assert j["ok"] is True and j["seat"] == 1

        m = c1.emit(
            "game:move",
            {"room": r["room"], "move": {"x": 7, "y": 7}},
            callback=True,
        )
        assert m["ok"] is True
        snap = manager.snapshot(r["room"])
        assert snap is not None
        assert snap["state"]["board"][7][7] == 1
        assert sum(row.count(2) for row in snap["state"]["board"]) == 1
        assert snap["turn"] == 0
        assert snap["difficulty"] == "easy"
    finally:
        c1.disconnect()


def test_pve_rejects_unknown_difficulty(setup):
    f1 = app.test_client()
    with f1.session_transaction() as s:
        s["uid"] = 10
    c1 = socketio.test_client(app, flask_test_client=f1)
    try:
        r = c1.emit(
            "game:ai:start",
            {"game": "gomoku", "difficulty": "impossible"},
            callback=True,
        )
        assert r["ok"] is False
        assert "难度" in r["error"]
    finally:
        c1.disconnect()
