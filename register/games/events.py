"""Socket.IO 事件层：好友对战（PvP）+ 小鲸 AI 对战（PvE）。

认证：复用 Flask session（cookie 随握手发送），不另发 token。
房间：PvP 用 conversation_id 作为 room_id，PvE 用负数 uid 作为 room_id。
持久化：对战邀请写入 game_invite，接收方上线后可读取；棋盘热态仍只在内存。
"""

import datetime
import json
import logging

import db as root_db
from flask import request, session
from flask_socketio import emit, join_room

from . import ai, manager, rules, store

# 归档重试未来可能从后台任务触发，日志不能依赖 Flask 请求上下文。
logger = logging.getLogger(__name__)

AI_PLAYER = "ai:whale"


def register(socketio):
    """把事件处理器挂到 socketio 实例。"""

    def current_uid():
        """Socket.IO 握手/事件共用：校验用户仍存在且未停用。"""
        uid = session.get("uid")
        if not uid:
            return None
        u = root_db.get_user(uid)
        if not u or u.get("status") != "active":
            return None
        return uid

    def serialize_invites(rows):
        items = []
        for row in rows or []:
            item = dict(row)
            at = item.get("created_at")
            if isinstance(at, (datetime.datetime, datetime.date)):
                item["created_at"] = at.isoformat(sep=" ", timespec="seconds")
            items.append(item)
        return items

    def pending_invites(uid):
        """投递待处理邀请。

        邀请在 MySQL、房间在进程内存，二者寿命不同：进程重启后 DB 里仍可能
        留着 pending 邀请而房间已不存在。此时不收口邀请——on_join 会按 DB
        记录把房间重建出来，离线邀请才真正名副其实。只有「房间已终局」
        才说明这局已经打完，把残留邀请收掉。
        """
        try:
            rows = serialize_invites(store.pending_for(uid))
        except Exception:
            logger.exception("读取离线对战邀请失败 uid=%s", uid)
            return []

        alive = []
        for item in rows:
            rid = item.get("conv_id")
            r = manager.get_room(rid) if rid else None
            if r and r["status"] == "finished":
                try:
                    store.expire_pending(rid, uid)
                except Exception:
                    logger.exception("收口已终局邀请失败 room=%s uid=%s", rid, uid)
                continue
            alive.append(item)
        return alive

    def deliver_pending(uid):
        emit("game:invites", {"items": pending_invites(uid)})

    def restore_room_from_invite(room_id, uid):
        """房间因重启/超时消失时，凭仍有效的 DB 邀请重建。

        必须校验邀请归属、好友关系与会话，否则任何人都能凭猜到的 room_id 建房。
        成功返回房间，失败返回 None（调用方负责收口邀请）。
        """
        if not isinstance(room_id, int) or room_id <= 0:
            return None
        try:
            inv = store.pending_in_room(room_id, uid)
        except Exception:
            logger.exception("重建房间读取邀请失败 room=%s", room_id)
            return None
        if (not inv or inv.get("to_id") != uid
                or not rules.supported(inv.get("game"))):
            return None
        from_id = inv.get("from_id")
        if (not isinstance(from_id, int) or isinstance(from_id, bool)
                or not root_db.is_friend(uid, from_id)):
            return None
        conv = root_db.get_pair_conversation(uid, from_id)
        if not conv or int(conv["id"]) != room_id:
            return None
        try:
            manager.create_room(room_id, inv["game"], from_id, uid)
        except manager.RoomError:
            # 并发下已被别人重建，直接复用即可
            pass
        return manager.get_room(room_id)

    def _persist(payload):
        """把一份归档快照写入 game_record，返回是否成功。"""
        room_id = payload["room_id"]
        result = payload["result"]
        try:
            root_db.save_game_record(
                conv_id=room_id if isinstance(room_id, int) and room_id > 0 else None,
                game=payload["game"],
                player_a=payload["players"][0],
                player_b=payload["players"][1],
                winner=result.get("winner"),
                reason=result.get("reason", ""),
                moves=json.dumps(payload["moves"], ensure_ascii=False),
                steps=payload["steps"],
                ai_difficulty=payload["difficulty"],
            )
            return True
        except Exception:
            # 归档失败绝不销毁房间：moves 是唯一副本，销毁即永久丢失。
            # 日志里带完整着法 JSON，即使重试也失败，仍可人工补录。
            logger.error(
                "对局归档失败（房间已保留待重试）room=%s attempts=%s "
                "game=%s players=%s result=%s steps=%s moves=%s",
                room_id, payload["attempts"] + 1, payload["game"],
                payload["players"], result, payload["steps"],
                json.dumps(payload["moves"], ensure_ascii=False),
                exc_info=True,
            )
            return False

    def archive(room_id):
        """终局归档；成功才允许销毁房间。返回是否成功。"""
        # 原子占位：并发重试（多人同时上线）只会有一个拿到归档权。
        payload = manager.claim_archive(room_id)
        if not payload:
            return False
        if _persist(payload):
            manager.mark_archived(room_id)
            return True
        manager.note_archive_failure(room_id)
        return False

    def retry_pending_archives():
        """用户上线/刷新邀请时，顺带补偿此前归档失败的终局。"""
        for room_id in manager.pending_archives():
            archive(room_id)

    def finalize(room_id, snap):
        if snap.get("status") == "finished" and snap.get("result"):
            # 对局结果照常广播，不因归档失败而让用户看不到胜负。
            emit("game:over", snap, to=room_id)
            # archive 成功时自行销毁房间；失败时保留房间、写可恢复日志，
            # 等上线/刷新时补偿重试。用户若此时点「再来一局」会收到明确提示。
            archive(room_id)

    def ai_reply(room_id, snap):
        """PvE：真人落子后服务端立即计算并校验 AI 着法。"""
        r = manager.get_room(room_id)
        if not r or r["status"] != "active":
            return snap
        if r["players"][r["turn"]] != AI_PLAYER:
            return snap
        try:
            move = ai.choose_move(
                snap["state"], r.get("difficulty") or "normal", player=2,
            )
            if move is None:
                return manager.finish(room_id, {"winner": None, "reason": "draw"})
            return manager.apply_move(room_id, AI_PLAYER, move)
        except Exception:
            # 不能把用户留在“AI 回合”却永远等不到落子；按异常平局收局。
            logger.exception("AI 落子失败 room=%s", room_id)
            return manager.finish(room_id, {"winner": None, "reason": "ai_error"})

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
        # 上次归档失败的终局，趁有人上线补偿一次。
        retry_pending_archives()
        deliver_pending(uid)

    @socketio.on("disconnect")
    def on_disconnect(reason=None):
        uid = session.get("socket_uid")
        if uid and uid in _sids:
            _sids[uid].discard(request.sid)
            if not _sids[uid]:
                _sids.pop(uid, None)
        # 不立即销毁房间：对方断线后重连应能恢复（见 §8.3）

    @socketio.on("game:invites")
    def on_list_invites(data=None):
        """客户端也可主动刷新待处理邀请；始终只返回当前登录用户自己的。"""
        uid = current_uid()
        if not uid:
            return {"ok": False, "error": "未登录", "items": []}
        retry_pending_archives()
        items = pending_invites(uid)
        emit("game:invites", {"items": items})
        return {"ok": True, "items": items}

    @socketio.on("game:invite")
    def on_invite(data):
        """A 邀请好友 B 对局。邀请先持久化，再向在线连接推送。"""
        uid = current_uid()
        if not uid:
            return {"ok": False, "error": "未登录"}
        if not isinstance(data, dict):
            return {"ok": False, "error": "参数错误"}

        peer = data.get("to")
        game = data.get("game")
        if (not isinstance(peer, int) or isinstance(peer, bool)
                or not isinstance(game, str) or not rules.supported(game)):
            return {"ok": False, "error": "参数错误"}

        # 好友关系：friend 表双向存两行，查一行即可
        if not root_db.is_friend(uid, peer):
            return {"ok": False, "error": "对方不是你的好友"}

        conv = root_db.get_pair_conversation(uid, peer)
        if not conv:
            return {"ok": False, "error": "会话不存在，请先成为好友"}
        room_id = int(conv["id"])
        # 邀请即建房；房间以会话 id 为键，同一对好友同一时刻只保留一局。
        r = manager.get_room(room_id)
        if r and r["status"] == "finished":
            if r.get("archived"):
                # 已落库的终局房间没有保留价值，直接释放以便开新局。
                manager.destroy(room_id)
                r = None
            else:
                # 房间里的 moves 是唯一副本，绝不能销毁重建。
                # 先补偿归档，仍失败则拒绝开新局，等下次重试完成。
                archive(room_id)
                r = manager.get_room(room_id)
                if r:
                    return {"ok": False, "error": "上一局战绩尚未归档，请稍后重试"}
        created = False
        if not r:
            try:
                manager.create_room(room_id, game, uid, peer)
                created = True
            except manager.RoomError as e:
                return {"ok": False, "error": str(e)}
        else:
            if uid not in r["players"] or peer not in r["players"]:
                return {"ok": False, "error": "该会话已有进行中的对局"}
            # 已落子的活跃棋盘不能复用：否则 B 点「接受」会接上一局的残局。
            # 仅允许重复邀请刚建好、尚未落子的空房间（幂等重发）。
            if r.get("seq", 0) > 0:
                return {"ok": False, "error": "该会话已有进行中的对局，请先结束"}

        # 先落库再通知：好友离线/页面未打开时，上线仍能看到邀请。
        try:
            store.create_invite(room_id, game, uid, peer)
        except Exception:
            if created:
                manager.destroy(room_id)
            logger.exception("保存对战邀请失败 room=%s", room_id)
            return {"ok": False, "error": "邀请保存失败，请稍后重试"}

        peer_sid = _peer_sid(peer)
        if peer_sid:
            emit("game:invited", {
                "from": uid,
                "game": game,
                "room": room_id,
            }, to=peer_sid)
        return {"ok": True, "room": room_id, "delivered": bool(peer_sid)}

    @socketio.on("game:invite:decline")
    def on_decline(data):
        uid = current_uid()
        if not uid:
            return {"ok": False, "error": "未登录"}
        if not isinstance(data, dict):
            return {"ok": False, "error": "参数错误"}
        try:
            room_id = int(data.get("room") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "房间号错误"}
        try:
            row = store.decline_pending(room_id, uid)
        except Exception:
            logger.exception("拒绝对战邀请失败 room=%s", room_id)
            return {"ok": False, "error": "操作失败，请稍后重试"}
        if row:
            sid = _peer_sid(row["from_id"])
            if sid:
                emit("game:invite:declined", {"room": room_id, "by": uid}, to=sid)
            # 邀请即建房，被拒后这个空房间不该继续留着让发起人单方面开局。
            # 只在尚未落子时清理：有 moves 或已终局的房间一律交给归档流程。
            r = manager.get_room(room_id)
            if (r and r["status"] == "active" and r.get("seq", 0) == 0):
                manager.destroy(room_id)
        return {"ok": True}

    @socketio.on("game:join")
    def on_join(data):
        """加入房间（接受邀请后双方调用）。"""
        uid = current_uid()
        if not uid:
            return {"ok": False, "error": "未登录"}
        if not isinstance(data, dict):
            return {"ok": False, "error": "参数错误"}
        try:
            room_id = int(data.get("room") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "房间号错误"}
        r = manager.get_room(room_id)
        if not r and room_id > 0:
            # 房间消失但邀请仍在库（进程重启后常见）：凭邀请重建，而非让用户
            # 看到一条点了必然失败的死邀请。
            r = restore_room_from_invite(room_id, uid)
        if not r:
            try:
                store.expire_pending(room_id, uid)
            except Exception:
                logger.exception("清理过期邀请失败 room=%s", room_id)
            return {"ok": False, "error": "邀请已过期，请让对方重新发起"}
        if r["status"] != "active":
            return {"ok": False, "error": "对局已结束"}
        if uid not in r["players"]:
            return {"ok": False, "error": "你不是该房间玩家"}
        join_room(room_id)
        if room_id > 0:
            try:
                store.accept_pending(room_id, uid)
            except Exception:
                logger.exception("接受对战邀请落库失败 room=%s", room_id)
        emit("game:state", manager.snapshot(room_id))
        # 座位由服务端下发，客户端不得自行推断（复用房间时座次可能与上次相反）
        return {"ok": True, "seat": manager.seat_of(room_id, uid)}

    @socketio.on("game:ai:start")
    def on_ai_start(data):
        """创建 PvE 房间。AI 始终为后手，难度由服务端保存。"""
        uid = current_uid()
        if not uid:
            return {"ok": False, "error": "未登录"}
        if not isinstance(data, dict):
            return {"ok": False, "error": "参数错误"}
        game = data.get("game")
        difficulty = data.get("difficulty", "normal")
        if game != "gomoku" or not rules.supported(game):
            return {"ok": False, "error": "AI 对手暂只支持五子棋"}
        if difficulty not in ai.DIFFICULTIES:
            return {"ok": False, "error": "难度参数错误"}

        room_id = -int(uid)
        old = manager.get_room(room_id)
        if old:
            if old["status"] == "active" and old.get("seq", 0) > 0:
                return {"ok": False, "error": "已有进行中的对局，请先结束"}
            # 终局但归档未完成：先补偿，绝不直接销毁带 moves 的房间。
            if old["status"] == "finished" and not old.get("archived"):
                archive(room_id)
                old = manager.get_room(room_id)
                if old:
                    return {"ok": False, "error": "上一局战绩尚未归档，请稍后重试"}
            else:
                # 已归档的终局房间、或尚未落子的空房间，均无复盘价值。
                manager.destroy(room_id)
        try:
            manager.create_room(room_id, game, uid, AI_PLAYER,
                                difficulty=difficulty)
        except manager.RoomError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "room": room_id, "difficulty": difficulty}

    @socketio.on("game:move")
    def on_move(data):
        """落子：服务端权威校验后广播完整快照；PvE 自动接一步 AI 着法。"""
        uid = current_uid()
        if not uid:
            return {"ok": False, "error": "未登录"}
        if not isinstance(data, dict):
            return {"ok": False, "error": "参数错误"}
        try:
            room_id = int(data.get("room") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "房间号错误"}
        move = data.get("move")
        # 只把坐标交给服务端规则层；客户端传来的 state 一律忽略，
        # 棋盘由 rules 从服务端状态派生，杜绝伪造棋盘与胜负。
        try:
            snap = manager.apply_move(room_id, uid, move)
        except manager.RoomError as e:
            return {"ok": False, "error": str(e)}
        emit("game:state", snap, to=room_id)

        r = manager.get_room(room_id)
        if (snap["status"] == "active" and r
                and AI_PLAYER in r["players"]
                and r["players"][r["turn"]] == AI_PLAYER):
            snap = ai_reply(room_id, snap)
            emit("game:state", snap, to=room_id)

        finalize(room_id, snap)
        return {"ok": True}

    @socketio.on("game:resign")
    def on_resign(data):
        uid = current_uid()
        if not uid:
            return {"ok": False, "error": "未登录"}
        if not isinstance(data, dict):
            return {"ok": False, "error": "参数错误"}
        try:
            room_id = int(data.get("room") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "房间号错误"}
        r = manager.get_room(room_id)
        if not r or uid not in r["players"]:
            return {"ok": False, "error": "无权操作"}
        # 已终局的棋局再认输会覆盖结果、重复归档，必须拒绝。
        if r["status"] != "active":
            return {"ok": False, "error": "对局已结束"}
        winner = r["players"][1 - r["players"].index(uid)]
        snap = manager.finish(room_id, {"winner": winner, "reason": "resign"})
        finalize(room_id, snap)
        return {"ok": True}


# uid -> {sid, ...}（一个用户可多连接）
_sids = {}


def _peer_sid(peer_uid):
    """取该用户任意一个在线连接；投递到任一端即可，前端会同步。"""
    sids = _sids.get(peer_uid)
    return next(iter(sids)) if sids else None
