"""增量部署清单与失败退出回归测试。"""

import importlib.util
import io
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "deploy_incremental", ROOT / "deploy" / "deploy_incremental.py",
)
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


def test_manifest_covers_phase_two_and_excludes_secrets():
    files = set(deploy.source_files())
    assert {
        "ideas/__init__.py", "ideas/routes.py", "ideas/store.py",
        "archive_api.py", "archive_data.py", "schema_idea.sql", "schema_tags.sql",
        "schema_category.sql", "schema_moderation.sql", "schema_profile.sql",
        "templates/ideas_plaza.html", "templates/idea_detail.html",
        "templates/idea_form.html", "static/idea.js", "static/idea.css",
        "static/archive.js", "static/archive.css", "static/content_profile.js",
    } <= files
    assert ".env" not in files
    assert not any(path.startswith(("tests/", "deploy/", "var/")) for path in files)


def test_migrations_are_in_dependency_order_and_exclude_destructive_script():
    assert deploy.SCHEMAS.index("schema_game.sql") < deploy.SCHEMAS.index("schema_game_ai.sql")
    assert deploy.SCHEMAS.index("schema_idea.sql") < deploy.SCHEMAS.index("schema_tags.sql")
    assert "schema_admin_2fa.sql" in deploy.SCHEMAS
    assert "schema_chat_migrate.sql" not in deploy.SCHEMAS


def test_grants_cover_idea_and_tag_tables():
    assert {"idea", "idea_tag", "tag_dict", "idea_comment", "idea_ai_job"} <= set(deploy.DML_TABLES)
    assert deploy.APPEND_ONLY_TABLES == ("idea_moderation_log",)
    assert deploy.APPEND_ONLY_GRANTS["idea_moderation_log"] == ("SELECT", "INSERT")
    assert deploy.REQUIRED_TABLES == deploy.DML_TABLES + deploy.APPEND_ONLY_TABLES
    assert "idea_moderation_log" in deploy.REQUIRED_TABLES
    assert "idea_moderation_log" not in deploy.DML_TABLES
    assert deploy.TABLE_GRANTS["admin_user"] == ("SELECT", "INSERT", "UPDATE")
    assert deploy.TABLE_GRANTS["access_log"] == ("SELECT", "INSERT")
    assert deploy.TABLE_GRANTS["student"] == ("SELECT", "INSERT", "UPDATE", "DELETE")


def _grant_rows(extra=None):
    rows = []
    for table, privileges in {**deploy.TABLE_GRANTS, **deploy.APPEND_ONLY_GRANTS}.items():
        for privilege in privileges:
            rows.append(f"{table}\t{privilege}\tNO")
    rows.extend(extra or [])
    return "\n".join(rows)


def test_grant_validation_accepts_exact_allowlist(monkeypatch):
    remote = deploy.Remote(_Client(0), "secret")

    def fake_mysql(sql, timeout=120):
        if sql.startswith("SELECT table_name, privilege_type"):
            return _grant_rows()
        return "0"

    monkeypatch.setattr(remote, "mysql", fake_mysql)
    remote.grant()


def test_grant_validation_rejects_extra_or_grantable_privileges(monkeypatch):
    for extra in ("idea\tDROP\tNO", "idea\tSELECT\tYES"):
        remote = deploy.Remote(_Client(0), "secret")

        def fake_mysql(sql, timeout=120, extra=extra):
            if sql.startswith("SELECT table_name, privilege_type"):
                return _grant_rows([extra])
            return "0"

        monkeypatch.setattr(remote, "mysql", fake_mysql)
        try:
            remote.grant()
        except deploy.DeployError:
            pass
        else:
            raise AssertionError(f"额外授权未被拒绝：{extra}")


def test_full_deploy_orders_idea_before_migrations_and_grants_audit_minimally():
    source = (ROOT / "deploy" / "deploy.py").read_text(encoding="utf-8")
    assert '"schema_idea.sql": 1, "schema_tags.sql": 2' in source
    assert "school.idea_moderation_log" in source
    assert "GRANT SELECT, INSERT ON school.idea_moderation_log" in source
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON school.idea_moderation_log" not in source


def test_listener_check_rejects_missing_duplicate_or_public_bindings():
    deploy.validate_listeners("127.0.0.1:8081\n0.0.0.0:22")
    for output in (
        "", "0.0.0.0:8081", "[::]:8081",
        "127.0.0.1:8081\n0.0.0.0:8081",
        "127.0.0.1:8081\n127.0.0.1:8081",
    ):
        try:
            deploy.validate_listeners(output)
        except deploy.DeployError:
            pass
        else:
            raise AssertionError(f"不安全的监听未被拒绝：{output!r}")


class _Channel:
    def __init__(self, status):
        self.status = status
        self.stdin = _Stdin()

    def recv_exit_status(self):
        return self.status


class _Stdin:
    def __init__(self):
        self.channel = self
        self.parts = []
        self.closed = False

    def write(self, text):
        self.parts.append(text)

    def flush(self):
        pass

    def shutdown_write(self):
        self.closed = True


class _Stream:
    def __init__(self, text, status):
        self.buffer = io.BytesIO(text.encode())
        self.channel = _Channel(status)

    def read(self, *args):
        return self.buffer.read()


class _Client:
    def __init__(self, status, output=""):
        self.status = status
        self.output = output
        self.stdin = None
        self.command = None

    def exec_command(self, command, timeout=300):
        self.command = command
        self.stdin = _Stdin()
        return self.stdin, _Stream(self.output, self.status), _Stream("", self.status)


def test_nonzero_remote_command_raises():
    remote = deploy.Remote(_Client(7, "boom"), "secret")
    command = "MYSQL_PWD=secret mysql -uroot < /tmp/schema.sql"
    try:
        remote.run(command)
    except deploy.DeployError as exc:
        message = str(exc)
        assert "exit=7" in message and "boom" in message
        assert "secret" not in message and command not in message
    else:
        raise AssertionError("远程失败未抛出异常")


def test_mysql_password_is_sent_over_stdin_not_command_line():
    client = _Client(0, "1")
    remote = deploy.Remote(client, "p@ss'word")
    assert remote.mysql("SELECT 1;").strip() == "1"
    assert client.command.startswith("timeout ")
    assert "bash -c" in client.command and "bash -s" in client.command
    assert "p@ss'word" not in client.command
    script = "".join(client.stdin.parts)
    assert "MYSQL_PWD=" in script and "SELECT 1" in script
    assert client.stdin.closed is True


def test_venv_shebang_rewrite_moves_staged_entries_to_runtime_path(tmp_path):
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    pip = bin_dir / "pip"
    pip.write_text("#!/opt/bnu-register/venv/bin/python\nprint('pip')\n", encoding="utf-8")
    other = bin_dir / "other"
    other.write_text("#!/usr/bin/env python\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", deploy.venv_shebang_script(
            "/opt/bnu-register", "/opt/bnu-register-next-test",
        )],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert pip.read_text(encoding="utf-8").startswith(
        "#!/opt/bnu-register-next-test/venv/bin/python\n"
    )
    assert other.read_text(encoding="utf-8") == "#!/usr/bin/env python\n"


def test_switch_and_rollback_scripts_use_shell_failed_variable(monkeypatch):
    remote = deploy.Remote(_Client(0), "secret")
    captured = []

    def fake_run(command, timeout=300, stdin_text=None):
        captured.append(stdin_text or "")
        return ""

    monkeypatch.setattr(remote, "run", fake_run)
    old = remote.switch_release("/opt/bnu-register-next-test")
    remote.rollback(old)
    assert len(captured) == 2
    assert all('mv -T /opt/bnu-register "$failed"' in script for script in captured)
    assert all("restore_on_failure" in script for script in captured)


def test_deployment_uses_locking_staging_backup_validation_and_rollback():
    source = (ROOT / "deploy" / "deploy_incremental.py").read_text(encoding="utf-8")
    for marker in (
        "LOCK_DIR =", "mkdir -m 700", "tar -tzf", "gzip -t",
        "def stage_sources", "def switch_release", "def rollback",
        "https://bnuailab.tech", "sha256sum {REMOTE}/.env",
        "mv -T {stage} {REMOTE}", "mv -T {old} {REMOTE}",
        "restore_on_failure", "cp -a {REMOTE}/var/. {old}/var/",
    ):
        assert marker in source
    assert "MYSQL_PWD=" in source


def test_module_import_has_no_deployment_side_effects():
    assert deploy.REMOTE == "/opt/bnu-register"
    assert deploy.source_files()
