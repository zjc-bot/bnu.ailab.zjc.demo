"""Idea 社区页面与 JSON API（Phase 1）。

接入方式（由主代理在 app.py 中完成，本模块不自动注册）：
    from ideas import ideas_bp
    app.register_blueprint(ideas_bp)

不 import app.py，避免蓝图注册时的循环导入；
login_required / CSRF 校验按 app.py 的实现等价重写。
"""

import hashlib
import hmac
import re
import secrets
from functools import wraps

from flask import (
    Blueprint, abort, jsonify, redirect, render_template, request, session, url_for,
)

from . import store

ideas_bp = Blueprint("ideas", __name__)

CATEGORIES = ("ai", "edu", "bio", "energy", "mat", "other")
VISIBILITIES = ("public", "friends", "private")
STATUSES = ("draft", "published", "archived")
MAX_TITLE = 200
MAX_CONTENT = 20000
MAX_COMMENT = 2000
MAX_TAGS = 8
MAX_TAG_LEN = 20


# ---------- 登录与 CSRF（与 app.py 等价） ----------

def _csrf():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def _check_csrf(token):
    expect = session.get("_csrf", "")
    return bool(expect) and bool(token) and hmac.compare_digest(expect, token)


def _api_csrf_ok():
    # 首选任务约定的 X-CSRF；兼容 app.py 现有 API 使用的 X-CSRF-Token。
    token = request.headers.get("X-CSRF") or request.headers.get("X-CSRF-Token", "")
    return _check_csrf(token)


def _login_required(api=False):
    """页面未登录跳转登录页；API 未登录返回 401 JSON。均校验账号仍为 active。"""

    def deco(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            uid = session.get("uid")
            user = store.get_user(uid) if uid else None
            if not uid or not user or user.get("status") != "active":
                session.clear()
                if api:
                    return jsonify(error="请先登录或登录已失效"), 401
                return redirect(url_for("login_page"))
            return fn(*args, **kwargs)

        return inner

    return deco


page_login_required = _login_required(False)
api_login_required = _login_required(True)


# ---------- 输入校验 ----------

def _normalize_tags(raw):
    if raw is None or raw == "":
        return ""
    if isinstance(raw, str):
        parts = [p.strip() for p in re.split(r"[,，]", raw)]
    elif isinstance(raw, (list, tuple)):
        parts = [str(p).strip() for p in raw]
    else:
        raise ValueError("标签格式不正确")
    parts = [p for p in parts if p]
    if len(parts) > MAX_TAGS:
        raise ValueError("标签最多 8 个")
    for tag in parts:
        if len(tag) > MAX_TAG_LEN:
            raise ValueError("单个标签最多 20 字")
    return ",".join(parts)


def _validate(data, partial=False):
    """校验并规范化写入字段；不合法时抛 ValueError。"""
    out = {}

    if "title" in data or not partial:
        title = str(data.get("title") or "").strip()
        if not 1 <= len(title) <= MAX_TITLE:
            raise ValueError("标题需为 1-200 字")
        out["title"] = title

    if "content" in data or not partial:
        content = str(data.get("content") or "").strip()
        if not 1 <= len(content) <= MAX_CONTENT:
            raise ValueError("正文需为 1-20000 字")
        out["content"] = content
        out["content_hash"] = hashlib.sha256(content.encode("utf-8")).hexdigest()

    if "category" in data or not partial:
        # 分类可自定义，不再做白名单校验（仅限制长度）。
        category = str(data.get("category") or "").strip()[:60] or None
        out["category"] = category

    if "tags" in data or not partial:
        out["tags"] = _normalize_tags(data.get("tags"))

    if "visibility" in data or not partial:
        visibility = str(data.get("visibility") or "public").strip()
        if visibility not in VISIBILITIES:
            raise ValueError("可见性不在允许范围内")
        out["visibility"] = visibility

    if "status" in data and str(data.get("status") or "") not in STATUSES:
        raise ValueError("状态不在允许范围内")
    if "status" in data:
        out["status"] = str(data["status"])

    return out




@ideas_bp.after_request
def _bust_archive_cache(resp):
    """idea 写操作成功后让公开页缓存立即失效，避免撤回残留窗口。"""
    if request.method in ("POST", "PUT", "DELETE", "PATCH") and resp.status_code < 400:
        try:
            from archive_api import invalidate_cache
            invalidate_cache()
        except Exception:
            pass
    return resp

def _forbidden():
    return jsonify(error="CSRF 校验失败"), 403


def _missing():
    return jsonify(error="未找到该 idea"), 404


# ---------- 页面路由 ----------

@ideas_bp.get("/ideas")
@page_login_required
def ideas_plaza():
    return render_template("ideas_plaza.html", csrf=_csrf(), categories=CATEGORIES)


@ideas_bp.get("/ideas/new")
@page_login_required
def idea_new():
    return render_template(
        "idea_form.html",
        idea=None,
        csrf=_csrf(),
        categories=CATEGORIES,
        visibilities=VISIBILITIES,
    )


@ideas_bp.get("/ideas/<int:idea_id>")
@page_login_required
def idea_detail(idea_id):
    uid = session["uid"]
    idea = store.get_idea(idea_id)
    if not idea or not store.can_view_idea(idea_id, uid):
        abort(404)
    return render_template(
        "idea_detail.html",
        idea=idea,
        comments=store.list_comments(idea_id, uid),
        favorited=store.user_has_favorited(idea_id, uid),
        liked=store.user_has_liked(idea_id, uid),
        can_edit=idea["author_id"] == uid,
        csrf=_csrf(),
    )


# ---------- JSON API ----------

@ideas_bp.post("/api/ideas")
@api_login_required
def api_idea_create():
    if not _api_csrf_ok():
        return _forbidden()
    try:
        payload = _validate(request.get_json(silent=True) or {})
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    # 发布即公开：默认 published，否则列表只查 published 会看不到刚发布的想法。
    # 显式传 draft 时仍可存草稿（前端表单当前不提供该选项）。
    payload.setdefault("status", "published")
    idea_id = store.create_idea(session["uid"], payload)
    return jsonify(id=idea_id, idea=store.get_idea(idea_id)), 201


@ideas_bp.get("/api/ideas")
@api_login_required
def api_idea_list():
    items, total = store.list_ideas(
        session["uid"],
        category=request.args.get("category") or None,
        tag=request.args.get("tag") or None,
        q=request.args.get("q") or None,
        author_id=request.args.get("author", type=int),
        page=request.args.get("page", 1, type=int),
        size=request.args.get("size", 20, type=int),
    )
    return jsonify(items=items, total=total)


@ideas_bp.get("/api/ideas/featured")
@api_login_required
def api_idea_featured():
    return jsonify(items=store.featured_by_category())


@ideas_bp.get("/api/tags")
@api_login_required
def api_tag_list():
    """标签字典：关键词搜索 + 置顶优先，供管理与筛选共用。"""
    return jsonify(items=store.list_tags(q=request.args.get("q") or None))


@ideas_bp.get("/api/ideas/<int:idea_id>")
@api_login_required
def api_idea_get(idea_id):
    uid = session["uid"]
    idea = store.get_idea(idea_id)
    if not idea or not store.can_view_idea(idea_id, uid):
        return _missing()
    return jsonify(
        idea=idea,
        comments=store.list_comments(idea_id, uid),
        favorited=store.user_has_favorited(idea_id, uid),
        liked=store.user_has_liked(idea_id, uid),
        can_edit=idea["author_id"] == uid,
    )


@ideas_bp.put("/api/ideas/<int:idea_id>")
@api_login_required
def api_idea_update(idea_id):
    if not _api_csrf_ok():
        return _forbidden()
    uid = session["uid"]
    idea = store.get_idea(idea_id)
    if not idea:
        return _missing()
    if idea["author_id"] != uid:
        return jsonify(error="无权修改"), 403
    try:
        payload = _validate(request.get_json(silent=True) or {}, partial=True)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if not payload:
        return jsonify(error="没有可更新的字段"), 400
    if not store.update_idea(idea_id, uid, payload):
        return jsonify(error="更新失败"), 400
    return jsonify(ok=True, idea=store.get_idea(idea_id))


@ideas_bp.delete("/api/ideas/<int:idea_id>")
@api_login_required
def api_idea_delete(idea_id):
    if not _api_csrf_ok():
        return _forbidden()
    uid = session["uid"]
    idea = store.get_idea(idea_id)
    if not idea:
        return _missing()
    if idea["author_id"] != uid:
        return jsonify(error="无权删除"), 403
    store.delete_idea(idea_id, uid)
    return jsonify(ok=True)


@ideas_bp.post("/api/ideas/<int:idea_id>/favorite")
@api_login_required
def api_idea_favorite(idea_id):
    if not _api_csrf_ok():
        return _forbidden()
    uid = session["uid"]
    if not store.can_view_idea(idea_id, uid):
        return _missing()
    state = store.toggle_favorite(idea_id, uid)
    if state is None:
        return _missing()
    return jsonify(favorited=state)


@ideas_bp.post("/api/ideas/<int:idea_id>/like")
@api_login_required
def api_idea_like(idea_id):
    if not _api_csrf_ok():
        return _forbidden()
    uid = session["uid"]
    if not store.can_view_idea(idea_id, uid):
        return _missing()
    state = store.toggle_like(idea_id, uid)
    if state is None:
        return _missing()
    return jsonify(liked=state)


@ideas_bp.get("/api/ideas/<int:idea_id>/comments")
@api_login_required
def api_idea_comments(idea_id):
    uid = session["uid"]
    if not store.can_view_idea(idea_id, uid):
        return _missing()
    return jsonify(items=store.list_comments(idea_id, uid))


@ideas_bp.post("/api/ideas/<int:idea_id>/comments")
@api_login_required
def api_idea_comment_add(idea_id):
    if not _api_csrf_ok():
        return _forbidden()
    uid = session["uid"]
    if not store.can_view_idea(idea_id, uid):
        return _missing()
    data = request.get_json(silent=True) or {}
    content = str(data.get("content") or "").strip()
    if not 1 <= len(content) <= MAX_COMMENT:
        return jsonify(error="评论需为 1-2000 字"), 400
    parent_id = data.get("parent_id")
    if parent_id in (None, ""):
        parent_id = None
    else:
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            return jsonify(error="parent_id 格式不正确"), 400
    comment_id = store.add_comment(idea_id, uid, content, parent_id)
    if comment_id is None:
        return jsonify(error="评论失败：父评论不存在或创意不可见"), 400
    return jsonify(id=comment_id), 201
