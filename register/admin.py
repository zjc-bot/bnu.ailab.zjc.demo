"""管理后台：注册数据与访问统计。

与前台完全隔离：
  - 独立表 admin_user，独立 session 键 aid
  - 独立装饰器 admin_required
  - 独立 CSRF token
"""

import csv
import hmac
import io
import os
import re
import secrets
import time
from datetime import date, timedelta

from flask import (
    Blueprint, Response, abort, current_app, redirect, render_template,
    request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import db
import mailer

bp = Blueprint("admin", __name__, url_prefix="/admin")

SITE_URL = os.environ.get("SITE_URL", "http://127.0.0.1:8082").rstrip("/")
RESET_TTL = 30

LOGIN_LIMIT = 5
LOGIN_WINDOW = 600
_fails = {}


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


def admin_required(fn):
    from functools import wraps

    @wraps(fn)
    def inner(*a, **kw):
        if not session.get("aid"):
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
    if session.get("aid"):
        return redirect(url_for("admin.dash"))
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
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE admin_user SET last_login_at=NOW(), last_login_ip=%s WHERE id=%s",
                (ip, row["id"]),
            )
            conn.commit()

    session.clear()
    session["aid"] = row["id"]
    session["aname"] = row["display_name"] or row["username"]
    session["_acsrf"] = secrets.token_urlsafe(32)
    session.permanent = True
    return redirect(url_for("admin.dash"))


@bp.route("/logout", methods=["POST"])
def logout():
    if _check_csrf(request.form.get("csrf", "")):
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

    return render_template(
        "admin/dash.html", csrf=_csrf(),
        aname=session.get("aname", "admin"),
        s=summary(d_from, d_to),
        d_from=d_from.isoformat(), d_to=d_to.isoformat(),
        today_iso=today.isoformat(),
        min_iso=(today - timedelta(days=MAX_DAYS - 1)).isoformat(),
        presets=presets, active_days=active_days,
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

    admin_name = session.get("aname", "admin")
    current_app.logger.warning(
        "管理员删除用户 admin=%s uid=%s student=%s name=%s email=%s",
        admin_name, uid, row["student_no"], row["real_name"], email,
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
    return render_template(
        "admin/account.html", csrf=_csrf(),
        aname=session.get("aname", "admin"), me=me,
        err=request.args.get("e"), ok=request.args.get("ok"),
    )


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
