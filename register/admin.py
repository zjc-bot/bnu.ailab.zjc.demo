"""管理后台：注册数据与访问统计。

与前台完全隔离：
  - 独立表 admin_user，独立 session 键 aid
  - 独立装饰器 admin_required
  - 独立 CSRF token
"""

import csv
import hashlib
import hmac
import html
import io
import os
import re
import secrets
import threading
import time
from datetime import date, timedelta

from flask import (
    Blueprint, Response, abort, current_app, make_response, redirect, render_template,
    request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import db
import mailer
from ideas import moderation as idea_moderation

bp = Blueprint("admin", __name__, url_prefix="/admin")

SITE_URL = os.environ.get("SITE_URL", "http://127.0.0.1:8082").rstrip("/")
RESET_TTL = 30

LOGIN_LIMIT = 5
LOGIN_WINDOW = 600
_fails = {}

# 二次认证挑战与后台会话只存服务端；Cookie 仅持有随机挑战/会话标识。
TOTP_TTL = 300
TOTP_ATTEMPT_LIMIT = 5
TOTP_SEND_LIMIT = 5
TOTP_SEND_WINDOW = 3600
MAX_A2FA_CHALLENGES = 1000
MAX_A2FA_SEND_KEYS = 1000
MAX_ADMIN_SESSIONS = 1000
_a2fa_challenges = {}
_a2fa_sends = {}
_admin_sessions = {}
_state_lock = threading.RLock()


# ---------- 工具 ----------

def _ip():
    return request.remote_addr or "unknown"


def _csrf():
    if "_acsrf" not in session:
        session["_acsrf"] = secrets.token_urlsafe(32)
    return session["_acsrf"]


def _check_csrf(token):
    expect = session.get("_acsrf", "")
    return bool(expect) and bool(token) and hmac.compare_digest(expect, token)


def _clear_admin_auth():
    sid = session.pop("a_sid", None)
    if sid:
        _admin_sessions.pop(sid, None)
    for key in ("aid", "a2fa", "aname"):
        session.pop(key, None)


def _revoke_admin_state(aid):
    with _state_lock:
        for sid, rec in list(_admin_sessions.items()):
            if rec["aid"] == aid:
                _admin_sessions.pop(sid, None)
        for token, challenge in list(_a2fa_challenges.items()):
            if challenge["aid"] == aid:
                _a2fa_challenges.pop(token, None)


def _admin_session_valid():
    sid = session.get("a_sid")
    rec = _admin_sessions.get(sid)
    if (not sid or not rec or rec["expires"] <= time.time()
            or rec["aid"] != session.get("aid")):
        _clear_admin_auth()
        return False
    return True


def _issue_admin_session(aid, name):
    _clear_admin_auth()
    now = time.time()
    for key, rec in list(_admin_sessions.items()):
        if rec["expires"] <= now:
            _admin_sessions.pop(key, None)
    while len(_admin_sessions) >= MAX_ADMIN_SESSIONS:
        _admin_sessions.pop(next(iter(_admin_sessions)))
    sid = secrets.token_urlsafe(32)
    lifetime = current_app.permanent_session_lifetime.total_seconds()
    _admin_sessions[sid] = {"aid": aid, "expires": now + lifetime}
    session["a_sid"] = sid
    session["aid"] = aid
    session["a2fa"] = True
    session["aname"] = name
    session.permanent = True


def admin_required(fn):
    from functools import wraps

    @wraps(fn)
    def inner(*a, **kw):
        if not _admin_session_valid():
            return redirect(url_for("admin.login"))
        return fn(*a, **kw)

    return inner


def _locked(ip):
    rec = _fails.get(ip)
    if not rec:
        return True
    if time.time() - rec[1] > LOGIN_WINDOW:
        _fails.pop(ip, None)
        return True
    return rec[0] < LOGIN_LIMIT


def _note_fail(ip):
    rec = _fails.get(ip)
    if not rec or time.time() - rec[1] > LOGIN_WINDOW:
        _fails[ip] = [1, time.time()]
    else:
        rec[0] += 1


def _totp_allowed(ip):
    rec = _a2fa_sends.get(ip)
    if not rec or time.time() - rec[1] > TOTP_SEND_WINDOW:
        return True
    return rec[0] < TOTP_SEND_LIMIT


def _note_totp(ip):
    rec = _a2fa_sends.get(ip)
    if not rec or time.time() - rec[1] > TOTP_SEND_WINDOW:
        _a2fa_sends[ip] = [1, time.time()]
    else:
        rec[0] += 1


def _sweep_challenges(now):
    for key, rec in list(_a2fa_challenges.items()):
        if rec["expires"] <= now:
            _a2fa_challenges.pop(key, None)
    while len(_a2fa_challenges) >= MAX_A2FA_CHALLENGES:
        _a2fa_challenges.pop(next(iter(_a2fa_challenges)))


def _create_challenge(aid, purpose, target, name, ip):
    now = time.time()
    with _state_lock:
        _sweep_challenges(now)
        token = secrets.token_urlsafe(32)
        code = f"{secrets.randbelow(1000000):06d}"
        digest = hashlib.sha256((token + code).encode("ascii")).hexdigest()
        _a2fa_challenges[token] = {
            "aid": aid, "purpose": purpose, "target": target, "name": name,
            "ip": ip, "code_hash": digest, "expires": now + TOTP_TTL, "attempts": 0,
        }
    return token, code


def _get_challenge():
    token = session.get("a2fa_challenge")
    rec = _a2fa_challenges.get(token)
    if not token or not rec or rec["ip"] != _ip():
        session.pop("a2fa_challenge", None)
        return None, None
    return token, rec


def _clear_challenge():
    token = session.pop("a2fa_challenge", None)
    if token:
        _a2fa_challenges.pop(token, None)


def _send_challenge(aid, purpose, target, name, ip):
    with _state_lock:
        now = time.time()
        for key, rec in list(_a2fa_sends.items()):
            if now - rec[1] > TOTP_SEND_WINDOW:
                _a2fa_sends.pop(key, None)
        while len(_a2fa_sends) >= MAX_A2FA_SEND_KEYS:
            _a2fa_sends.pop(next(iter(_a2fa_sends)))
        if not _totp_allowed(ip):
            return None, "验证码发送过于频繁，请稍后再试"
        token, code = _create_challenge(aid, purpose, target, name, ip)
        _note_totp(ip)
    try:
        mailer.send_code(
            target, code, ttl_minutes=TOTP_TTL // 60,
            purpose="admin" if purpose == "login" else purpose,
        )
    except Exception:
        with _state_lock:
            _a2fa_challenges.pop(token, None)
        current_app.logger.exception("后台二次认证邮件发送失败 purpose=%s", purpose)
        return None, "验证码邮件发送失败，请联系管理员检查邮件配置"
    session["a2fa_challenge"] = token
    session["_acsrf"] = secrets.token_urlsafe(32)
    return token, None


def _consume_challenge(token, challenge, code):
    digest = (hashlib.sha256((token + code).encode("ascii")).hexdigest()
              if re.fullmatch(r"[0-9]{6}", code) else "")
    with _state_lock:
        if _a2fa_challenges.get(token) is not challenge:
            return "missing", challenge
        if challenge["expires"] <= time.time():
            _a2fa_challenges.pop(token, None)
            session.pop("a2fa_challenge", None)
            return "expired", challenge
        if not digest or not hmac.compare_digest(challenge["code_hash"], digest):
            challenge["attempts"] += 1
            if challenge["attempts"] >= TOTP_ATTEMPT_LIMIT:
                _a2fa_challenges.pop(token, None)
                session.pop("a2fa_challenge", None)
                return "locked", challenge
            return "wrong", challenge
        _a2fa_challenges.pop(token, None)
        session.pop("a2fa_challenge", None)
        return "ok", challenge


# ---------- 查询 ----------

def q_one(sql, params=()):
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def q_all(sql, params=()):
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


DEFAULT_DAYS = 14
MAX_DAYS = 30


def _parse_range():
    """解析日期范围，限制跨度不超过 MAX_DAYS 天，且不晚于今天。"""
    today = date.today()
    to_s = (request.args.get("to") or "").strip()
    from_s = (request.args.get("from") or "").strip()

    try:
        d_to = date.fromisoformat(to_s) if to_s else today
    except ValueError:
        d_to = today
    try:
        d_from = (
            date.fromisoformat(from_s) if from_s
            else d_to - timedelta(days=DEFAULT_DAYS - 1)
        )
    except ValueError:
        d_from = d_to - timedelta(days=DEFAULT_DAYS - 1)

    if d_to > today:
        d_to = today
    if d_from > d_to:
        d_from = d_to
    if (d_to - d_from).days + 1 > MAX_DAYS:
        d_from = d_to - timedelta(days=MAX_DAYS - 1)
    return d_from, d_to


def summary(d_from, d_to):
    span = {"from": d_from.isoformat(), "to": d_to.isoformat(),
            "days": (d_to - d_from).days + 1}

    total = q_one("SELECT COUNT(*) AS c FROM app_user")["c"]
    today = q_one("SELECT COUNT(*) AS c FROM app_user WHERE DATE(created_at)=CURDATE()")["c"]
    in_range = q_one(
        "SELECT COUNT(*) AS c FROM app_user WHERE DATE(created_at) BETWEEN %s AND %s",
        (d_from, d_to),
    )["c"]

    trend_raw = q_all(
        "SELECT DATE(created_at) AS d, COUNT(*) AS c FROM app_user "
        "WHERE DATE(created_at) BETWEEN %s AND %s GROUP BY d",
        (d_from, d_to),
    )
    tmap = {r["d"]: r["c"] for r in trend_raw}
    trend = [
        {
            "d": (d_from + timedelta(days=i)).strftime("%m-%d"),
            "c": tmap.get(d_from + timedelta(days=i), 0),
        }
        for i in range(span["days"])
    ]

    by_major = q_all(
        "SELECT IFNULL(s.major,'未知') AS major, COUNT(*) AS c "
        "FROM app_user u LEFT JOIN student s ON s.student_no=u.student_no "
        "GROUP BY s.major ORDER BY c DESC"
    )
    by_dorm = q_all(
        "SELECT IFNULL(s.dorm_room,'未知') AS dorm, COUNT(*) AS c "
        "FROM app_user u LEFT JOIN student s ON s.student_no=u.student_no "
        "GROUP BY s.dorm_room ORDER BY c DESC LIMIT 12"
    )

    hours_raw = q_all(
        "SELECT HOUR(created_at) AS h, COUNT(*) AS c FROM access_log "
        "WHERE DATE(created_at) BETWEEN %s AND %s GROUP BY h",
        (d_from, d_to),
    )
    hmap = {r["h"]: r["c"] for r in hours_raw}
    hours = [{"h": i, "c": hmap.get(i, 0)} for i in range(24)]

    pv = q_one(
        "SELECT COUNT(*) AS c FROM access_log WHERE DATE(created_at) BETWEEN %s AND %s",
        (d_from, d_to),
    )["c"]
    pv_today = q_one(
        "SELECT COUNT(*) AS c FROM access_log WHERE DATE(created_at)=CURDATE()"
    )["c"]
    uv = q_one(
        "SELECT COUNT(DISTINCT ip) AS c FROM access_log "
        "WHERE DATE(created_at) BETWEEN %s AND %s",
        (d_from, d_to),
    )["c"]
    uv_today = q_one(
        "SELECT COUNT(DISTINCT ip) AS c FROM access_log WHERE DATE(created_at)=CURDATE()"
    )["c"]

    hot_paths = q_all(
        "SELECT path, COUNT(*) AS c FROM access_log "
        "WHERE DATE(created_at) BETWEEN %s AND %s "
        "GROUP BY path ORDER BY c DESC LIMIT 8",
        (d_from, d_to),
    )

    # AI 用量
    ai_today = q_one(
        "SELECT IFNULL(SUM(calls),0) AS c FROM ai_usage WHERE day=CURDATE()"
    )["c"]
    ai_total = q_one("SELECT IFNULL(SUM(calls),0) AS c FROM ai_usage")["c"]
    ai_people = q_one("SELECT COUNT(DISTINCT user_id) AS c FROM ai_usage")["c"]
    byok = q_one("SELECT COUNT(*) AS c FROM user_ai_key")["c"]

    return dict(
        total=total, today=today, week=in_range, span=span,
        trend=trend, by_major=by_major, by_dorm=by_dorm,
        pv=pv, pv_today=pv_today, uv=uv, uv_today=uv_today,
        hot_paths=hot_paths, hours=hours,
        ai_today=ai_today, ai_total=ai_total, ai_people=ai_people, byok=byok,
    )


# ---------- 登录 ----------

@bp.route("/login", methods=["GET"])
def login():
    if _admin_session_valid():
        return redirect(url_for("admin.dash"))
    if not session.get("a2fa_challenge"):
        _clear_admin_auth()
    return render_template("admin/login.html", csrf=_csrf())


@bp.route("/login", methods=["POST"])
def login_submit():
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)

    ip = _ip()
    if not _locked(ip):
        return render_template("admin/login.html", csrf=_csrf(),
                               err="尝试次数过多，请 10 分钟后再试")

    u = (request.form.get("username") or "").strip()
    p = request.form.get("password") or ""
    row = q_one(
        "SELECT id, username, password_hash, display_name FROM admin_user WHERE username=%s",
        (u,),
    )
    if not row or not check_password_hash(row["password_hash"], p):
        _note_fail(ip)
        return render_template("admin/login.html", csrf=_csrf(), err="账号或密码错误")

    _fails.pop(ip, None)
    try:
        erow = q_one("SELECT email FROM admin_user WHERE id=%s", (row["id"],))
        email = (erow.get("email") or "").strip() if erow else ""
    except Exception:
        current_app.logger.exception("后台二次认证邮箱查询失败 aid=%s", row["id"])
        return render_template("admin/login.html", csrf=_csrf(),
                               err="二次认证暂不可用，请联系管理员检查数据库")
    if not email:
        current_app.logger.error("管理员未配置二次认证邮箱，拒绝登录 aid=%s", row["id"])
        return render_template("admin/login.html", csrf=_csrf(),
                               err="管理员尚未配置二次认证邮箱，暂时无法登录")

    name = row["display_name"] or row["username"]
    session.clear()
    session.permanent = True
    _, err = _send_challenge(row["id"], "login", email, name, ip)
    if err:
        return render_template("admin/login.html", csrf=_csrf(), err=err)
    return redirect(url_for("admin.verify_2fa"))


@bp.route("/verify", methods=["GET"])
def verify_2fa():
    if _admin_session_valid():
        return redirect(url_for("admin.dash"))
    _, challenge = _get_challenge()
    if not challenge or challenge["expires"] <= time.time():
        _clear_challenge()
        return redirect(url_for("admin.login"))
    return render_template(
        "admin/verify.html", csrf=_csrf(),
        aname=challenge["name"], purpose=challenge["purpose"],
        target=challenge["target"],
    )


@bp.route("/verify", methods=["POST"])
def verify_2fa_submit():
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)
    token, challenge = _get_challenge()
    if not challenge:
        return redirect(url_for("admin.login"))

    code = (request.form.get("code") or "").strip()
    status, challenge = _consume_challenge(token, challenge, code)
    if status == "missing":
        return redirect(url_for("admin.login"))
    if status == "expired":
        return render_template(
            "admin/verify.html", csrf=_csrf(), aname=challenge["name"],
            purpose=challenge["purpose"], target=challenge["target"],
            err="验证码已过期，请重新登录",
        )
    if status == "locked":
        return render_template(
            "admin/verify.html", csrf=_csrf(), aname=challenge["name"],
            purpose=challenge["purpose"], target=challenge["target"],
            err="验证码错误次数过多，请重新登录",
        )
    if status == "wrong":
        return render_template(
            "admin/verify.html", csrf=_csrf(), aname=challenge["name"],
            purpose=challenge["purpose"], target=challenge["target"],
            err="验证码不正确，请重试",
        )

    ip = _ip()
    if challenge["purpose"] == "email":
        if not _admin_session_valid() or session.get("aid") != challenge["aid"]:
            return redirect(url_for("admin.login"))
        try:
            with db.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE admin_user SET email=%s WHERE id=%s",
                                (challenge["target"], challenge["aid"]))
                    conn.commit()
        except Exception:
            current_app.logger.exception("二次认证邮箱确认写入失败 aid=%s", challenge["aid"])
            return redirect(url_for("admin.account", e="邮箱确认失败，旧邮箱未改变"))
        return redirect(url_for("admin.account", ok="二次认证邮箱已确认并更新"))

    if challenge["purpose"] != "login":
        current_app.logger.error("未知后台二次认证用途")
        return redirect(url_for("admin.login"))
    try:
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE admin_user SET last_login_at=NOW(), last_login_ip=%s WHERE id=%s",
                    (ip, challenge["aid"]),
                )
                conn.commit()
    except Exception:
        current_app.logger.exception("后台登录记录写入失败 aid=%s", challenge["aid"])
        session.clear()
        return render_template("admin/login.html", csrf=_csrf(),
                               err="登录暂不可用，请稍后重试")
    session.clear()
    _issue_admin_session(challenge["aid"], challenge["name"])
    session["_acsrf"] = secrets.token_urlsafe(32)
    return redirect(url_for("admin.dash"))


@bp.route("/logout", methods=["POST"])
def logout():
    if _check_csrf(request.form.get("csrf", "")):
        sid = session.pop("a_sid", None)
        if sid:
            _admin_sessions.pop(sid, None)
        session.clear()
    return redirect(url_for("admin.login"))


# ---------- 仪表盘 ----------

@bp.route("/")
@admin_required
def dash():
    d_from, d_to = _parse_range()
    today = date.today()

    presets = [
        {"label": "近 7 天", "days": 7,
         "from": (d_to - timedelta(days=6)).isoformat(), "to": d_to.isoformat()},
        {"label": "近 14 天", "days": 14,
         "from": (d_to - timedelta(days=13)).isoformat(), "to": d_to.isoformat()},
        {"label": "近 30 天", "days": 30,
         "from": (d_to - timedelta(days=29)).isoformat(), "to": d_to.isoformat()},
    ]
    active_days = (d_to - d_from).days + 1

    # 二次认证提示：检测当前管理员是否已配邮箱（列不存在时视为未配置）
    try:
        me = q_one("SELECT email FROM admin_user WHERE id=%s", (session.get("aid"),))
        twofa_missing = not bool(me and (me.get("email") or "").strip())
    except Exception:
        twofa_missing = True

    return render_template(
        "admin/dash.html", csrf=_csrf(),
        aname=session.get("aname", "admin"),
        s=summary(d_from, d_to),
        d_from=d_from.isoformat(), d_to=d_to.isoformat(),
        today_iso=today.isoformat(),
        min_iso=(today - timedelta(days=MAX_DAYS - 1)).isoformat(),
        presets=presets, active_days=active_days,
        twofa_missing=twofa_missing,
    )


# ---------- 成员列表 ----------

@bp.route("/users")
@admin_required
def users():
    kw = (request.args.get("q") or "").strip()[:50]
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    size = 30
    offset = (page - 1) * size

    where, params = "", []
    if kw:
        where = (" WHERE u.student_no LIKE %s OR u.real_name LIKE %s "
                 "OR u.nickname LIKE %s OR u.email LIKE %s")
        like = f"%{kw}%"
        params = [like] * 4

    total = q_one(f"SELECT COUNT(*) AS c FROM app_user u{where}", params)["c"]
    rows = q_all(
        "SELECT u.id, u.student_no, u.real_name, u.nickname, u.email, u.status, "
        "u.created_at, u.last_login_at, s.major, s.dorm_room, s.gender, "
        "uk.key_hint AS api_hint "
        "FROM app_user u "
        "LEFT JOIN student s ON s.student_no=u.student_no "
        "LEFT JOIN user_ai_key uk ON uk.user_id=u.id"
        + where
        + " ORDER BY u.id DESC LIMIT %s OFFSET %s",
        params + [size, offset],
    )

    return render_template(
        "admin/users.html", csrf=_csrf(), aname=session.get("aname", "admin"),
        rows=rows, total=total, page=page, size=size, kw=kw,
        pages=max(1, (total + size - 1) // size),
        ok=request.args.get("ok"), err=request.args.get("e"),
    )


@bp.route("/users/<int:uid>/reset", methods=["POST"])
@admin_required
def reset_user_password(uid):
    """向用户邮箱发送重置链接。管理员全程看不到新密码。"""
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)

    user = q_one("SELECT id, nickname, email FROM app_user WHERE id=%s", (uid,))
    if not user:
        return redirect(url_for("admin.users", e="用户不存在"))

    token = secrets.token_urlsafe(32)
    db.create_reset_token(uid, token, RESET_TTL, _ip())
    url = f"{SITE_URL}/reset?token={token}"

    try:
        mailer.send_reset_link(user["email"], user["nickname"], url, RESET_TTL)
    except mailer.MailError as ex:
        return redirect(url_for("admin.users", e=f"重置邮件发送失败：{ex}"))

    return redirect(url_for(
        "admin.users",
        ok=f"重置链接已发送至 {user['email']}，{RESET_TTL} 分钟内有效",
    ))


@bp.route("/users/<int:uid>/status", methods=["POST"])
@admin_required
def toggle_user_status(uid):
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)

    user = q_one("SELECT id, status FROM app_user WHERE id=%s", (uid,))
    if not user:
        return redirect(url_for("admin.users", e="用户不存在"))

    new = "disabled" if user["status"] == "active" else "active"
    db.set_status(uid, new)
    return redirect(url_for(
        "admin.users",
        ok="账号已停用" if new == "disabled" else "账号已启用",
    ))


@bp.route("/ideas")
@admin_required
def ideas():
    page = request.args.get("page", 1, type=int)
    items, total = idea_moderation.list_ideas(
        q=request.args.get("q") or None,
        state=request.args.get("state") or None,
        page=page,
    )
    response = make_response(render_template(
        "admin/ideas.html", items=items, total=total, page=page,
        q=request.args.get("q", ""), state=request.args.get("state", ""),
        csrf=_csrf(), aname=session.get("aname", "admin"),
    ))
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/ideas/<int:idea_id>")
@admin_required
def idea_detail(idea_id):
    item = idea_moderation.get_metadata(idea_id)
    if not item:
        abort(404)
    content = idea_moderation.get_viewable_content(idea_id)
    try:
        idea_moderation.record_audit(
            idea_id, "view_metadata", session["aid"], session.get("aname", "admin"),
            ip=_ip(), ua=request.headers.get("User-Agent", ""),
        )
        if content is not None:
            idea_moderation.record_audit(
                idea_id, "view_content", session["aid"], session.get("aname", "admin"),
                ip=_ip(), ua=request.headers.get("User-Agent", ""),
            )
    except Exception:
        current_app.logger.exception("idea 查看审计写入失败")
        abort(503)
    response = make_response(render_template(
        "admin/idea_detail.html", item=item, content=content,
        audit=idea_moderation.list_audit(idea_id), csrf=_csrf(),
        aname=session.get("aname", "admin"),
        reason_codes=idea_moderation.REASON_CODES,
    ))
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/ideas/<int:idea_id>/moderate", methods=["POST"])
@admin_required
def idea_moderate(idea_id):
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)
    action = request.form.get("action", "")
    try:
        result = idea_moderation.moderate(
            idea_id, action, session["aid"], session.get("aname", "admin"),
            request.form.get("row_version", ""), request.form.get("reason_code", ""),
            request.form.get("reason_text", ""), request.form.get("internal_note", ""),
            request.form.get("request_id", ""), _ip(), request.headers.get("User-Agent", ""),
        )
    except ValueError as exc:
        return redirect(url_for("admin.idea_detail", idea_id=idea_id, e=str(exc)))
    if result is None:
        return redirect(url_for("admin.ideas", e="idea 不存在"))
    if not result.get("ok"):
        return redirect(url_for("admin.idea_detail", idea_id=idea_id, e=result["error"]))
    if not result.get("idempotent"):
        try:
            from archive_api import invalidate_cache
            invalidate_cache()
        except Exception:
            current_app.logger.warning("idea 治理后公开缓存失效失败", exc_info=True)
        author = q_one("SELECT nickname,email FROM app_user WHERE id=%s", (result["author_id"],))
        notify_request_id = str(idea_moderation.uuid5(
            idea_moderation.NAMESPACE_URL, request.form.get("request_id", "") + "-notify",
        ))
        if author and author.get("email"):
            state_text = "撤销" if action == "revoke" else "恢复"
            reason = request.form.get("reason_text", "").strip()
            try:
                mailer._send(
                    author["email"], f"【BNU AI Lab】你的 idea 已{state_text}",
                    f"{author['nickname']}，你的 idea 已由管理员{state_text}。原因：{reason}",
                    f"<p>{html.escape(str(author['nickname']))}，你的 idea 已由管理员{state_text}。</p><p>原因：{html.escape(reason)}</p>",
                )
                idea_moderation.record_audit(
                    idea_id, "notify_sent", session["aid"], session.get("aname", "admin"),
                    request_id=notify_request_id,
                    ip=_ip(), ua=request.headers.get("User-Agent", ""),
                )
            except Exception:
                current_app.logger.warning("idea 治理通知发送失败 idea_id=%s", idea_id, exc_info=True)
                idea_moderation.record_audit(
                    idea_id, "notify_failed", session["aid"], session.get("aname", "admin"),
                    request_id=notify_request_id,
                    ip=_ip(), ua=request.headers.get("User-Agent", ""),
                )
    return redirect(url_for("admin.idea_detail", idea_id=idea_id, ok="处置已记录"))


@bp.route("/users/<int:uid>/delete", methods=["POST"])
@admin_required
def delete_user(uid):
    """彻底删除用户及其全部关联数据（PIPL 第 47 条要求的删除权）。"""
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)

    row = q_one(
        "SELECT id, student_no, real_name, nickname, email FROM app_user WHERE id=%s",
        (uid,),
    )
    if not row:
        return redirect(url_for("admin.users", e="用户不存在"))

    email = row["email"]
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, email FROM app_user WHERE id=%s FOR UPDATE", (uid,))
            locked_user = cur.fetchone()
            if not locked_user:
                conn.rollback()
                return redirect(url_for("admin.users", e="用户不存在"))
            email = locked_user["email"]
            cur.execute("SELECT COUNT(*) AS n FROM idea WHERE author_id=%s", (uid,))
            idea_count = cur.fetchone()["n"]
            if idea_count:
                conn.rollback()
                return redirect(url_for(
                    "admin.users", e=f"该用户仍有 {idea_count} 条 idea，请先在内容治理中处置后再删除账号",
                ))
            cur.execute(
                "SELECT idea_id FROM idea_favorite WHERE user_id=%s "
                "UNION SELECT idea_id FROM idea_like WHERE user_id=%s "
                "UNION SELECT idea_id FROM idea_comment WHERE user_id=%s",
                (uid, uid, uid),
            )
            affected_ideas = [row["idea_id"] for row in cur.fetchall()]
            cur.execute(
                "UPDATE idea_comment child JOIN idea_comment parent "
                "ON child.parent_id=parent.id SET child.parent_id=NULL WHERE parent.user_id=%s",
                (uid,),
            )
            for table in ("idea_favorite", "idea_like", "idea_comment", "idea_ai_job"):
                cur.execute(f"DELETE FROM {table} WHERE user_id=%s", (uid,))
            for idea_id in affected_ideas:
                cur.execute(
                    "UPDATE idea SET like_count=(SELECT COUNT(*) FROM idea_like WHERE idea_id=%s), "
                    "favorite_count=(SELECT COUNT(*) FROM idea_favorite WHERE idea_id=%s), "
                    "comment_count=(SELECT COUNT(*) FROM idea_comment WHERE idea_id=%s) WHERE id=%s",
                    (idea_id, idea_id, idea_id, idea_id),
                )
            # 对局归档与邀请：PvP 引用 conv_id，PvE 引用 player_a，均须清理
            cur.execute(
                "DELETE FROM game_record WHERE "
                "conv_id IN (SELECT id FROM conversation WHERE user_a=%s OR user_b=%s) "
                "OR player_a=%s OR player_b=%s",
                (uid, uid, uid, str(uid)),
            )
            cur.execute(
                "DELETE FROM game_invite WHERE from_id=%s OR to_id=%s",
                (uid, uid),
            )
            # 通讯数据：先删消息再删会话，否则留下孤儿记录
            cur.execute(
                "DELETE FROM message WHERE conv_id IN "
                "(SELECT id FROM conversation WHERE user_a=%s OR user_b=%s)",
                (uid, uid),
            )
            cur.execute(
                "DELETE FROM conversation WHERE user_a=%s OR user_b=%s", (uid, uid)
            )
            cur.execute(
                "DELETE FROM friend WHERE user_id=%s OR friend_id=%s", (uid, uid)
            )
            cur.execute(
                "DELETE FROM friend_request WHERE from_id=%s OR to_id=%s", (uid, uid)
            )
            # AI 相关
            cur.execute("DELETE FROM chat_message WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM ai_usage WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM user_ai_key WHERE user_id=%s", (uid,))
            # 账号与登录
            cur.execute("DELETE FROM password_reset WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM login_log WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM email_code WHERE email=%s", (email,))
            cur.execute("DELETE FROM app_user WHERE id=%s", (uid,))
            conn.commit()

    # 清理该用户的头像文件（命名规则：u{uid}_{12位hex}.webp）
    avatar_removed = 0
    avatar_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "var", "avatar")
    prefix = f"u{uid}_"
    if os.path.isdir(avatar_dir):
        for name in os.listdir(avatar_dir):
            if name.startswith(prefix) and name.endswith(".webp"):
                try:
                    os.remove(os.path.join(avatar_dir, name))
                    avatar_removed += 1
                except OSError:
                    pass

    admin_name = session.get("aname", "admin")
    current_app.logger.warning(
        "管理员删除用户 admin=%s uid=%s student=%s name=%s email=%s 头像文件=%d",
        admin_name, uid, row["student_no"], row["real_name"], email, avatar_removed,
    )

    return redirect(url_for(
        "admin.users",
        ok=f"已删除 {row['real_name']}（{row['student_no']}）及其全部数据",
    ))


def _csv_safe(v):
    """防 CSV 注入：以 = + - @ 开头的单元格会被 Excel 当公式执行。"""
    s = "" if v is None else str(v)
    if s[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


@bp.route("/export.csv")
@admin_required
def export_csv():
    rows = q_all(
        "SELECT u.student_no, u.real_name, u.nickname, u.email, "
        "s.major, s.dorm_room, s.gender, u.created_at, u.last_login_at "
        "FROM app_user u LEFT JOIN student s ON s.student_no=u.student_no "
        "ORDER BY u.id"
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["学号", "姓名", "昵称", "邮箱", "专业", "寝室", "性别", "注册时间", "最近登录"])
    for r in rows:
        w.writerow([
            _csv_safe(r["student_no"]), _csv_safe(r["real_name"]),
            _csv_safe(r["nickname"]), _csv_safe(r["email"]),
            _csv_safe(r["major"] or ""), _csv_safe(r["dorm_room"] or ""),
            _csv_safe(r["gender"] or ""),
            _csv_safe(r["created_at"]), _csv_safe(r["last_login_at"] or ""),
        ])

    data = "\ufeff" + buf.getvalue()      # BOM 让 Excel 正确识别 UTF-8
    return Response(
        data, mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=members.csv"},
    )


# ---------- 管理员账号管理 ----------

@bp.route("/account")
@admin_required
def account():
    me = q_one(
        "SELECT id, username, display_name, last_login_at, last_login_ip, created_at "
        "FROM admin_user WHERE id=%s",
        (session.get("aid"),),
    )
    # email 列可能尚未迁移，单独取且容错，保持账号页可用
    try:
        erow = q_one("SELECT email FROM admin_user WHERE id=%s", (session.get("aid"),))
        me["email"] = (erow.get("email") or "") if erow else ""
    except Exception:
        me["email"] = ""
    return render_template(
        "admin/account.html", csrf=_csrf(),
        aname=session.get("aname", "admin"), me=me,
        err=request.args.get("e"), ok=request.args.get("ok"),
    )


@bp.route("/account/email", methods=["POST"])
@admin_required
def account_email():
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)

    pw = request.form.get("password") or ""
    email = (request.form.get("email") or "").strip().lower()
    row = q_one("SELECT password_hash FROM admin_user WHERE id=%s", (session.get("aid"),))
    if not row or not check_password_hash(row["password_hash"], pw):
        return redirect(url_for("admin.account", e="密码不正确，修改未生效"))
    if not re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", email):
        return redirect(url_for("admin.account", e="邮箱格式不正确"))

    _, err = _send_challenge(
        session.get("aid"), "email", email, session.get("aname", "管理员"), _ip(),
    )
    if err:
        return redirect(url_for("admin.account", e=err))
    return redirect(url_for("admin.verify_2fa"))


@bp.route("/account/name", methods=["POST"])
@admin_required
def account_name():
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)

    pw = request.form.get("password") or ""
    username = (request.form.get("username") or "").strip()
    disp = (request.form.get("display_name") or "").strip()

    row = q_one("SELECT password_hash FROM admin_user WHERE id=%s", (session.get("aid"),))
    if not row or not check_password_hash(row["password_hash"], pw):
        return redirect(url_for("admin.account", e="密码不正确，修改未生效"))

    if not re.match(r"^[A-Za-z0-9_]{3,32}$", username):
        return redirect(url_for("admin.account", e="用户名需 3–32 位，仅字母、数字、下划线"))

    dup = q_one(
        "SELECT id FROM admin_user WHERE username=%s AND id<>%s",
        (username, session.get("aid")),
    )
    if dup:
        return redirect(url_for("admin.account", e="该用户名已被其他管理员占用"))

    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE admin_user SET username=%s, display_name=%s WHERE id=%s",
                (username, disp or username, session.get("aid")),
            )
            conn.commit()

    session["aname"] = disp or username
    return redirect(url_for("admin.account", ok="账号信息已更新"))


@bp.route("/account/password", methods=["POST"])
@admin_required
def account_password():
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)

    old = request.form.get("old") or ""
    new = request.form.get("new") or ""
    new2 = request.form.get("new2") or ""

    row = q_one("SELECT password_hash FROM admin_user WHERE id=%s", (session.get("aid"),))
    if not row or not check_password_hash(row["password_hash"], old):
        return redirect(url_for("admin.account", e="当前密码不正确"))

    if len(new) < 10 or len(new) > 64:
        return redirect(url_for("admin.account", e="管理员密码长度需为 10–64 位"))
    if not (re.search(r"[A-Za-z]", new) and re.search(r"\d", new)):
        return redirect(url_for("admin.account", e="密码需同时包含字母和数字"))
    if new != new2:
        return redirect(url_for("admin.account", e="两次输入的新密码不一致"))
    if new == old:
        return redirect(url_for("admin.account", e="新密码不能与当前密码相同"))

    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE admin_user SET password_hash=%s WHERE id=%s",
                (generate_password_hash(new), session.get("aid")),
            )
            conn.commit()

    aid = session.get("aid")
    _revoke_admin_state(aid)
    session.clear()
    return redirect(url_for("admin.login", pw=1))


# ---------- 访问日志 ----------

@bp.route("/logs")
@admin_required
def logs():
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    size = 40
    offset = (page - 1) * size

    total = q_one("SELECT COUNT(*) AS c FROM access_log")["c"]
    rows = q_all(
        "SELECT ip, method, path, status, ua, created_at FROM access_log "
        "ORDER BY id DESC LIMIT %s OFFSET %s",
        (size, offset),
    )
    top_ips = q_all(
        "SELECT ip, COUNT(*) AS c, MAX(created_at) AS last_seen "
        "FROM access_log GROUP BY ip ORDER BY c DESC LIMIT 15"
    )

    return render_template(
        "admin/logs.html", csrf=_csrf(), aname=session.get("aname", "admin"),
        rows=rows, total=total, page=page, size=size,
        pages=max(1, (total + size - 1) // size), top_ips=top_ips,
    )
