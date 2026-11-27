"""Idea 社区数据访问层（Phase 1）。

设计约定：
  - 直接复用 register/db.py 的 connect()，确保 DB_* 配置单一来源；
    参数化 %s、with 连接、显式 commit。
  - 所有 SQL 的值一律参数化；动态 SET 的列名取自硬编码白名单字典，
    扫描/分页条件用「%s IS NULL OR ...」写法，因此没有任何字符串拼接。
  - 计数（like/favorite/comment）在同一事务内按关系表 COUNT 重算，保证一致。
"""

import db  # 与注册系统共用同一份 DB_* 配置与连接工厂，避免配置漂移
from .constants import CATEGORY_LABELS, CATEGORIES


def connect():
    return db.connect()


# 分类展示名与允许值统一来自 ideas/constants.py。


CATEGORY_LABELS = CATEGORY_LABELS
CATEGORIES = CATEGORIES


# update_idea 允许写入的列：key 为外部字段名，value 为固定 SQL 语句。
# 逐列更新而非动态拼 SET 子句，保证 SQL 中不存在任何字符串拼接。
_UPDATES = {
    "title": "UPDATE idea SET title=%s, updated_at=NOW() WHERE id=%s AND author_id=%s",
    "content": "UPDATE idea SET content=%s, updated_at=NOW() WHERE id=%s AND author_id=%s",
    "category": "UPDATE idea SET category=%s, updated_at=NOW() WHERE id=%s AND author_id=%s",
    "tags": "UPDATE idea SET tags=%s, updated_at=NOW() WHERE id=%s AND author_id=%s",
    "status": "UPDATE idea SET status=%s, updated_at=NOW() WHERE id=%s AND author_id=%s",
    "visibility": "UPDATE idea SET visibility=%s, updated_at=NOW() WHERE id=%s AND author_id=%s",
    "ai_category": "UPDATE idea SET ai_category=%s, updated_at=NOW() WHERE id=%s AND author_id=%s",
    "ai_summary": "UPDATE idea SET ai_summary=%s, updated_at=NOW() WHERE id=%s AND author_id=%s",
    "ai_tags": "UPDATE idea SET ai_tags=%s, updated_at=NOW() WHERE id=%s AND author_id=%s",
    "content_hash": "UPDATE idea SET content_hash=%s, updated_at=NOW() WHERE id=%s AND author_id=%s",
}


def _serialize(row):
    """DictCursor 行 -> 可 jsonify 的 dict（datetime 转 ISO 字符串）。"""
    d = dict(row)
    category = d.get("category")
    d["category_label"] = CATEGORY_LABELS.get(category, category or "其他")
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat(sep=" ", timespec="seconds")
    return d


def get_user(uid):
    """供路由层校验登录态，与 app.py 中 db.get_user 的用途一致。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, nickname, status FROM app_user WHERE id=%s",
                (uid,),
            )
            return cur.fetchone()


def create_idea(author_id, data):
    """创建 idea，返回新 id。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM app_user WHERE id=%s AND status='active' FOR UPDATE", (author_id,))
            if not cur.fetchone():
                conn.rollback()
                return None
            cur.execute(
                "INSERT INTO idea "
                "(author_id, title, content, category, tags, status, visibility, content_hash) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    author_id,
                    data.get("title"),
                    data.get("content"),
                    data.get("category"),
                    data.get("tags"),
                    data.get("status", "draft"),
                    data.get("visibility", "public"),
                    data.get("content_hash"),
                ),
            )
            idea_id = cur.lastrowid
            sync_idea_tags(conn, idea_id, data.get("tags"))
            conn.commit()
            return idea_id


def get_idea(idea_id):
    """返回 idea 字典（附作者昵称），不存在返回 None。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT i.*, u.nickname AS author_nickname FROM idea i "
                "LEFT JOIN app_user u ON u.id=i.author_id WHERE i.id=%s",
                (idea_id,),
            )
            return cur.fetchone()


def _can_view(cur, idea_id, viewer_id):
    """可见性判定：public 全部登录用户；friends 作者或双向好友；private 仅作者。

    额外规则：非作者只能看到 published 的条目，草稿/归档不对外泄露。
    """
    cur.execute(
        "SELECT author_id, visibility, status, moderation_state FROM idea WHERE id=%s",
        (idea_id,),
    )
    row = cur.fetchone()
    if not row:
        return False
    if row["author_id"] == viewer_id:
        return True
    if row["moderation_state"] != "active" or row["status"] != "published":
        return False
    if row["visibility"] == "public":
        return True
    if row["visibility"] == "friends":
        cur.execute(
            "SELECT 1 FROM friend WHERE "
            "(user_id=%s AND friend_id=%s) OR (user_id=%s AND friend_id=%s) LIMIT 1",
            (row["author_id"], viewer_id, viewer_id, row["author_id"]),
        )
        return cur.fetchone() is not None
    return False


def can_view_idea(idea_id, viewer_id):
    """供路由层在渲染详情前做可见性判定。"""
    with connect() as conn:
        with conn.cursor() as cur:
            return _can_view(cur, idea_id, viewer_id)


def list_ideas(viewer_id, category=None, tag=None, author_id=None, page=1, size=20,
               q=None, sort="new"):
    """分页列表，返回 (items, total)。可见性过滤在 SQL 层完成。

    q 匹配标题、正文、兼容标签串、启用中的标签字典及当前作者昵称；tag 支持
    同一口径的精确筛选。排序仅使用固定白名单，分页 LIMIT/OFFSET 保持参数化。
    """
    page = max(1, int(page or 1))
    size = min(100, max(1, int(size or 20)))
    offset = (page - 1) * size
    order = ("i.like_count DESC, i.created_at DESC, i.id DESC"
             if sort == "hot" else "i.created_at DESC, i.id DESC")
    # 关键词去掉 %、_ 与反斜杠，避免用户输入改变 LIKE 通配或转义语义。
    clean = "".join(ch for ch in str(q or "").strip() if ch not in ("%", "_", "\\"))[:60]
    kw = ("%" + clean + "%") if clean else None
    kw6 = [kw] * 6 if kw else [None] * 6
    params = [
        viewer_id, viewer_id, viewer_id,
        category, category,
        tag, tag, tag,
        author_id, author_id,
        *kw6,
    ]

    # 关键词条件：1 个判空 + 5 个 LIKE；昵称与标签字典条件均不产生重复行。
    _KW = ("AND (%s IS NULL OR i.title LIKE %s OR i.content LIKE %s "
           "OR i.tags LIKE %s OR u.nickname LIKE %s OR EXISTS (SELECT 1 FROM idea_tag it "
           "JOIN tag_dict d ON d.id=it.tag_id WHERE it.idea_id=i.id "
           "AND d.status='active' AND d.name LIKE %s))")
    _TAG = ("AND (%s IS NULL OR FIND_IN_SET(%s, i.tags)>0 OR EXISTS ("
            "SELECT 1 FROM idea_tag it JOIN tag_dict d ON d.id=it.tag_id "
            "WHERE it.idea_id=i.id AND d.status='active' AND d.name=%s))")

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total FROM idea i "
                "LEFT JOIN app_user u ON u.id=i.author_id "
                "WHERE i.status='published' AND i.moderation_state='active' AND ("
                "i.visibility='public' OR i.author_id=%s "
                "OR (i.visibility='friends' AND ("
                "EXISTS (SELECT 1 FROM friend f1 "
                "WHERE f1.user_id=i.author_id AND f1.friend_id=%s) "
                "OR EXISTS (SELECT 1 FROM friend f2 "
                "WHERE f2.user_id=%s AND f2.friend_id=i.author_id)"
                "))) "
                "AND (%s IS NULL OR i.category=%s) "
                + _TAG +
                " AND (%s IS NULL OR i.author_id=%s) " + _KW,
                params,
            )
            total = cur.fetchone()["total"]

            cur.execute(
                "SELECT i.id, i.author_id, i.title, i.content, i.category, i.tags, "
                "i.status, i.visibility, i.like_count, i.favorite_count, i.comment_count, "
                "i.ai_category, i.ai_summary, i.ai_tags, i.created_at, i.updated_at, "
                "u.nickname AS author_nickname FROM idea i "
                "LEFT JOIN app_user u ON u.id=i.author_id "
                "WHERE i.status='published' AND i.moderation_state='active' AND ("
                "i.visibility='public' OR i.author_id=%s "
                "OR (i.visibility='friends' AND ("
                "EXISTS (SELECT 1 FROM friend f1 "
                "WHERE f1.user_id=i.author_id AND f1.friend_id=%s) "
                "OR EXISTS (SELECT 1 FROM friend f2 "
                "WHERE f2.user_id=%s AND f2.friend_id=i.author_id)"
                "))) "
                "AND (%s IS NULL OR i.category=%s) "
                + _TAG +
                " AND (%s IS NULL OR i.author_id=%s) " + _KW + " "
                "ORDER BY " + order + " LIMIT %s OFFSET %s",
                params + [size, offset],
            )
            items = [_serialize(r) for r in cur.fetchall()]
            return items, total


# 领域头条：与 /api/archive.json 共用同一公开口径（published + public），
# **不带 viewer_id**，从结构上杜绝 friends/private/draft 进入公开展示位。
_FEATURED_SQL = (
    "SELECT t.id, t.category, t.title, t.tags, "
    "t.like_count, t.favorite_count, t.comment_count, "
    "t.author_nickname, t.created_at "
    "FROM ("
    "  SELECT i.id, i.category, i.title, i.tags, "
    "         i.like_count, i.favorite_count, i.comment_count, "
    "         u.nickname AS author_nickname, i.created_at, "
    "         ROW_NUMBER() OVER ("
    "           PARTITION BY i.category "
    "           ORDER BY i.like_count DESC, i.created_at DESC, i.id DESC"
    "         ) AS rn "
    "  FROM idea i "
    "  LEFT JOIN app_user u ON u.id=i.author_id "
    "  WHERE i.status='published' AND i.visibility='public' AND i.moderation_state='active'"
    ") t "
    "WHERE t.rn=1 "
    "ORDER BY t.like_count DESC, t.category"
)


def featured_by_category(viewer_id=None):
    """领域头条：每个分类点赞最高、已发布且公开的一条 idea。

    viewer_id 仅为兼容旧调用保留，不参与查询；公开口径硬编码在 SQL。
    分类固定为六类，中文名仅作显示回退。
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_FEATURED_SQL)
            rows = cur.fetchall()

    items = []
    for row in rows:
        item = _serialize(row)
        cat = item.get("category")
        if cat is None or str(cat).strip() == "":
            continue
        item["category_label"] = CATEGORY_LABELS.get(cat, cat)
        items.append(item)
    return items


def list_owned_ideas(viewer_id, page=1, size=20, q=None, category=None,
                     status=None, tag=None, sort="updated"):
    page = max(1, int(page or 1))
    size = min(100, max(1, int(size or 20)))
    clean = "".join(ch for ch in str(q or "").strip() if ch not in ("%", "_", "\\"))[:60]
    kw = ("%" + clean + "%") if clean else None
    clean_tag = "".join(ch for ch in str(tag or "").strip() if ch not in ("%", "_", "\\"))[:20]
    exact_tag = clean_tag or None
    params = [viewer_id, category, category, status, status, exact_tag, exact_tag, exact_tag, kw, kw, kw, kw, kw]
    where = (
        "i.author_id=%s AND (%s IS NULL OR i.category=%s) "
        "AND (%s IS NULL OR i.status=%s) "
        "AND (%s IS NULL OR FIND_IN_SET(%s, i.tags)>0 OR EXISTS (SELECT 1 FROM idea_tag it "
        "JOIN tag_dict d ON d.id=it.tag_id WHERE it.idea_id=i.id "
        "AND d.status='active' AND d.name=%s)) "
        "AND (%s IS NULL OR i.title LIKE %s OR i.content LIKE %s "
        "OR i.tags LIKE %s OR EXISTS (SELECT 1 FROM idea_tag it "
        "JOIN tag_dict d ON d.id=it.tag_id WHERE it.idea_id=i.id "
        "AND d.status='active' AND d.name LIKE %s))"
    )
    order = ("i.like_count DESC, i.updated_at DESC, i.id DESC"
             if sort == "hot" else "i.updated_at DESC, i.id DESC")
    fields = (
        "i.id, i.author_id, i.title, i.content, i.category, i.tags, i.status, "
        "i.visibility, i.moderation_state, i.moderation_reason, i.row_version, "
        "i.like_count, i.favorite_count, i.comment_count, i.created_at, i.updated_at"
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM idea i WHERE " + where, params)
            total = cur.fetchone()["total"]
            cur.execute(
                "SELECT " + fields + " FROM idea i WHERE " + where +
                " ORDER BY " + order + " LIMIT %s OFFSET %s",
                params + [size, (page - 1) * size],
            )
            return [_serialize(row) for row in cur.fetchall()], total


def list_favorited_ideas(viewer_id, page=1, size=20, q=None, category=None,
                         tag=None, sort="new", include_unavailable=False):
    page = max(1, int(page or 1))
    size = min(100, max(1, int(size or 20)))
    clean = "".join(ch for ch in str(q or "").strip() if ch not in ("%", "_", "\\"))[:60]
    kw = ("%" + clean + "%") if clean else None
    params = [
        viewer_id, viewer_id, viewer_id, viewer_id,
        category, category, tag, tag, tag, kw, kw, kw, kw, kw,
    ]
    where = (
        "f.user_id=%s AND (i.author_id=%s OR (i.moderation_state='active' "
        "AND i.status='published' AND (i.visibility='public' OR "
        "(i.visibility='friends' AND (EXISTS (SELECT 1 FROM friend f1 "
        "WHERE f1.user_id=i.author_id AND f1.friend_id=%s) OR EXISTS "
        "(SELECT 1 FROM friend f2 WHERE f2.user_id=%s AND f2.friend_id=i.author_id)))))) "
        "AND (%s IS NULL OR i.category=%s) "
        "AND (%s IS NULL OR FIND_IN_SET(%s, i.tags)>0 OR EXISTS (SELECT 1 FROM idea_tag it "
        "JOIN tag_dict d ON d.id=it.tag_id WHERE it.idea_id=i.id AND d.status='active' AND d.name=%s)) "
        "AND (%s IS NULL OR i.title LIKE %s OR i.content LIKE %s OR i.tags LIKE %s "
        "OR EXISTS (SELECT 1 FROM idea_tag it JOIN tag_dict d ON d.id=it.tag_id "
        "WHERE it.idea_id=i.id AND d.status='active' AND d.name LIKE %s))"
    )
    order = ("f.created_at DESC, f.idea_id DESC" if sort == "new"
             else "i.like_count DESC, f.created_at DESC, f.idea_id DESC")
    fields = (
        "i.id, i.author_id, i.title, i.content, i.category, i.tags, i.status, "
        "i.visibility, i.moderation_state, i.moderation_reason, i.row_version, i.like_count, "
        "i.favorite_count, i.comment_count, i.created_at, i.updated_at, "
        "u.nickname AS author_nickname, f.created_at AS favorited_at"
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total FROM idea_favorite f "
                "LEFT JOIN idea i ON i.id=f.idea_id WHERE " + where, params,
            )
            total = cur.fetchone()["total"]
            cur.execute(
                "SELECT " + fields + " FROM idea_favorite f "
                "LEFT JOIN idea i ON i.id=f.idea_id "
                "LEFT JOIN app_user u ON u.id=i.author_id WHERE " + where +
                " ORDER BY " + order + " LIMIT %s OFFSET %s",
                params + [size, (page - 1) * size],
            )
            items = [_serialize(row) for row in cur.fetchall()]
    unavailable = 0
    if include_unavailable and not any((q, category, tag)):
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS total FROM idea_favorite WHERE user_id=%s", (viewer_id,))
                unavailable = max(0, int(cur.fetchone()["total"]) - int(total))
    return items, total, unavailable


def profile_summary(viewer_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, COUNT(*) AS n FROM idea WHERE author_id=%s "
                "AND moderation_state='active' GROUP BY status", (viewer_id,),
            )
            counts = {row["status"]: int(row["n"]) for row in cur.fetchall()}
            cur.execute(
                "SELECT COALESCE(SUM(like_count),0) AS likes, "
                "COALESCE(SUM(favorite_count),0) AS favorites, "
                "COALESCE(SUM(comment_count),0) AS comments FROM idea "
                "WHERE author_id=%s AND moderation_state='active'", (viewer_id,),
            )
            metrics = cur.fetchone()
            cur.execute(
                "SELECT COUNT(*) AS total FROM idea_favorite f JOIN idea i ON i.id=f.idea_id "
                "WHERE f.user_id=%s AND (i.author_id=%s OR (i.moderation_state='active' "
                "AND i.status='published' AND (i.visibility='public' OR "
                "(i.visibility='friends' AND (EXISTS (SELECT 1 FROM friend f1 "
                "WHERE f1.user_id=i.author_id AND f1.friend_id=%s) OR EXISTS "
                "(SELECT 1 FROM friend f2 WHERE f2.user_id=%s AND f2.friend_id=i.author_id))))))",
                (viewer_id, viewer_id, viewer_id, viewer_id),
            )
            visible_favorites = int(cur.fetchone()["total"])
    return {
        "published": counts.get("published", 0),
        "draft": counts.get("draft", 0),
        "archived": counts.get("archived", 0),
        "likes": int(metrics["likes"]),
        "favorites": int(metrics["favorites"]),
        "comments": int(metrics["comments"]),
        "visible_favorites": visible_favorites,
    }


# ---------- 自定义标签字典 ----------

def _slug(name):
    return str(name).strip().lower().replace(" ", "_")[:60]


def sync_idea_tags(conn, idea_id, raw_tags):
    """以启用中的标签字典为准，同步 idea.tags 与 idea_tag。"""
    names = []
    seen = set()
    for part in str(raw_tags or "").split(","):
        name = part.strip()
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    names = names[:8]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM idea_tag WHERE idea_id=%s", (idea_id,))
        accepted = []
        for name in names:
            cur.execute(
                "INSERT INTO tag_dict (name, slug) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE slug=slug",
                (name[:60], _slug(name)),
            )
            cur.execute(
                "SELECT id, name, status FROM tag_dict WHERE slug=%s", (_slug(name),)
            )
            row = cur.fetchone()
            if row and row["status"] == "active":
                cur.execute(
                    "INSERT IGNORE INTO idea_tag (idea_id, tag_id) VALUES (%s, %s)",
                    (idea_id, row["id"]),
                )
                accepted.append(row["name"])
        cur.execute("UPDATE idea SET tags=%s WHERE id=%s", (",".join(accepted), idea_id))


def list_tags(q=None, limit=100, viewer_id=None):
    """返回当前用户可见已发布 idea 使用过的 active 标签。"""
    if viewer_id is None:
        raise ValueError("viewer_id is required")
    clean = "".join(ch for ch in str(q or "").strip() if ch not in ("%", "_", "\\"))[:60]
    kw = ("%" + clean + "%") if clean else None
    visible = (
        "vi.status='published' AND vi.moderation_state='active' AND ("
        "vi.visibility='public' OR vi.author_id=%s OR "
        "(vi.visibility='friends' AND ("
        "EXISTS (SELECT 1 FROM friend vf1 "
        "WHERE vf1.user_id=vi.author_id AND vf1.friend_id=%s) "
        "OR EXISTS (SELECT 1 FROM friend vf2 "
        "WHERE vf2.user_id=%s AND vf2.friend_id=vi.author_id)"
        ")))"
    )
    sql = (
        "SELECT d.id, d.name, d.slug, d.pinned, d.status, d.created_at, "
        "(SELECT COUNT(*) FROM idea_tag t JOIN idea vi ON vi.id=t.idea_id "
        f" WHERE t.tag_id=d.id AND {visible}) AS use_count "
        "FROM tag_dict d "
        "WHERE d.status='active' AND (%s IS NULL OR d.name LIKE %s) "
        "AND EXISTS (SELECT 1 FROM idea_tag et JOIN idea vi ON vi.id=et.idea_id "
        f" WHERE et.tag_id=d.id AND {visible}) "
        "ORDER BY d.pinned DESC, use_count DESC, d.created_at DESC LIMIT %s"
    )
    params = (
        viewer_id, viewer_id, viewer_id,
        viewer_id, viewer_id, viewer_id,
        kw, kw, min(200, max(1, int(limit))),
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [_serialize(r) for r in cur.fetchall()]


def list_categories(viewer_id=None):
    """固定六类与顺序；细分主题由标签表达，不随历史脏数据漂移。"""
    return [
        {"value": code, "label": CATEGORY_LABELS[code]} for code in CATEGORIES
    ]


def update_idea(idea_id, author_id, data, expected_version):
    """仅 active 作者可更新；版本冲突返回 conflict，撤销内容返回 revoked。"""
    pending = [(sql, data[k]) for k, sql in _UPDATES.items() if k in data]
    if not pending:
        return False
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT author_id, moderation_state, row_version, tags FROM idea "
                "WHERE id=%s FOR UPDATE",
                (idea_id,),
            )
            row = cur.fetchone()
            if not row or row["author_id"] != author_id:
                conn.rollback()
                return False
            if row["moderation_state"] != "active":
                conn.rollback()
                return "revoked"
            try:
                version_matches = int(expected_version) == int(row["row_version"])
            except (TypeError, ValueError):
                version_matches = False
            if not version_matches:
                conn.rollback()
                return "conflict"
            for sql, value in pending:
                cur.execute(sql, (value, idea_id, author_id))
            if any(key in data for key in ("title", "content", "category", "tags")):
                cur.execute(
                    "UPDATE idea SET ai_category=NULL, ai_summary=NULL, ai_tags=NULL WHERE id=%s",
                    (idea_id,),
                )
            if "tags" in data:
                old_tags = [t.strip().casefold() for t in str(row["tags"] or "").split(",") if t.strip()]
                new_tags = [t.strip().casefold() for t in str(data["tags"] or "").split(",") if t.strip()]
                if old_tags != new_tags:
                    sync_idea_tags(conn, idea_id, data["tags"])
            cur.execute("UPDATE idea SET row_version=row_version+1 WHERE id=%s", (idea_id,))
            conn.commit()
            return True


def delete_idea(idea_id, author_id):
    """仅作者可删除，同时清理关系表，返回是否命中记录。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT author_id, moderation_state FROM idea WHERE id=%s AND author_id=%s FOR UPDATE",
                (idea_id, author_id),
            )
            row = cur.fetchone()
            if not row or row["moderation_state"] != "active":
                conn.rollback()
                return "revoked" if row else False
            cur.execute(
                "DELETE FROM idea WHERE id=%s AND author_id=%s",
                (idea_id, author_id),
            )
            if not cur.rowcount:
                conn.rollback()
                return False
            cur.execute("DELETE FROM idea_favorite WHERE idea_id=%s", (idea_id,))
            cur.execute("DELETE FROM idea_like WHERE idea_id=%s", (idea_id,))
            cur.execute("DELETE FROM idea_comment WHERE idea_id=%s", (idea_id,))
            cur.execute("DELETE FROM idea_tag WHERE idea_id=%s", (idea_id,))
            cur.execute("DELETE FROM idea_ai_job WHERE idea_id=%s", (idea_id,))
            conn.commit()
            return True


# 收藏 / 点赞切换用固定 SQL（表名、列名写死，无任何拼接）
_FAV_DELETE = "DELETE FROM idea_favorite WHERE user_id=%s AND idea_id=%s"
_FAV_INSERT = (
    "INSERT INTO idea_favorite(user_id, idea_id) VALUES(%s,%s) "
    "ON DUPLICATE KEY UPDATE user_id=user_id"
)
_FAV_COUNT = (
    "UPDATE idea SET favorite_count="
    "(SELECT COUNT(*) FROM idea_favorite WHERE idea_id=%s) WHERE id=%s"
)
_LIKE_DELETE = "DELETE FROM idea_like WHERE user_id=%s AND idea_id=%s"
_LIKE_INSERT = (
    "INSERT INTO idea_like(user_id, idea_id) VALUES(%s,%s) "
    "ON DUPLICATE KEY UPDATE user_id=user_id"
)
_LIKE_COUNT = (
    "UPDATE idea SET like_count="
    "(SELECT COUNT(*) FROM idea_like WHERE idea_id=%s) WHERE id=%s"
)


def _toggle(delete_sql, insert_sql, count_sql, idea_id, user_id):
    """通用切换：先删后插（ON DUPLICATE KEY 兜底并发），按关系表重算计数。

    返回切换后的状态 True/False；idea 不存在返回 None。
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM app_user WHERE id=%s AND status='active' FOR UPDATE", (user_id,))
            if not cur.fetchone():
                conn.rollback()
                return None
            cur.execute(
                "SELECT author_id, visibility, status, moderation_state FROM idea WHERE id=%s FOR UPDATE",
                (idea_id,),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return None
            if row["moderation_state"] != "active":
                conn.rollback()
                return None
            if not _can_view(cur, idea_id, user_id):
                conn.rollback()
                return None
            cur.execute(delete_sql, (user_id, idea_id))
            removed = cur.rowcount > 0
            if not removed:
                cur.execute(insert_sql, (user_id, idea_id))
            cur.execute(count_sql, (idea_id, idea_id))
            conn.commit()
            return not removed


def toggle_favorite(idea_id, user_id):
    """切换收藏，返回切换后是否收藏；idea 不存在返回 None。"""
    return _toggle(_FAV_DELETE, _FAV_INSERT, _FAV_COUNT, idea_id, user_id)


def toggle_like(idea_id, user_id):
    """切换点赞，返回切换后是否点赞；idea 不存在返回 None。"""
    return _toggle(_LIKE_DELETE, _LIKE_INSERT, _LIKE_COUNT, idea_id, user_id)


def user_has_favorited(idea_id, user_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM idea_favorite WHERE user_id=%s AND idea_id=%s",
                (user_id, idea_id),
            )
            return cur.fetchone() is not None


def user_has_liked(idea_id, user_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM idea_like WHERE user_id=%s AND idea_id=%s",
                (user_id, idea_id),
            )
            return cur.fetchone() is not None


def list_comments(idea_id, viewer_id):
    """评论列表；idea 不可见时返回空列表。"""
    with connect() as conn:
        with conn.cursor() as cur:
            if not _can_view(cur, idea_id, viewer_id):
                return []
            cur.execute(
                "SELECT c.id, c.idea_id, c.user_id, c.parent_id, c.content, c.created_at, "
                "u.nickname AS author_nickname FROM idea_comment c "
                "LEFT JOIN app_user u ON u.id=c.user_id "
                "WHERE c.idea_id=%s ORDER BY c.id ASC",
                (idea_id,),
            )
            return [_serialize(r) for r in cur.fetchall()]


def add_comment(idea_id, user_id, content, parent_id=None):
    """新增评论，返回 id；idea 不可见或 parent 非法时返回 None。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM app_user WHERE id=%s AND status='active' FOR UPDATE", (user_id,))
            if not cur.fetchone():
                conn.rollback()
                return None
            cur.execute(
                "SELECT author_id, visibility, status, moderation_state FROM idea WHERE id=%s FOR UPDATE",
                (idea_id,),
            )
            idea = cur.fetchone()
            if not idea or idea["moderation_state"] != "active":
                conn.rollback()
                return None
            if not _can_view(cur, idea_id, user_id):
                conn.rollback()
                return None
            if parent_id is not None:
                cur.execute(
                    "SELECT idea_id FROM idea_comment WHERE id=%s",
                    (parent_id,),
                )
                parent = cur.fetchone()
                if not parent or parent["idea_id"] != idea_id:
                    conn.rollback()
                    return None
            cur.execute(
                "INSERT INTO idea_comment(idea_id, user_id, parent_id, content) "
                "VALUES(%s,%s,%s,%s)",
                (idea_id, user_id, parent_id, content),
            )
            comment_id = cur.lastrowid
            cur.execute(
                "UPDATE idea SET comment_count="
                "(SELECT COUNT(*) FROM idea_comment WHERE idea_id=%s) WHERE id=%s",
                (idea_id, idea_id),
            )
            conn.commit()
            return comment_id
