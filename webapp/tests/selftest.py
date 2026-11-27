"""本地自测：不连数据库/服务器，验证应用与部署安全回归。"""

import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

os.environ["APP_USER"] = "admin"
os.environ["APP_PASSWORD_HASH"] = (
    "scrypt:32768:8:1$jxmqUpYIfHr98WqS$"
    "353a1da372889bb27d9bf74164ddd663c55bbf94a92e77ba16a8ef2fde1f2348c8d3416824e8e29db95aa0890376887ec2fb818326fc7b56e3bcd947c55ab9bc"
)
os.environ["SECRET_KEY"] = "selftest-secret"
os.environ["DB_USER"] = "dummy"
os.environ["DB_PASSWORD"] = "dummy"
os.environ["COOKIE_SECURE"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as A  # noqa: E402

ok = 0
fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name} {extra}")


def csrf_of(html):
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    return m.group(1) if m else ""


print("[1] 未登录访问控制")
c = A.app.test_client()
r = c.get("/login")
check("GET /login = 200", r.status_code == 200, r.status_code)
check("返回 CSP 头", "default-src 'self'" in r.headers.get("Content-Security-Policy", ""))
check("返回 X-Frame-Options", r.headers.get("X-Frame-Options") == "DENY")
check("无 X-Powered-By", "X-Powered-By" not in r.headers)

r = c.get("/")
check("GET / 未登录重定向", r.status_code == 302, r.status_code)

r = c.get("/api/students")
check("GET /api/students 未登录 = 401", r.status_code == 401, r.status_code)

print("[2] CSRF 防护")
r = c.post("/login", data={"user": "admin", "pass": "test123", "csrf": "bogus"})
check("伪造 CSRF 被拒", r.status_code == 400, r.status_code)

print("[3] 登录")
html = c.get("/login").get_data(as_text=True)
token = csrf_of(html)
check("登录页含 csrf token", bool(token))

r = c.post("/login", data={"user": "admin", "pass": "wrong", "csrf": token})
check("错误密码不放行", r.status_code == 200 and "用户名或密码错误" in r.get_data(as_text=True))

html = c.get("/login").get_data(as_text=True)
token = csrf_of(html)
r = c.post("/login", data={"user": "admin", "pass": "test123", "csrf": token})
check("正确密码登录成功", r.status_code == 302, r.status_code)

r = c.get("/")
body = r.get_data(as_text=True)
check("登录后 GET / = 200", r.status_code == 200, r.status_code)
check("页面含统计区", "stat-total" in body)
check("页面含表格", "student_no" in body or "学号" in body)

print("[4] 暴力破解锁定")
c3 = A.app.test_client()
for i in range(6):
    h = c3.get("/login").get_data(as_text=True)
    t = csrf_of(h)
    rr = c3.post("/login", data={"user": "admin", "pass": f"bad{i}", "csrf": t})
    last = rr.get_data(as_text=True)
check("第 6 次触发锁定", "尝试次数过多" in last)

print("[5] 登出")
h = c.get("/").get_data(as_text=True)
t = csrf_of(h)
r = c.post("/logout", data={"csrf": t})
check("登出后重定向", r.status_code == 302)
r = c.get("/")
check("登出后无法访问首页", r.status_code == 302)

print("[6] 部署安全回归（不连服务器）")
with A.app.test_client() as client:
    client.get(
        "/login", headers={"X-Forwarded-For": "198.51.100.7"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    check("ProxyFix 使用覆盖后的客户端 IP",
          A.request.remote_addr == "198.51.100.7", A.request.remote_addr)

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
nginx_files = sorted(DEPLOY.glob("nginx*.conf"))
check("覆盖全部 webapp Nginx 模板", len(nginx_files) == 2)
for path in nginx_files:
    text = path.read_text(encoding="utf-8")
    headers = re.findall(r"proxy_set_header\s+X-Forwarded-For\s+([^;]+);", text)
    check(f"{path.name} 禁止追加 XFF", "proxy_add_x_forwarded_for" not in text)
    check(f"{path.name} 所有 XFF 均覆盖为远端地址",
          len(headers) == 2 and all(h.strip() == "$remote_addr" for h in headers), headers)
    listeners = re.findall(r"^\s*listen\s+([^;]+);", text, re.MULTILINE)
    check(f"{path.name} 仅绑定回环 80",
          listeners and all(v.split()[0] in {"127.0.0.1:80", "[::1]:80"} for v in listeners), listeners)

spec = importlib.util.spec_from_file_location("student_web_deploy", DEPLOY / "deploy.py")
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)


def preflight_case(files="", users="0", file_rc=0, db_rc=0):
    old_run, old_mysql = D.run, D.mysql
    D.run = lambda *a, **k: (files, "", file_rc)
    D.mysql = lambda *a, **k: (users, db_rc)
    try:
        D.preflight(object())
        return ""
    except SystemExit as exc:
        return str(exc)
    finally:
        D.run, D.mysql = old_run, old_mysql


check("空环境预检通过", preflight_case() == "")
for marker in ("/opt/student-web/.env", "/etc/nginx/conf.d/student-web.conf",
               "/etc/systemd/system/student-web.service"):
    check(f"已有配置 {marker} 触发熔断", marker in preflight_case(files=marker + "\n"))
check("已有 studentapp 触发熔断",
      "database user: studentapp" in preflight_case(users="1"))
check("数据库用户状态未知时熔断", "无法确认" in preflight_case(users="", db_rc=1))
check("文件预检失败时熔断", "无法完成" in preflight_case(file_rc=1))

LISTENERS = (
    "LISTEN 0 128 127.0.0.1:80 0.0.0.0:*\n"
    "LISTEN 0 128 127.0.0.1:8080 0.0.0.0:*\n"
)


def verify_case(service_rc=0, nginx_rc=0, syntax_rc=0, listeners=LISTENERS,
                root_code="302", login_code="200"):
    old_run = D.run

    def fake_run(c, cmd, timeout=30, stdin_text=None):
        if cmd == "systemctl is-active --quiet student-web":
            return "", "inactive", service_rc
        if cmd == "systemctl is-active --quiet nginx":
            return "", "inactive", nginx_rc
        if cmd == "nginx -t":
            return "", "bad config", syntax_rc
        if cmd == "ss -H -lnt":
            return listeners, "", 0
        if cmd.endswith("http://127.0.0.1/"):
            return root_code, "", 0
        if cmd.endswith("http://127.0.0.1/login"):
            return login_code, "", 0
        raise AssertionError(cmd)

    D.run = fake_run
    try:
        D.verify(object())
        return ""
    except SystemExit as exc:
        return str(exc)
    finally:
        D.run = old_run


check("完整部署验收通过", verify_case() == "")
check("应用服务失活阻止完成", "student-web" in verify_case(service_rc=3))
check("nginx 服务失活阻止完成", "nginx systemd" in verify_case(nginx_rc=3))
check("nginx 语法失败阻止完成", "nginx 配置语法" in verify_case(syntax_rc=1))
check("公网 80 监听阻止完成", "监听端口" in verify_case(
    listeners=LISTENERS + "LISTEN 0 128 0.0.0.0:80 0.0.0.0:*\n"))
check("缺少回环监听阻止完成", "监听端口" in verify_case(listeners=""))
check("登录页 500 阻止完成", "登录页响应" in verify_case(login_code="500"))
check("首页非预期响应阻止完成", "首页跳转" in verify_case(root_code="200"))

install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
deploy_source = (DEPLOY / "deploy.py").read_text(encoding="utf-8")
check("安装器拒绝 --force", "本脚本不支持 --force" in install)
check("部署器拒绝 --force", "本脚本不支持 --force" in deploy_source)
check("安装器数据库预检先于建用户",
      install.index("SELECT COUNT(*) FROM mysql.user") < install.index("CREATE USER 'studentapp'"))
check("安装器不轮换 studentapp 密码",
      "ALTER USER 'studentapp'@'127.0.0.1' IDENTIFIED BY" not in install)
check("安装器不写 UFW", "ufw allow" not in install and "ufw enable" not in install)
check("部署器不回显密码", "登录密码：{WEB_PW}" not in deploy_source
      and "数据库账号：studentapp / {DB_PW}" not in deploy_source)
check("安装器允许预装 nginx 主配置", "/etc/nginx/nginx.conf" not in install)
check("部署器允许预装 nginx 主配置", "/etc/nginx/nginx.conf" not in deploy_source)

start = install.index("existing=()")
end = install.index('MYSQL_PW="${MYSQL_PW:?')
preflight = install[start:end]
with tempfile.TemporaryDirectory(prefix="webapp-preflight-") as tmp:
    root = Path(tmp).as_posix().rstrip("/")
    if re.match(r"^[A-Za-z]:/", root):
        root = "/" + root[0].lower() + root[2:]
    sandbox = preflight
    for prefix in ("/opt/", "/etc/", "/lib/", "/www/"):
        sandbox = sandbox.replace(prefix, root + prefix)

    bash = shutil.which("bash")
    if not bash:
        raise SystemExit("缺少 Bash，无法执行安装器只读预检回归。")

    def run_preflight():
        return subprocess.run(
            [bash, "-c", sandbox], capture_output=True, text=True, encoding="utf-8",
        )

    result = run_preflight()
    check("真实执行安装器只读预检：空环境通过", result.returncode == 0, result.stderr)
    marker = Path(tmp) / "opt/student-web/.env"
    marker.parent.mkdir(parents=True)
    marker.write_text("sentinel", encoding="utf-8")
    result = run_preflight()
    check("真实执行安装器只读预检：已有 .env 熔断",
          result.returncode != 0 and root + "/opt/student-web/.env" in result.stderr, result.stderr)
    marker.unlink()
    marker.parent.rmdir()
    default = Path(tmp) / "etc/nginx/sites-enabled/default"
    default.parent.mkdir(parents=True)
    default.write_text("default", encoding="utf-8")
    result = run_preflight()
    check("真实执行安装器只读预检：允许包默认站点", result.returncode == 0, result.stderr)
    default.unlink()
    custom = Path(tmp) / "etc/nginx/conf.d/custom.conf"
    custom.parent.mkdir(parents=True, exist_ok=True)
    custom.write_text("custom", encoding="utf-8")
    result = run_preflight()
    check("真实执行安装器只读预检：自定义站点熔断",
          result.returncode != 0 and root + "/etc/nginx/conf.d/custom.conf" in result.stderr, result.stderr)

print(f"\n结果：{ok} 通过 / {fail} 失败")
sys.exit(1 if fail else 0)
