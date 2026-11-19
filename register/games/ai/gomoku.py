"""五子棋本地 AI：必胜/必堵优先，启发式排序与有界 Minimax。

所有输入均来自服务端棋盘；返回的坐标还会经公共规则层再次校验。
简单档在高分候选中随机选择，普通档搜索 2 层，困难档搜索 3 层。
"""

import random

from ..rules import gomoku


DIFFICULTIES = {"easy", "normal", "hard"}
WIN_SCORE = 100_000_000
_DIRECTIONS = ((1, 0), (0, 1), (1, 1), (1, -1))


def choose_move(state, difficulty="normal", player=gomoku.P2, rng=None):
    """返回一个合法着法；没有可下位置时返回 None。"""
    if difficulty not in DIFFICULTIES:
        raise ValueError("未知 AI 难度")
    if player not in (gomoku.P1, gomoku.P2):
        raise ValueError("玩家标识非法")
    rng = rng or random
    board = state["board"]
    cells = _candidate_cells(board, radius=1)
    if not cells:
        return None
    if not any(any(row) for row in board):
        return {"x": gomoku.BOARD // 2, "y": gomoku.BOARD // 2}

    # 所有难度都先取胜、再堵住对手的一步必胜，避免随机扰动破坏基本棋力。
    winning = [cell for cell in cells if _wins(board, cell, player)]
    if winning:
        return _coord(rng.choice(winning))
    opponent = gomoku.P1 if player == gomoku.P2 else gomoku.P2
    blocks = [cell for cell in cells if _wins(board, cell, opponent)]
    if blocks:
        return _coord(rng.choice(blocks))

    candidates = _candidate_cells(board, radius=2)
    ordered = _ordered_moves(board, candidates, player)
    if difficulty == "easy":
        # 保留基础启发式，同时让简单档不完全固定、会漏掉较深组合。
        return _coord(rng.choice(ordered[:min(6, len(ordered))]))

    depth, width = (2, 8) if difficulty == "normal" else (3, 10)
    best_value = -WIN_SCORE * 2
    best = []
    for x, y in ordered[:width]:
        new_board = _play(board, x, y, player)
        value = _alpha_beta(
            new_board, depth - 1, opponent, player,
            -WIN_SCORE * 2, WIN_SCORE * 2, width,
        )
        if value > best_value:
            best_value = value
            best = [(x, y)]
        elif value == best_value:
            best.append((x, y))
    return {"x": best[0][0], "y": best[0][1]} if len(best) == 1 else _coord(rng.choice(best))


def _alpha_beta(board, depth, turn, root, alpha, beta, width):
    opponent = gomoku.P1 if turn == gomoku.P2 else gomoku.P2
    cells = _candidate_cells(board, radius=2)
    if not cells:
        return 0
    ordered = _ordered_moves(board, cells, turn)[:width]
    maximizing = turn == root
    best = -WIN_SCORE * 2 if maximizing else WIN_SCORE * 2
    for x, y in ordered:
        new_board = _play(board, x, y, turn)
        if gomoku._five_in_row(new_board, x, y, turn):
            value = WIN_SCORE if turn == root else -WIN_SCORE
        elif depth <= 1:
            value = _evaluate(new_board, root)
        else:
            value = _alpha_beta(new_board, depth - 1, opponent, root, alpha, beta, width)
        if maximizing:
            best = max(best, value)
            alpha = max(alpha, best)
        else:
            best = min(best, value)
            beta = min(beta, best)
        if beta <= alpha:
            break
    return best


def _candidate_cells(board, radius):
    """只搜索已有棋子附近的空位；空棋盘由调用方走中心点。"""
    cells = set()
    has_stone = False
    for y in range(gomoku.BOARD):
        for x in range(gomoku.BOARD):
            if board[y][x] == gomoku.EMPTY:
                continue
            has_stone = True
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    nx, ny = x + dx, y + dy
                    if (0 <= nx < gomoku.BOARD and 0 <= ny < gomoku.BOARD
                            and board[ny][nx] == gomoku.EMPTY):
                        cells.add((nx, ny))
    if not has_stone:
        return [(gomoku.BOARD // 2, gomoku.BOARD // 2)]
    return sorted(cells)


def _ordered_moves(board, cells, player):
    opponent = gomoku.P1 if player == gomoku.P2 else gomoku.P2
    scored = []
    for x, y in cells:
        attack = _placement_score(board, x, y, player)
        defence = _placement_score(board, x, y, opponent)
        center = gomoku.BOARD - abs(x - 7) - abs(y - 7)
        scored.append((attack * 1.08 + defence + center, x, y))
    scored.sort(reverse=True)
    return [(x, y) for _, x, y in scored]


def _placement_score(board, x, y, player):
    total = 0
    for dx, dy in _DIRECTIONS:
        count = 1
        open_ends = 0
        for sign in (1, -1):
            nx, ny = x + dx * sign, y + dy * sign
            while 0 <= nx < gomoku.BOARD and 0 <= ny < gomoku.BOARD and board[ny][nx] == player:
                count += 1
                nx += dx * sign
                ny += dy * sign
            if 0 <= nx < gomoku.BOARD and 0 <= ny < gomoku.BOARD and board[ny][nx] == gomoku.EMPTY:
                open_ends += 1
        if count >= 5:
            total += 10_000_000
        elif count == 4:
            total += (1_000_000 if open_ends == 2 else 100_000) if open_ends else 0
        elif count == 3:
            total += (50_000 if open_ends == 2 else 5_000) if open_ends else 0
        elif count == 2:
            total += (1_000 if open_ends == 2 else 100) if open_ends else 0
        elif open_ends:
            total += 20 if open_ends == 2 else 2
    return total


def _evaluate(board, root):
    """扫描所有五格窗口，评价双方成棋潜力；双方同处一个窗口则抵消。"""
    opponent = gomoku.P1 if root == gomoku.P2 else gomoku.P2
    values = (0, 2, 30, 400, 20_000, 2_000_000)
    score = 0
    for y in range(gomoku.BOARD):
        for x in range(gomoku.BOARD):
            for dx, dy in _DIRECTIONS:
                ex, ey = x + dx * 4, y + dy * 4
                if not (0 <= ex < gomoku.BOARD and 0 <= ey < gomoku.BOARD):
                    continue
                own = other = 0
                for i in range(5):
                    value = board[y + dy * i][x + dx * i]
                    own += value == root
                    other += value == opponent
                if own and not other:
                    score += values[own]
                elif other and not own:
                    score -= int(values[other] * 1.12)
    return score


def _play(board, x, y, player):
    return gomoku.apply_move(
        {"board": board, "winner": None}, {"x": x, "y": y}, player,
    )["board"]


def _wins(board, cell, player):
    x, y = cell
    new_board = _play(board, x, y, player)
    return bool(gomoku._five_in_row(new_board, x, y, player))


def _coord(cell):
    return {"x": cell[0], "y": cell[1]}
