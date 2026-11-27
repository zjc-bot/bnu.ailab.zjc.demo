"""BNU AI Lab 增量部署：备份、迁移、暂存、切换、验收与回滚。

仅用于已有服务器；首次初始化仍使用 deploy.py。关键步骤失败时立即非零退出，
不会执行 schema_chat_migrate.sql 等含数据删除语句的历史迁移。
"""

import argparse
import os
import re
import secrets
import shlex

LOCAL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTE = "/opt/bnu-register"
LOCK_DIR = "/run/bnu-register-deploy.lock"
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", "deploy", "tests", "var"}
SOURCE_SUFFIXES = {
    ".py", ".sql", ".html", ".css", ".js", ".svg", ".png", ".jpg", ".jpeg",
    ".webp", ".ico", ".woff", ".woff2", ".json", ".txt",
}
SCHEMAS = (
    "schema_game.sql",
    "schema_message_v2.sql",
    "schema_game_ai.sql",
    "schema_admin_2fa.sql",
    "schema_idea.sql",
    "schema_tags.sql",
    "schema_category.sql",
    "schema_moderation.sql",
    "schema_profile.sql",
)
TABLE_GRANTS = {
    "app_user": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "email_code": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "admin_user": ("SELECT", "INSERT", "UPDATE"),
    "access_log": ("SELECT", "INSERT"),
    "chat_message": ("SELECT", "INSERT", "DELETE"),
    "ai_usage": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "ai_config": ("SELECT", "INSERT", "UPDATE"),
    "user_ai_key": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "friend_request": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "friend": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "conversation": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "message": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "password_reset": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "login_log": ("SELECT", "INSERT", "DELETE"),
    "game_record": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "game_invite": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "idea": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "idea_favorite": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "idea_like": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "idea_comment": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "idea_ai_job": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "tag_dict": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "idea_tag": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "student": ("SELECT", "INSERT", "UPDATE", "DELETE"),
}
APPEND_ONLY_GRANTS = {"idea_moderation_log": ("SELECT", "INSERT")}
DML_TABLES = tuple(TABLE_GRANTS)
APPEND_ONLY_TABLES = tuple(APPEND_ONLY_GRANTS)
REQUIRED_TABLES = DML_TABLES + APPEND_ONLY_TABLES
HTTP_CHECKS = (
    ("/login", "200"),
    ("/register", "200"),
    ("/captcha.png", "200"),
    ("/archive", "200"),
    ("/api/archive.json", "200"),
    ("/ideas", "302"),
    ("/api/ideas", "401"),
    ("/admin/login", "200"),
    ("/admin/verify", "302"),
    ("/static/idea.js?v=4", "200"),
    ("/static/idea.css?v=5", "200"),
    ("/static/archive.js?v=6", "200"),
    ("/static/archive.css?v=5", "200"),
    ("/static/content_profile.js?v=3", "200"),
    ("/profile", "302"),
)
HTTPS_CHECKS = (
    ("/archive", "200"),
    ("/api/archive.json", "200"),
    ("/login", "200"),
)


class DeployError(RuntimeError):
    pass


def source_files():
    files = []
    for root, dirs, names in os.walk(LOCAL):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            rel = os.path.relpath(os.path.join(root, name), LOCAL).replace("\\", "/")
            if rel == ".env.example" or os.path.splitext(name)[1].lower() in SOURCE_SUFFIXES:
                files.append(rel)
    return files


def connect(host, key_path):
    import paramiko

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        host, 22, "root", pkey=paramiko.RSAKey.from_private_key_file(key_path),
        timeout=20, banner_timeout=30, auth_timeout=30,
    )
    return client


def validate_listeners(output):
    addresses = [line.strip() for line in output.splitlines() if line.strip()]
    port_8081 = [address for address in addresses
                 if address.rsplit(":", 1)[-1] == "8081"]
    if port_8081 != ["127.0.0.1:8081"]:
        raise DeployError(f"8081 监听地址不安全：{port_8081 or '未监听'}")


def venv_shebang_script(source_prefix, target_prefix):
    return (
        "from pathlib import Path\n"
        "source = " + repr(source_prefix) + "\n"
        "target = " + repr(target_prefix) + "\n"
        "for path in Path('venv/bin').iterdir():\n"
        "    if path.is_file() and not path.is_symlink():\n"
        "        data = path.read_bytes()\n"
        "        prefix = b'#!' + source.encode()\n"
        "        if data.startswith(prefix):\n"
        "            path.write_bytes(b'#!' + target.encode() + data[len(prefix):])\n"
    )


class Remote:
    def __init__(self, client, mysql_password):
        self.client = client
        self.mysql_password = mysql_password
        self._lock_acquired = False

    def _redact(self, text):
        if self.mysql_password:
            return text.replace(self.mysql_password, "[REDACTED]")
        return text

    def run(self, command, timeout=300, stdin_text=None):
        watchdog = max(30, int(timeout) + 30)
        wrapped = (
            f"timeout --signal=TERM --kill-after=10s {watchdog}s "
            f"bash -c {shlex.quote(command)}"
        )
        stdin, stdout, stderr = self.client.exec_command(
            wrapped, timeout=watchdog,
        )
        if stdin_text is not None:
            stdin.write(stdin_text)
            stdin.flush()
            stdin.channel.shutdown_write()
        output = self._redact(
            stdout.read().decode("utf-8", "replace") +
            stderr.read().decode("utf-8", "replace")
        ).strip()
        status = stdout.channel.recv_exit_status()
        if status:
            raise DeployError(f"远程命令失败（exit={status}）：\n{output}")
        return output

    def mysql_file(self, local_path, timeout=120):
        with open(local_path, "r", encoding="utf-8") as handle:
            return self.mysql(handle.read(), timeout)

    def mysql(self, sql, timeout=120):
        script = (
            "set -euo pipefail\n"
            "MYSQL_PWD=" + shlex.quote(self.mysql_password) +
            " mysql -N -B -uroot --default-character-set=utf8mb4 2>&1 <<'SQL'\n" +
            sql.rstrip().rstrip(";") + "\nSQL\n"
        )
        return self.run("bash -s", timeout, stdin_text=script)

    def acquire_lock(self):
        self.run(f"mkdir -m 700 {LOCK_DIR}")
        self._lock_acquired = True

    def release_lock(self):
        if self._lock_acquired:
            self.run(f"rmdir {LOCK_DIR}")
            self._lock_acquired = False

    def mkdir(self, path):
        current = ""
        sftp = self.client.open_sftp()
        try:
            for part in path.strip("/").split("/"):
                current += "/" + part
                try:
                    sftp.stat(current)
                except IOError:
                    sftp.mkdir(current)
        finally:
            sftp.close()

    def upload(self, rel, remote_root=REMOTE):
        src = os.path.join(LOCAL, rel.replace("/", os.sep))
        dst = f"{remote_root}/{rel}"
        self.mkdir(os.path.dirname(dst))
        sftp = self.client.open_sftp()
        try:
            sftp.put(src, dst)
        finally:
            sftp.close()

    def preflight(self):
        if self.run("systemctl is-active --quiet bnu-register; echo $?") != "0":
            raise DeployError("bnu-register 当前不是 active，拒绝部署")
        exec_start = self.run("systemctl show bnu-register -p ExecStart --value")
        if not re.search(r"--workers\s+1(?:\s|$)", exec_start):
            raise DeployError(f"Gunicorn 不是单 worker：{exec_start}")
        if "--bind 127.0.0.1:8081" not in exec_start:
            raise DeployError(f"Gunicorn 监听不是 127.0.0.1:8081：{exec_start}")
        self.run(f"test -d {REMOTE} && test ! -L {REMOTE} && test -s {REMOTE}/.env")
        self.run("nginx -t")
        if self.mysql("SELECT 1").strip() != "1":
            raise DeployError("MySQL 只读连通性检查失败")
        env_hash = self.run(f"sha256sum {REMOTE}/.env | cut -d' ' -f1").strip()
        print(f"部署前检查通过；.env SHA-256：{env_hash}")
        return env_hash

    def backup(self):
        stamp = self.run("date -u +%Y%m%dT%H%M%SZ").strip()
        backup_dir = f"/root/bnu-register-backups/{stamp}"
        script = f"""set -euo pipefail
umask 077
mkdir -p {backup_dir}
tar -czf {backup_dir}/code.tar.gz -C /opt bnu-register
tar -tzf {backup_dir}/code.tar.gz >/dev/null
systemctl cat bnu-register > {backup_dir}/bnu-register.service
sha256sum {REMOTE}/.env > {backup_dir}/env.sha256
dump=$(mktemp /tmp/_bnu_backup.XXXXXX.sql)
trap 'rm -f "$dump"' EXIT
MYSQL_PWD={shlex.quote(self.mysql_password)} mysqldump -uroot \
  --single-transaction --quick --routines --events --triggers --hex-blob \
  --default-character-set=utf8mb4 --set-gtid-purged=OFF --no-tablespaces \
  --databases school mysql --result-file="$dump"
gzip -c "$dump" > {backup_dir}/school-and-mysql.sql.gz
gzip -t {backup_dir}/school-and-mysql.sql.gz
MYSQL_PWD={shlex.quote(self.mysql_password)} mysql -N -B -uroot \
  -e "SHOW GRANTS FOR 'studentapp'@'127.0.0.1'" > {backup_dir}/studentapp-grants.txt
test -s {backup_dir}/code.tar.gz
test -s {backup_dir}/school-and-mysql.sql.gz
ls -lh {backup_dir}/code.tar.gz {backup_dir}/school-and-mysql.sql.gz
"""
        output = self.run("bash -s", 600, stdin_text=script)
        print(f"备份目录：{backup_dir}\n{output}")
        return backup_dir

    def migrate(self):
        for name in SCHEMAS:
            self.mysql_file(os.path.join(LOCAL, name))
            print(f"迁移完成：{name}")
        tables = ",".join("'" + name + "'" for name in REQUIRED_TABLES)
        value = self.mysql(
            "SELECT CONCAT_WS(',', "
            f"(SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='school' "
            f"AND table_name IN ({tables})), "
            "(SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='school' "
            "AND table_name='message' AND column_name IN "
            "('quote_id','deleted_by_a','deleted_by_b','forward_from')), "
            "(SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='school' "
            "AND table_name='game_record' AND (column_name='ai_difficulty' OR "
            "(column_name='conv_id' AND is_nullable='YES'))), "
            "(SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='school' "
            "AND table_name='admin_user' AND column_name='email'), "
            "(SELECT CHARACTER_MAXIMUM_LENGTH FROM information_schema.columns "
            "WHERE table_schema='school' AND table_name='idea' AND column_name='category'), "
            "(SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='school' "
            "AND table_name='idea' AND column_name IN "
            "('category_legacy','moderation_state','row_version','moderation_reason_code',"
            "'moderation_reason','moderated_at','moderated_by')))"
        ).strip()
        expected = f"{len(REQUIRED_TABLES)},4,2,1,30,7"
        if value != expected:
            raise DeployError(f"迁移校验失败：期望 {expected}，实际 {value!r}")
        governance = self.mysql(
            "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='school' "
            "AND table_name='idea' AND ("
            "(column_name='category_legacy' AND data_type='varchar' "
            "AND character_maximum_length=30 AND is_nullable='YES') OR "
            "(column_name='moderation_state' AND column_type=\"enum('active','revoked')\" "
            "AND is_nullable='NO' AND column_default='active') OR "
            "(column_name='row_version' AND data_type='bigint' AND column_type='bigint unsigned' "
            "AND is_nullable='NO' AND column_default='0') OR "
            "(column_name='moderation_reason_code' AND data_type='varchar' "
            "AND character_maximum_length=30 AND is_nullable='YES') OR "
            "(column_name='moderation_reason' AND data_type='varchar' "
            "AND character_maximum_length=500 AND is_nullable='YES') OR "
            "(column_name='moderated_at' AND data_type='datetime' AND is_nullable='YES') OR "
            "(column_name='moderated_by' AND data_type='int' AND column_type='int unsigned' "
            "AND is_nullable='YES'))"
        ).strip()
        if governance != "7":
            raise DeployError(f"idea 治理列结构漂移：期望 7 个精确定义，实际 {governance!r}")
        indexes = self.mysql(
            "SELECT COUNT(*) FROM ("
            "SELECT table_name, index_name, MAX(non_unique) AS non_unique, "
            "GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',') AS cols "
            "FROM information_schema.statistics WHERE table_schema='school' AND ("
            "(table_name='idea' AND index_name='idx_moderation_public') OR "
            "(table_name='idea' AND index_name='idx_author_status_updated') OR "
            "(table_name='idea_favorite' AND index_name='idx_user_created')) "
            "GROUP BY table_name, index_name "
            "HAVING (table_name='idea' AND index_name='idx_moderation_public' AND non_unique=1 "
            "AND cols='moderation_state,status,visibility,created_at') OR "
            "(table_name='idea' AND index_name='idx_author_status_updated' AND non_unique=1 "
            "AND cols='author_id,status,updated_at,id') OR "
            "(table_name='idea_favorite' AND index_name='idx_user_created' AND non_unique=1 "
            "AND cols='user_id,created_at,idea_id')"
            ") AS checked_indexes"
        ).strip()
        if indexes != "3":
            raise DeployError(f"idea 索引结构漂移：期望 3 个索引，实际 {indexes!r}")
        missing_emails = self.mysql(
            "SELECT COUNT(*) FROM school.admin_user "
            "WHERE email IS NULL OR TRIM(email)=''"
        ).strip()
        if missing_emails != "0":
            raise DeployError("管理员二次认证邮箱未配置完整，已中止部署")

    def grant(self):
        statements = [
            f"GRANT {', '.join(privileges)} ON school.{table} "
            "TO 'studentapp'@'127.0.0.1'"
            for table, privileges in TABLE_GRANTS.items()
        ]
        statements += [
            f"GRANT {', '.join(privileges)} ON school.{table} "
            "TO 'studentapp'@'127.0.0.1'"
            for table, privileges in APPEND_ONLY_GRANTS.items()
        ]
        statements.append("FLUSH PRIVILEGES")
        self.mysql(";\n".join(statements))
        grantee = (
            "CONCAT(CHAR(39),'studentapp',CHAR(39),'@',CHAR(39),'127.0.0.1',CHAR(39))"
        )
        rows = self.mysql(
            "SELECT table_name, privilege_type, is_grantable "
            "FROM information_schema.table_privileges WHERE grantee=" + grantee +
            " ORDER BY table_name, privilege_type"
        ).splitlines()
        actual = {}
        for row in rows:
            parts = row.split("\t")
            if len(parts) != 3:
                raise DeployError(f"无法解析授权查询结果：{row!r}")
            table, privilege, grantable = parts
            if grantable.upper() == "YES":
                raise DeployError(f"studentapp 仍持有 GRANT OPTION：{table}.{privilege}")
            actual.setdefault(table, set()).add(privilege)
        expected = {table: set(privs) for table, privs in TABLE_GRANTS.items()}
        expected.update({table: set(privs) for table, privs in APPEND_ONLY_GRANTS.items()})
        if set(actual) != set(expected):
            raise DeployError(
                f"授权表集合漂移：缺少 {sorted(set(expected) - set(actual))}，"
                f"多出 {sorted(set(actual) - set(expected))}"
            )
        for table in sorted(expected):
            if actual[table] != expected[table]:
                raise DeployError(
                    f"授权漂移：{table} 期望 {sorted(expected[table])}，"
                    f"实际 {sorted(actual[table])}"
                )
        checks = {
            "column_privileges": (
                "SELECT COUNT(*) FROM information_schema.column_privileges "
                "WHERE grantee=" + grantee,
                "0",
            ),
            "routine_privileges": (
                "SELECT COUNT(*) FROM mysql.procs_priv "
                "WHERE User='studentapp' AND Host='127.0.0.1'",
                "0",
            ),
            "schema_dangerous": (
                "SELECT COUNT(*) FROM information_schema.schema_privileges "
                "WHERE grantee=" + grantee + " AND privilege_type <> 'USAGE'",
                "0",
            ),
            "global_dangerous": (
                "SELECT COUNT(*) FROM information_schema.user_privileges "
                "WHERE grantee=" + grantee + " AND privilege_type <> 'USAGE'",
                "0",
            ),
        }
        for label, (sql, expected_value) in checks.items():
            value = self.mysql(sql).strip()
            if value != expected_value:
                raise DeployError(
                    f"授权校验失败（{label}）：期望 {expected_value}，实际 {value!r}"
                )

    def stage_sources(self):
        stamp = self.run("date -u +%Y%m%dT%H%M%SZ").strip()
        stage = f"/opt/bnu-register-next-{stamp}"
        self.run(
            "set -e; "
            f"test ! -e {stage}; mkdir -m 755 {stage}; "
            f"cp -a {REMOTE}/.env {stage}/.env; "
            f"cp -a {REMOTE}/var {stage}/var; "
            f"cp -a {REMOTE}/venv {stage}/venv"
        )
        files = source_files()
        for rel in files:
            self.upload(rel, stage)
        self.run(
            "set -e; "
            f"chown -R root:root {stage}; "
            f"chown -R regweb:regweb {stage}/var; "
            f"chmod 600 {stage}/.env"
        )
        print(f"暂存完成：{stage}（{len(files)} 个源文件）")
        return stage

    def _rewrite_venv_shebangs(self, stage, source_prefix, target_prefix):
        script = venv_shebang_script(source_prefix, target_prefix)
        self.run(f"cd {stage} && ./venv/bin/python - <<'PY'\n{script}PY")

    def prepare_stage(self, stage):
        self._rewrite_venv_shebangs(stage, REMOTE, stage)
        self.run(
            "set -e; "
            f"cd {stage} && ./venv/bin/python -m pip install -q -r requirements.txt",
            600,
        )
        self.run(
            f"cd {stage} && ./venv/bin/python -m compileall -q -x '(/venv/|/var/)' ."
        )
        self._rewrite_venv_shebangs(stage, stage, REMOTE)
        print("暂存环境依赖、语法检查和入口路径重写完成")

    def switch_release(self, stage):
        token = secrets.token_hex(6)
        old = f"/opt/bnu-register-rollback-{token}"
        script = f"""set -euo pipefail
failed=/opt/bnu-register-failed-{token}
restore_on_failure() {{
  status=$?
  trap - EXIT
  if [ -d {old} ]; then
    if [ -e {REMOTE} ]; then mv -T {REMOTE} "$failed" 2>/dev/null || true; fi
    if [ ! -e {REMOTE} ]; then mv -T {old} {REMOTE} || true; fi
  fi
  systemctl start bnu-register >/dev/null 2>&1 || true
  exit $status
}}
trap restore_on_failure EXIT
systemctl stop bnu-register
cp -a {REMOTE}/var/. {stage}/var/
test -d {REMOTE}
test ! -e {old}
test -d {stage}
mv -T {REMOTE} {old}
mv -T {stage} {REMOTE}
trap - EXIT
"""
        self.run("bash -s", 180, stdin_text=script)
        return old

    def rollback(self, old):
        failed = f"/opt/bnu-register-failed-{secrets.token_hex(6)}"
        script = f"""set -euo pipefail
restore_on_failure() {{
  status=$?
  trap - EXIT
  if [ -d {old} ]; then
    if [ -e {REMOTE} ]; then mv -T {REMOTE} "$failed" 2>/dev/null || true; fi
    if [ ! -e {REMOTE} ]; then mv -T {old} {REMOTE} || true; fi
  fi
  systemctl start bnu-register >/dev/null 2>&1 || true
  exit $status
}}
trap restore_on_failure EXIT
systemctl stop bnu-register
cp -a {REMOTE}/var/. {old}/var/
mv -T {REMOTE} {failed}
mv -T {old} {REMOTE}
systemctl start bnu-register
trap - EXIT
"""
        self.run("bash -s", 180, stdin_text=script)
        return failed

    def verify_runtime(self, expected_env_hash):
        current_env_hash = self.run(f"sha256sum {REMOTE}/.env | cut -d' ' -f1").strip()
        if current_env_hash != expected_env_hash:
            raise DeployError(".env SHA-256 与部署前不一致")
        since = self.run("date +%s").strip()
        self.run("systemctl start bnu-register", 120)
        active = self.run("systemctl is-active bnu-register").strip()
        if active != "active":
            raise DeployError(f"服务未启动：{active}")
        listeners = self.run("ss -lntH | awk '{print $4}'")
        validate_listeners(listeners)
        self.run("nginx -t")
        for path, expected in HTTP_CHECKS:
            command = (
                "set -e; code=$(curl -sS --connect-timeout 5 --max-time 20 "
                "--retry 10 --retry-connrefused --retry-delay 1 "
                f"-o /dev/null -w '%{{http_code}}' 'http://127.0.0.1:8081{path}'); "
                f"test \"$code\" = {expected}"
            )
            self.run(command, 60)
            print(f"验收通过：{path} -> {expected}")
        for path, expected in HTTPS_CHECKS:
            command = (
                "set -e; code=$(curl -fsS --connect-timeout 5 --max-time 20 "
                "--resolve bnuailab.tech:443:127.0.0.1 "
                f"-o /dev/null -w '%{{http_code}}' 'https://bnuailab.tech{path}'); "
                f"test \"$code\" = {expected}"
            )
            self.run(command, 60)
            print(f"HTTPS 验收通过：{path} -> {expected}")
        logs = self.run(
            f"journalctl -u bnu-register --since @{since} --no-pager"
        )
        if re.search(r"traceback|critical|\[error\]", logs, re.IGNORECASE):
            raise DeployError(f"重启后日志出现错误：\n{logs}")
        env_after = self.run(f"sha256sum {REMOTE}/.env | cut -d' ' -f1").strip()
        if env_after != expected_env_hash:
            raise DeployError(".env 在部署过程中发生变化")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("DEPLOY_HOST", "47.118.28.10"))
    parser.add_argument("--key", default=os.path.expanduser("~/.ssh/id_rsa"))
    parser.add_argument("--dry-run", action="store_true", help="只打印部署清单，不连接服务器")
    args = parser.parse_args()
    files = source_files()
    if args.dry_run:
        print("迁移：", ", ".join(SCHEMAS))
        print("授权：")
        for table, privileges in {**TABLE_GRANTS, **APPEND_ONLY_GRANTS}.items():
            print(f"  {table}: {', '.join(privileges)}")
        print("源文件：", len(files))
        for rel in files:
            print(rel)
        return 0
    password = os.environ.get("MYSQL_PW", "")
    if not password:
        raise DeployError("缺少 MYSQL_PW 环境变量")
    for name in SCHEMAS:
        if not os.path.isfile(os.path.join(LOCAL, name)):
            raise DeployError(f"缺少迁移文件：{name}")
    client = connect(args.host, args.key)
    remote = Remote(client, password)
    completed = False
    try:
        remote.acquire_lock()
        env_hash = remote.preflight()
        backup_dir = remote.backup()
        remote.migrate()
        remote.grant()
        stage = remote.stage_sources()
        remote.prepare_stage(stage)
        old = remote.switch_release(stage)
        try:
            remote.verify_runtime(env_hash)
        except Exception as exc:
            try:
                failed = remote.rollback(old)
            except Exception as rollback_exc:
                raise DeployError(
                    f"验收失败且回滚失败：{exc}；回滚错误：{rollback_exc}；"
                    f"旧版本目录：{old}"
                ) from exc
            raise DeployError(f"验收失败，已回滚到旧版本；失败目录：{failed}；原因：{exc}") from exc
        completed = True
        print(f"增量部署完成；备份：{backup_dir}；旧版本保留在：{old}")
        return 0
    finally:
        try:
            if completed:
                remote.release_lock()
            elif remote._lock_acquired:
                print(f"部署未完成，保留锁 {LOCK_DIR}；确认远端无残留进程后再手动 rmdir")
        finally:
            client.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DeployError as exc:
        raise SystemExit(f"部署失败：{exc}")
