"""服务端游戏 AI。当前提供五子棋三档本地策略，无外部 API 依赖。"""

from .gomoku import DIFFICULTIES, choose_move

__all__ = ["DIFFICULTIES", "choose_move"]
