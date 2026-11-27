"""注册系统数据访问层。"""

import hashlib
import hmac
import os

import pymysql
from pymysql.cursors import DictCursor


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


# ---------- 名单校验 ----------

def find_student(student_no, real_name):
    """学号 + 姓名 同时匹配才返回记录。名单里姓名缺失的占位行不算。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, student_no, name, major, dorm_room FROM student "
                "WHERE student_no=%s AND name=%s AND name NOT LIKE '%%待补录%%'",
                (student_no, real_name),
            )
            return cur.fetchone()


# ---------- 唯一性 ----------

def is_taken(student_no=None, nickname=None, email=None):
    conds, params = [], []
    if student_no:
        conds.append("student_no=%s")
        params.append(student_no)
    if nickname:
        conds.append("nickname=%s")
        params.append(nickname)
    if email:
        conds.append("email=%s")
        params.append(email)
    if not conds:
        return None

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT student_no, nickname, email FROM app_user WHERE "
                + " OR ".join(conds),
                params,
            )
            return cur.fetchone()


# ---------- 验证码 ----------

CODE_ATTEMPT_PURPOSE = "register_attempt"
CODE_ATTEMPT_LIMIT = 5
CODE_ATTEMPT_WINDOW = 300


def _attempt_key(scope, value):
    """合成键落在现有 (email, purpose, created_at) 索引上，无需改表。"""
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    return scope + ":" + digest


def _attempt_lock_name(key):
    return "regtry:" + hashlib.sha256(key.encode("ascii")).hexdigest()[:48]


def save_code(email, code, ttl_minutes, ip=None):
    with connect() as conn:
        with conn.cursor() as cur:
            # 尝试事件只保留短时间；发码频率远低于验证频率，在这里分批清理，
            # 避免在每次校验的热路径上做无界 DELETE。
            cur.execute(
                "DELETE FROM email_code WHERE purpose=%s "
                "AND created_at <= DATE_SUB(NOW(), INTERVAL 10 MINUTE) "
                "ORDER BY id LIMIT 1000",
                (CODE_ATTEMPT_PURPOSE,),
            )
            # 同邮箱的旧码作废，保证只有最新一条有效
            cur.execute(
                "UPDATE email_code SET used=1 WHERE email=%s AND purpose='register' AND used=0",
                (email,),
            )
            cur.execute(
                "INSERT INTO email_code(email, code, purpose, expires_at, ip) "
                "VALUES(%s,%s,'register', DATE_ADD(NOW(), INTERVAL %s MINUTE), %s)",
                (email, code, ttl_minutes, ip),
            )
            challenge = cur.lastrowid
            conn.commit()
            return challenge


def check_code(email, code):
    """兼容旧调用方的只读校验；注册提交必须使用原子 verify_code。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM email_code "
                "WHERE email=%s AND code=%s AND purpose='register' "
                "AND used=0 AND expires_at > NOW() "
                "ORDER BY id DESC LIMIT 1",
                (email, code),
            )
            row = cur.fetchone()
            return row["id"] if row else None


def verify_code(email, code, challenge, ip, limit=CODE_ATTEMPT_LIMIT,
                window=CODE_ATTEMPT_WINDOW):
    """原子校验并消费最新验证码，返回 (code_id, remaining, status)。

    challenge 是 save_code 返回的服务端行 ID。挑战、邮箱、IP 三个滑动窗口
    各最多 limit 次；MySQL 命名锁串行化同一 bucket 的并发请求，行锁保证
    正确验证码只能被消费一次。旧会话没有 challenge 时按邮箱锁兼容迁移。
    """
    if challenge is not None:
        if not isinstance(challenge, (int, str)) or isinstance(challenge, bool):
            return None, 0, "invalid"
        try:
            challenge = int(challenge)
        except (TypeError, ValueError):
            return None, 0, "invalid"
        if challenge <= 0:
            return None, 0, "invalid"
    if limit < 1 or window < 1:
        return None, 0, "invalid"

    keys = {
        "email": _attempt_key("e", email),
        "ip": _attempt_key("i", ip or "unknown"),
    }
    if challenge is not None:
        keys["challenge"] = _attempt_key("c", challenge)
    # 固定为 IP -> 挑战 -> 邮箱；不同请求共享任一 bucket 时不会交叉等待成环。
    lock_names = [_attempt_lock_name(keys["ip"])]
    if "challenge" in keys:
        lock_names.append(_attempt_lock_name(keys["challenge"]))
    lock_names.append(_attempt_lock_name(keys["email"]))

    with connect() as conn:
        acquired = []
        try:
            with conn.cursor() as cur:
                for name in lock_names:
                    cur.execute("SELECT GET_LOCK(%s, 5) AS locked", (name,))
                    row = cur.fetchone()
                    if not row or row["locked"] != 1:
                        conn.rollback()
                        return None, 0, "busy"
                    acquired.append(name)

                # 先锁当前验证码行；这同时保证同邮箱的不同挑战也串行。
                cur.execute(
                    "SELECT id, code, expires_at FROM email_code "
                    "WHERE email=%s AND purpose='register' AND used=0 "
                    "AND expires_at > NOW() ORDER BY id DESC LIMIT 1 FOR UPDATE",
                    (email,),
                )
                current = cur.fetchone()
                if challenge is None and current:
                    challenge = int(current["id"])
                    keys["challenge"] = _attempt_key("c", challenge)

                remaining = limit - 1
                for key in keys.values():
                    cur.execute(
                        "SELECT COUNT(*) AS c FROM email_code "
                        "WHERE email=%s AND purpose=%s "
                        "AND created_at > DATE_SUB(NOW(), INTERVAL %s SECOND)",
                        (key, CODE_ATTEMPT_PURPOSE, window),
                    )
                    count = int(cur.fetchone()["c"])
                    remaining = min(remaining, limit - count - 1)
                    if count >= limit:
                        conn.commit()
                        return None, 0, "limited"

                # 三个范围各记一条事件；合成键避免 IP 计数退化为全表扫描。
                for key in keys.values():
                    cur.execute(
                        "INSERT INTO email_code(email, code, purpose, expires_at, ip) "
                        "VALUES(%s,'000000',%s,DATE_ADD(NOW(), INTERVAL %s SECOND),NULL)",
                        (key, CODE_ATTEMPT_PURPOSE, window),
                    )

                if (not current or int(current["id"]) != challenge
                        or current["expires_at"] is None):
                    conn.commit()
                    return None, max(0, remaining), "invalid"
                if not isinstance(code, str) or not hmac.compare_digest(
                        str(current["code"]), code):
                    conn.commit()
                    return None, max(0, remaining), "mismatch"

                cur.execute(
                    "UPDATE email_code SET used=1 WHERE id=%s AND used=0 "
                    "AND expires_at > NOW()",
                    (current["id"],),
                )
                if cur.rowcount != 1:
                    conn.rollback()
                    return None, 0, "invalid"
                conn.commit()
                return int(current["id"]), max(0, remaining), "ok"
        finally:
            if acquired:
                try:
                    with conn.cursor() as cur:
                        for name in reversed(acquired):
                            cur.execute("SELECT RELEASE_LOCK(%s) AS released", (name,))
                except Exception:
                    # 连接关闭也会释放命名锁；不能因清理失败改变校验结果。
                    pass


def release_code(code_id):
    """账号创建失败时归还已原子占用的验证码，保留原有重试体验。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE email_code SET used=0 WHERE id=%s AND used=1 "
                "AND purpose='register' AND expires_at > NOW()",
                (code_id,),
            )
            conn.commit()
            return cur.rowcount == 1


def consume_code(code_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE email_code SET used=1 WHERE id=%s", (code_id,))
            conn.commit()


def recent_code_count(email, minutes=60):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM email_code "
                "WHERE email=%s AND purpose='register' "
                "AND created_at > DATE_SUB(NOW(), INTERVAL %s MINUTE)",
                (email, minutes),
            )
            return cur.fetchone()["c"]


def last_code_age(email):
    """距上次发码的秒数，没有记录返回 None。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT TIMESTAMPDIFF(SECOND, created_at, NOW()) AS s "
                "FROM email_code WHERE email=%s AND purpose='register' "
                "ORDER BY id DESC LIMIT 1",
                (email,),
            )
            row = cur.fetchone()
            return row["s"] if row else None


# ---------- 用户 ----------

def create_user(student_no, real_name, nickname, email, password_hash):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO app_user(student_no, real_name, nickname, email, "
                "password_hash, email_verified, privacy_agreed_at) "
                "VALUES(%s,%s,%s,%s,%s,1,NOW())",
                (student_no, real_name, nickname, email, password_hash),
            )
            conn.commit()
            return cur.lastrowid


def get_user_by_login(login):
    """login 可以是邮箱或学号。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, student_no, real_name, nickname, email, password_hash, "
                "status, created_at, last_login_at "
                "FROM app_user WHERE email=%s OR student_no=%s LIMIT 1",
                (login, login),
            )
            return cur.fetchone()


def get_user(uid):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, student_no, real_name, nickname, email, avatar_url, "
                "status, created_at, last_login_at FROM app_user WHERE id=%s",
                (uid,),
            )
            return cur.fetchone()


def touch_login(uid):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE app_user SET last_login_at=NOW() WHERE id=%s", (uid,))
            conn.commit()


def update_nickname(uid, nickname):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE app_user SET nickname=%s WHERE id=%s", (nickname, uid))
            conn.commit()
            return cur.rowcount


def user_count():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM app_user")
            return cur.fetchone()["c"]


# ---------- 主页所需 ----------

def get_student_by_no(student_no):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT student_no, name, major, dorm_room, gender "
                "FROM student WHERE student_no=%s",
                (student_no,),
            )
            return cur.fetchone()


def get_teammates(dorm_room, exclude_uid):
    """同寝室且已注册的同学。"""
    if not dorm_room:
        return []
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT u.id, u.nickname, u.real_name, u.student_no "
                "FROM app_user u JOIN student s ON s.student_no = u.student_no "
                "WHERE s.dorm_room=%s AND u.id<>%s ORDER BY u.id",
                (dorm_room, exclude_uid),
            )
            return cur.fetchall()


def member_stats():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM app_user")
            total = cur.fetchone()["c"]
            cur.execute(
                "SELECT IFNULL(s.major,'未知') AS major, COUNT(*) AS c "
                "FROM app_user u LEFT JOIN student s ON s.student_no = u.student_no "
                "GROUP BY s.major ORDER BY c DESC"
            )
            by_major = cur.fetchall()
            cur.execute(
                "SELECT u.nickname, u.real_name, u.created_at "
                "FROM app_user u ORDER BY u.id DESC LIMIT 5"
            )
            latest = cur.fetchall()
    return {"total": total, "by_major": by_major, "latest": latest}


def list_members(exclude_uid=None):
    """已启用成员，用于左侧会话列表。"""
    sql = ("SELECT id, nickname, real_name, student_no FROM app_user "
           "WHERE status='active'")
    params = []
    if exclude_uid:
        sql += " AND id<>%s"
        params.append(exclude_uid)
    sql += " ORDER BY id DESC"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


# ---------- 密码 ----------

def get_password_hash(uid):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT password_hash FROM app_user WHERE id=%s", (uid,))
            row = cur.fetchone()
            return row["password_hash"] if row else None


def update_password(uid, pw_hash):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE app_user SET password_hash=%s WHERE id=%s", (pw_hash, uid))
            conn.commit()
            return cur.rowcount


# ---------- 密码重置 ----------

def create_reset_token(user_id, token, ttl_minutes=30, ip=None):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE password_reset SET used=1 WHERE user_id=%s AND used=0",
                (user_id,),
            )
            cur.execute(
                "INSERT INTO password_reset(user_id, token, expires_at, ip) "
                "VALUES(%s,%s, DATE_ADD(NOW(), INTERVAL %s MINUTE), %s)",
                (user_id, token, ttl_minutes, ip),
            )
            conn.commit()


def get_valid_reset(token):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT r.id, r.user_id, u.email, u.nickname "
                "FROM password_reset r JOIN app_user u ON u.id = r.user_id "
                "WHERE r.token=%s AND r.used=0 AND r.expires_at > NOW()",
                (token,),
            )
            return cur.fetchone()


def consume_reset(reset_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE password_reset SET used=1 WHERE id=%s", (reset_id,))
            conn.commit()


def claim_reset(token):
    """原子占用重置令牌：仅当未使用且未过期时置 used=1。

    返回 (user_id, email) 或 None。单条 UPDATE 的 rowcount 保证并发下只有一个请求成功，
    杜绝「校验→改密→消费」分离造成的 TOCTOU。
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT r.id, r.user_id, u.email FROM password_reset r "
                "JOIN app_user u ON u.id=r.user_id WHERE r.token=%s",
                (token,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cur.execute(
                "UPDATE password_reset SET used=1 WHERE id=%s AND used=0 "
                "AND expires_at > NOW()",
                (row["id"],),
            )
            claimed = cur.rowcount == 1
            conn.commit()
            if not claimed:
                return None
            return row["user_id"], row["email"]


# ---------- 登录历史 ----------

def last_login_ip(user_id):
    """返回该用户上一次登录的 IP（不含本次）。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ip FROM login_log WHERE user_id=%s ORDER BY id DESC LIMIT 1",
                (user_id,),
            )
            row = cur.fetchone()
            return row["ip"] if row else None


def add_login_log(user_id, ip, ua):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO login_log(user_id, ip, ua) VALUES(%s,%s,%s)",
                (user_id, ip, (ua or "")[:200]),
            )
            conn.commit()


# ---------- 账号状态 ----------

def set_status(user_id, status):
    if status not in ("active", "disabled"):
        raise ValueError("invalid status")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE app_user SET status=%s WHERE id=%s", (status, user_id))
            conn.commit()
            return cur.rowcount


# ---------- AI 对话 ----------

def add_chat_message(user_id, role, content, emotion=None, tokens=0):
    """写入 AI 会话历史（chat_message 表），不要与即时通讯的 add_im_message 混用。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_message(user_id, role, content, emotion, tokens) "
                "VALUES(%s,%s,%s,%s,%s)",
                (user_id, role, content, emotion, tokens),
            )
            conn.commit()
            return cur.lastrowid


def recent_messages(user_id, limit=24):
    """取最近 N 条，按时间正序返回（供拼装上游对话上下文）。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role, content FROM ("
                "  SELECT id, role, content FROM chat_message "
                "  WHERE user_id=%s ORDER BY id DESC LIMIT %s"
                ") t ORDER BY id ASC",
                (user_id, limit),
            )
            return cur.fetchall()


def chat_history(user_id, limit=50):
    """供前端渲染历史：含情绪与时间，按时间正序返回。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role, content, emotion, created_at FROM ("
                "  SELECT id, role, content, emotion, created_at FROM chat_message "
                "  WHERE user_id=%s ORDER BY id DESC LIMIT %s"
                ") t ORDER BY id ASC",
                (user_id, limit),
            )
            return cur.fetchall()


def all_chat_messages(user_id):
    """导出用：取该用户全部对话历史，按时间正序。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role, content, emotion, created_at FROM chat_message "
                "WHERE user_id=%s ORDER BY id ASC",
                (user_id,),
            )
            return cur.fetchall()


def clear_messages(user_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chat_message WHERE user_id=%s", (user_id,))
            conn.commit()
            return cur.rowcount


# ---------- 用量 ----------

def usage_today(user_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT calls FROM ai_usage WHERE user_id=%s AND day=CURDATE()",
                (user_id,),
            )
            row = cur.fetchone()
            return row["calls"] if row else 0


def bump_usage(user_id, tokens=0):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ai_usage(user_id, day, calls, tokens) "
                "VALUES(%s, CURDATE(), 1, %s) "
                "ON DUPLICATE KEY UPDATE calls=calls+1, tokens=tokens+VALUES(tokens)",
                (user_id, tokens),
            )
            conn.commit()


# ---------- AI 配置 ----------

def get_ai_config(key, default=""):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM ai_config WHERE key_name=%s", (key,))
            row = cur.fetchone()
            return row["value"] if row and row["value"] is not None else default


def set_ai_config(key, value):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ai_config(key_name, value) VALUES(%s,%s) "
                "ON DUPLICATE KEY UPDATE value=VALUES(value)",
                (key, value),
            )
            conn.commit()


# ---------- 用户自带 Key ----------

def save_user_key(user_id, key_enc, key_hint, base_url=None, model=None):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO user_ai_key(user_id, key_enc, key_hint, base_url, model, verified_at) "
                "VALUES(%s,%s,%s,%s,%s,NOW()) "
                "ON DUPLICATE KEY UPDATE key_enc=VALUES(key_enc), key_hint=VALUES(key_hint), "
                "base_url=VALUES(base_url), model=VALUES(model), verified_at=NOW()",
                (user_id, key_enc, key_hint, base_url, model),
            )
            conn.commit()


def get_user_key(user_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, key_enc, key_hint, base_url, model, verified_at "
                "FROM user_ai_key WHERE user_id=%s",
                (user_id,),
            )
            return cur.fetchone()


def delete_user_key(user_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_ai_key WHERE user_id=%s", (user_id,))
            conn.commit()
            return cur.rowcount


def key_owner_ids():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM user_ai_key")
            return {r["user_id"] for r in cur.fetchall()}


# ============ 即时通讯 ============

def search_user_by_no(student_no, exclude_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, student_no, real_name, nickname, avatar_url FROM app_user "
                "WHERE student_no=%s AND status='active' AND id<>%s",
                (student_no, exclude_id),
            )
            return cur.fetchone()


def set_avatar(user_id, url):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE app_user SET avatar_url=%s WHERE id=%s", (url, user_id))
            conn.commit()


def is_friend(user_id, other_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 AS x FROM friend WHERE user_id=%s AND friend_id=%s",
                (user_id, other_id),
            )
            return cur.fetchone() is not None


def send_friend_request(from_id, to_id, note=""):
    """返回 (ok, 说明)。已存在待处理申请时不重复插入。"""
    if from_id == to_id:
        return False, "不能添加自己"

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 AS x FROM friend WHERE user_id=%s AND friend_id=%s",
                (from_id, to_id),
            )
            if cur.fetchone():
                return False, "你们已经是好友了"

            cur.execute(
                "SELECT id FROM friend_request "
                "WHERE from_id=%s AND to_id=%s AND status='pending'",
                (from_id, to_id),
            )
            if cur.fetchone():
                return False, "已经发过申请，等对方处理"

            # 对方也给你发过申请 → 直接互加
            cur.execute(
                "SELECT id FROM friend_request "
                "WHERE from_id=%s AND to_id=%s AND status='pending'",
                (to_id, from_id),
            )
            rev = cur.fetchone()
            if rev:
                cur.execute(
                    "UPDATE friend_request SET status='accepted', handled_at=NOW() WHERE id=%s",
                    (rev["id"],),
                )
                _link_pair(cur, from_id, to_id)
                conn.commit()
                return True, "对方已申请过，已直接互为好友"

            try:
                # uk_pair 唯一约束兜底并发重复；已拒绝的申请重发时复活为 pending
                cur.execute(
                    "INSERT INTO friend_request(from_id, to_id, note, status) "
                    "VALUES(%s,%s,%s,'pending') "
                    "ON DUPLICATE KEY UPDATE "
                    "status='pending', note=VALUES(note), created_at=NOW(), handled_at=NULL",
                    (from_id, to_id, (note or "")[:100]),
                )
                conn.commit()
            except pymysql.err.IntegrityError:
                conn.rollback()
                return False, "已经发过申请，等对方处理"
            return True, "好友申请已发送"


def _link_pair(cur, a, b):
    cur.execute(
        "INSERT IGNORE INTO friend(user_id, friend_id) VALUES(%s,%s),(%s,%s)",
        (a, b, b, a),
    )
    lo, hi = (a, b) if a < b else (b, a)
    cur.execute(
        "INSERT IGNORE INTO conversation(user_a, user_b) VALUES(%s,%s)",
        (lo, hi),
    )


def pending_requests(to_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT r.id, r.from_id, r.note, r.created_at, "
                "u.nickname, u.real_name, u.student_no "
                "FROM friend_request r JOIN app_user u ON u.id=r.from_id "
                "WHERE r.to_id=%s AND r.status='pending' ORDER BY r.id DESC",
                (to_id,),
            )
            return cur.fetchall()


def handle_request(req_id, to_id, accept):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT from_id, to_id, status FROM friend_request WHERE id=%s",
                (req_id,),
            )
            row = cur.fetchone()
            if not row or row["to_id"] != to_id or row["status"] != "pending":
                return False

            cur.execute(
                "UPDATE friend_request SET status=%s, handled_at=NOW() WHERE id=%s",
                ("accepted" if accept else "rejected", req_id),
            )
            if accept:
                _link_pair(cur, row["from_id"], to_id)
            conn.commit()
            return True


def list_friends(user_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT u.id, u.student_no, u.nickname, u.real_name, u.avatar_url, f.created_at "
                "FROM friend f JOIN app_user u ON u.id=f.friend_id "
                "WHERE f.user_id=%s ORDER BY u.nickname",
                (user_id,),
            )
            return cur.fetchall()


def remove_friend(user_id, friend_id):
    """解除好友关系，同时删掉会话与聊天记录。

    只删 friend 表是不够的：会话仍然存在，双方还能继续发消息，
    因为发消息只校验「是否会话参与者」。这里一并清理。
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM friend WHERE (user_id=%s AND friend_id=%s) "
                "OR (user_id=%s AND friend_id=%s)",
                (user_id, friend_id, friend_id, user_id),
            )
            removed = cur.rowcount

            lo, hi = (user_id, friend_id) if user_id < friend_id else (friend_id, user_id)
            cur.execute(
                "SELECT id FROM conversation WHERE user_a=%s AND user_b=%s",
                (lo, hi),
            )
            row = cur.fetchone()
            if row:
                cur.execute("DELETE FROM message WHERE conv_id=%s", (row["id"],))
                cur.execute("DELETE FROM conversation WHERE id=%s", (row["id"],))

            conn.commit()
            return removed


def list_conversations(user_id):
    """会话列表：带对方信息、最后一条消息、未读数。

    用 UNION ALL 拆成两支，而不是 WHERE a=? OR b=?：
    OR 跨两列走不了索引，会退化为全表扫描。
    """
    sql = """
    SELECT c.id, c.last_at, c.user_b AS peer_id,
           u.nickname, u.real_name, u.student_no, u.avatar_url,
           (SELECT content FROM message m WHERE m.conv_id=c.id AND m.deleted_by_a=0
            ORDER BY m.id DESC LIMIT 1) AS last_text,
           (SELECT COUNT(*) FROM message m
            WHERE m.conv_id=c.id AND m.read_at IS NULL AND m.sender_id<>%s
              AND m.deleted_by_a=0) AS unread
    FROM conversation c
    JOIN app_user u ON u.id = c.user_b
    WHERE c.user_a = %s

    UNION ALL

    SELECT c.id, c.last_at, c.user_a AS peer_id,
           u.nickname, u.real_name, u.student_no, u.avatar_url,
           (SELECT content FROM message m WHERE m.conv_id=c.id AND m.deleted_by_b=0
            ORDER BY m.id DESC LIMIT 1) AS last_text,
           (SELECT COUNT(*) FROM message m
            WHERE m.conv_id=c.id AND m.read_at IS NULL AND m.sender_id<>%s
              AND m.deleted_by_b=0) AS unread
    FROM conversation c
    JOIN app_user u ON u.id = c.user_a
    WHERE c.user_b = %s

    ORDER BY last_at DESC, id DESC
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (user_id, user_id, user_id, user_id))
            return cur.fetchall()


def get_conversation(conv_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_a, user_b FROM conversation WHERE id=%s", (conv_id,)
            )
            return cur.fetchone()


def ensure_conversation(uid_a, uid_b):
    """取或建两人的单聊会话，返回会话 id。

    给「点开一个新好友直接发消息」用：此时会话尚未建立。
    user_a/user_b 固定小 id 在前，配合 uk_pair 唯一键保证幂等；
    并发下 INSERT 冲突则以 ON DUPLICATE KEY 兜底。
    """
    a, b = sorted((int(uid_a), int(uid_b)))
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO conversation(user_a, user_b) VALUES(%s, %s) "
                "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)",
                (a, b),
            )
            conn.commit()
            return cur.lastrowid


def get_pair_conversation(uid_a, uid_b):
    """按两个用户 id 取会话（对局房间用）。小 id 在前。"""
    a, b = sorted((int(uid_a), int(uid_b)))
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_a, user_b FROM conversation "
                "WHERE user_a=%s AND user_b=%s",
                (a, b),
            )
            return cur.fetchone()


def add_im_message(conv_id, sender_id, content, quote_id=None, forward_from=None):
    """写入即时通讯消息（message 表），不要与 AI 对话的 add_chat_message 混用。

    quote_id / forward_from 见总纲 §9B：引用不设外键，转发只存来源会话 id。
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO message(conv_id, sender_id, content, quote_id, forward_from) "
                "VALUES(%s,%s,%s,%s,%s)",
                (conv_id, sender_id, content, quote_id, forward_from),
            )
            mid = cur.lastrowid
            cur.execute(
                "UPDATE conversation SET last_msg_id=%s, last_at=NOW() WHERE id=%s",
                (mid, conv_id),
            )
            conn.commit()
            return mid


# 消息查询字段（含 §9B 新增列），集中定义避免两处 SELECT 不一致
_MSG_COLS = ("id, sender_id, content, quote_id, forward_from, "
             "read_at, created_at")


def list_messages(conv_id, after_id=0, limit=50, viewer_uid=None):
    """after_id>0 时只取新消息（轮询用）；否则取最近 N 条。

    viewer_uid 给定时过滤该用户已删除的消息（§9B.2 个人视图删除）。
    """
    with connect() as conn:
        with conn.cursor() as cur:
            # 在连接内查会话侧别，避免额外连接
            cur.execute("SELECT user_a, user_b FROM conversation WHERE id=%s", (conv_id,))
            conv = cur.fetchone()
            if viewer_uid and conv:
                col = ("deleted_by_a" if viewer_uid == conv["user_a"]
                       else "deleted_by_b" if viewer_uid == conv["user_b"] else None)
                if col is None:
                    return []
                where = f"AND {col}=0"
            else:
                where = ""

            if after_id:
                cur.execute(
                    f"SELECT {_MSG_COLS} FROM message "
                    f"WHERE conv_id=%s AND id>%s {where} ORDER BY id ASC LIMIT %s",
                    (conv_id, after_id, limit),
                )
                return cur.fetchall()
            cur.execute(
                f"SELECT * FROM (SELECT {_MSG_COLS} FROM message "
                f"WHERE conv_id=%s {where} ORDER BY id DESC LIMIT %s) t "
                "ORDER BY id ASC",
                (conv_id, limit),
            )
            return cur.fetchall()


def soft_delete_messages(conv_id, uid, ids):
    """批量置当前用户侧的删除标志，返回实际更新条数。

    只改自己视图，对方不受影响；消息物理保留，导出/备份仍可追溯。
    """
    if not ids:
        return 0
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_a, user_b FROM conversation WHERE id=%s", (conv_id,))
            conv = cur.fetchone()
            if not conv or uid not in (conv["user_a"], conv["user_b"]):
                return 0
            col = "deleted_by_a" if uid == conv["user_a"] else "deleted_by_b"
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                f"UPDATE message SET {col}=1 "
                f"WHERE conv_id=%s AND id IN ({placeholders})",
                (conv_id, *ids),
            )
            affected = cur.rowcount
            conn.commit()
            return affected


def get_messages_by_ids(conv_id, ids):
    """按 id 批量取指定会话内的消息（转发用）。只返回存在的、属于该会话的。"""
    if not ids:
        return []
    placeholders = ",".join(["%s"] * len(ids))
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, sender_id, content FROM message "
                f"WHERE conv_id=%s AND id IN ({placeholders}) ORDER BY id ASC",
                (conv_id, *ids),
            )
            return cur.fetchall()


def is_message_in_conv(msg_id, conv_id):
    """校验消息属于指定会话（引用防跨会话）。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM message WHERE id=%s AND conv_id=%s LIMIT 1",
                (msg_id, conv_id),
            )
            return cur.fetchone() is not None


def get_quote_summaries(ids):
    """按 id 批量取消息摘要，供引用块渲染。返回 {id: {sender_id, content}}。"""
    if not ids:
        return {}
    placeholders = ",".join(["%s"] * len(ids))
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, sender_id, content FROM message "
                f"WHERE id IN ({placeholders})",
                tuple(ids),
            )
            return {r["id"]: r for r in cur.fetchall()}


def mark_read_ids(conv_id, reader_id, ids):
    """只标记「实际展示给用户」的那批消息。

    调用方传 list_messages 返回的 id 集合。这样更早未展示的未读不会被误标，
    重复打开会话也不会把上一批之外的消息标掉。
    """
    if not ids:
        return 0
    placeholders = ",".join(["%s"] * len(ids))
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE message SET read_at=NOW() "
                f"WHERE conv_id=%s AND sender_id<>%s AND read_at IS NULL "
                f"AND id IN ({placeholders})",
                (conv_id, reader_id, *ids),
            )
            conn.commit()
            return cur.rowcount


def mark_all_read(conv_id, reader_id):
    """显式「全部标已读」（前端 /api/messages/read 调用）。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE message SET read_at=NOW() "
                "WHERE conv_id=%s AND sender_id<>%s AND read_at IS NULL",
                (conv_id, reader_id),
            )
            conn.commit()
            return cur.rowcount


def has_older_messages(conv_id, before_id):
    """是否存在指定 id 之前的消息。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM message WHERE conv_id=%s AND id<%s LIMIT 1",
                (conv_id, before_id),
            )
            return cur.fetchone() is not None


def total_unread(user_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM message m "
                "JOIN conversation c ON c.id=m.conv_id "
                "WHERE (c.user_a=%s OR c.user_b=%s) "
                "  AND m.sender_id<>%s AND m.read_at IS NULL "
                "  AND CASE WHEN c.user_a=%s THEN m.deleted_by_a=0 "
                "           ELSE m.deleted_by_b=0 END",
                (user_id, user_id, user_id, user_id),
            )
            return cur.fetchone()["c"]


# ---------- 对战归档 ----------

def save_game_record(conv_id, game, player_a, player_b, winner, reason, moves, steps,
                     ai_difficulty=None):
    """终局写一条归档。moves 为着法列表，由调用方转成 JSON 字符串。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO game_record"
                "(conv_id, game, ai_difficulty, player_a, player_b, winner, reason, moves, steps) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (conv_id, game, ai_difficulty, player_a, player_b, winner, reason,
                 moves, steps),
            )
            rid = cur.lastrowid
            conn.commit()
            return rid


def list_game_records(user_id, limit=20):
    """个人战绩：该用户参与的最近 N 局，附带对手昵称。

    PvE 的 player_b / winner 是字符串标记，查询与 Jinja 比较前统一处理。
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT g.id, g.conv_id, g.game, g.ai_difficulty, "
                "       g.player_a, g.player_b, g.winner, g.reason, "
                "       g.steps, g.created_at, "
                "       CASE WHEN g.player_b='ai:whale' "
                "            THEN CONCAT('小鲸', "
                "              IF(g.ai_difficulty IS NULL, '', "
                "                 CONCAT('（', g.ai_difficulty, '）'))) "
                "            ELSE u.nickname END AS opponent_name "
                "FROM game_record g "
                "LEFT JOIN app_user u ON u.id = CASE WHEN g.player_a=%s "
                "                          THEN g.player_b ELSE g.player_a END "
                "WHERE g.player_a=%s OR "
                "      (g.player_b REGEXP '^[0-9]+$' AND "
                "       CAST(g.player_b AS UNSIGNED)=%s) "
                "ORDER BY g.id DESC LIMIT %s",
                (user_id, user_id, user_id, limit),
            )
            rows = cur.fetchall()
    reason_labels = {
        "five_in_row": "五子连珠",
        "resign": "认输",
        "draw": "和棋",
        "ai_error": "AI 异常",
        "checkmate": "将死",
        "uno_out": "先出完牌",
    }
    for row in rows:
        winner = row.get("winner")
        if isinstance(winner, str) and winner.isdigit():
            row["winner"] = int(winner)
        row["reason_text"] = reason_labels.get(row.get("reason"), row.get("reason"))
    return rows
