"""本地自测：不连数据库，只验证认证、CSRF、安全头、模板渲染。"""

import os
import re
import sys

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

print(f"\n结果：{ok} 通过 / {fail} 失败")
sys.exit(1 if fail else 0)
