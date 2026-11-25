"""学习分享室公开数据只读 API（蓝图，app.py 已注册，无需改动 app.py）。

  - 纯只读、无需登录，返回契约中的 4 个字段：items / stats / tags / source；
  - 数据由 archive_data.load_public_ideas() 提供；DB 不可用时返回
    source='static' 的空结构（前端显示空态，不再回退写死示例）；
  - 内存缓存 TTL 30 秒；invalidate_cache() 供 idea 写操作后主动失效。
"""

import threading
import time

from flask import Blueprint, jsonify

from archive_data import load_public_ideas

archive_bp = Blueprint("archive_api", __name__)

_TTL = 30.0  # 秒
_cache = {"value": None, "expires": 0.0}
_lock = threading.Lock()


def invalidate_cache():
    """清空缓存；供主代理在 idea 写操作后接线调用（本模块不负责接线）。"""
    with _lock:
        _cache["value"] = None
        _cache["expires"] = 0.0


def _cached_payload():
    """TTL 缓存；monotonic 避免系统时间调整影响，双重检查避免并发重复查库。"""
    now = time.monotonic()
    cached = _cache["value"]
    if cached is not None and now < _cache["expires"]:
        return cached

    with _lock:
        now = time.monotonic()
        cached = _cache["value"]
        if cached is not None and now < _cache["expires"]:
            return cached
        payload = load_public_ideas()
        _cache["value"] = payload
        _cache["expires"] = now + _TTL
        return payload


@archive_bp.get("/api/archive.json")
def archive_json():
    return jsonify(**_cached_payload())
