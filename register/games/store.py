"""游戏子系统自有的持久化数据访问。

邀请存 game_invite，而不是把机器 JSON 混进普通 IM 文本；所有 SQL 参数化。
进行中的棋盘仍只放内存，本模块不保存每步状态。
"""

import db as root_db


def create_invite(room_id, game, from_id, to_id):
    """创建或复用同一发起人的待处理邀请，返回邀请 id。

    旧邀请与房间同寿命（1 小时）；重复发起时先让旧记录过期，
    避免接收方上线后看到一叠已失效的邀请。
    """
    with root_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE game_invite SET status='expired', handled_at=NOW() "
                "WHERE conv_id=%s AND to_id=%s AND status='pending' "
                "AND created_at < NOW() - INTERVAL 1 HOUR",
                (room_id, to_id),
            )
            cur.execute(
                "SELECT id FROM game_invite "
                "WHERE conv_id=%s AND game=%s AND from_id=%s AND to_id=%s "
                "AND status='pending' AND created_at >= NOW() - INTERVAL 1 HOUR "
                "ORDER BY id DESC LIMIT 1",
                (room_id, game, from_id, to_id),
            )
            row = cur.fetchone()
            if row:
                conn.commit()
                return row["id"]
            cur.execute(
                "INSERT INTO game_invite(conv_id, game, from_id, to_id) "
                "VALUES(%s,%s,%s,%s)",
                (room_id, game, from_id, to_id),
            )
            invite_id = cur.lastrowid
            conn.commit()
            return invite_id


def pending_for(uid, limit=20):
    """用户上线时读取待处理邀请；不依赖对方当前在线。"""
    with root_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT g.id, g.conv_id, g.game, g.from_id, g.to_id, "
                "       g.created_at, u.nickname AS from_name "
                "FROM game_invite g "
                "LEFT JOIN app_user u ON u.id=g.from_id "
                "WHERE g.to_id=%s AND g.status='pending' "
                "AND g.created_at >= NOW() - INTERVAL 1 HOUR "
                "ORDER BY g.id DESC LIMIT %s",
                (uid, limit),
            )
            return cur.fetchall()


def pending_in_room(room_id, uid):
    with root_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, conv_id, game, from_id, to_id FROM game_invite "
                "WHERE conv_id=%s AND to_id=%s AND status='pending' "
                "AND created_at >= NOW() - INTERVAL 1 HOUR "
                "ORDER BY id DESC LIMIT 1",
                (room_id, uid),
            )
            return cur.fetchone()


def accept_pending(room_id, uid):
    """接受房间中属于自己的全部待处理邀请，返回是否有记录。"""
    with root_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE game_invite SET status='accepted', handled_at=NOW() "
                "WHERE conv_id=%s AND to_id=%s AND status='pending'",
                (room_id, uid),
            )
            changed = cur.rowcount
            conn.commit()
            return changed > 0


def decline_pending(room_id, uid):
    """仅邀请接收方可拒绝；返回邀请记录供在线通知发起人。"""
    with root_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, conv_id, game, from_id, to_id FROM game_invite "
                "WHERE conv_id=%s AND to_id=%s AND status='pending' "
                "AND created_at >= NOW() - INTERVAL 1 HOUR "
                "ORDER BY id DESC LIMIT 1",
                (room_id, uid),
            )
            row = cur.fetchone()
            if not row:
                return None
            cur.execute(
                "UPDATE game_invite SET status='declined', handled_at=NOW() "
                "WHERE id=%s AND to_id=%s AND status='pending'",
                (row["id"], uid),
            )
            conn.commit()
            return row if cur.rowcount else None


def expire_pending(room_id, uid):
    """内存房间已过期时，清理该用户在此房间的旧待处理邀请。"""
    with root_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE game_invite SET status='expired', handled_at=NOW() "
                "WHERE conv_id=%s AND to_id=%s AND status='pending'",
                (room_id, uid),
            )
            conn.commit()
