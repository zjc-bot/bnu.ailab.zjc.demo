"""对局房间管理：内存态，单 worker 适用。

设计约束（见总纲 §7.2）：
  - 进行中的棋盘/回合/seq 放内存，不在每步落 MySQL
  - 终局由路由层写 game_record，房间随之销毁
  - 所有状态变更必须服务端权威校验，不信任客户端
"""

import logging
import threading
import time

from . import rules

logger = logging.getLogger(__name__)

# room_id -> {game, players, state, turn, seq, created_at, status}
_rooms = {}
_lock = threading.RLock()

ROOM_TTL = 3600          # 房间最长存活 1 小时
MAX_ROOMS = 256          # 防止内存无限增长
ARCHIVE_KEEP_TTL = 86400  # 归档未成功的终局房间，最多再留 24 小时供重试


class RoomError(Exception):
    pass


def create_room(room_id, game, p1, p2, initial_state=None, difficulty=None):
    """创建对局房间。p1/p2 为用户 id（int），AI 对手用 'ai:whale' 字符串。

    difficulty 仅对 PvE 生效，由服务端保存，客户端不能在落子时改写。
    """
    with _lock:
        # 每次建房都先清理过期房间，不必等到撞上 MAX_ROOMS。
        sweep()
        r = _rooms.get(room_id)
        if r:
            # 终局但战绩尚未归档：绝不能覆盖，否则 moves 永久丢失。
            if _is_pending_archive(r):
                raise RoomError("上一局战绩尚未归档，请稍后重试")
            raise RoomError("房间已存在")
        if len(_rooms) >= MAX_ROOMS:
            raise RoomError("房间数已达上限")
        try:
            state = rules.initial_state(game)
        except rules.GameRuleError as e:
            raise RoomError(str(e))
        _rooms[room_id] = {
            "game": game,
            "players": [p1, p2],
            "state": state,             # 服务端权威棋盘，客户端无法改写
            "turn": 0,                  # players 下标
            "seq": 0,
            "moves": [],                # 着法序列 [{player,x,y}]，终局归档用
            "created_at": time.time(),
            "status": "active",
            "difficulty": difficulty if isinstance(p2, str) else None,
            "archived": False,          # 终局战绩是否已成功写入 game_record
            "archiving": False,         # 归档占位，防止并发重试重复写 game_record
            "archive_attempts": 0,      # 归档失败次数，用于退避与告警
            "finished_at": None,        # 终局时间，决定待归档房间的保留期
        }
        return snapshot(room_id)


def _is_pending_archive(r):
    """终局且战绩未落库 —— 这类房间的 moves 是唯一副本，不能清理或覆盖。"""
    return r.get("status") == "finished" and not r.get("archived")


def get_room(room_id):
    with _lock:
        r = _rooms.get(room_id)
        if not r:
            return None
        # 未归档房间按 finished_at 多留 24 小时，给重试留出窗口；
        # 已归档/进行中的房间仍按创建时间 1 小时过期。
        if _is_pending_archive(r):
            ttl = ARCHIVE_KEEP_TTL
            since = r.get("finished_at") or r["created_at"]
        else:
            ttl = ROOM_TTL
            since = r["created_at"]
        if time.time() - since > ttl:
            _rooms.pop(room_id, None)
            return None
        return r


def snapshot(room_id):
    """完整状态快照，供广播与断线重连。"""
    r = get_room(room_id)
    if not r:
        return None
    return {
        "room": room_id,
        "game": r["game"],
        "players": list(r["players"]),
        "state": r["state"],
        "turn": r["turn"],
        "seq": r["seq"],
        "status": r["status"],
        "result": r.get("result"),   # 终局结果，供 game:over 广播与重连恢复
        "difficulty": r.get("difficulty"),
        "moves": list(r.get("moves", [])),
    }


def apply_move(room_id, uid, move):
    """服务端权威落子：棋盘由规则层从当前 state 派生，绝不采信客户端 state。

    成功返回新快照；非法着法/越权/规则错误一律抛 RoomError。
    """
    with _lock:
        r = get_room(room_id)
        if not r:
            raise RoomError("房间不存在或已过期")
        if r["status"] != "active":
            raise RoomError("对局已结束")
        if r["players"][r["turn"]] != uid:
            raise RoomError("还没轮到你")

        # player 编号由服务端按 turn 推导，客户端无法冒充对手
        player = r["turn"] + 1
        try:
            new_state = rules.apply_move(r["game"], r["state"], move, player)
        except (rules.GameRuleError, rules.gomoku.RuleError) as e:
            raise RoomError(str(e))

        r["state"] = new_state
        r["seq"] += 1
        # 记录权威着法（player 由 turn 推导，不采信客户端）
        r.setdefault("moves", []).append(
            {"player": player, "x": move.get("x"), "y": move.get("y")}
        )
        # 五连即终局；无胜负判定规则的游戏继续轮流
        winner_code = new_state.get("winner")
        if winner_code is not None:
            r["status"] = "finished"
            r["finished_at"] = time.time()
            if winner_code == 0:      # 和棋
                r["result"] = {"winner": None, "reason": "draw"}
            else:
                r["result"] = {"winner": r["players"][winner_code - 1],
                               "reason": rules.result_reason(r["game"])}
        else:
            r["turn"] = 1 - r["turn"]
        return snapshot(room_id)


def finish(room_id, result):
    """终局：标记结果并保留快照，待 events 层归档成功后才销毁。"""
    with _lock:
        r = get_room(room_id)
        if not r:
            raise RoomError("房间不存在")
        if r["status"] == "active":
            r["status"] = "finished"
            r["finished_at"] = time.time()
            r["result"] = result
        return snapshot(room_id)


def mark_archived(room_id):
    """归档成功后标记；房间随即可以安全销毁。"""
    with _lock:
        r = _rooms.get(room_id)
        if r:
            r["archived"] = True
    return destroy(room_id)


def claim_archive(room_id):
    """原子占位：同一终局只允许一个线程/事件进入归档。

    重试可能由多个用户同时上线触发，没有占位会写两条重复战绩。
    返回归档快照；已被占用或已归档则返回 None。
    """
    with _lock:
        r = _rooms.get(room_id)
        if not r or not _is_pending_archive(r) or r.get("archiving"):
            return None
        r["archiving"] = True
        return archive_payload(room_id)


def note_archive_failure(room_id):
    """归档失败：释放占位、保留房间与 moves，累计次数供退避/告警。"""
    with _lock:
        r = _rooms.get(room_id)
        if r:
            r["archiving"] = False
            r["archive_attempts"] = r.get("archive_attempts", 0) + 1
            return r["archive_attempts"]
    return 0


def pending_archives():
    """返回所有「已终局但战绩未落库」的房间 id，供重试。"""
    with _lock:
        return [rid for rid, r in _rooms.items() if _is_pending_archive(r)]


def archive_payload(room_id):
    """取一份归档所需的不可变快照；不暴露内部可变对象。"""
    r = get_room(room_id)
    if not r or not _is_pending_archive(r):
        return None
    return {
        "room_id": room_id,
        "game": r["game"],
        "players": list(r["players"]),
        "result": dict(r.get("result") or {}),
        "moves": [dict(m) for m in r.get("moves", [])],
        "steps": r.get("seq", 0),
        "difficulty": r.get("difficulty"),
        "attempts": r.get("archive_attempts", 0),
    }


def destroy(room_id):
    with _lock:
        return _rooms.pop(room_id, None) is not None


def seat_of(room_id, uid):
    """返回玩家座位（1/2）；不在房间返回 0。"""
    r = get_room(room_id)
    if not r:
        return 0
    try:
        return r["players"].index(uid) + 1
    except ValueError:
        return 0


def is_finished(room_id):
    r = get_room(room_id)
    return bool(r and r["status"] == "finished")


def sweep():
    """清理过期与已归档房间；未归档的终局房间必须保留，否则战绩永久丢失。

    由 create_room 在建房前调用，也可由运维/重试逻辑显式触发。
    """
    now = time.time()
    with _lock:
        for rid in list(_rooms):
            r = _rooms[rid]
            if _is_pending_archive(r):
                since = r.get("finished_at") or r["created_at"]
                if now - since > ARCHIVE_KEEP_TTL:
                    # 超过保留窗口仍未归档：放弃前再留一条完整棋谱日志，
                    # 否则这点唯一副本连人工补录的机会都没有。
                    logger.error(
                        "放弃未归档终局房间 room=%s attempts=%s game=%s "
                        "players=%s result=%s steps=%s moves=%s",
                        rid, r.get("archive_attempts", 0), r["game"],
                        r["players"], r.get("result"), r.get("seq", 0),
                        r.get("moves", []),
                    )
                    _rooms.pop(rid, None)
                continue
            if now - r["created_at"] > ROOM_TTL or r["status"] == "finished":
                _rooms.pop(rid, None)


def count():
    with _lock:
        return len(_rooms)
