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
    Blueprint, abort, jsonify, make_response, redirect, render_template, request, session, url_for,
)

from . import store
from .constants import CATEGORIES, CATEGORY_LABELS

ideas_bp = Blueprint("ideas", __name__)

VISIBILITIES = ("public", "friends", "private")
STATUSES = ("draft", "published", "archived")
MAX_TITLE = 200
MAX_CONTENT = 20000
MAX_COMMENT = 2000
MAX_TAGS = 8
MAX_TAG_LEN = 20
MAX_CATEGORY = 30


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
        if not all(isinstance(p, str) for p in raw):
            raise ValueError("标签格式不正确")
        parts = [part.strip() for value in raw
                 for part in re.split(r"[,，]", value)]
    else:
        raise ValueError("标签格式不正确")
    parts = [p for p in parts if p]
    unique = []
    seen = set()
    for tag in parts:
        if len(tag) > MAX_TAG_LEN:
            raise ValueError("单个标签最多 20 字")
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(tag)
    if len(unique) > MAX_TAGS:
        raise ValueError("标签最多 8 个")
    return ",".join(unique)


def _text(value, name):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(name + "需为字符串")
    return value.strip()


def _json_object():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("请求体需为 JSON 对象")
    return data


def _validate(data, partial=False):
    """校验并规范化写入字段；不合法时抛 ValueError。"""
    out = {}

    if "title" in data or not partial:
        title = _text(data.get("title"), "标题")
        if not 1 <= len(title) <= MAX_TITLE:
            raise ValueError("标题需为 1-200 字")
        out["title"] = title

    if "content" in data or not partial:
        content = _text(data.get("content"), "正文")
        if not 1 <= len(content) <= MAX_CONTENT:
            raise ValueError("正文需为 1-20000 字")
        out["content"] = content
        out["content_hash"] = hashlib.sha256(content.encode("utf-8")).hexdigest()

    if "category" in data or not partial:
        value = data.get("category")
        category = _text("other" if value in (None, "") else value, "分类").lower()
        if category not in CATEGORIES:
            raise ValueError("分类需为 ai/edu/bio/energy/math/other 之一")
        out["category"] = category

    if "tags" in data or not partial:
        out["tags"] = _normalize_tags(data.get("tags"))

    if "visibility" in data or not partial:
        value = data.get("visibility")
        visibility = _text("public" if value in (None, "") else value, "可见性")
        if visibility not in VISIBILITIES:
            raise ValueError("可见性不在允许范围内")
        out["visibility"] = visibility

    if "status" in data:
        status = _text(data.get("status"), "状态")
        if status not in STATUSES:
            raise ValueError("状态不在允许范围内")
        out["status"] = status

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
        categories=[{"value": code, "label": CATEGORY_LABELS[code]} for code in CATEGORIES],
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
        can_edit=idea["author_id"] == uid and idea.get("moderation_state") == "active",
        csrf=_csrf(),
    )


@ideas_bp.get("/ideas/<int:idea_id>/edit")
@page_login_required
def idea_edit(idea_id):
    uid = session["uid"]
    idea = store.get_idea(idea_id)
    if not idea or idea["author_id"] != uid:
        abort(404)
    return render_template(
        "idea_form.html",
        idea=idea,
        csrf=_csrf(),
        categories=[{"value": code, "label": CATEGORY_LABELS[code]} for code in CATEGORIES],
        visibilities=VISIBILITIES,
        read_only=idea.get("moderation_state") != "active",
    )

@ideas_bp.get("/profile")
@page_login_required
def content_profile():
    initial_view = "favorites" if request.args.get("view") == "favorites" else "owned"
    response = make_response(render_template(
        "content_profile.html", csrf=_csrf(), initial_view=initial_view,
    ))
    response.headers["Cache-Control"] = "private, no-store"
    return response


@ideas_bp.get("/api/profile/summary")
@api_login_required
def api_profile_summary():
    response = jsonify(store.profile_summary(session["uid"]))
    response.headers["Cache-Control"] = "private, no-store"
    return response


@ideas_bp.get("/api/profile/ideas")
@api_login_required
def api_profile_ideas():
    items, total = store.list_owned_ideas(
        session["uid"], q=request.args.get("q") or None,
        category=request.args.get("category") or None,
        tag=request.args.get("tag") or None,
        status=request.args.get("status") or None,
        sort=request.args.get("sort") or "updated",
        page=request.args.get("page", 1, type=int),
        size=request.args.get("size", 20, type=int),
    )
    response = jsonify(items=items, total=total)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@ideas_bp.get("/api/profile/favorites")
@api_login_required
def api_profile_favorites():
    items, total, unavailable = store.list_favorited_ideas(
        session["uid"], q=request.args.get("q") or None,
        category=request.args.get("category") or None,
        tag=request.args.get("tag") or None,
        sort=request.args.get("sort") or "new",
        page=request.args.get("page", 1, type=int),
        size=request.args.get("size", 20, type=int),
        include_unavailable=not any(request.args.get(k) for k in ("q", "category", "tag")),    )
    response = jsonify(items=items, total=total, unavailable_count=unavailable)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@ideas_bp.post("/api/ideas")
@api_login_required
def api_idea_create():
    if not _api_csrf_ok():
        return _forbidden()
    try:
        payload = _validate(_json_object())
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    # 发布即公开：默认 published，否则列表只查 published 会看不到刚发布的想法。
    # 显式传 draft 时仍可存草稿（前端表单当前不提供该选项）。
    payload.setdefault("status", "published")
    idea_id = store.create_idea(session["uid"], payload)
    if idea_id is None:
        return jsonify(error="账号不可用，请重新登录"), 401
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
        sort=request.args.get("sort") or "new",
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
    return jsonify(items=store.list_tags(
        q=request.args.get("q") or None,
        viewer_id=session["uid"],
    ))


@ideas_bp.get("/api/categories")
@api_login_required
def api_category_list():
    return jsonify(items=[
        {"value": code, "label": CATEGORY_LABELS[code]} for code in CATEGORIES
    ])


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
        can_edit=idea["author_id"] == uid and idea.get("moderation_state") == "active",
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
        raw = _json_object()
        payload = _validate(raw, partial=True)
        expected_version = raw.get("row_version")
        if (isinstance(expected_version, bool)
                or not isinstance(expected_version, (int, str))
                or not str(expected_version).isdigit()):
            return jsonify(error="row_version 需为非负整数"), 400
        expected_version = int(expected_version)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if not payload:
        return jsonify(error="没有可更新的字段"), 400
    result = store.update_idea(idea_id, uid, payload, expected_version)
    if result == "conflict":
        return jsonify(error="内容已被修改，请刷新后重试", code="conflict"), 409
    if result == "revoked":
        return jsonify(error="该 idea 已被撤销，仅可查看"), 403
    if not result:
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
    result = store.delete_idea(idea_id, uid)
    if result == "revoked":
        return jsonify(error="该 idea 已被撤销，不能删除"), 403
    if not result:
        return jsonify(error="删除失败"), 400
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
    try:
        data = _json_object()
        content = _text(data.get("content"), "评论")
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
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
