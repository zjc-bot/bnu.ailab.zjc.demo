"""Socket.IO 事件层：好友对战（PvP）主线。

认证：复用 Flask session（cookie 随握手发送），不另发 token。
房间：conversation_id 作为 room_id，仅好友可加入。
"""

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
        _sids[uid] = request.sid
        emit("connected", {"uid": uid})

    @socketio.on("disconnect")
    def on_disconnect(reason=None):
        uid = session.get("socket_uid")
        if uid and _sids.get(uid) == request.sid:
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

    @socketio.on("game:move")
    def on_move(data):
        """落子：服务端权威校验后广播完整快照。"""
        uid = current_uid()
        if not uid:
            return {"ok": False, "error": "未登录"}
        room_id = int(data.get("room") or 0)
        move = data.get("move")
        next_state = data.get("state")
        # 注意：next_state 来自客户端，仅作暂存；真实校验由 rules 层在 Phase 3 补齐。
        # 当前阶段用 manager 的回合校验防止乱序与越权。
        try:
            snap = manager.apply_move(room_id, uid, move, next_state)
        except manager.RoomError as e:
            return {"ok": False, "error": str(e)}
        emit("game:state", snap, to=room_id)
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
        emit("game:over", snap, to=room_id)
        return {"ok": True}


# uid -> sid 映射（用于定向推送邀请）
_sids = {}


def _peer_sid(peer_uid):
    return _sids.get(peer_uid)
