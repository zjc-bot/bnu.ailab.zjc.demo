"""数据库访问层：全部使用参数化查询，禁止拼接 SQL。"""

import os

import pymysql
from pymysql.cursors import DictCursor

# 排序字段白名单：值只来自这里，不接受用户输入拼接
SORTABLE = {
    "id": "st.id",
    "student_no": "st.student_no",
    "name": "st.name",
    "dorm_room": "st.dorm_room",
    "major": "st.major",
}

BASE_SELECT = """
SELECT st.id, st.student_no, st.name, st.gender, st.major, st.dorm_room,
       st.remark, st.phone, st.email
FROM student st
"""


def _config():
    return dict(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", ""),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get("DB_NAME", "school"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
    )


def connect():
    return pymysql.connect(**_config())


def _like(value):
    """转义 LIKE 通配符，避免用户输入 % 或 _ 变成全表匹配。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _where(keyword, major):
    conds, params = [], []
    if keyword:
        conds.append(
            "(st.student_no LIKE %s OR st.name LIKE %s OR st.dorm_room LIKE %s "
            "OR st.major LIKE %s OR st.remark LIKE %s)"
        )
        kw = f"%{_like(keyword)}%"
        params += [kw] * 5
    if major:
        conds.append("st.major = %s")
        params.append(major)
    return (" WHERE " + " AND ".join(conds)) if conds else "", params


def list_students(keyword="", page=1, size=20, sort_by="student_no",
                  order="asc", major=None):
    sort_col = SORTABLE.get(sort_by, "st.student_no")
    direction = "DESC" if str(order).lower() == "desc" else "ASC"
    offset = (page - 1) * size
    where, params = _where(keyword, major)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS c FROM student st{where}", params)
            total = cur.fetchone()["c"]

            cur.execute(
                BASE_SELECT + where
                + f" ORDER BY {sort_col} {direction} LIMIT %s OFFSET %s",
                params + [size, offset],
            )
            rows = cur.fetchall()

    return {"items": rows, "total": total, "page": page, "size": size}


def get_student(sid):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(BASE_SELECT + " WHERE st.id=%s", (sid,))
            return cur.fetchone()


def create_student(d):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO student(student_no, name, gender, major, dorm_room, "
                "remark, phone, email) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (d["student_no"], d["name"], d["gender"], d["major"],
                 d["dorm_room"], d["remark"], d["phone"], d["email"]),
            )
            conn.commit()
            return cur.lastrowid


def update_student(sid, d):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE student SET student_no=%s, name=%s, gender=%s, major=%s, "
                "dorm_room=%s, remark=%s, phone=%s, email=%s WHERE id=%s",
                (d["student_no"], d["name"], d["gender"], d["major"],
                 d["dorm_room"], d["remark"], d["phone"], d["email"], sid),
            )
            conn.commit()
            return cur.rowcount


def delete_student(sid):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM student WHERE id=%s", (sid,))
            conn.commit()
            return cur.rowcount


def stats():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM student")
            total = cur.fetchone()["total"]

            cur.execute("SELECT COUNT(DISTINCT major) AS c FROM student")
            majors_cnt = cur.fetchone()["c"]

            cur.execute("SELECT COUNT(DISTINCT dorm_room) AS c FROM student")
            dorms_cnt = cur.fetchone()["c"]

            cur.execute(
                "SELECT major, COUNT(*) AS c FROM student "
                "GROUP BY major ORDER BY c DESC"
            )
            by_major = cur.fetchall()

    return {
        "total": total,
        "majors": majors_cnt,
        "dorms": dorms_cnt,
        "by_major": by_major,
    }
