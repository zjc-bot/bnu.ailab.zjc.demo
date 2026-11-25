"""Idea 社区数据访问层（Phase 1）。

设计约定：
  - 直接复用 register/db.py 的 connect()，确保 DB_* 配置单一来源；
    参数化 %s、with 连接、显式 commit。
  - 所有 SQL 的值一律参数化；动态 SET 的列名取自硬编码白名单字典，
    扫描/分页条件用「%s IS NULL OR ...」写法，因此没有任何字符串拼接。
  - 计数（like/favorite/comment）在同一事务内按关系表 COUNT 重算，保证一致。
"""

import db  # 与注册系统共用同一份 DB_* 配置与连接工厂，避免配置漂移


def connect():
    return db.connect()


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
                    data.get("visibility", "friends"),
                    data.get("content_hash"),
                ),
            )
            idea_id = cur.lastrowid
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
        "SELECT author_id, visibility, status FROM idea WHERE id=%s",
        (idea_id,),
    )
    row = cur.fetchone()
    if not row:
        return False
    if row["author_id"] == viewer_id:
        return True
    if row["status"] != "published":
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


def list_ideas(viewer_id, category=None, tag=None, author_id=None, page=1, size=20):
    """分页列表，返回 (items, total)。可见性过滤在 SQL 层完成。

    category / tag / author 三个筛选项用「%s IS NULL OR ...」表达，
    避免任何动态 SQL 拼接；tag 用 FIND_IN_SET 匹配逗号分隔标签。
    """
    page = max(1, int(page or 1))
    size = min(100, max(1, int(size or 20)))
    offset = (page - 1) * size
    params = [
        viewer_id, viewer_id, viewer_id,
        category, category,
        tag, tag,
        author_id, author_id,
    ]

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total FROM idea i "
                "WHERE i.status='published' AND ("
                "i.visibility='public' OR i.author_id=%s "
                "OR (i.visibility='friends' AND ("
                "EXISTS (SELECT 1 FROM friend f1 "
                "WHERE f1.user_id=i.author_id AND f1.friend_id=%s) "
                "OR EXISTS (SELECT 1 FROM friend f2 "
                "WHERE f2.user_id=%s AND f2.friend_id=i.author_id)"
                "))) "
                "AND (%s IS NULL OR i.category=%s) "
                "AND (%s IS NULL OR FIND_IN_SET(%s, i.tags)>0) "
                "AND (%s IS NULL OR i.author_id=%s)",
                params,
            )
            total = cur.fetchone()["total"]

            cur.execute(
                "SELECT i.id, i.author_id, i.title, i.content, i.category, i.tags, "
                "i.status, i.visibility, i.like_count, i.favorite_count, i.comment_count, "
                "i.ai_category, i.ai_summary, i.ai_tags, i.created_at, i.updated_at, "
                "u.nickname AS author_nickname FROM idea i "
                "LEFT JOIN app_user u ON u.id=i.author_id "
                "WHERE i.status='published' AND ("
                "i.visibility='public' OR i.author_id=%s "
                "OR (i.visibility='friends' AND ("
                "EXISTS (SELECT 1 FROM friend f1 "
                "WHERE f1.user_id=i.author_id AND f1.friend_id=%s) "
                "OR EXISTS (SELECT 1 FROM friend f2 "
                "WHERE f2.user_id=%s AND f2.friend_id=i.author_id)"
                "))) "
                "AND (%s IS NULL OR i.category=%s) "
                "AND (%s IS NULL OR FIND_IN_SET(%s, i.tags)>0) "
                "AND (%s IS NULL OR i.author_id=%s) "
                "ORDER BY i.created_at DESC, i.id DESC LIMIT %s OFFSET %s",
                params + [size, offset],
            )
            items = [_serialize(r) for r in cur.fetchall()]
            return items, total


def update_idea(idea_id, author_id, data):
    """仅作者可更新，返回是否命中记录。"""
    pending = [(sql, data[k]) for k, sql in _UPDATES.items() if k in data]
    if not pending:
        return False
    with connect() as conn:
        with conn.cursor() as cur:
            hit = False
            for sql, value in pending:
                cur.execute(sql, (value, idea_id, author_id))
                hit = hit or cur.rowcount > 0
            if hit:
                conn.commit()
            else:
                conn.rollback()
            return hit


def delete_idea(idea_id, author_id):
    """仅作者可删除，同时清理关系表，返回是否命中记录。"""
    with connect() as conn:
        with conn.cursor() as cur:
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
            cur.execute("SELECT 1 FROM idea WHERE id=%s", (idea_id,))
            if not cur.fetchone():
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
