"""Socket.IO 事件层：好友对战（PvP）主线。

认证：复用 Flask session（cookie 随握手发送），不另发 token。
房间：conversation_id 作为 room_id，仅好友可加入。
"""

import json

import db as root_db
from flask import request, session
from flask_socketio import emit, join_room, leave_room

from . import manager


def register(socketio):
    """把事件处理器挂到 socketio 实例。"""

    def current_uid():
        return session.get("uid")

    @socketio.on("connect")
    def on_connect(auth=None):
        uid = current_uid()
        if not uid:
            return False          # 拒绝匿名连接
        session["socket_uid"] = uid
        # 一个用户可能有多个标签页，保留全部 sid；单值会被后连的覆盖，
        # 导致邀请只投到最后一个连接（可能已关闭）。
        _sids.setdefault(uid, set()).add(request.sid)
        emit("connected", {"uid": uid})

    @socketio.on("disconnect")
    def on_disconnect(reason=None):
        uid = session.get("socket_uid")
        if uid and uid in _sids:
            _sids[uid].discard(request.sid)
            if not _sids[uid]:
                _sids.pop(uid, None)
        # 不立即销毁房间：对方断线后重连应能恢复（见 §8.3）

    @socketio.on("game:invite")
    def on_invite(data):
        """A 邀请好友 B 对局。校验好友关系后返回 room_id 供双方加入。"""
        uid = current_uid()
        if not uid:
            return {"ok": False, "error": "未登录"}
        if not isinstance(data, dict):
            return {"ok": False, "error": "参数错误"}

        peer = data.get("to")
        game = data.get("game")
        if not isinstance(peer, int) or not game:
            return {"ok": False, "error": "参数错误"}

        # 好友关系：friend 表双向存两行，查一行即可
        if not root_db.is_friend(uid, peer):
            return {"ok": False, "error": "对方不是你的好友"}

        conv = root_db.get_pair_conversation(uid, peer)
        if not conv:
            return {"ok": False, "error": "会话不存在，请先成为好友"}
        room_id = int(conv["id"])
        # 邀请即建房：否则 game:join 拿到的 room_id 在 manager 里不存在，全链路断裂。
        # 房间以会话 id 为 room_id，天然保证同一对好友同一时刻只有一局。
        try:
            manager.create_room(room_id, game, uid, peer)
        except manager.RoomError:
            # 已存在房间（对方正在对局）：直接复用，不重复创建
            pass
        peer_sid = _peer_sid(peer)
        if peer_sid:
            emit("game:invited", {
                "from": uid,
                "game": game,
                "room": room_id,
            }, to=peer_sid)
        # 离线时不推送；邀请本身已落到 message 表（Phase 3 补），上线后可查
        return {"ok": True, "room": room_id, "delivered": bool(peer_sid)}

    @socketio.on("game:join")
    def on_join(data):
        """加入房间（接受邀请后双方调用）。"""
        uid = current_uid()
        if not uid:
            return {"ok": False, "error": "未登录"}
        room_id = int(data.get("room") or 0)
        r = manager.get_room(room_id)
        if not r:
            return {"ok": False, "error": "房间不存在"}
        if uid not in r["players"]:
            return {"ok": False, "error": "你不是该房间玩家"}
        join_room(room_id)
        emit("game:state", manager.snapshot(room_id))
        return {"ok": True}

    def archive(room_id):
        """终局归档：一步棋不落库，只在结束时写一条。失败只记日志，不影响对局。"""
        r = manager.get_room(room_id)
        if not r or not r.get("result"):
            return
        result = r["result"]
        try:
            root_db.save_game_record(
                conv_id=room_id,
                game=r["game"],
                player_a=r["players"][0],
                player_b=r["players"][1],
                winner=result.get("winner"),
                reason=result.get("reason", ""),
                moves=json.dumps(r.get("moves", []), ensure_ascii=False),
                steps=r.get("seq", 0),
            )
        except Exception:
            # 归档失败不应让对局端收到错误；日志留痕供排查。
            import flask
            flask.current_app.logger.exception("对局归档失败 room=%s", room_id)

    @socketio.on("game:move")
    def on_move(data):
        """落子：服务端权威校验后广播完整快照。"""
        uid = current_uid()
        if not uid:
            return {"ok": False, "error": "未登录"}
        room_id = int(data.get("room") or 0)
        move = data.get("move")
        # 只把坐标交给服务端规则层；客户端传来的 state 一律忽略，
        # 棋盘由 rules 从服务端状态派生，杜绝伪造棋盘与胜负。
        try:
            snap = manager.apply_move(room_id, uid, move)
        except manager.RoomError as e:
            return {"ok": False, "error": str(e)}
        emit("game:state", snap, to=room_id)
        if snap["status"] == "finished" and snap.get("result"):
            archive(room_id)
            emit("game:over", snap, to=room_id)
        return {"ok": True}

    @socketio.on("game:resign")
    def on_resign(data):
        uid = current_uid()
        if not uid:
            return {"ok": False, "error": "未登录"}
        room_id = int(data.get("room") or 0)
        r = manager.get_room(room_id)
        if not r or uid not in r["players"]:
            return {"ok": False, "error": "无权操作"}
        winner = r["players"][1 - r["players"].index(uid)]
        snap = manager.finish(room_id, {"winner": winner, "reason": "resign"})
        archive(room_id)
        emit("game:over", snap, to=room_id)
        return {"ok": True}


# uid -> {sid, ...}（一个用户可多连接）
_sids = {}


def _peer_sid(peer_uid):
    """取该用户任意一个在线连接；投递到任一端即可，前端会同步。"""
    sids = _sids.get(peer_uid)
    return next(iter(sids)) if sids else None
