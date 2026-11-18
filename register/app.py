"""BNU AI Lab 注册系统。

安全设计：
  - 实名校验：学号 + 姓名必须与官方名单精确匹配
  - 邮箱门槛：只接受 @mail.bnu.edu.cn，校外邮箱无法注册
  - 密码：scrypt 哈希，永不明文落库
  - 验证码：6 位数字，5 分钟有效，一次性消费，按邮箱限频
  - 会话：登录后重建，HttpOnly + SameSite
  - CSRF / CSP / 安全响应头：与主站保持一致
"""

import hmac
import io
import json
import mimetypes
import os
import re
import secrets
import time
from functools import wraps

# 老版本 Python 的 mimetypes 表里没有 webp，显式注册
mimetypes.add_type("image/webp", ".webp")

import requests
from flask import (
    Flask, Response, abort, jsonify, redirect, render_template,
    request, session, url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import admin
import captcha
import db
import mailer
import secret_box

app = Flask(__name__)
app.json.ensure_ascii = False
# 本服务经 SSH 隧道直连（gunicorn bind 127.0.0.1:8081），前方没有 nginx 反代。
# 因此不信任 X-Forwarded-For（x_for=0）：否则客户端可伪造 XFF: 127.0.0.1
# 覆盖 remote_addr，绕过下方 /admin 的本机白名单。
# 若将来改为 nginx 反代，须让 nginx 强制重写 XFF 并重新评估此处信任链。
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=0, x_proto=1, x_host=1)
app.register_blueprint(admin.bp)

# SECRET_KEY 必须由环境注入，缺失即拒绝启动。
# 随机回退会导致重启后 session 失效、已存的 BYOK API Key 永久无法解密。
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
    PERMANENT_SESSION_LIFETIME=3600,
    # 上传接口允许 5MB，这里必须留出余量，否则 Flask 会在进入路由前就 413
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,
)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@mail\.bnu\.edu\.cn$")
NICK_RE = re.compile(r"^[\w\u4e00-\u9fa5.\-]{2,20}$")
NO_RE = re.compile(r"^[A-Za-z0-9]{6,20}$")

CODE_TTL = 5
RESEND_GAP = 60          # 同一邮箱重发间隔（秒）
RESEND_HOURLY = 5        # 同一邮箱每小时上限
REG_IP_LIMIT = 10        # 同一 IP 每小时提交上限

_rate = {}   # key -> [count, first_ts]


# ---------- 工具 ----------

def _ip():
    return request.remote_addr or "unknown"


def _hit(key, limit, window):
    """计数限流，返回 True 表示允许。"""
    now = time.time()
    rec = _rate.get(key)
    if not rec or now - rec[1] > window:
        _rate[key] = [1, now]
        return True
    rec[0] += 1
    return rec[0] <= limit


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
            return redirect(url_for("login_page"))
        return fn(*a, **kw)
    return inner


@app.after_request
def security_headers(resp):
    # style-src 放开 unsafe-inline：图表宽度、进度条需要动态内联样式，
    # 且所有输出都经 Jinja 自动转义，样式注入的危害远低于脚本注入
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'"
    )
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    resp.headers.pop("X-Powered-By", None)

    _log_access(resp.status_code)
    return resp


SKIP_LOG_PREFIX = ("/static/", "/admin", "/favicon.ico")
SKIP_LOG_EXACT = ("/captcha.png",)


def _log_access(status):
    """记录页面访问，用于统计访问人群。失败不影响响应。"""
    p = request.path
    if p.startswith(SKIP_LOG_PREFIX) or p in SKIP_LOG_EXACT:
        return
    try:
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO access_log(ip, method, path, status, ua, referer) "
                    "VALUES(%s,%s,%s,%s,%s,%s)",
                    (
                        _ip(),
                        request.method,
                        p[:200],
                        status,
                        (request.headers.get("User-Agent") or "")[:200],
                        (request.headers.get("Referer") or "")[:200],
                    ),
                )
                conn.commit()
    except Exception:
        app.logger.debug("access_log 写入失败", exc_info=True)


@app.errorhandler(404)
def _404(_e):
    return render_template("error.html", code=404, msg="页面不存在"), 404


@app.errorhandler(403)
def _403(_e):
    return render_template("error.html", code=403, msg="无权访问"), 403


# 管理后台只允许本机访问：
#   SSH 隧道直连 8081 → 真实 TCP 对端 = 127.0.0.1，放行
#   XFF 不再参与判定（见上方 ProxyFix 注释），伪造头无效
ADMIN_ALLOWED = {"127.0.0.1", "::1", "localhost"}


@app.before_request
def restrict_admin_to_localhost():
    if not request.path.startswith("/admin"):
        return None
    ip = request.remote_addr or ""
    if ip not in ADMIN_ALLOWED:
        app.logger.warning("非本机访问管理后台被拒 ip=%s path=%s", ip, request.path)
        return render_template("error.html", code=403, msg="管理后台仅限本机隧道访问"), 403
    return None


@app.errorhandler(413)
def _413(_e):
    return jsonify(error="请求体过大"), 413


# ---------- 图形验证码 ----------

# 验证码明文必须留在服务端：Flask 的 session 是「签名但不加密」的 cookie，
# 客户端可以 base64 解码读出内容。放 session 等于把答案发给用户。
_captcha_store = {}
CAPTCHA_TTL = 300


def _sweep_captcha(now):
    for k, (_, ts) in list(_captcha_store.items()):
        if now - ts > CAPTCHA_TTL:
            _captcha_store.pop(k, None)


@app.get("/captcha.png")
def captcha_png():
    data, text = captcha.generate()
    now = time.time()
    _sweep_captcha(now)

    tok = secrets.token_urlsafe(16)
    _captcha_store[tok] = (text.lower(), now)
    session["cap_tok"] = tok

    resp = Response(data, mimetype="image/png")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


def _check_captcha(user_input):
    tok = session.pop("cap_tok", None)
    if not tok:
        return False

    item = _captcha_store.pop(tok, None)
    if not item:
        return False

    expect, ts = item
    if time.time() - ts > CAPTCHA_TTL:
        return False
    if not user_input:
        return False

    return hmac.compare_digest(expect, str(user_input).strip().lower())


# ---------- 首页 ----------

@app.get("/")
def index():
    if session.get("uid"):
        return redirect(url_for("home"))
    return redirect(url_for("register"))


@app.get("/privacy")
def privacy():
    return render_template("privacy.html")


# ---------- 注册 ① 身份核验 ----------

IDENT_TTL = 900   # 身份核验结果保留 15 分钟


def _ident():
    d = session.get("ident")
    if not d:
        return None
    if time.time() - d.get("ts", 0) > IDENT_TTL:
        session.pop("ident", None)
        return None
    return d


@app.get("/register")
def register():
    if session.get("uid"):
        return redirect(url_for("home"))
    return render_template("register_step1.html", csrf=_csrf(), form={}, step=1)


@app.post("/register/step1")
def register_step1():
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)

    f = request.form
    form = {
        "student_no": (f.get("student_no") or "").strip(),
        "real_name": (f.get("real_name") or "").strip(),
    }

    def fail(msg):
        return render_template("register_step1.html", csrf=_csrf(),
                               form=form, err=msg, step=1)

    if not _hit(f"step1:{_ip()}", 15, 600):
        return fail("尝试过于频繁，请稍后再试")

    if not _check_captcha(f.get("captcha", "")):
        return fail("图形验证码错误或已过期")

    if not (form["student_no"] and form["real_name"]):
        return fail("请填写学号和真实姓名")

    if not NO_RE.match(form["student_no"]):
        return fail("学号格式不正确")

    stu = db.find_student(form["student_no"], form["real_name"])
    if not stu:
        return fail("学号与姓名不匹配，或不在 26 级名单中。请核对后重试")

    if db.is_taken(student_no=form["student_no"]):
        return fail("该学号已完成注册，请直接登录")

    session["ident"] = {
        "student_no": stu["student_no"],
        "real_name": stu["name"],
        "major": stu.get("major"),
        "dorm_room": stu.get("dorm_room"),
        "ts": int(time.time()),
    }
    return redirect(url_for("register_step2"))


# ---------- 注册 ② 填写账号资料 ----------

@app.get("/register/step2")
def register_step2():
    if session.get("uid"):
        return redirect(url_for("home"))
    ident = _ident()
    if not ident:
        return redirect(url_for("register"))
    return render_template("register_step2.html", csrf=_csrf(),
                           ident=ident, form={}, step=2)


@app.post("/register/step2")
def register_step2_submit():
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)

    ident = _ident()
    if not ident:
        return redirect(url_for("register"))

    f = request.form
    form = {
        "nickname": (f.get("nickname") or "").strip(),
        "email": (f.get("email") or "").strip().lower(),
    }
    pwd = f.get("password") or ""
    pwd2 = f.get("password2") or ""

    def fail(msg):
        return render_template("register_step2.html", csrf=_csrf(),
                               ident=ident, form=form, err=msg, step=2)

    if not _hit(f"reg:{_ip()}", REG_IP_LIMIT, 3600):
        return fail("提交过于频繁，请稍后再试")

    if not (form["nickname"] and form["email"]):
        return fail("请完整填写昵称和校内邮箱")

    if not NICK_RE.match(form["nickname"]):
        return fail("昵称需 2–20 位，可用中英文、数字、下划线、点、短横线")

    if not EMAIL_RE.match(form["email"]):
        return fail("仅接受北京师范大学学生邮箱（@mail.bnu.edu.cn）")

    if len(pwd) < 8 or len(pwd) > 64:
        return fail("密码长度需为 8–64 位")
    if not (re.search(r"[A-Za-z]", pwd) and re.search(r"\d", pwd)):
        return fail("密码需同时包含字母和数字")
    if pwd != pwd2:
        return fail("两次输入的密码不一致")

    if f.get("agree") != "1":
        return fail("请先阅读并同意隐私条款")

    taken = db.is_taken(nickname=form["nickname"], email=form["email"])
    if taken:
        if taken["nickname"] == form["nickname"]:
            return fail("该昵称已被占用，换一个吧")
        return fail("该邮箱已注册，请直接登录")

    gap = db.last_code_age(form["email"])
    if gap is not None and gap < RESEND_GAP:
        return fail(f"验证码发送过于频繁，请 {RESEND_GAP - gap} 秒后再试")
    if db.recent_code_count(form["email"]) >= RESEND_HOURLY:
        return fail("该邮箱一小时内发送次数过多，请稍后再试")

    code = f"{secrets.randbelow(1000000):06d}"
    try:
        mailer.send_code(form["email"], code, CODE_TTL)
    except mailer.MailError as e:
        app.logger.exception("发信失败")
        return fail(f"验证码发送失败：{e}")

    db.save_code(form["email"], code, CODE_TTL, _ip())

    session["pending"] = {
        "student_no": ident["student_no"],
        "real_name": ident["real_name"],
        "nickname": form["nickname"],
        "email": form["email"],
        "pw_hash": generate_password_hash(pwd),
        "ts": int(time.time()),
    }
    return redirect(url_for("verify"))


# ---------- 邮箱验证 ----------

def _mask_email(e):
    local, _, domain = e.partition("@")
    if not local:
        return e
    if len(local) <= 3:
        return local[0] + "***@" + domain
    return local[:3] + "****@" + domain


@app.get("/verify")
def verify():
    p = session.get("pending")
    if not p:
        return redirect(url_for("register"))
    return render_template("verify.html", csrf=_csrf(), email=p["email"],
                           masked=_mask_email(p["email"]), ttl=CODE_TTL, step=3)


@app.post("/verify")
def verify_submit():
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)

    p = session.get("pending")
    if not p:
        return redirect(url_for("register"))

    if time.time() - p["ts"] > 1200:      # 20 分钟内完成
        session.pop("pending", None)
        return redirect(url_for("register"))

    # 验证码只有 6 位，必须限制尝试次数，否则可被穷举
    tries = session.get("code_tries", 0)
    if tries >= 5:
        session.pop("pending", None)
        session.pop("code_tries", None)
        return redirect(url_for("register"))

    code = (request.form.get("code") or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        return render_template("verify.html", csrf=_csrf(), email=p["email"],
                               masked=_mask_email(p["email"]), ttl=CODE_TTL, step=3,
                               err="请输入 6 位数字验证码")

    cid = db.check_code(p["email"], code)
    if not cid:
        session["code_tries"] = tries + 1
        left = 5 - tries - 1
        msg = "验证码错误或已过期"
        if left <= 2:
            msg += f"，还可尝试 {left} 次"
        return render_template("verify.html", csrf=_csrf(), email=p["email"],
                               masked=_mask_email(p["email"]), ttl=CODE_TTL, step=3,
                               err=msg)

    try:
        uid = db.create_user(
            p["student_no"], p["real_name"], p["nickname"], p["email"], p["pw_hash"]
        )
    except Exception:
        app.logger.exception("创建账号失败")
        return render_template("verify.html", csrf=_csrf(), email=p["email"],
                               masked=_mask_email(p["email"]), ttl=CODE_TTL, step=3,
                               err="账号创建失败，请稍后重试")

    db.consume_code(cid)
    session.pop("pending", None)
    session.clear()
    session["uid"] = uid
    session["_csrf"] = secrets.token_urlsafe(32)
    session.permanent = True
    app.logger.info("新用户注册 uid=%s student=%s", uid, p["student_no"])
    return redirect(url_for("home"))


@app.post("/api/resend")
def resend():
    if not _check_csrf(request.headers.get("X-CSRF-Token", "")):
        return jsonify(error="CSRF 校验失败"), 403

    p = session.get("pending")
    if not p:
        return jsonify(error="会话已过期，请重新填写"), 400

    gap = db.last_code_age(p["email"])
    if gap is not None and gap < RESEND_GAP:
        return jsonify(error=f"请 {RESEND_GAP - gap} 秒后再试"), 429
    if db.recent_code_count(p["email"]) >= RESEND_HOURLY:
        return jsonify(error="发送次数过多，请稍后再试"), 429

    code = f"{secrets.randbelow(1000000):06d}"
    try:
        mailer.send_code(p["email"], code, CODE_TTL)
    except mailer.MailError as e:
        return jsonify(error=str(e)), 502

    db.save_code(p["email"], code, CODE_TTL, _ip())
    return jsonify(ok=True)


# ---------- 登录 / 登出 ----------

@app.get("/login")
def login_page():
    if session.get("uid"):
        return redirect(url_for("home"))
    return render_template("login.html", csrf=_csrf())


@app.post("/login")
def login_submit():
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)

    if not _hit(f"login:{_ip()}", 10, 600):
        return render_template("login.html", csrf=_csrf(), err="尝试过于频繁，请稍后再试")

    login_id = (request.form.get("login") or "").strip()
    pwd = request.form.get("password") or ""

    user = db.get_user_by_login(login_id) if login_id else None
    if not user or not check_password_hash(user["password_hash"], pwd):
        return render_template("login.html", csrf=_csrf(), err="账号或密码错误")

    if user["status"] != "active":
        return render_template("login.html", csrf=_csrf(), err="账号已被停用，请联系管理员")

    # 异地登录检测：与上一次登录 IP 比对，不同则发提醒
    cur_ip = _ip()
    prev_ip = db.last_login_ip(user["id"])
    ua = (request.headers.get("User-Agent") or "")[:80]
    db.add_login_log(user["id"], cur_ip, ua)
    db.touch_login(user["id"])

    if prev_ip and prev_ip != cur_ip:
        try:
            mailer.send_login_alert(
                user["email"], user["nickname"], cur_ip, ua,
                time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            app.logger.info("已发送异地登录提醒 uid=%s prev=%s cur=%s",
                            user["id"], prev_ip, cur_ip)
        except mailer.MailError:
            app.logger.warning("异地登录提醒发送失败 uid=%s", user["id"])

    session.clear()
    session["uid"] = user["id"]
    session["_csrf"] = secrets.token_urlsafe(32)
    session.permanent = True
    return redirect(url_for("home"))


# ---------- 密码重置（由管理员触发，用户凭邮件链接完成）----------

@app.get("/reset")
def reset_form():
    token = request.args.get("token") or ""
    row = db.get_valid_reset(token)
    if not row:
        return render_template("error.html", code=400,
                               msg="重置链接无效或已过期，请联系管理员重新发起"), 400
    return render_template("reset.html", csrf=_csrf(), token=token,
                           nickname=row["nickname"])


@app.post("/reset")
def reset_submit():
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)

    token = request.form.get("token") or ""
    pw = request.form.get("password") or ""
    pw2 = request.form.get("password2") or ""

    row = db.get_valid_reset(token)
    if not row:
        return render_template("error.html", code=400,
                               msg="重置链接无效或已过期，请联系管理员重新发起"), 400

    def fail(msg):
        return render_template("reset.html", csrf=_csrf(), token=token,
                               nickname=row["nickname"], err=msg)

    if len(pw) < 8 or len(pw) > 64:
        return fail("密码长度需为 8–64 位")
    if not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
        return fail("密码需同时包含字母和数字")
    if pw != pw2:
        return fail("两次输入的密码不一致")

    db.update_password(row["user_id"], generate_password_hash(pw))
    db.consume_reset(row["id"])
    app.logger.info("用户通过邮件链接重置密码 uid=%s", row["user_id"])
    session.clear()
    return redirect(url_for("login_page", reset=1))


@app.post("/logout")
def logout():
    if _check_csrf(request.form.get("csrf", "")):
        session.clear()
    return redirect(url_for("login_page"))


# ---------- 主页 ----------

AI_MODEL = os.environ.get("AI_MODEL", "未接入")
@app.get("/home")
@login_required
def home():
    user = db.get_user(session["uid"])
    if not user:
        session.clear()
        return redirect(url_for("login_page"))

    stu = db.get_student_by_no(user["student_no"])
    members = db.list_members(exclude_uid=user["id"])

    return render_template("home.html", csrf=_csrf(), user=user, stu=stu,
                           members=members, ms=db.member_stats())


# ---------- AI 对话 ----------

AI_BASE = os.environ.get("AI_BASE_URL", "https://api.deepseek.com").rstrip("/")
AI_KEY = os.environ.get("AI_API_KEY", "")

EMO_RE = re.compile(r"\[\[emo:(\w+)\]\]")
EMO_PREFIX = "[[emo:"
EMO_HINT = (
    "\n\n【输出格式要求】回复的最后单独一行输出情绪标记，格式 [[emo:xxx]]，"
    "xxx 只能是 happy / sad / angry / sleep / surprised / neutral 之一。"
    "这一行不会展示给用户。"
)


class _EmotionFilter:
    """流式吞掉 [[emo:xxx]] 标记，避免标记在前端逐字闪现。

    按字符处理，能跨 SSE chunk 识别标记；对非标记文本（含普通 '['）原样放行。
    """

    def __init__(self):
        self.pending = ""    # 可能是标记前缀的暂存字符
        self.tagged = None   # 已进入标记后累积的内容
        self.emotion = ""

    def _drain(self):
        """吐出 pending 中确定不属于标记前缀的部分，保留仍是前缀真前缀的后缀。"""
        out = self.pending
        keep = ""
        for n in range(min(len(EMO_PREFIX) - 1, len(out)), 0, -1):
            if out.endswith(EMO_PREFIX[:n]):
                keep = out[-n:]
                break
        self.pending = keep
        return out[:len(out) - len(keep)] if keep else out

    def _close_tag(self):
        inner = self.tagged[:-2]
        if re.fullmatch(r"\w+", inner):
            self.emotion = inner
        else:
            return EMO_PREFIX + self.tagged  # 非法标记，原样吐出
        return ""

    def feed(self, text):
        out = []
        for ch in text:
            if self.tagged is not None:
                self.tagged += ch
                if self.tagged.endswith("]]"):
                    leaked = self._close_tag()
                    if leaked:
                        out.append(leaked)
                    self.tagged = None
                elif len(self.tagged) > 24:  # 迟迟不闭合，视为普通文本
                    out.append(EMO_PREFIX + self.tagged)
                    self.tagged = None
                continue

            self.pending += ch
            if EMO_PREFIX.startswith(self.pending):
                continue  # 仍是前缀的一部分，继续等待
            if self.pending.startswith(EMO_PREFIX):
                self.tagged = self.pending[len(EMO_PREFIX):]
                self.pending = ""
                if self.tagged.endswith("]]"):
                    leaked = self._close_tag()
                    if leaked:
                        out.append(leaked)
                    self.tagged = None
                continue
            out.append(self._drain())
        return "".join(out)

    def finish(self):
        """流结束时吐出残留字符（未闭合的标记按原文放行）。"""
        tail = self.pending
        if self.tagged is not None:
            tail += EMO_PREFIX + self.tagged
        self.pending, self.tagged = "", None
        return tail


SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(event, data):
    return "event: %s\ndata: %s\n\n" % (event, json.dumps(data, ensure_ascii=False))


@app.post("/api/chat")
@login_required
def chat():
    if not _check_csrf(request.headers.get("X-CSRF-Token", "")):
        return jsonify(error="CSRF 校验失败"), 403

    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify(error="消息不能为空"), 400
    if len(text) > 2000:
        return jsonify(error="单条消息不能超过 2000 字"), 400

    uid = session["uid"]

    # 优先使用用户自带的凭据
    uk = db.get_user_key(uid)
    use_key, use_base, byok, user_model = AI_KEY, AI_BASE, False, None
    if uk:
        dec = secret_box.decrypt(app.config["SECRET_KEY"], uk["key_enc"])
        if dec:
            use_key = dec
            use_base = uk["base_url"] or AI_BASE
            user_model = uk["model"]
            byok = True

    try:
        limit = int(db.get_ai_config("daily_limit", "40") or 40)
    except ValueError:
        limit = 40
    limit = max(1, min(limit, 1000))

    # 自带 key 不占系统配额
    if not byok and db.usage_today(uid) >= limit:
        return jsonify(error=f"今天的 {limit} 次对话已经用完了，明天再来吧"), 429

    if not use_key:
        return _mock_chat(uid, text)

    persona = db.get_ai_config("persona", "")
    model = user_model or db.get_ai_config("model", "deepseek-flash")
    try:
        turns = int(db.get_ai_config("history_turns", "12") or 12)
    except ValueError:
        turns = 12
    turns = max(0, min(turns, 100))

    msgs = [{"role": "system", "content": persona + EMO_HINT}]
    for h in db.recent_messages(uid, turns * 2):
        msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": text})

    db.add_chat_message(uid, "user", text)
    db.bump_usage(uid)

    def gen():
        buf = []
        ef = _EmotionFilter()
        yield _sse("start", {"model": model})
        try:
            with requests.post(
                use_base + "/chat/completions",
                headers={
                    "Authorization": "Bearer " + use_key,
                    "Content-Type": "application/json",
                },
                json={"model": model, "messages": msgs, "stream": True},
                stream=True,
                timeout=(10, 180),
            ) as r:
                if r.status_code != 200:
                    app.logger.warning("上游 %s：%s", r.status_code, r.text[:200])
                    yield _sse("error", {"message": "AI 服务暂时不可用，稍后再试"})
                    return

                for raw in r.iter_lines():
                    if not raw:
                        continue
                    line = raw.decode("utf-8", "replace")
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                        delta = obj["choices"][0]["delta"].get("content") or ""
                    except Exception:
                        continue
                    if delta:
                        buf.append(delta)
                        visible = ef.feed(delta)
                        if visible:
                            yield _sse("delta", {"text": visible})
            tail = ef.finish()
            if tail:
                yield _sse("delta", {"text": tail})
        except requests.Timeout:
            yield _sse("error", {"message": "AI 响应超时"})
        except Exception:
            app.logger.exception("chat 转发失败")
            yield _sse("error", {"message": "服务异常，请稍后再试"})
        finally:
            answer = "".join(buf)
            if answer:
                m = EMO_RE.search(answer)
                emo = m.group(1) if m else ""
                clean = EMO_RE.sub("", answer).strip()
                db.add_chat_message(uid, "assistant", clean, emo)
                yield _sse("end", {"emotion": emo})

    return Response(gen(), mimetype="text/event-stream", headers=SSE_HEADERS)


def _mock_chat(uid, text):
    """未配置 AI_API_KEY 时的联调回复，便于先把界面跑通。"""
    def gen():
        yield _sse("start", {"model": "mock"})
        reply = ("还没接入 AI 接口，所以现在只能这样回你。"
                 "等配置好 API Key，我就能真的聊天了。")
        for ch in reply:
            yield _sse("delta", {"text": ch})
            time.sleep(0.018)
        db.add_chat_message(uid, "user", text)
        db.add_chat_message(uid, "assistant", reply, "happy")
        yield _sse("end", {"emotion": "happy"})

    return Response(gen(), mimetype="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/chat/clear")
@login_required
def chat_clear():
    if not _check_csrf(request.headers.get("X-CSRF-Token", "")):
        return jsonify(error="CSRF 校验失败"), 403
    n = db.clear_messages(session["uid"])
    return jsonify(ok=True, deleted=n)


@app.get("/api/chat/history")
@login_required
def chat_history():
    """拉取最近对话历史，供前端刷新后恢复上下文。"""
    rows = db.chat_history(session["uid"])
    items = []
    for r in rows:
        d = _row_dict(r)
        d["text"] = d.pop("content", "") or ""
        items.append(d)
    return jsonify(messages=items)


# ---------- 即时通讯 ----------

def _row_dict(r):
    d = dict(r)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat(sep=" ", timespec="seconds")
    return d


def _api_csrf_ok():
    return _check_csrf(request.headers.get("X-CSRF-Token", ""))


@app.get("/api/users/search")
@login_required
def api_user_search():
    # 不限流就能用学号遍历整个名单查姓名
    if not _hit(f"search:{session['uid']}", 60, 3600):
        return jsonify(error="查询过于频繁，请稍后再试"), 429

    no = (request.args.get("no") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{6,20}", no):
        return jsonify(error="学号格式不正确"), 400

    u = db.search_user_by_no(no, session["uid"])
    if not u:
        return jsonify(found=False)

    return jsonify(found=True, user={
        "id": u["id"],
        "student_no": u["student_no"],
        "nickname": u["nickname"],
        "real_name": u["real_name"],
        "is_friend": db.is_friend(session["uid"], u["id"]),
    })


@app.post("/api/friends/request")
@login_required
def api_friend_request():
    if not _api_csrf_ok():
        return jsonify(error="CSRF 校验失败"), 403
    if not _hit(f"fr:{session['uid']}", 20, 3600):
        return jsonify(error="操作过于频繁，稍后再试"), 429

    d = request.get_json(silent=True) or {}
    no = (d.get("student_no") or "").strip()
    note = (d.get("note") or "").strip()

    u = db.search_user_by_no(no, session["uid"])
    if not u:
        return jsonify(error="没有找到该学号的成员"), 404

    ok, msg = db.send_friend_request(session["uid"], u["id"], note)
    return jsonify(ok=ok, message=msg), (200 if ok else 400)


@app.get("/api/friends/requests")
@login_required
def api_friend_requests():
    rows = db.pending_requests(session["uid"])
    return jsonify(requests=[{
        "id": r["id"],
        "from_id": r["from_id"],
        "note": r["note"] or "",
        "nickname": r["nickname"],
        "real_name": r["real_name"],
        "student_no": r["student_no"],
        "at": r["created_at"].isoformat(sep=" ", timespec="minutes"),
    } for r in rows])


@app.post("/api/friends/handle")
@login_required
def api_friend_handle():
    if not _api_csrf_ok():
        return jsonify(error="CSRF 校验失败"), 403

    d = request.get_json(silent=True) or {}
    try:
        req_id = int(d.get("id") or 0)
    except (TypeError, ValueError):
        return jsonify(error="参数错误"), 400

    ok = db.handle_request(req_id, session["uid"], bool(d.get("accept")))
    if not ok:
        return jsonify(error="申请不存在或已处理"), 404
    return jsonify(ok=True)


@app.get("/api/friends")
@login_required
def api_friends():
    return jsonify(friends=[_row_dict(r) for r in db.list_friends(session["uid"])])


@app.post("/api/friends/remove")
@login_required
def api_friend_remove():
    if not _api_csrf_ok():
        return jsonify(error="CSRF 校验失败"), 403
    d = request.get_json(silent=True) or {}
    try:
        fid = int(d.get("id") or 0)
    except (TypeError, ValueError):
        return jsonify(error="参数错误"), 400
    n = db.remove_friend(session["uid"], fid)
    return jsonify(ok=True, removed=n)


@app.get("/api/conversations")
@login_required
def api_conversations():
    items = []
    for r in db.list_conversations(session["uid"]):
        d = _row_dict(r)
        d["last_text"] = (d.get("last_text") or "")[:60]
        items.append(d)
    return jsonify(items=items)


@app.get("/api/messages")
@login_required
def api_messages():
    try:
        conv_id = int(request.args.get("conv") or 0)
        after = int(request.args.get("after") or 0)
    except ValueError:
        return jsonify(error="参数错误"), 400

    c = db.get_conversation(conv_id)
    if not c or session["uid"] not in (c["user_a"], c["user_b"]):
        return jsonify(error="会话不存在"), 404

    # 先标记已读再查，否则返回的第一批消息 read_at 仍是空的
    if not after:
        db.mark_read(conv_id, session["uid"])

    rows = db.list_messages(conv_id, after)

    return jsonify(messages=[_row_dict(r) for r in rows],
                   me=session["uid"])


@app.post("/api/messages")
@login_required
def api_send_message():
    if not _api_csrf_ok():
        return jsonify(error="CSRF 校验失败"), 403
    if not _hit(f"msg:{session['uid']}", 120, 60):
        return jsonify(error="发送太快了，歇一下"), 429

    d = request.get_json(silent=True) or {}
    try:
        conv_id = int(d.get("conv") or 0)
    except (TypeError, ValueError):
        return jsonify(error="参数错误"), 400

    content = (d.get("content") or "").strip()
    if not content:
        return jsonify(error="消息不能为空"), 400
    if len(content) > 2000:
        return jsonify(error="单条消息不能超过 2000 字"), 400

    c = db.get_conversation(conv_id)
    if not c or session["uid"] not in (c["user_a"], c["user_b"]):
        return jsonify(error="会话不存在"), 404

    mid = db.add_im_message(conv_id, session["uid"], content)
    return jsonify(ok=True, id=mid,
                   at=time.strftime("%Y-%m-%d %H:%M:%S"))


@app.post("/api/messages/read")
@login_required
def api_mark_read():
    if not _api_csrf_ok():
        return jsonify(error="CSRF 校验失败"), 403
    d = request.get_json(silent=True) or {}
    try:
        conv_id = int(d.get("conv") or 0)
    except (TypeError, ValueError):
        return jsonify(error="参数错误"), 400

    c = db.get_conversation(conv_id)
    if not c or session["uid"] not in (c["user_a"], c["user_b"]):
        return jsonify(error="会话不存在"), 404

    return jsonify(ok=True, marked=db.mark_read(conv_id, session["uid"]))


# ---------- 个人中心 ----------

# ---------- 头像 ----------

AVATAR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "var", "avatar")
os.makedirs(AVATAR_DIR, exist_ok=True)
AVATAR_MAX = 8 * 1024 * 1024        # 8MB，与前端校验一致
AVATAR_ALLOW = {"image/jpeg", "image/jpg", "image/png", "image/webp"}


@app.post("/me/avatar")
@login_required
def upload_avatar():
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)
    if not _hit(f"avatar:{session['uid']}", 10, 3600):
        return redirect(url_for("profile", e="上传过于频繁，请稍后再试"))

    f = request.files.get("avatar")
    if not f or not f.filename:
        return redirect(url_for("profile", e="请选择图片"))

    if f.mimetype not in AVATAR_ALLOW:
        return redirect(url_for("profile", e="只支持 JPG / PNG / WebP 格式"))

    data = f.read()
    if len(data) > AVATAR_MAX:
        return redirect(url_for("profile", e="图片不能超过 8MB"))

    from PIL import Image, ImageOps

    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        return redirect(url_for("profile", e="图片无法解析，请换一张"))

    if im.width < 80 or im.height < 80:
        return redirect(url_for("profile", e="图片太小，短边至少 40 像素"))
    if im.width * im.height > 40_000_000:
        return redirect(url_for("profile", e="图片像素过大，请压缩后重试"))

    # 居中裁成正方形，避免把人像拉变形
    im = ImageOps.fit(im.convert("RGB"), (320, 320), Image.LANCZOS, centering=(0.5, 0.38))
    name = f"u{session['uid']}_{secrets.token_hex(6)}.webp"
    im.save(os.path.join(AVATAR_DIR, name), "WEBP", quality=90, method=6)

    db.set_avatar(session["uid"], url_for("avatar_file", name=name))

    # 删掉该用户更早的头像
    for old in os.listdir(AVATAR_DIR):
        if old.startswith(f"u{session['uid']}_") and old != name:
            try:
                os.remove(os.path.join(AVATAR_DIR, old))
            except OSError:
                pass

    app.logger.info("用户更新头像 uid=%s file=%s", session["uid"], name)
    return redirect(url_for("profile", ok="头像已更新"))


@app.post("/api/pet/avatar")
@login_required
def upload_cropped_avatar():
    """接收浏览器端 Cropper.js 裁好的 320×320 图，服务端只做校验与落盘。"""
    from PIL import Image, ImageOps

    if not _check_csrf(request.form.get("csrf", "")):
        return jsonify(error="CSRF 校验失败"), 403
    if not _hit(f"avatar:{session['uid']}", 10, 3600):
        return jsonify(error="上传过于频繁"), 429

    f = request.files.get("avatar")
    if not f:
        return jsonify(error="没有收到图片"), 400

    data = f.read()
    if len(data) > AVATAR_MAX:
        return jsonify(error="图片不能超过 8MB"), 400

    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        return jsonify(error="图片无法解析"), 400

    # 前端裁过，这里兜底再 fit 一次，防止伪造请求塞非正方形图
    im = ImageOps.fit(im.convert("RGB"), (320, 320), Image.LANCZOS)
    name = f"u{session['uid']}_{secrets.token_hex(6)}.webp"
    im.save(os.path.join(AVATAR_DIR, name), "WEBP", quality=90, method=6)

    db.set_avatar(session["uid"], url_for("avatar_file", name=name))

    for old in os.listdir(AVATAR_DIR):
        if old.startswith(f"u{session['uid']}_") and old != name:
            try:
                os.remove(os.path.join(AVATAR_DIR, old))
            except OSError:
                pass

    app.logger.info("用户更新头像（前端裁剪）uid=%s file=%s", session["uid"], name)
    return jsonify(ok=True, url=url_for("avatar_file", name=name))


@app.post("/me/avatar/delete")
@login_required
def delete_avatar():
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)
    db.set_avatar(session["uid"], None)
    return redirect(url_for("profile", ok="已恢复默认头像"))


@app.get("/avatar/<name>")
def avatar_file(name):
    from flask import send_from_directory

    if not re.fullmatch(r"u\d+_[0-9a-f]{12}\.webp", name):
        abort(404)
    return send_from_directory(AVATAR_DIR, name, max_age=86400)


@app.get("/me")
@login_required
def profile():
    user = db.get_user(session["uid"])
    if not user:
        session.clear()
        return redirect(url_for("login_page"))
    return render_template("profile.html", csrf=_csrf(), user=user,
                           total=db.user_count(),
                           my_key=db.get_user_key(user["id"]),
                           err=request.args.get("e"), ok=request.args.get("ok"))


def _probe_api_key(api_key, base_url):
    """用一次极小的请求验证 key 是否可用。"""
    try:
        r = requests.post(
            (base_url or AI_BASE) + "/chat/completions",
            headers={"Authorization": "Bearer " + api_key},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
                "stream": False,
            },
            timeout=15,
        )
        if r.status_code == 200:
            return True, ""
        if r.status_code in (401, 403):
            return False, "密钥无效或没有权限"
        if r.status_code == 402:
            return False, "账户余额不足"
        return False, f"服务返回 {r.status_code}"
    except requests.Timeout:
        return False, "连接超时"
    except Exception as e:
        return False, f"连接失败：{type(e).__name__}"


@app.post("/me/api-key")
@login_required
def save_api_key():
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)

    api_key = (request.form.get("api_key") or "").strip()
    base_url = (request.form.get("base_url") or "").strip() or None
    model = (request.form.get("model") or "").strip() or None

    if not api_key:
        return redirect(url_for("profile", e="请填写 API Key"))
    if len(api_key) < 20 or len(api_key) > 200:
        return redirect(url_for("profile", e="API Key 长度不正确"))
    if not re.fullmatch(r"[A-Za-z0-9_\-\.]+", api_key):
        return redirect(url_for("profile", e="API Key 含有非法字符"))
    if base_url and not re.fullmatch(r"https?://[^\s]{4,180}", base_url):
        return redirect(url_for("profile", e="Base URL 格式不正确"))

    if not _hit(f"keyprobe:{session['uid']}", 8, 3600):
        return redirect(url_for("profile", e="验证过于频繁，请稍后再试"))

    ok, why = _probe_api_key(api_key, base_url)
    if not ok:
        return redirect(url_for("profile", e=f"密钥验证失败：{why}"))

    enc = secret_box.encrypt(app.config["SECRET_KEY"], api_key)
    db.save_user_key(session["uid"], enc, secret_box.mask(api_key), base_url, model)
    app.logger.info("用户保存自带 API Key uid=%s hint=%s",
                    session["uid"], secret_box.mask(api_key))
    return redirect(url_for("profile", ok="API Key 已保存并验证通过"))


@app.post("/me/api-key/delete")
@login_required
def delete_api_key():
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)
    db.delete_user_key(session["uid"])
    app.logger.info("用户删除自带 API Key uid=%s", session["uid"])
    return redirect(url_for("profile", ok="API Key 已删除"))


@app.post("/me/nickname")
@login_required
def change_nickname():
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)

    nick = (request.form.get("nickname") or "").strip()
    if not NICK_RE.match(nick):
        return redirect(url_for("profile", e="昵称格式不正确"))

    taken = db.is_taken(nickname=nick)
    if taken and taken["nickname"] == nick:
        return redirect(url_for("profile", e="该昵称已被占用"))

    db.update_nickname(session["uid"], nick)
    return redirect(url_for("profile", ok="昵称已更新"))


@app.post("/me/password")
@login_required
def change_password():
    if not _check_csrf(request.form.get("csrf", "")):
        abort(400)

    old = request.form.get("old") or ""
    new = request.form.get("new") or ""
    new2 = request.form.get("new2") or ""

    cur_hash = db.get_password_hash(session["uid"])
    if not cur_hash or not check_password_hash(cur_hash, old):
        return redirect(url_for("profile", e="当前密码不正确"))
    if len(new) < 8 or len(new) > 64:
        return redirect(url_for("profile", e="新密码长度需为 8–64 位"))
    if not (re.search(r"[A-Za-z]", new) and re.search(r"\d", new)):
        return redirect(url_for("profile", e="新密码需同时包含字母和数字"))
    if new != new2:
        return redirect(url_for("profile", e="两次输入的新密码不一致"))
    if new == old:
        return redirect(url_for("profile", e="新密码不能与当前密码相同"))

    db.update_password(session["uid"], generate_password_hash(new))
    app.logger.info("用户修改密码 uid=%s", session["uid"])
    session.clear()          # 改密后强制重新登录
    return redirect(url_for("login_page", pw=1))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8081, debug=False)
