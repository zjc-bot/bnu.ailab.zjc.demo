"""规则引擎分发：按游戏名取初始状态与落子函数。

服务端权威：棋盘状态只由这里派生，客户端提交的数据仅作为着法输入。
"""

from . import gomoku

# game 名 -> 规则模块
_RULES = {
    "gomoku": gomoku,
}

# 尚未实现规则的游戏的初始状态（模板占位，不允许落子）
_PLACEHOLDER = {
    "chess": {},
    "xiangqi": {},
    "uno": {},
}


class GameRuleError(Exception):
    pass


def supported(game):
    return game in _RULES


def initial_state(game):
    if game in _RULES:
        return _RULES[game].initial_state()
    if game in _PLACEHOLDER:
        return {}
    raise GameRuleError(f"未知游戏：{game}")


def apply_move(game, state, move, player):
    """返回新 state；非法着法抛 RuleError/GameRuleError。"""
    if game not in _RULES:
        raise GameRuleError(f"游戏 {game} 的规则尚未接入，拒绝落子")
    try:
        return _RULES[game].apply_move(state, move, player)
    except gomoku.RuleError:
        raise
    except Exception as e:  # 规则层异常一律拒绝，绝不退回采信客户端
        raise GameRuleError(f"规则校验失败：{type(e).__name__}")
