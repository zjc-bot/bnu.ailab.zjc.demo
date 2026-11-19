"""增量部署游戏子系统到服务器。

安全约束：
  - 不重新生成 .env（保留现有 SECRET_KEY、SITE_URL、SMTP 配置）
  - 不重跑全量 schema，只建缺失的 game_record 表
  - 不改 systemd worker 类型（保持同步 gthread，Socket.IO 走长轮询）
  - 部署前已在服务器做代码 + 数据库备份
"""

import os
import paramiko

HOST = os.environ.get("DEPLOY_HOST", "47.118.28.10")
KEY = os.path.expanduser("~/.ssh/id_rsa")
MYSQL_PW = os.environ.get("MYSQL_PW", "")
if not MYSQL_PW:
    raise SystemExit("缺少 MYSQL_PW 环境变量")

LOCAL = r"D:\MySQL\register"
REMOTE = "/opt/bnu-register"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, 22, "root", pkey=paramiko.RSAKey.from_private_key_file(KEY), timeout=20)


def run(cmd, t=300):
    i, o, e = c.exec_command(cmd, timeout=t)
    return (o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")).strip()


def mysql(sql, t=120):
    # 直接把 SQL 写进临时文件执行，避免 shell 层引号转义破坏 GRANT 语句
    sftp = c.open_sftp()
    with sftp.file("/tmp/_dml.sql", "w") as f:
        f.write(sql + ";\n")
    sftp.close()
    out = run(f"mysql -uroot -p'{MYSQL_PW}' < /tmp/_dml.sql 2>&1; rm -f /tmp/_dml.sql", t)
    return out


print("=== 1. 建 game_record 表（幂等）===")
sftp = c.open_sftp()
sftp.put(os.path.join(LOCAL, "schema_game.sql"), "/tmp/game_schema.sql")
sftp.close()
print(" ", run(f"mysql -uroot -p'{MYSQL_PW}' < /tmp/game_schema.sql 2>&1 | grep -v Warning; rm -f /tmp/game_schema.sql") or "OK")
print("  确认:", mysql("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='school' AND table_name='game_record'"))

print("\n=== 2. 授权 app_user 对 game_record ===")
mysql("GRANT SELECT, INSERT, UPDATE, DELETE ON school.game_record TO 'studentapp'@'127.0.0.1'")
mysql("FLUSH PRIVILEGES")
print("  完成")

print("\n=== 3. 上传新增/变更文件 ===")
FILES = [
    "app.py", "db.py", "admin.py", "requirements.txt",
    "games/__init__.py", "games/events.py", "games/manager.py",
    "games/rules/__init__.py", "games/rules/gomoku.py",
    "static/game.js", "static/socket.io/socket.io.min.js",
    "templates/games.html",
    "templates/home.html", "templates/profile.html",
    "static/im.js", "static/im.css", "static/avatar-crop.js", "static/style.css",
]
sftp = c.open_sftp()
for rel in FILES:
    src = os.path.join(LOCAL, rel.replace("/", os.sep))
    dst = f"{REMOTE}/{rel}"
    folder = os.path.dirname(dst)
    cur = ""
    for part in folder.strip("/").split("/"):
        cur += "/" + part
        try:
            sftp.stat(cur)
        except IOError:
            sftp.mkdir(cur)
    sftp.put(src, dst)
    print(f"  {rel}")
sftp.close()

print("\n=== 4. 安装新依赖 ===")
out = run(f"cd {REMOTE} && ./venv/bin/pip install -q -r requirements.txt 2>&1 | tail -5", 600)
print(" ", out or "OK")
print("  校验:", run(f"cd {REMOTE} && ./venv/bin/python -c \"import flask_socketio,gevent;print('socketio',flask_socketio.__version__,'gevent',gevent.__version__)\""))

print("\n=== 5. 保留 .env，仅确认存在 ===")
print(" ", run(f"ls -l {REMOTE}/.env && grep -c '^SECRET_KEY=' {REMOTE}/.env"))

print("\n=== 6. 重启服务 ===")
print(" ", run("chown -R root:root /opt/bnu-register && "
               "chown -R regweb:regweb /opt/bnu-register/var && "
               "systemctl restart bnu-register && sleep 4 && systemctl is-active bnu-register", 120))

print("\n=== 7. 验证 ===")
print("  监听:", run("ss -lntp | grep 8081 | awk '{print $4}'"))
for path in ["/login", "/register", "/captcha.png", "/static/socket.io/socket.io.min.js",
             "/static/game.js", "/games"]:
    code = run(f"curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:8081{path}")
    print(f"    {path:42s} {code}")
print("\n  错误日志:")
print(run("journalctl -u bnu-register -n 30 --no-pager | grep -iE 'error|traceback' | tail -5") or "  无")

c.close()
print("\n完成")
