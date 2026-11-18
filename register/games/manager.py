"""对局房间管理：内存态，单 worker 适用。

设计约束（见总纲 §7.2）：
  - 进行中的棋盘/回合/seq 放内存，不在每步落 MySQL
  - 终局由路由层写 game_record，房间随之销毁
  - 所有状态变更必须服务端权威校验，不信任客户端
"""

import threading
import time

from . import rules

# room_id -> {game, players, state, turn, seq, created_at, status}
_rooms = {}
_lock = threading.RLock()

ROOM_TTL = 3600          # 房间最长存活 1 小时
MAX_ROOMS = 256          # 防止内存无限增长


class RoomError(Exception):
    pass


def create_room(room_id, game, p1, p2, initial_state=None):
    """创建对局房间。p1/p2 为用户 id（int），AI 对手用 'ai:whale' 字符串。"""
    with _lock:
        if room_id in _rooms:
            raise RoomError("房间已存在")
        if len(_rooms) >= MAX_ROOMS:
            sweep()
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
            "created_at": time.time(),
            "status": "active",
        }
        return snapshot(room_id)


def get_room(room_id):
    with _lock:
        r = _rooms.get(room_id)
        if not r:
            return None
        if time.time() - r["created_at"] > ROOM_TTL:
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
        # 五连即终局；无胜负判定规则的游戏继续轮流
        if new_state.get("winner"):
            r["status"] = "finished"
            r["result"] = {"winner": r["players"][new_state["winner"] - 1],
                           "reason": "five_in_row"}
        else:
            r["turn"] = 1 - r["turn"]
        return snapshot(room_id)


def finish(room_id, result):
    """终局：标记结果并保留快照供查询，稍后由路由层归档后调用 destroy。"""
    with _lock:
        r = get_room(room_id)
        if not r:
            raise RoomError("房间不存在")
        r["status"] = "finished"
        r["result"] = result
        return snapshot(room_id)


def destroy(room_id):
    with _lock:
        return _rooms.pop(room_id, None) is not None


def sweep():
    """清理过期与已结束房间。"""
    now = time.time()
    with _lock:
        for rid in list(_rooms):
            r = _rooms[rid]
            if now - r["created_at"] > ROOM_TTL or r["status"] == "finished":
                _rooms.pop(rid, None)


def count():
    with _lock:
        return len(_rooms)
