import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar

BASE = "http://127.0.0.1:8080"
PASS = os.environ.get("APP_PASSWORD", "")
if not PASS:
    raise SystemExit("缺少 APP_PASSWORD 环境变量，请设置为应用登录密码后重试。")

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

h = op.open(BASE + "/login", timeout=10).read().decode()
t = re.search(r'name="csrf" value="([^"]+)"', h).group(1)
r = op.open(BASE + "/login",
            urllib.parse.urlencode({"user": "admin", "pass": PASS, "csrf": t}).encode(),
            timeout=10)
print("登录:", r.status, "->", r.url)


def j(p):
    try:
        return json.loads(op.open(BASE + p, timeout=10).read())
    except urllib.error.HTTPError as e:
        print(f"  [{p}] HTTP {e.code}")
        return None


d = j("/api/students?size=2")
if d:
    print("列表 total:", d["total"])
    print("首条:", json.dumps(d["items"][0], ensure_ascii=False))

s = j("/api/stats")
if s:
    print(f"统计: {s['total']} 人 / {s['majors']} 专业 / {s['dorms']} 寝室")
    print("专业分布:", [(m["major"], m["c"]) for m in s["by_major"]])

print("场次接口:", end=" ")
try:
    op.open(BASE + "/api/sessions", timeout=10)
    print("仍存在 ✗")
except urllib.error.HTTPError as e:
    print(e.code, "✓ 已移除")

# 编辑功能实测
item = j("/api/students?size=1")["items"][0]
page = op.open(BASE + "/", timeout=10).read().decode()
csrf = re.search(r'<meta name="csrf" content="([^"]+)"', page).group(1)
keys = ["student_no", "name", "gender", "major", "dorm_room", "phone", "email", "remark"]

mod = {k: item[k] for k in keys}
mod["remark"] = "编辑功能自测"
req = urllib.request.Request(
    BASE + "/api/students/" + str(item["id"]),
    data=json.dumps(mod).encode(),
    headers={"Content-Type": "application/json", "X-CSRF-Token": csrf},
    method="PUT")
print("PUT 编辑:", op.open(req, timeout=10).read().decode())

back = j("/api/students?size=1")["items"][0]
print("  读回备注:", back["remark"], "| 姓名:", back["name"], "| 寝室:", back["dorm_room"])

orig = {k: item[k] for k in keys}
req2 = urllib.request.Request(
    BASE + "/api/students/" + str(item["id"]),
    data=json.dumps(orig).encode(),
    headers={"Content-Type": "application/json", "X-CSRF-Token": csrf},
    method="PUT")
op.open(req2, timeout=10)
print("  已还原:", j("/api/students?size=1")["items"][0]["remark"])

print("\n页面检查:", {
    "寝室列": "寝室" in page,
    "场次列(应为False)": "场次" in page,
    "版本号v=3": "?v=3" in page,
    "寝室输入框": "f-dorm" in page,
})
