"""Idea 社区蓝图包。

接入方式（由主代理在 app.py 中完成，本模块不自动注册）：
    from ideas import ideas_bp
    app.register_blueprint(ideas_bp)
"""

from .routes import ideas_bp

__all__ = ["ideas_bp"]
