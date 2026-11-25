"""研究成果数据只读 API（新增蓝图，纯增量，不改动 app.py）。

接入方式：在 app.py 中
    from archive_api import archive_bp
    app.register_blueprint(archive_bp)
（由主代理决定是否接入，本次不自动改 app.py。）

说明：
  - 纯只读、无需登录，公开展示数据与页面一致；
  - DB 不可用时 load_achievements() 返回 []，source 标记为 "static"，
    由调用方回退前端静态数据；
  - 简单内存缓存 TTL 60 秒，避免频繁查库。
"""

import threading
import time

from flask import Blueprint, jsonify

from archive_data import load_achievements

archive_bp = Blueprint("archive_api", __name__)

_TTL = 60.0  # 秒
_cache = {"value": None, "expires": 0.0}
_lock = threading.Lock()


def _cached_items():
    """TTL 缓存；用 monotonic 避免系统时间调整影响。"""
    now = time.monotonic()
    cached = _cache["value"]
    if cached is not None and now < _cache["expires"]:
        return cached

    with _lock:
        # 双重检查：等锁期间可能已被其他线程刷新。
        now = time.monotonic()
        cached = _cache["value"]
        if cached is not None and now < _cache["expires"]:
            return cached
        items = load_achievements()
        _cache["value"] = items
        _cache["expires"] = now + _TTL
        return items


@archive_bp.get("/api/archive.json")
def archive_json():
    items = _cached_items()
    return jsonify(items=items, source="mysql" if items else "static")
