"""五子棋规则：服务端权威落子与胜负判定。

客户端只提交坐标 {"x": int, "y": int}；棋盘由服务端维护，
绝不采信客户端传来的 state —— 否则客户端可伪造棋盘与胜负。
"""

BOARD = 15
EMPTY = 0
P1 = 1
P2 = 2


class RuleError(Exception):
    """非法着法。"""


def initial_state():
    return {"board": [[EMPTY] * BOARD for _ in range(BOARD)], "winner": None}


def apply_move(state, move, player):
    """在 board 上落子，返回新 state。player 为 P1/P2（服务端按 turn 推导）。

    不修改入参，返回新对象，避免快照与房间状态共享引用。
    """
    if not isinstance(state, dict) or "board" not in state:
        raise RuleError("棋盘状态损坏")
    board = state["board"]
    if not isinstance(board, list) or len(board) != BOARD:
        raise RuleError("棋盘状态损坏")

    if not isinstance(move, dict):
        raise RuleError("着法格式错误")
    x, y = move.get("x"), move.get("y")
    if not isinstance(x, int) or not isinstance(y, int) or isinstance(x, bool) or isinstance(y, bool):
        raise RuleError("坐标必须是整数")
    if not (0 <= x < BOARD and 0 <= y < BOARD):
        raise RuleError("坐标越界")
    if player not in (P1, P2):
        raise RuleError("玩家标识非法")
    if board[y][x] != EMPTY:
        raise RuleError("该位置已有棋子")

    new_board = [row[:] for row in board]
    new_board[y][x] = player
    winner = _five_in_row(new_board, x, y, player)
    return {"board": new_board, "winner": winner}


def _five_in_row(board, x, y, player):
    """只检查刚落子点的四个方向，O(4×BOARD)。"""
    for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
        count = 1
        for sign in (1, -1):
            sx, sy = x + dx * sign, y + dy * sign
            while 0 <= sx < BOARD and 0 <= sy < BOARD and board[sy][sx] == player:
                count += 1
                sx += dx * sign
                sy += dy * sign
        if count >= 5:
            return player
    return None
