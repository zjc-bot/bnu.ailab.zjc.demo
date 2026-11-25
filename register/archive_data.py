"""学习分享室（archive）公开数据访问层。

设计原则：
  1. 与 ideas/store.py 一致：import db; db.connect()，复用同一份 DB_* 配置，
     消除自实现 _config() 带来的配置漂移与误连风险；
  2. 公开口径硬编码在 SQL（status='published' AND visibility='public'），
     不带 viewer_id，从结构上杜绝 friends/private 泄漏；
  3. 所有 SQL 都是静态常量字符串：过滤值为硬编码枚举常量、无外部输入，
     因此没有任何字符串拼接 / f-string，天然免疫注入；
  4. 只执行只读 SELECT，不写任何数据；
  5. 任何异常（表不存在 / 权限不足 / 连接失败 / 映射异常）一律记 warning
     并返回 static 空结构，绝不把异常抛给请求。
"""

import logging
from collections import Counter

import db  # 与注册系统共用同一份 DB_* 配置与连接工厂

log = logging.getLogger(__name__)

# 8 种纸片形态：按序号（index）轮换，覆盖全部 8 种视觉。
_KINDS = ("poster", "sheet", "ticket", "card", "photo", "note", "journal", "blueprint")

# 8 组几何常量 (x, y, w, h, r, z)，与前端 paint 依赖的初始摆位一致。
_GEOMETRY = (
    (210, 78, 266, 212, -2, 3),
    (470, 58, 288, 200, 1.2, 2),
    (738, 92, 326, 132, -3, 5),
    (1008, 218, 202, 116, -7, 6),
    (232, 330, 238, 198, 3, 4),
    (500, 292, 232, 192, -4, 7),
    (752, 322, 252, 198, 2, 8),
    (988, 386, 196, 206, 5, 9),
)

# 公开纸片：硬编码公开过滤 + 稳定排序 + 限量，无 viewer_id、无外部值。
_ITEMS_SQL = (
    "SELECT i.id, i.title, i.content, i.category, i.tags, "
    "i.like_count, i.favorite_count, i.comment_count, i.created_at "
    "FROM idea i WHERE i.status='published' AND i.visibility='public' "
    "ORDER BY i.id DESC LIMIT 24"
)

# 标签聚合数据源：同一公开范围内的 idea.tags 逗号串（不 LIMIT，覆盖全部）。
_TAGS_SQL = (
    "SELECT i.tags FROM idea i "
    "WHERE i.status='published' AND i.visibility='public'"
)

# stats 五项：全部由 SQL 实时计算，过滤值为硬编码常量。
_STATS_SQL = (
    ("已参加人数", "SELECT COUNT(*) AS v FROM app_user WHERE status='active'"),
    ("平台内发布的总 idea 数", "SELECT COUNT(*) AS v FROM idea WHERE status='published'"),
    ("累计点赞", "SELECT COALESCE(SUM(like_count),0) AS v FROM idea WHERE status='published'"),
    ("累计收藏", "SELECT COALESCE(SUM(favorite_count),0) AS v FROM idea WHERE status='published'"),
    ("讨论数", "SELECT COUNT(*) AS v FROM idea_comment"),
)


def _empty_payload():
    """DB 不可用时的兜底：空 items + 五项 0 + 仅「全部」标签。"""
    return {
        "items": [],
        "stats": [{"label": label, "value": 0} for label, _ in _STATS_SQL],
        "tags": [{"id": "all", "label": "全部"}],
        "source": "static",
    }


def _tags(raw):
    """逗号分隔字符串 -> 去空白、去空项的标签列表。"""
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _year(created_at):
    """created_at -> 4 位年份字符串；兼容 datetime / date / 字符串 / None。"""
    if created_at is None:
        return ""
    if hasattr(created_at, "year"):
        return str(created_at.year)
    return str(created_at)[:4]


def _summary(content):
    """正文截断 120 字，只返回摘要，绝不返回全文。"""
    if not content:
        return ""
    return str(content)[:120]


def _code(idea_id):
    """I- 前缀 + 2 位补零编号（MySQL LPAD(id,2,'0') 的 Python 侧实现）。"""
    return "I-" + str(idea_id).zfill(2)


def _geometry(index):
    """按 index % 8 取几何；超过 8 条时抬高 z，避免整组纸片堆在同一层。"""
    x, y, w, h, r, z = _GEOMETRY[index % len(_GEOMETRY)]
    if index >= len(_GEOMETRY):
        z += (index // len(_GEOMETRY)) * 10
    return x, y, w, h, r, z


def _to_item(row, index):
    """idea 行 -> 学习分享室纸片结构（owner 统一脱敏为「社区成员」）。"""
    x, y, w, h, r, z = _geometry(index)
    like_count = row.get("like_count") or 0
    return {
        "id": row.get("id"),
        "code": _code(row.get("id")),
        "cat": row.get("category"),
        "kind": _KINDS[index % len(_KINDS)],
        "title": row.get("title"),
        "year": _year(row.get("created_at")),
        "summary": _summary(row.get("content")),
        "tags": _tags(row.get("tags")),
        "owner": "社区成员",
        "metric": str(like_count),
        "metricLabel": "赞",
        "method": "",
        "finding": "",
        "impact": "",
        "status": "已发布",
        "st": "",
        "rows": [],
        "red": "",
        "refs": "",
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "r": r,
        "z": z,
    }


def _build_tags(rows):
    """聚合公开范围内的 idea.tags：次数 DESC、名称 ASC，取前 9 + 「全部」= ≤10。"""
    counter = Counter()
    for row in rows:
        counter.update(_tags(row.get("tags")))
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    tags = [{"id": "all", "label": "全部"}]
    for name, _count in ordered[:9]:
        # id 用标签名本身，前端按 id 过滤 cat/tags。
        tags.append({"id": name, "label": name})
    return tags[:10]


def load_public_ideas():
    """返回契约中的完整 dict：items / stats / tags / source。

    DB 异常时降级为 static 空结构（source='static'、items=[]、stats 全 0、
    tags 仅「全部」），不抛异常给请求。
    """
    try:
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_ITEMS_SQL)
                rows = cur.fetchall()
                items = [_to_item(row, idx) for idx, row in enumerate(rows)]

                cur.execute(_TAGS_SQL)
                tags = _build_tags(cur.fetchall())

                stats = []
                for label, sql in _STATS_SQL:
                    cur.execute(sql)
                    stat_row = cur.fetchone() or {}
                    value = stat_row.get("v") or 0
                    stats.append({"label": label, "value": int(value)})

        return {
            "items": items,
            "stats": stats,
            "tags": tags,
            "source": "mysql",
        }
    except Exception as exc:
        log.warning("学习分享室公开数据读取失败，回退 static 空结构: %s", exc)
        return _empty_payload()


def load_achievements():
    """兼容别名：旧调用方只需要纸片列表，等价于 load_public_ideas()['items']。"""
    return load_public_ideas()["items"]
