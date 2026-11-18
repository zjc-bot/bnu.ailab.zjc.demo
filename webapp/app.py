"""学生信息管理 Web 应用。

安全设计要点：
- 认证：密码以 scrypt 哈希存储，登录后重置 session 防固定攻击
- 授权：所有数据接口均要求登录；数据库使用最小权限专用账号
- 注入：全部参数化查询，排序字段走白名单
- CSRF：所有写操作校验一次性 token
- 暴力破解：按来源 IP 失败计数，超阈值锁定
- 响应头：CSP / X-Frame-Options / nosniff / Referrer-Policy
- 错误：不回显堆栈与数据库信息
"""

import hmac
import logging
import os
import secrets
import time
from functools import wraps

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import db

BASE = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.json.ensure_ascii = False

# 只信任一层反向代理（本机 nginx），让限流拿到真实客户端 IP。
# 直连 8080 时若无 XFF 头，remote_addr 不会被改写。
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# SECRET_KEY 必须由环境注入，缺失即拒绝启动（禁止随机回退）。
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
if not SECRET_KEY:
    raise RuntimeError(
        "缺少 SECRET_KEY 环境变量：拒绝以随机密钥启动。"
        "请在 .env 或环境变量中设置一个固定的随机字符串（至少 32 字节）。"
    )

app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=1800,
    MAX_CONTENT_LENGTH=256 * 1024,
)

APP_USER = os.environ.get("APP_USER", "admin")
APP_PASSWORD_HASH = os.environ.get("APP_PASSWORD_HASH", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("student-web")

FAIL_WINDOW = 300
FAIL_LIMIT = 5
_fails = {}


def _ip():
    return request.remote_addr or "unknown"


def _locked(ip):
    """返回剩余可尝试次数；无记录时返回满额，达上限返回 0。"""
    rec = _fails.get(ip)
    if not rec:
        return FAIL_LIMIT
    cnt, first = rec
    if time.time() - first > FAIL_WINDOW:
        _fails.pop(ip, None)
        return FAIL_LIMIT
    return max(0, FAIL_LIMIT - cnt)


def _note_fail(ip):
    cnt, first = _fails.get(ip, (0, time.time()))
    if time.time() - first > FAIL_WINDOW:
        cnt, first = 0, time.time()
    _fails[ip] = (cnt + 1, first)


def _csrf():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def _check_csrf(token):
    expect = session.get("_csrf", "")
    return bool(expect) and bool(token) and hmac.compare_digest(expect, token)


def login_required(fn):
    @wraps(fn)
    def inner(*a, **kw):
        if not session.get("uid"):
            if request.path.startswith("/api/"):
                return jsonify(error="请先登录"), 401
            return redirect(url_for("login"))
        return fn(*a, **kw)

    return inner


@app.after_request
def security_headers(resp):
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'"
    )
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    resp.headers.pop("X-Powered-By", None)
    return resp


@app.errorhandler(404)
def _404(_e):
    return jsonify(error="资源不存在"), 404


@app.errorhandler(500)
def _500(_e):
    log.exception("内部错误")
    return jsonify(error="服务器内部错误"), 500


@app.route("/login", methods=["GET"], endpoint="login")
def login_page():
    if session.get("uid"):
        return redirect(url_for("index"))
    return render_template("login.html", csrf=_csrf(), err=request.args.get("e"))


@app.route("/login", methods=["POST"])
def login_submit():
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)

    ip = _ip()
    left = _locked(ip)
    if left == 0:
        log.warning("登录被锁定 ip=%s", ip)
        return render_template(
            "login.html", csrf=_csrf(), err="尝试次数过多，请 5 分钟后再试"
        )

    user = (request.form.get("user") or "").strip()[:64]
    pwd = request.form.get("pass") or ""

    ok_user = hmac.compare_digest(user, APP_USER)
    ok_pass = bool(APP_PASSWORD_HASH) and check_password_hash(APP_PASSWORD_HASH, pwd)

    if ok_user and ok_pass:
        session.clear()
        session["uid"] = user
        session["_csrf"] = secrets.token_urlsafe(32)
        session.permanent = True
        _fails.pop(ip, None)
        log.info("登录成功 user=%s ip=%s", user, ip)
        return redirect(url_for("index"))

    _note_fail(ip)
    log.warning("登录失败 user=%s ip=%s", user, ip)
    return render_template(
        "login.html",
        csrf=session.get("_csrf") or _csrf(),
        err="用户名或密码错误",
    )


@app.route("/logout", methods=["POST"])
def logout():
    if _check_csrf(request.form.get("csrf", "")):
        log.info("登出 ip=%s", _ip())
        session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("index.html", csrf=_csrf(), user=session.get("uid"))


def _payload():
    raw = request.get_json(silent=True) or {}

    gender = raw.get("gender")
    if gender not in ("男", "女", "其他"):
        gender = None

    def clean(key, limit):
        v = raw.get(key)
        if v is None:
            return None
        v = str(v).strip()
        return v[:limit] if v else None

    return {
        "student_no": clean("student_no", 20),
        "name": clean("name", 50),
        "gender": gender,
        "major": clean("major", 50),
        "dorm_room": clean("dorm_room", 20),
        "remark": clean("remark", 200),
        "phone": clean("phone", 20),
        "email": clean("email", 100),
    }


@app.get("/api/students")
@login_required
def api_list():
    kw = (request.args.get("q") or "").strip()[:50]
    try:
        page = max(1, int(request.args.get("page", 1)))
        size = min(100, max(5, int(request.args.get("size", 20))))
    except ValueError:
        page, size = 1, 20

    sort_by = request.args.get("sort", "student_no")
    order = request.args.get("order", "asc")

    return jsonify(
        db.list_students(
            kw, page, size, sort_by, order,
            major=(request.args.get("major") or None),
        )
    )


@app.get("/api/stats")
@login_required
def api_stats():
    return jsonify(db.stats())


@app.post("/api/students")
@login_required
def api_create():
    if not _check_csrf(request.headers.get("X-CSRF-Token", "")):
        return jsonify(error="CSRF 校验失败"), 403

    d = _payload()
    if not d["name"] or not d["student_no"]:
        return jsonify(error="姓名和学号为必填"), 400
    if not d["student_no"].isalnum():
        return jsonify(error="学号只能包含字母和数字"), 400

    try:
        sid = db.create_student(d)
    except Exception as e:
        if "Duplicate" in type(e).__name__ or getattr(e, "args", [""])[0] == 1062:
            return jsonify(error="学号已存在"), 409
        log.exception("新增失败")
        return jsonify(error="写入失败"), 500
    return jsonify(id=sid), 201


@app.put("/api/students/<int:sid>")
@login_required
def api_update(sid):
    if not _check_csrf(request.headers.get("X-CSRF-Token", "")):
        return jsonify(error="CSRF 校验失败"), 403

    d = _payload()
    if not d["name"] or not d["student_no"]:
        return jsonify(error="姓名和学号为必填"), 400

    try:
        n = db.update_student(sid, d)
    except Exception:
        log.exception("更新失败")
        return jsonify(error="更新失败"), 500
    if n == 0:
        return jsonify(error="记录不存在"), 404
    return jsonify(ok=True)


@app.delete("/api/students/<int:sid>")
@login_required
def api_delete(sid):
    if not _check_csrf(request.headers.get("X-CSRF-Token", "")):
        return jsonify(error="CSRF 校验失败"), 403

    n = db.delete_student(sid)
    if n == 0:
        return jsonify(error="记录不存在"), 404
    log.info("删除学生 id=%s by=%s", sid, session.get("uid"))
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=False)
