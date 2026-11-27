"""内容升级的权限、并发、迁移与审计边界回归。"""

import json
import os
import sys
import uuid
from pathlib import Path

import pytest
from pymysql.err import IntegrityError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SECRET_KEY", "test-secret-for-content")

import app as app_module  # noqa: E402
import admin  # noqa: E402
from ideas import moderation, routes, store  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    app_module.app.config["TESTING"] = True
    monkeypatch.setattr(store, "get_user", lambda uid: {"id": uid, "status": "active"})
    with app_module.app.test_client() as c:
        with c.session_transaction() as s:
            s["uid"] = 7
            s["_csrf"] = "csrf-token"
        yield c


class Cursor:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.queries = []
        self.insert_error = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        if self.insert_error and sql.startswith("INSERT INTO idea_moderation_log"):
            raise IntegrityError(1062, "Duplicate request_id")

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        return []


class Connection:
    def __init__(self, rows=None):
        self.cur = Cursor(rows)
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _idea_row(state="active", version=2):
    return {
        "author_id": 7, "status": "published", "visibility": "public",
        "moderation_state": state, "row_version": version,
        "content_hash": "hash", "tags": "AI",
    }


def test_visibility_matrix_keeps_revoked_private_from_non_authors(monkeypatch):
    cases = [
        (7, "public", "draft", "revoked", True),
        (8, "private", "published", "revoked", False),
        (8, "public", "published", "active", True),
        (8, "private", "published", "active", False),
        (8, "public", "draft", "active", False),
        (8, "public", "archived", "active", False),
    ]
    for viewer, visibility, status, state, expected in cases:
        conn = Connection([{
            "author_id": 7, "visibility": visibility,
            "status": status, "moderation_state": state,
        }])
        monkeypatch.setattr(store, "connect", lambda conn=conn: conn)
        assert store.can_view_idea(4, viewer) is expected


@pytest.mark.parametrize("operation", ["favorite", "like", "comment"])
def test_revoked_interactions_lock_and_abort_before_writes(monkeypatch, operation):
    conn = Connection([{"id": 8}, _idea_row("revoked")])
    monkeypatch.setattr(store, "connect", lambda: conn)
    if operation == "favorite":
        result = store.toggle_favorite(4, 8)
    elif operation == "like":
        result = store.toggle_like(4, 8)
    else:
        result = store.add_comment(4, 8, "评论")
    assert result is None
    assert conn.rolled_back and not conn.committed
    assert "FROM app_user" in conn.cur.queries[0][0]
    assert "FOR UPDATE" in conn.cur.queries[1][0]
    assert len(conn.cur.queries) == 2


def test_update_conflict_and_revoked_are_distinct(monkeypatch):
    for state, expected in [("active", "conflict"), ("revoked", "revoked")]:
        conn = Connection([_idea_row(state, 3)])
        monkeypatch.setattr(store, "connect", lambda conn=conn: conn)
        assert store.update_idea(4, 7, {"title": "新标题"}, 2) == expected
        assert conn.rolled_back
        assert not any(sql.startswith("UPDATE") for sql, _ in conn.cur.queries)


def test_update_content_clears_old_ai_preview(monkeypatch):
    conn = Connection([_idea_row()])
    monkeypatch.setattr(store, "connect", lambda: conn)
    assert store.update_idea(4, 7, {"content": "新正文", "content_hash": "new"}, 2)
    updates = [sql for sql, _ in conn.cur.queries if "ai_category=NULL" in sql]
    assert len(updates) == 1
    assert "ai_summary=NULL" in updates[0] and "ai_tags=NULL" in updates[0]
    assert conn.committed


@pytest.mark.parametrize("field", ["title", "category", "tags"])
def test_update_derived_fields_also_clears_old_ai_preview(monkeypatch, field):
    conn = Connection([_idea_row()])
    monkeypatch.setattr(store, "connect", lambda: conn)
    assert store.update_idea(4, 7, {field: "new"}, 2)
    assert any("ai_category=NULL" in sql for sql, _ in conn.cur.queries)


def test_update_store_never_allows_missing_version(monkeypatch):
    conn = Connection([_idea_row()])
    monkeypatch.setattr(store, "connect", lambda: conn)
    assert store.update_idea(4, 7, {"title": "新标题"}, None) == "conflict"
    assert conn.rolled_back


def test_profile_apis_ignore_identity_parameters_and_disable_cache(client, monkeypatch):
    captured = {}

    def fake_owned(viewer_id, **kwargs):
        captured.update(viewer_id=viewer_id, **kwargs)
        return [], 0

    monkeypatch.setattr(store, "list_owned_ideas", fake_owned)
    response = client.get("/api/profile/ideas?author=99&user=99&tag=AI&status=published")
    assert response.status_code == 200
    assert captured["viewer_id"] == 7
    assert captured["tag"] == "AI"
    assert response.headers["Cache-Control"] == "private, no-store"

    monkeypatch.setattr(store, "list_favorited_ideas", lambda viewer_id, **kwargs: ([], 0, 3))
    response = client.get("/api/profile/favorites?viewer=99")
    assert response.get_json()["unavailable_count"] == 3
    assert response.headers["Cache-Control"] == "private, no-store"


def test_profile_page_uses_session_and_disables_cache(client, monkeypatch):
    monkeypatch.setattr(store, "profile_summary", lambda uid: {"published": 1})
    response = client.get("/profile?uid=99")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "我的 idea 与收藏" in response.get_data(as_text=True)
    response = client.get("/profile?view=favorites")
    assert 'data-initial-view="favorites"' in response.get_data(as_text=True)


def test_favorite_count_and_items_share_visibility_predicate(monkeypatch):
    conn = Connection([{"total": 2}])
    monkeypatch.setattr(store, "connect", lambda: conn)
    items, total, unavailable = store.list_favorited_ideas(7, tag="AI", q="学习", page=2, size=5)
    assert (items, total, unavailable) == ([], 2, 0)
    count_sql, count_params = conn.cur.queries[0]
    list_sql, list_params = conn.cur.queries[1]
    count_where = count_sql.split(" WHERE ", 1)[1]
    list_where = list_sql.split(" WHERE ", 1)[1].split(" ORDER BY ", 1)[0]
    assert count_where == list_where
    assert count_params == list_params[:-2]
    assert "i.moderation_state='active'" in count_where
    assert "i.visibility='public'" in count_where
    assert list_params[-2:] == [5, 5]


def test_owned_list_forces_author_and_uses_exact_safe_tag(monkeypatch):
    conn = Connection([{"total": 1}])
    monkeypatch.setattr(store, "connect", lambda: conn)
    store.list_owned_ideas(7, tag=" A_%\\ ", q="x")
    for sql, params in conn.cur.queries:
        assert "i.author_id=%s" in sql
        assert params[0] == 7
    assert conn.cur.queries[0][1][5:8] == ["A", "A", "A"]


def test_edit_api_rejects_missing_or_non_integer_version(client, monkeypatch):
    monkeypatch.setattr(store, "get_idea", lambda idea_id: {"id": idea_id, "author_id": 7})
    monkeypatch.setattr(store, "update_idea", lambda *args: pytest.fail("缺版本不应写入"))
    for payload in ({"title": "新标题"}, {"title": "新标题", "row_version": True},
                    {"title": "新标题", "row_version": 1.5}):
        response = client.put("/api/ideas/4", json=payload, headers={"X-CSRF": "csrf-token"})
        assert response.status_code == 400


def test_edit_api_reports_version_conflict(client, monkeypatch):
    monkeypatch.setattr(store, "get_idea", lambda idea_id: {"id": idea_id, "author_id": 7})
    monkeypatch.setattr(store, "update_idea", lambda *args: "conflict")
    response = client.put("/api/ideas/4", json={"title": "新标题", "row_version": 2}, headers={"X-CSRF": "csrf-token"})
    assert response.status_code == 409
    assert response.get_json()["code"] == "conflict"


def test_moderation_commits_snapshot_and_audit_without_body(monkeypatch):
    conn = Connection([None, dict(_idea_row(), content="不能复制到审计的正文")])
    monkeypatch.setattr(moderation.db, "connect", lambda: conn)
    request_id = str(uuid.uuid4())
    result = moderation.moderate(
        4, "revoke", 1, "管理员", 2, "spam", "广告内容", "内部备注", request_id,
    )
    assert result == {"ok": True, "idempotent": False, "state": "revoked", "author_id": 7}
    assert conn.committed
    insert_sql, values = conn.cur.queries[-1]
    assert insert_sql.startswith("INSERT INTO idea_moderation_log")
    snapshot = json.loads(values[12])
    assert "content" not in snapshot and "title" not in snapshot
    assert snapshot["content_hash"] == "hash"
    assert values[9] == request_id


def test_moderation_version_conflict_makes_no_changes(monkeypatch):
    conn = Connection([None, _idea_row(version=3)])
    monkeypatch.setattr(moderation.db, "connect", lambda: conn)
    result = moderation.moderate(4, "revoke", 1, "管理员", 2, "spam", "广告", "", str(uuid.uuid4()))
    assert result["conflict"] is True
    assert len(conn.cur.queries) == 2


def test_moderation_repeated_request_is_idempotent(monkeypatch):
    request_id = str(uuid.uuid4())
    fingerprint = moderation._request_fingerprint(4, "revoke", 2, "spam", "广告", "")
    conn = Connection([{"snapshot_json": json.dumps({"request_fingerprint": fingerprint})}])
    monkeypatch.setattr(moderation.db, "connect", lambda: conn)
    result = moderation.moderate(4, "revoke", 1, "管理员", 2, "spam", "广告", "", request_id)
    assert result == {"ok": True, "idempotent": True}
    assert len(conn.cur.queries) == 1


def test_moderation_request_id_rejects_different_payload(monkeypatch):
    conn = Connection([{"snapshot_json": json.dumps({"request_fingerprint": "other"})}])
    monkeypatch.setattr(moderation.db, "connect", lambda: conn)
    result = moderation.moderate(4, "revoke", 1, "管理员", 2, "spam", "广告", "", str(uuid.uuid4()))
    assert result["ok"] is False and result["conflict"] is True
    assert len(conn.cur.queries) == 1


def test_moderation_duplicate_audit_race_returns_idempotent(monkeypatch):
    request_id = str(uuid.uuid4())
    fingerprint = moderation._request_fingerprint(4, "revoke", 2, "spam", "广告", "")
    failed = Connection([None, _idea_row()])
    failed.cur.insert_error = True
    confirmed = Connection([{"snapshot_json": json.dumps({"request_fingerprint": fingerprint})}])
    connections = iter([failed, confirmed])
    monkeypatch.setattr(moderation.db, "connect", lambda: next(connections))
    result = moderation.moderate(4, "revoke", 1, "管理员", 2, "spam", "广告", "", request_id)
    assert result == {"ok": True, "idempotent": True}
    assert not failed.committed


def test_admin_private_content_is_not_rendered(client, monkeypatch):
    monkeypatch.setattr(admin, "_admin_session_valid", lambda: True)
    monkeypatch.setattr(moderation, "get_metadata", lambda idea_id: {"id": idea_id, "visibility": "private"})
    loaded = []
    monkeypatch.setattr(moderation, "get_viewable_content", lambda idea_id: loaded.append(idea_id))
    monkeypatch.setattr(moderation, "list_audit", lambda idea_id: [])
    monkeypatch.setattr(moderation, "record_audit", lambda *a, **kw: True)
    with client.session_transaction() as s:
        s["aid"] = 1
    response = client.get("/admin/ideas/4")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert loaded == [4]
    assert "仅展示元数据" in response.get_data(as_text=True)
    assert "私密正文" not in response.get_data(as_text=True)


def test_delete_user_checks_ideas_under_user_lock(client, monkeypatch):
    monkeypatch.setattr(admin, "_admin_session_valid", lambda: True)
    monkeypatch.setattr(admin, "q_one", lambda *a: {
        "id": 7, "student_no": "s", "real_name": "姓名", "nickname": "昵称", "email": "u@example.org",
    })
    conn = Connection([{"id": 7, "email": "u@example.org"}, {"n": 1}])
    monkeypatch.setattr(admin.db, "connect", lambda: conn)
    with client.session_transaction() as s:
        s["aid"] = 1
        s["_acsrf"] = "csrf-token"
    response = client.post("/admin/users/7/delete", data={"csrf": "csrf-token"})
    assert response.status_code == 302
    assert "idea" in response.location
    assert "FOR UPDATE" in conn.cur.queries[0][0]
    assert conn.rolled_back and not conn.committed


def test_create_locks_active_user_before_insert(monkeypatch):
    conn = Connection([{"id": 7}])
    conn.cur.lastrowid = 4
    monkeypatch.setattr(store, "connect", lambda: conn)
    monkeypatch.setattr(store, "sync_idea_tags", lambda *a: None)
    assert store.create_idea(7, {"title": "标题", "content": "正文"}) == 4
    assert "FOR UPDATE" in conn.cur.queries[0][0]
    assert conn.cur.queries[1][0].startswith("INSERT INTO idea")
    assert conn.committed


def test_create_refuses_user_deleted_before_lock(monkeypatch):
    conn = Connection([None])
    monkeypatch.setattr(store, "connect", lambda: conn)
    assert store.create_idea(7, {"title": "标题", "content": "正文"}) is None
    assert conn.rolled_back and len(conn.cur.queries) == 1


def test_admin_private_metadata_is_redacted_and_search_excludes_private(monkeypatch):
    conn = Connection([{"total": 0}, {
        "id": 4, "title": "私密标题", "tags": "私密标签", "visibility": "private",
    }])
    monkeypatch.setattr(moderation.db, "connect", lambda: conn)
    items, total = moderation.list_ideas(q="私密", state="revoked")
    assert total == 0 and items == []
    for sql, params in conn.cur.queries:
        assert sql.count("%s") == len(params)
        assert "i.visibility<>'private'" in sql
        if "AS total" not in sql:
            assert "CONCAT('[private idea #'" in sql
    conn.cur.rows = [{
        "id": 4, "title": "私密标题", "tags": "私密标签", "visibility": "private",
    }]
    metadata = moderation.get_metadata(4)
    assert metadata["visibility"] == "private"

def test_admin_pages_disable_cache_and_audit_failure_blocks_body(client, monkeypatch):
    monkeypatch.setattr(admin, "_admin_session_valid", lambda: True)
    monkeypatch.setattr(moderation, "list_ideas", lambda **kwargs: ([], 0))
    response = client.get("/admin/ideas")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"

    monkeypatch.setattr(moderation, "get_metadata", lambda idea_id: {
        "id": idea_id, "visibility": "public", "title": "公开标题",
    })
    monkeypatch.setattr(moderation, "get_viewable_content", lambda idea_id: "正文")
    monkeypatch.setattr(moderation, "record_audit", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db")))
    with client.session_transaction() as s:
        s["aid"] = 1
    response = client.get("/admin/ideas/4")
    assert response.status_code == 503
    assert "公开标题" not in response.get_data(as_text=True)


def test_delete_user_clears_interactions_and_recomputes_counts(client, monkeypatch):
    monkeypatch.setattr(admin, "_admin_session_valid", lambda: True)
    monkeypatch.setattr(admin, "q_one", lambda *a: {
        "id": 7, "student_no": "s", "real_name": "姓名", "nickname": "昵称", "email": "u@example.org",
    })
    conn = Connection([{"id": 7, "email": "u@example.org"}, {"n": 0}])
    conn.cur.fetchall = lambda: [{"idea_id": 4}, {"idea_id": 5}]
    monkeypatch.setattr(admin.db, "connect", lambda: conn)
    with client.session_transaction() as s:
        s["aid"] = 1
        s["_acsrf"] = "csrf-token"
    response = client.post("/admin/users/7/delete", data={"csrf": "csrf-token"})
    assert response.status_code == 302 and conn.committed
    sql = [query for query, _ in conn.cur.queries]
    for table in ("idea_favorite", "idea_like", "idea_comment", "idea_ai_job"):
        assert f"DELETE FROM {table} WHERE user_id=%s" in sql
    assert sum("favorite_count=(SELECT COUNT(*)" in query for query in sql) == 2
    assert any("child.parent_id=NULL" in query for query in sql)


def test_category_migration_preserves_legacy_before_normalizing():
    sql = (ROOT / "schema_category.sql").read_text(encoding="utf-8")
    update = sql.split("UPDATE idea", 1)[1]
    assert update.index("category_legacy=") < update.index("category=CASE")
    assert "WHEN '人工智能' THEN 'ai'" in update
    assert "WHEN '数学' THEN 'math'" in update
    assert "WHEN '材料与传感' THEN 'math'" in update
    assert "category NOT IN ('ai','edu','bio','energy','math','other')" in update
    legacy, normalized = update.split("UPDATE idea", 1)
    assert "category='math'" in legacy and "WHERE category='mat'" in legacy


def test_new_schema_has_governance_and_profile_indexes():
    sql = (ROOT / "schema_idea.sql").read_text(encoding="utf-8")
    for token in (
        "category_legacy", "moderation_state", "row_version", "moderation_reason",
        "idx_moderation_public", "idx_author_status_updated",
    ):
        assert token in sql
    assert "ALTER TABLE idea_favorite ADD INDEX idx_user_created" in (ROOT / "schema_profile.sql").read_text(encoding="utf-8")
