"""一键部署学生信息管理 Web 应用。

步骤：
  0. 只读预检；已有部署配置或 studentapp 用户即熔断
  1. SSH 登录，检查 school 库 / student 表
  2. 缺什么补什么（执行 school_student.sql）
  3. 上传代码到 /tmp/student-web-src
  4. 执行 install.sh（二次预检后才创建 studentapp）
  5. 验证服务

仅用于确认过的空环境，不提供 --force 绕过。
"""

import os
import re
import secrets
import shlex
import sys

HOST = "47.118.28.10"
USER = "root"
KEY = os.path.expanduser("~/.ssh/id_rsa")

# 凭据只从环境变量读取；通过 SSH stdin 传给远端，不进入远端命令行。
# 用法：预先设置 MYSQL_PW 与 WEB_PASSWORD，再执行 python deploy/deploy.py
MYSQL_ROOT_PW = os.environ.get("MYSQL_PW", "")
DB_PW = secrets.token_hex(16)
WEB_PW = os.environ.get("WEB_PASSWORD", "")
WEB_USER = "admin"

LOCAL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL_PATH = os.path.join(os.path.dirname(LOCAL_ROOT), "sql", "school_student.sql")
REMOTE_ROOT = "/tmp/student-web-src"
SKIP_DIRS = {"__pycache__", "tests", ".pytest_cache"}
EXISTING_PATHS = (
    "/opt/student-web",
    "/opt/student-web/.env",
    "/opt/bnu-register",
    "/opt/bnu-register/.env",
    "/etc/systemd/system/student-web.service",
    "/etc/systemd/system/student-web.service.d",
    "/etc/systemd/system/bnu-register.service",
    "/etc/systemd/system/bnu-register.service.d",
    "/lib/systemd/system/student-web.service",
    "/lib/systemd/system/bnu-register.service",
    "/www/server/panel/vhost/nginx/bnuailab.conf",
)


def connect():
    import paramiko

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


def run(c, cmd, timeout=120, stdin_text=None):
    stdin, out, err = c.exec_command(cmd, timeout=timeout, get_pty=False)
    if stdin_text is not None:
        stdin.write(stdin_text)
        stdin.flush()
        stdin.channel.shutdown_write()
    o = out.read().decode("utf-8", "replace")
    e = err.read().decode("utf-8", "replace")
    return o, e, out.channel.recv_exit_status()


def redact(text):
    """兜底过滤凭据，避免远端错误信息或日志把秘密带回控制台。"""
    for secret in (MYSQL_ROOT_PW, DB_PW, WEB_PW):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def mysql(c, sql, timeout=60):
    """用 root 执行一条 SQL；密码和 SQL 经 SSH stdin 传入。"""
    script = (
        "MYSQL_PWD=" + shlex.quote(MYSQL_ROOT_PW) + " mysql -uroot -N -B 2>&1 <<'SQL'\n"
        + sql
        + "\nSQL\n"
    )
    o, e, rc = run(c, "bash -s", timeout, stdin_text=script)
    return (o + e).strip(), rc


def preflight(c):
    """只读检查部署痕迹；任何不确定或已有配置都拒绝继续。"""
    checks = []
    for path in EXISTING_PATHS:
        checks.append(f"if [ -e {shlex.quote(path)} ] || [ -L {shlex.quote(path)} ]; "
                      f"then printf '%s\\n' {shlex.quote(path)}; fi")
    checks.append("if id -u studentweb >/dev/null 2>&1; "
                  "then printf '%s\\n' 'system user: studentweb'; fi")
    checks.append("if id -u regweb >/dev/null 2>&1; "
                  "then printf '%s\\n' 'system user: regweb'; fi")
    checks.append(
        "for path in /etc/nginx/conf.d/*.conf /etc/nginx/sites-enabled/* "
        "/etc/nginx/sites-available/* /www/server/panel/vhost/nginx/*.conf; do "
        "case \"$path\" in /etc/nginx/sites-enabled/default|"
        "/etc/nginx/sites-available/default) continue;; esac; "
        "if [ -e \"$path\" ] || [ -L \"$path\" ]; then printf '%s\\n' \"$path\"; fi; done"
    )
    out, err, rc = run(c, "; ".join(checks), 30)
    if rc != 0:
        raise SystemExit("熔断：无法完成服务器配置预检，拒绝部署。")
    existing = [line.strip() for line in (out + err).splitlines() if line.strip()]
    out, rc = mysql(c, "SELECT COUNT(*) FROM mysql.user WHERE User='studentapp'")
    if rc != 0 or not out.isdigit():
        raise SystemExit("熔断：无法确认 studentapp 数据库用户状态，拒绝部署。")
    if int(out) > 0:
        existing.append("database user: studentapp")
    if existing:
        raise SystemExit(
            "熔断：检测到已有部署配置，拒绝破坏性初始化（不使用 --force）：\n  - "
            + "\n  - ".join(existing)
            + "\n请对现有环境使用经审核的增量部署；本脚本不会轮换共享密码、"
              "重置 SECRET_KEY、覆盖 Nginx 或修改防火墙。"
        )


def verify(c):
    def checked(label, cmd, expected=None, timeout=30):
        out, err, rc = run(c, cmd, timeout)
        if rc != 0 or (expected is not None and out.strip() not in expected):
            detail = redact((out + err).strip()) or f"exit={rc}"
            raise SystemExit(f"熔断：{label}验收失败（{detail}），拒绝报告部署完成。")
        print(f"    {label}：通过")

    checked("student-web systemd 状态", "systemctl is-active --quiet student-web")
    checked("nginx systemd 状态", "systemctl is-active --quiet nginx")
    checked("nginx 配置语法", "nginx -t")
    out, err, rc = run(c, "ss -H -lnt", 30)
    if rc != 0:
        raise SystemExit("熔断：无法核验监听端口，拒绝报告部署完成。")
    listeners = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            listeners.add(parts[3])
    required = {"127.0.0.1:80", "127.0.0.1:8080"}
    public = {"0.0.0.0:80", "[::]:80", "0.0.0.0:8080", "[::]:8080"}
    if not required <= listeners or listeners & public:
        raise SystemExit(
            "熔断：监听端口不是预期的回环地址，拒绝报告部署完成："
            + ", ".join(sorted(listeners))
        )
    print("    监听端口：仅 127.0.0.1:80 与 127.0.0.1:8080")
    checked("未登录首页跳转", "curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1/", {"302"})
    checked("登录页响应", "curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1/login", {"200"})


def main():
    if len(sys.argv) > 1:
        raise SystemExit("本脚本不支持 --force；只允许在确认过的空环境部署。")
    if not MYSQL_ROOT_PW:
        raise SystemExit("缺少 MYSQL_PW 环境变量，请设置为 MySQL root 密码后重试。")

    c = connect()
    try:
        print("[0] 只读预检（在数据库/文件写入前熔断）")
        preflight(c)
        print("    未发现既有部署配置\n")
        if not WEB_PW:
            raise SystemExit("缺少 WEB_PASSWORD 环境变量，请设置网页登录密码后重试。")
        deploy(c)
    finally:
        c.close()


def deploy(c):
    print("SSH 已连接\n")

    print("[1] 检查数据库现状")
    out, rc = mysql(c, "SHOW DATABASES LIKE 'school'")
    if rc != 0:
        raise SystemExit("熔断：无法检查 school 数据库，拒绝继续。")
    has_db = "school" in out
    print(f"    school 库：{'存在' if has_db else '不存在'}")

    has_table = False
    if has_db:
        out, rc = mysql(c, "SHOW TABLES FROM school LIKE 'student'")
        if rc != 0:
            raise SystemExit("熔断：无法检查 student 表，拒绝继续。")
        has_table = "student" in out
        print(f"    student 表：{'存在' if has_table else '不存在'}")
        if has_table:
            out, rc = mysql(c, "SELECT COUNT(*) FROM school.student")
            if rc != 0:
                raise SystemExit("熔断：无法读取 student 表，拒绝继续。")
            print(f"    现有数据：{out} 条")

    print("\n[2] 补齐库表")
    if not has_db or not has_table:
        sftp = c.open_sftp()
        sftp.put(SQL_PATH, "/tmp/school_student.sql")
        sftp.close()
        script = (
            "MYSQL_PWD=" + shlex.quote(MYSQL_ROOT_PW)
            + " mysql -uroot < /tmp/school_student.sql 2>&1; "
              "rc=$?; rm -f /tmp/school_student.sql; exit $rc"
        )
        o, e, rc = run(c, "bash -s", 120, stdin_text=script)
        if rc != 0:
            raise SystemExit("熔断：school_student.sql 执行失败，拒绝继续。")
        print("    已执行 school_student.sql")
        out, rc = mysql(c, "SELECT COUNT(*) FROM school.student")
        if rc != 0:
            raise SystemExit("熔断：无法确认 student 表数据，拒绝继续。")
        print(f"    当前数据：{out} 条")
    else:
        print("    已存在，跳过")

    print("\n[3] 上传代码")
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

    print("\n[4] 执行部署脚本（装依赖可能需要 1-2 分钟）")
    script = (
        f"cd {shlex.quote(REMOTE_ROOT)}\n"
        f"export DB_PASSWORD={shlex.quote(DB_PW)}\n"
        f"export WEB_USER={shlex.quote(WEB_USER)}\n"
        f"export WEB_PASSWORD={shlex.quote(WEB_PW)}\n"
        f"export MYSQL_PW={shlex.quote(MYSQL_ROOT_PW)}\n"
        "exec bash deploy/install.sh 2>&1\n"
    )
    o, e, rc = run(c, "bash -s", timeout=600, stdin_text=script)
    for line in redact(o + e).splitlines():
        if line.strip():
            print("    " + line.rstrip())
    if rc != 0:
        raise SystemExit("熔断：install.sh 执行失败，拒绝报告部署完成。")

    print("\n[5] 验证")
    verify(c)

    print("\n[6] 服务日志（末尾 8 行）")
    o, _, _ = run(c, "journalctl -u student-web -n 8 --no-pager 2>&1", 30)
    for line in redact(o).splitlines():
        print("    " + line)

    print("\n" + "=" * 46)
    print(" 部署完成")
    print(" 访问方式：SSH 隧道 http://127.0.0.1:8080（不对公网开放）")
    print(f" 登录用户：{WEB_USER}")
    print(" 凭据未回显；登录密码为调用方设置的 WEB_PASSWORD。")
    print(" 数据库密码仅保存在 /opt/student-web/.env（权限 600）。")
    print("=" * 46)


if __name__ == "__main__":
    main()
