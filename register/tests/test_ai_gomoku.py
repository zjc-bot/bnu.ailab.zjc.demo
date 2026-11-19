"""五子棋服务端 AI 的单元测试（不连数据库、不启服务）。"""

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from games.ai import DIFFICULTIES, choose_move  # noqa: E402
from games.rules import gomoku  # noqa: E402


def empty_state():
    return gomoku.initial_state()


def test_all_difficulty_levels_exist():
    assert DIFFICULTIES == {"easy", "normal", "hard"}


def test_ai_opens_at_center():
    move = choose_move(empty_state(), "easy", gomoku.P2, rng=random.Random(1))
    assert move == {"x": gomoku.BOARD // 2, "y": gomoku.BOARD // 2}


def test_ai_takes_immediate_win():
    state = empty_state()
    for x in range(4):
        state["board"][0][x] = gomoku.P2
    move = choose_move(state, "easy", gomoku.P2, rng=random.Random(2))
    assert move == {"x": 4, "y": 0}


def test_ai_blocks_opponent_immediate_win():
    state = empty_state()
    for x in range(4):
        state["board"][0][x] = gomoku.P1
    move = choose_move(state, "normal", gomoku.P2, rng=random.Random(3))
    assert move == {"x": 4, "y": 0}


def test_hard_move_is_legal():
    state = empty_state()
    state["board"][7][7] = gomoku.P1
    move = choose_move(state, "hard", gomoku.P2, rng=random.Random(4))
    assert isinstance(move, dict)
    x, y = move["x"], move["y"]
    assert 0 <= x < gomoku.BOARD and 0 <= y < gomoku.BOARD
    assert state["board"][y][x] == gomoku.EMPTY
    # AI 返回的着法仍必须通过公共规则层校验。
    out = gomoku.apply_move(state, move, gomoku.P2)
    assert out["board"][y][x] == gomoku.P2


def test_unknown_difficulty_rejected():
    with pytest.raises(ValueError, match="未知 AI 难度"):
        choose_move(empty_state(), "impossible", gomoku.P2)
