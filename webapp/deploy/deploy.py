"""一键部署学生信息管理 Web 应用。

步骤：
  1. SSH 登录，检查 school 库 / student 表
  2. 缺什么补什么（执行 school_student.sql）
  3. 创建最小权限数据库账号 studentapp
  4. 上传代码到 /tmp/student-web-src
  5. 执行 install.sh
  6. 验证服务
"""

import os
import secrets

import paramiko

HOST = "47.118.28.10"
USER = "root"
KEY = os.path.expanduser("~/.ssh/id_rsa")

# 凭据只从环境变量读取，不进命令行历史 / ps 输出。
# 用法：MYSQL_PW=xxx python deploy/deploy.py
MYSQL_ROOT_PW = os.environ.get("MYSQL_PW", "")
if not MYSQL_ROOT_PW:
    raise SystemExit("缺少 MYSQL_PW 环境变量，请设置为 MySQL root 密码后重试。")
DB_PW = secrets.token_hex(16)
WEB_PW = secrets.token_urlsafe(12)
WEB_USER = "admin"

LOCAL_ROOT = r"D:\MySQL\webapp"
REMOTE_ROOT = "/tmp/student-web-src"
SKIP_DIRS = {"__pycache__", "tests", ".pytest_cache"}


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        HOST,
        port=22,
        username=USER,
        pkey=paramiko.RSAKey.from_private_key_file(KEY),
        timeout=20,
        banner_timeout=30,
        auth_timeout=30,
    )
    return c


def run(c, cmd, timeout=120, password=None):
    stdin, out, err = c.exec_command(cmd, timeout=timeout, get_pty=False)
    if password is not None:
        stdin.write(password + "\n")
        stdin.flush()
    o = out.read().decode("utf-8", "replace")
    e = err.read().decode("utf-8", "replace")
    return o, e, out.channel.recv_exit_status()


def mysql(c, sql, timeout=60):
    """用 root 执行一条 SQL，返回 (stdout, stderr, rc)。"""
    safe = sql.replace("\\", "\\\\").replace("'", "'\\''")
    cmd = f"mysql -uroot -p'{MYSQL_ROOT_PW}' -N -B -e '{safe}' 2>&1"
    o, e, rc = run(c, cmd, timeout)
    return (o + e).strip(), rc


def main():
    c = connect()
    print("SSH 已连接\n")

    print("[1] 检查数据库现状")
    out, rc = mysql(c, "SHOW DATABASES LIKE 'school'")
    has_db = "school" in out
    print(f"    school 库：{'存在' if has_db else '不存在'}")

    has_table = False
    if has_db:
        out, rc = mysql(c, "SHOW TABLES FROM school LIKE 'student'")
        has_table = "student" in out
        print(f"    student 表：{'存在' if has_table else '不存在'}")
        if has_table:
            out, _ = mysql(c, "SELECT COUNT(*) FROM school.student")
            print(f"    现有数据：{out} 条")

    print("\n[2] 补齐库表")
    if not has_db or not has_table:
        sftp = c.open_sftp()
        sftp.put(r"D:\MySQL\sql\school_student.sql", "/tmp/school_student.sql")
        sftp.close()
        o, e, rc = run(
            c, f"mysql -uroot -p'{MYSQL_ROOT_PW}' < /tmp/school_student.sql 2>&1", 120
        )
        print("    已执行 school_student.sql，rc=", rc)
        if o.strip():
            print("   ", o.strip()[:300])
        out, _ = mysql(c, "SELECT COUNT(*) FROM school.student")
        print(f"    当前数据：{out} 条")
    else:
        print("    已存在，跳过")

    print("\n[3] 创建最小权限账号 studentapp")
    for sql in [
        f"CREATE USER IF NOT EXISTS 'studentapp'@'127.0.0.1' IDENTIFIED BY '{DB_PW}'",
        f"ALTER USER 'studentapp'@'127.0.0.1' IDENTIFIED BY '{DB_PW}'",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON school.student TO 'studentapp'@'127.0.0.1'",
        "ALTER USER 'studentapp'@'127.0.0.1' WITH MAX_USER_CONNECTIONS 20",
        "FLUSH PRIVILEGES",
    ]:
        out, rc = mysql(c, sql)
        if rc != 0 and "already exists" not in out:
            print("    失败：", sql[:60], "->", out[:200])

    out, _ = mysql(c, "SHOW GRANTS FOR 'studentapp'@'127.0.0.1'")
    print("    当前授权：")
    for line in out.splitlines():
        if line.strip():
            print("      " + line.strip())

    print("\n[4] 上传代码")
    sftp = c.open_sftp()

    def ensure(path):
        parts = path.strip("/").split("/")
        cur = ""
        for p in parts:
            cur += "/" + p
            try:
                sftp.stat(cur)
            except IOError:
                sftp.mkdir(cur)

    ensure(REMOTE_ROOT)
    n = 0
    for root, dirs, files in os.walk(LOCAL_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = os.path.relpath(root, LOCAL_ROOT).replace("\\", "/")
        rdir = REMOTE_ROOT if rel == "." else f"{REMOTE_ROOT}/{rel}"
        ensure(rdir)
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                continue
            sftp.put(os.path.join(root, f), f"{rdir}/{f}")
            n += 1
    sftp.close()
    print(f"    上传 {n} 个文件 -> {REMOTE_ROOT}")

    print("\n[5] 执行部署脚本（装依赖可能需要 1-2 分钟）")
    cmd = (
        f"cd {REMOTE_ROOT} && "
        f"DB_PASSWORD='{DB_PW}' WEB_USER='{WEB_USER}' WEB_PASSWORD='{WEB_PW}' "
        f"bash deploy/install.sh 2>&1"
    )
    o, e, rc = run(c, cmd, timeout=600)
    for line in (o + e).splitlines():
        if line.strip():
            print("    " + line.rstrip())
    print("    install.sh rc =", rc)

    print("\n[6] 验证")
    for label, cmd in [
        ("systemd 状态", "systemctl is-active student-web"),
        ("nginx 状态", "systemctl is-active nginx"),
        ("监听端口", "ss -lntp | grep -E ':80 |:8080 ' || echo none"),
        ("首页响应", "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/"),
        ("登录页响应", "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/login"),
        ("未登录跳转", "curl -s -o /dev/null -w '%{http_code} -> %{redirect_url}' http://127.0.0.1/"),
    ]:
        o, _, _ = run(c, cmd, 30)
        print(f"    {label}：{o.strip()}")

    print("\n[7] 服务日志（末尾 8 行）")
    o, _, _ = run(c, "journalctl -u student-web -n 8 --no-pager 2>&1", 30)
    for line in o.splitlines():
        print("    " + line)

    c.close()

    print("\n" + "=" * 46)
    print(" 部署完成")
    print(f" 访问地址：http://{HOST}/")
    print(f" 登录用户：{WEB_USER}")
    print(f" 登录密码：{WEB_PW}")
    print(f" 数据库账号：studentapp / {DB_PW}")
    print("=" * 46)


main()
