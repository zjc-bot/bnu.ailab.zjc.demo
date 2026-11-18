"""部署 BNU AI Lab 注册系统到 ECS。

端口 8081，仅监听回环，经 SSH 隧道访问：ssh -L 8082:127.0.0.1:8081
"""

import glob
import os
import secrets

import paramiko

HOST = os.environ.get("DEPLOY_HOST", "47.118.28.10")
KEY = os.path.expanduser("~/.ssh/id_rsa")

# 凭据只从环境变量读取，不写进源码。
# 用法：MYSQL_PW=xxx DB_PW=yyy python deploy/deploy.py
MYSQL_PW = os.environ.get("MYSQL_PW", "")
DB_PW = os.environ.get("DB_PW", "")

if not MYSQL_PW or not DB_PW:
    raise SystemExit(
        "缺少凭据环境变量。请设置 MYSQL_PW（MySQL root 密码）"
        "和 DB_PW（应用数据库密码）后重试。"
    )

LOCAL = r"D:\MySQL\register"
REMOTE = "/opt/bnu-register"
SKIP = {"__pycache__", ".git", "deploy", "tests"}

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, 22, "root", pkey=paramiko.RSAKey.from_private_key_file(KEY), timeout=20)


def run(cmd, t=300):
    i, o, e = c.exec_command(cmd, timeout=t)
    return (o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")).strip()


def mysql(sql, t=120):
    q = sql.replace("\\", "\\\\").replace("'", "'\\''").replace('"', '\\"')
    return run(f"""mysql -uroot -p'{MYSQL_PW}' -N -B -e "{q}" 2>&1""", t)


print("=== 1. 建表（全部 schema）===")
# schema.sql 含基础用户表，必须最先；其余按文件名排序保证可重复执行。
schemas = sorted(glob.glob(os.path.join(LOCAL, "schema*.sql")))
schemas.sort(key=lambda p: (os.path.basename(p) != "schema.sql", p))
if not schemas:
    raise SystemExit("未找到 schema*.sql，终止部署。")
sftp = c.open_sftp()
for path in schemas:
    name = os.path.basename(path)
    remote_tmp = f"/tmp/reg_{name}"
    sftp.put(path, remote_tmp)
    out = run(f"mysql -uroot -p'{MYSQL_PW}' < {remote_tmp} 2>&1; rm -f {remote_tmp}", 120)
    print(f"  {name}: {out or 'OK'}")
sftp.close()
print("  表:", mysql("SHOW TABLES FROM school"))

print("\n=== 2. 授权 ===")
# 应用账号需要对全部业务表有 DML 权限。逐表授权，避免用 school.* 放权过宽。
TABLES = [
    "app_user", "email_code", "admin_user", "access_log",
    "chat_message", "ai_usage", "ai_config", "user_ai_key",
    "friend_request", "friend", "conversation", "message",
    "password_reset", "login_log",
]
for t in TABLES:
    mysql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON school.{t} TO 'studentapp'@'127.0.0.1'")
mysql("FLUSH PRIVILEGES")
print(mysql("SHOW GRANTS FOR 'studentapp'@'127.0.0.1'"))

print("\n=== 3. 系统用户 ===")
print(run("id -u regweb >/dev/null 2>&1 || useradd --system --no-create-home "
          "--shell /usr/sbin/nologin regweb; id regweb"))

print("\n=== 4. 上传代码 ===")
run(f"mkdir -p {REMOTE}")

def ensure(path):
    parts = path.strip("/").split("/")
    cur = ""
    for p in parts:
        cur += "/" + p
        try:
            sftp2 = c.open_sftp(); sftp2.stat(cur); sftp2.close()
        except IOError:
            sftp2 = c.open_sftp(); sftp2.mkdir(cur); sftp2.close()

sftp = c.open_sftp()
n = 0
for root, dirs, files in os.walk(LOCAL):
    dirs[:] = [d for d in dirs if d not in SKIP]
    rel = os.path.relpath(root, LOCAL).replace("\\", "/")
    rdir = REMOTE if rel == "." else f"{REMOTE}/{rel}"
    ensure(rdir)
    for f in files:
        if f.endswith((".pyc", ".pyo")):
            continue
        sftp.put(os.path.join(root, f), f"{rdir}/{f}")
        n += 1
sftp.close()
print(f"  上传 {n} 个文件")

print("\n=== 5. 虚拟环境 ===")
print(run(f"cd {REMOTE} && python3 -m venv venv 2>&1 | tail -2", 180) or "  venv 就绪")
out = run(f"cd {REMOTE} && ./venv/bin/pip install -q -r requirements.txt 2>&1 | tail -3", 600)
print(out or "  依赖安装完成")
print("  " + run(f"cd {REMOTE} && ./venv/bin/python -c \"import flask,PIL,pymysql;print('flask',flask.__version__,'| Pillow',PIL.__version__)\""))

print("\n=== 6. 生成 .env ===")
secret = secrets.token_hex(32)
env = f"""DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=studentapp
DB_PASSWORD={DB_PW}
DB_NAME=school
SECRET_KEY={secret}
SMTP_HOST=smtp.mail.bnu.edu.cn
SMTP_PORT=465
SMTP_USER=
SMTP_PASS=
SMTP_FROM_NAME=BNU AI Lab
COOKIE_SECURE=0
"""
sftp = c.open_sftp()
with sftp.file("/tmp/reg.env", "w") as f:
    f.write(env)
sftp.close()
print(run(f"install -m 600 -o regweb -g regweb /tmp/reg.env {REMOTE}/.env && rm -f /tmp/reg.env && ls -l {REMOTE}/.env"))

print("\n=== 7. systemd ===")
unit = """[Unit]
Description=BNU AI Lab Registration
After=network-online.target mysqld.service
Wants=network-online.target

[Service]
Type=simple
User=regweb
Group=regweb
WorkingDirectory=/opt/bnu-register
EnvironmentFile=/opt/bnu-register/.env
# 注意：当前为同步 worker，WebSocket 会退化成长轮询（HTTP 长轮询仍可用）。
# 若要启用原生 WebSocket 对战，需 hi 确认后改为：
#   gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker \
#            -w 1 --timeout 0 --bind 127.0.0.1:8081 app:app
# 同时 nginx 需加 /socket.io 的 Upgrade 头（见总纲 §9 Phase 2）。
ExecStart=/opt/bnu-register/venv/bin/gunicorn --workers 1 --threads 4 --bind 127.0.0.1:8081 --timeout 30 --access-logfile - --error-logfile - app:app
Restart=on-failure
RestartSec=3
UMask=0077

NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/opt/bnu-register
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictNamespaces=yes
LockPersonality=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
SystemCallFilter=@system-service
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target
"""
sftp = c.open_sftp()
with sftp.file("/tmp/reg.service", "w") as f:
    f.write(unit)
sftp.close()
print(run("install -m 644 /tmp/reg.service /etc/systemd/system/bnu-register.service && "
          "rm -f /tmp/reg.service && chown -R root:root /opt/bnu-register && "
          "systemctl daemon-reload && systemctl enable --now bnu-register >/dev/null 2>&1; "
          "sleep 3; systemctl is-active bnu-register", 120))

print("\n=== 8. 验证 ===")
print("  监听:", run("ss -lntp | grep 8081 || echo '未监听'"))
for path in ["/register", "/privacy", "/login", "/captcha.png"]:
    code = run(f"curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:8081{path}")
    print(f"  {path:14s} {code}")
print("\n  最近日志:")
print(run("journalctl -u bnu-register -n 8 --no-pager | tail -8"))

c.close()
print("\n完成")
