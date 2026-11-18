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
from games import manager  # noqa: E402

socketio = app_module.socketio
app = app_module.app


@pytest.fixture
def setup(monkeypatch):
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
        assert manager.get_room(7)["status"] == "finished"
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
