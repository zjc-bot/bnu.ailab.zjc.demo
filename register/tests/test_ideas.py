"""Idea 输入边界、标签同步与列表查询回归测试。"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret-for-ideas")

import app as app_module  # noqa: E402
import archive_data  # noqa: E402
from ideas import routes, store  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    app_module.app.config["TESTING"] = True
    monkeypatch.setattr(store, "get_user", lambda uid: {"id": uid, "status": "active"})
    with app_module.app.test_client() as c:
        with c.session_transaction() as s:
            s["uid"] = 7
            s["_csrf"] = "csrf-token"
        yield c


def test_create_rejects_non_object_json(client, monkeypatch):
    called = []
    monkeypatch.setattr(store, "create_idea", lambda *a: called.append(a))
    for payload in ([], None, "text"):
        resp = client.post("/api/ideas", json=payload, headers={"X-CSRF": "csrf-token"})
        assert resp.status_code == 400
        assert "JSON 对象" in resp.get_json()["error"]
    assert not called


def test_create_rejects_unknown_category(client, monkeypatch):
    called = []
    monkeypatch.setattr(store, "create_idea", lambda *a: called.append(a))
    resp = client.post(
        "/api/ideas",
        json={"title": "标题", "content": "正文", "category": "算法"},
        headers={"X-CSRF": "csrf-token"},
    )
    assert resp.status_code == 400
    assert "ai/edu/bio/energy/math/other" in resp.get_json()["error"]
    assert not called


def test_create_defaults_category_to_other(client, monkeypatch):
    captured = {}

    def fake_create(uid, payload):
        captured.update(payload)
        return 1

    monkeypatch.setattr(store, "create_idea", fake_create)
    monkeypatch.setattr(store, "get_idea", lambda idea_id: {"id": idea_id})
    resp = client.post(
        "/api/ideas", json={"title": "标题", "content": "正文"},
        headers={"X-CSRF": "csrf-token"},
    )
    assert resp.status_code == 201
    assert captured["category"] == "other"
    assert captured["visibility"] == "public"


@pytest.mark.parametrize("field", ["category", "visibility"])
def test_create_rejects_non_string_enum_values(field):
    payload = {"title": "标题", "content": "正文", field: False}
    with pytest.raises(ValueError):
        routes._validate(payload)


def test_categories_are_fixed_and_ordered(client):
    resp = client.get("/api/categories")
    assert [item["value"] for item in resp.get_json()["items"]] == [
        "ai", "edu", "bio", "energy", "math", "other",
    ]
    assert next(item for item in resp.get_json()["items"] if item["value"] == "math")["label"] == "数学"


def test_tags_are_trimmed_and_case_insensitively_deduplicated():
    assert routes._normalize_tags(" AI, ai ，小样本,小样本 ") == "AI,小样本"
    assert routes._normalize_tags(["AI", "ai", " 标签 "]) == "AI,标签"
    assert routes._normalize_tags(["AI,教育", "ai"]) == "AI,教育"
    with pytest.raises(ValueError):
        routes._normalize_tags(["AI", {"bad": "object"}])
    with pytest.raises(ValueError, match="最多 8 个"):
        routes._normalize_tags(["a,b,c,d,e,f,g,h,i"])


def test_list_passes_sort_and_uses_safe_pagination(client, monkeypatch):
    captured = {}

    def fake_list(viewer_id, **kwargs):
        captured.update(viewer_id=viewer_id, **kwargs)
        return [], 0

    monkeypatch.setattr(store, "list_ideas", fake_list)
    resp = client.get("/api/ideas?sort=hot&page=0&size=999&q=%E5%B0%8F%E6%9E%97")
    assert resp.status_code == 200
    assert captured["sort"] == "hot"
    assert captured["q"] == "小林"


def test_tags_route_passes_current_viewer(client, monkeypatch):
    captured = {}

    def fake_list_tags(*, q=None, limit=100, viewer_id=None):
        captured.update(q=q, limit=limit, viewer_id=viewer_id)
        return []

    monkeypatch.setattr(store, "list_tags", fake_list_tags)
    resp = client.get("/api/tags?q=AI")
    assert resp.status_code == 200
    assert captured == {"q": "AI", "limit": 100, "viewer_id": 7}


def test_tag_query_hides_labels_from_invisible_ideas(monkeypatch):
    conn = _Connection()
    monkeypatch.setattr(store, "connect", lambda: conn)
    store.list_tags(q="AI", viewer_id=7)
    assert len(conn.queries) == 1
    sql, params = conn.queries[0]
    assert sql.count("%s") == len(params)
    assert "vi.visibility='public'" in sql
    assert "vi.visibility='friends'" in sql
    assert "vi.author_id=%s" in sql
    assert "vi.moderation_state='active'" in sql
    assert params.count(7) == 6
    assert params[-2:] == ("%AI%", 100)


class _Cursor:
    def __init__(self, owner):
        self.owner = owner

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        self.owner.queries.append((sql, params))

    def fetchone(self):
        return {"total": 0}

    def fetchall(self):
        return []


class _Connection:
    def __init__(self):
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        pass


def test_list_sql_parameter_counts_and_hot_order(monkeypatch):
    conn = _Connection()
    monkeypatch.setattr(store, "connect", lambda: conn)
    items, total = store.list_ideas(
        7, category="ai", tag="AI", author_id=7, q="学习", page=2, size=20, sort="hot",
    )
    assert items == [] and total == 0
    assert len(conn.queries) == 2
    for sql, params in conn.queries:
        assert sql.count("%s") == len(params)
    assert "ORDER BY i.like_count DESC" in conn.queries[1][0]
    assert conn.queries[0][1].count("AI") == 3
    assert conn.queries[0][1].count("%学习%") == 6
    for sql, _ in conn.queries:
        assert "LEFT JOIN app_user u ON u.id=i.author_id" in sql
        assert "u.nickname LIKE %s" in sql
        assert "i.visibility='public'" in sql
        assert "i.visibility='friends'" in sql


def test_list_keyword_strips_wildcards_and_caps_length(monkeypatch):
    conn = _Connection()
    monkeypatch.setattr(store, "connect", lambda: conn)
    store.list_ideas(7, q=" %_" + "x" * 70 + "_% ")
    expected = "%" + "x" * 60 + "%"
    for _, params in conn.queries:
        assert params.count(expected) == 6


def test_list_keyword_strips_like_escape_character(monkeypatch):
    conn = _Connection()
    monkeypatch.setattr(store, "connect", lambda: conn)
    store.list_ideas(7, q="abc\\")
    for _, params in conn.queries:
        assert params.count("%abc%") == 6


class _TagCursor:
    def __init__(self, owner):
        self.owner = owner

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        self.owner.queries.append((sql, params))
        if sql.startswith("SELECT id, name, status"):
            self.row = ({"id": 2, "name": "Disabled", "status": "disabled"}
                        if params == ("disabled",) else
                        {"id": 1, "name": "AI", "status": "active"})
        elif sql.startswith("SELECT author_id, moderation_state, row_version, tags"):
            self.row = {"author_id": 7, "moderation_state": "active", "row_version": 0, "tags": "AI"}
        elif sql.startswith("SELECT 1 FROM idea"):
            self.row = {"1": 1}
        else:
            self.row = None

    def fetchone(self):
        return self.row

    def fetchall(self):
        return []


class _TagConnection(_Connection):
    def cursor(self):
        return _TagCursor(self)

    def rollback(self):
        pass


def test_tag_sync_keeps_only_active_canonical_names():
    conn = _TagConnection()
    store.sync_idea_tags(conn, 9, "AI, ai, Disabled")
    relation_sql = [sql for sql, _ in conn.queries if sql.startswith("INSERT IGNORE")]
    assert len(relation_sql) == 1
    assert ("UPDATE idea SET tags=%s WHERE id=%s", ("AI", 9)) in conn.queries
    assert conn.queries[0][0].startswith("DELETE FROM idea_tag")


def test_tag_sync_empty_clears_old_relations():
    conn = _TagConnection()
    store.sync_idea_tags(conn, 9, "")
    assert conn.queries[0][0].startswith("DELETE FROM idea_tag")
    assert ("UPDATE idea SET tags=%s WHERE id=%s", ("", 9)) in conn.queries


def test_tag_sync_defensively_caps_direct_store_calls():
    conn = _TagConnection()
    store.sync_idea_tags(conn, 9, ",".join("tag" + str(i) for i in range(9)))
    inserts = [sql for sql, _ in conn.queries if sql.startswith("INSERT INTO tag_dict")]
    assert len(inserts) == 8


def test_tag_migration_backfills_legacy_rows_without_reactivating_disabled_tags():
    sql = (ROOT / "schema_tags.sql").read_text(encoding="utf-8")
    assert sql.count("WITH RECURSIVE tag_parts AS") == 2
    assert "INSERT IGNORE INTO tag_dict (name, slug)\nWITH RECURSIVE" in sql
    assert "INSERT IGNORE INTO idea_tag (idea_id, tag_id)\nWITH RECURSIVE" in sql
    assert "INSERT IGNORE INTO tag_dict" in sql
    assert "INSERT IGNORE INTO idea_tag" in sql
    assert "d.status='active'" in sql
    assert "part_no < 8" in sql


def test_update_same_values_skips_tag_resync(monkeypatch):
    conn = _TagConnection()
    monkeypatch.setattr(store, "connect", lambda: conn)
    assert store.update_idea(9, 7, {"tags": "AI"}, expected_version=0) is True
    assert not any(sql.startswith("DELETE FROM idea_tag") for sql, _ in conn.queries)
    assert any("row_version=row_version+1" in sql for sql, _ in conn.queries)


def test_archive_tags_are_limited_and_stats_use_public_scope():
    rows = [{"name": "tag-" + str(i), "pinned": 0} for i in range(12)]
    tags = archive_data._build_tags(rows)
    assert len(tags) == 10 and tags[0]["id"] == "all"
    for label, sql in archive_data._STATS_SQL[1:]:
        assert "visibility='public'" in sql


def test_archive_detail_uses_full_idea_content_instead_of_placeholder_sections():
    content = "① 正文第一段\n② 论文 https://example.com/paper.pdf\n" + "完整正文" * 40
    item = archive_data._to_item({
        "id": 43, "title": "FFT", "content": content, "category": "算法",
        "tags": "DFT,FFT", "like_count": 1, "created_at": "2026-11-26",
    }, 0)
    assert item["content"] == content
    assert item["summary"] == content[:120]
    assert item["cat"] == "算法"
    assert item["catLabel"] == "算法"

    script = (ROOT / "static" / "archive.js").read_text(encoding="utf-8")
    assert "renderBody(p.content || p.summary)" in script
    assert "详情数据待补充" not in script
    assert 'class="d-section"' not in script
