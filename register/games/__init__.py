"""对战游戏子系统。

当前进度（Phase 2 骨架）：
  - Socket.IO 事件层：好友邀请、加入房间、落子广播、认输
  - 房间管理：内存态、服务端权威回合校验
  - 规则引擎：rules/ 目录预留，Phase 3 接入五子棋

设计原则（总纲 §8）：好友对战 PvP 是主线；AI 对手是可选增强。
"""

from flask_socketio import SocketIO

socketio = SocketIO(cors_allowed_origins=[], logger=False, engineio_logger=False)


def init_games(app):
    """把 Socket.IO 绑定到 Flask app 并注册事件。"""
    from . import events
    socketio.init_app(app)
    events.register(socketio)
    return socketio
