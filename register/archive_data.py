"""研究成果数据访问层（独立模块，纯增量，不改动 db.py / app.py）。

设计原则：
  1. 不 import db，按 db.py 的 _config() 思路自行实现配置读取；
  2. 关键凭据缺失时直接返回 []，不尝试连接、不抛异常；
  3. 连接/查询失败时仅记 warning 并返回 []，由调用方回退静态数据；
  4. 只执行只读 SELECT，不写任何数据。
"""

import logging
import os

import pymysql
from pymysql.cursors import DictCursor

log = logging.getLogger(__name__)

# 只读查询：固定列 + 稳定排序，避免 SELECT * 带来的字段耦合。
_SELECT_SQL = """
    SELECT id, category, kind, title, year, status, summary, tags,
           owner, metric, metric_label, method, finding, impact,
           geom_x, geom_y, geom_w, geom_h, geom_r, geom_z
    FROM research_achievement
    ORDER BY sort_order, id
"""

# 状态 -> 前端角标：已发表不显示角标，进行中 / 已结项分别显示 doing / done。
_STATUS_TO_ST = {
    "已发表": "",
    "进行中": "doing",
    "已结项": "done",
}


def _config():
    """按 db.py 的思路自行实现，避免 import db 造成耦合。"""
    return dict(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", ""),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get("DB_NAME", "school"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,  # 只读查询，无需事务
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
    )


def _tags(raw):
    """逗号分隔字符串 -> 去空白后的标签列表。"""
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _num(value):
    """可选几何字段：NULL 统一回退为 0，保证前端拿到数字。"""
    return 0 if value is None else value


def _to_item(row):
    """数据库行 -> 前端一致结构。"""
    status = row.get("status") or ""
    return {
        "id": row.get("id"),
        # 前端 code 与数据库主键同源（形如 P-01），DB 未单设 code 列。
        "code": row.get("id"),
        "cat": row.get("category"),
        "kind": row.get("kind"),
        "title": row.get("title"),
        "year": row.get("year"),
        "status": status,
        "st": _STATUS_TO_ST.get(status, ""),
        "summary": row.get("summary"),
        "tags": _tags(row.get("tags")),
        "owner": row.get("owner"),
        "metric": row.get("metric"),
        "metricLabel": row.get("metric_label"),
        "method": row.get("method"),
        "finding": row.get("finding"),
        "impact": row.get("impact"),
        # 前端部分纸片所需的装饰字段；DB 未设对应列时给安全空值，
        # 避免 archive.js 中 (p.rows || []) / p.red / p.refs 渲染异常。
        "rows": [],
        "red": "",
        "refs": "",
        "x": _num(row.get("geom_x")),
        "y": _num(row.get("geom_y")),
        "w": _num(row.get("geom_w")),
        "h": _num(row.get("geom_h")),
        "r": _num(row.get("geom_r")),
        "z": _num(row.get("geom_z")),
    }


def load_achievements():
    """返回与前端一致结构的 list[dict]；DB 不可用时返回 []（由调用方回退静态数据）。"""
    # 关键凭据缺失：不连接、不抛异常，直接降级。
    if not (os.environ.get("DB_USER") or "").strip():
        return []
    if not (os.environ.get("DB_PASSWORD") or "").strip():
        return []

    conn = None
    try:
        conn = pymysql.connect(**_config())
        with conn.cursor() as cur:
            cur.execute(_SELECT_SQL)
            return [_to_item(row) for row in cur.fetchall()]
    except Exception as exc:
        # DB 未启动、账号无权限、表不存在等情况一律降级，绝不影响请求。
        log.warning("研究成果数据读取失败，回退静态数据: %s", exc)
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ------------------------------------------------------------------
# 填数据示例（仅注释，不执行）。填好后去掉行首 "# " 即可手工导入：
#
# INSERT INTO research_achievement
#   (id, category, kind, title, year, status, summary, tags, owner,
#    metric, metric_label, method, finding, impact,
#    geom_x, geom_y, geom_w, geom_h, geom_r, geom_z, sort_order)
# VALUES
#   ('P-01', 'ai', 'poster', '多模态大模型评测基准', '2025', '已发表',
#    '构建跨模态一致性评测集', '多模态,评测', '张三', '92.5', '综合准确率',
#    '人工标注 + 自动校验', '跨模态对齐仍是主要短板', '已被三家团队采用',
#    120, 80, 220, 160, -6, 3, 1);
#
# INSERT INTO research_achievement
#   (id, category, kind, title, year, status, summary, tags, owner,
#    metric, metric_label, method, finding, impact,
#    geom_x, geom_y, geom_w, geom_h, geom_r, geom_z, sort_order)
# VALUES
#   ('P-02', 'bio', 'sheet', '蛋白质结构预测数据集', '2024', '进行中',
#    '覆盖罕见折叠类型的数据集', '生物信息,数据集', '李四', '1800', '样本数',
#    '同源建模与实验验证结合', '罕见折叠覆盖度不足', '补充了公开数据空白',
#    380, 140, 200, 150, 4, 2, 2);
#
# INSERT INTO research_achievement
#   (id, category, kind, title, year, status, summary, tags, owner,
#    metric, metric_label, method, finding, impact,
#    geom_x, geom_y, geom_w, geom_h, geom_r, geom_z, sort_order)
# VALUES
#   ('P-03', 'energy', 'blueprint', '固态电解质界面模型', '2023', '已结项',
#    '界面离子输运的可解释模型', '能源材料,模拟', '王五', '3.2', '倍率提升',
#    '分子动力学 + 阻抗谱拟合', '界面阻抗主导衰减', '指导了下一代配方设计',
#    640, 90, 240, 170, 8, 1, 3);
# ------------------------------------------------------------------
