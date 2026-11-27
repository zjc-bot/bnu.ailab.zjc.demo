"""Idea 内容治理：元数据、单条撤销/恢复与追加审计。"""

import hashlib
import json
import uuid
from uuid import uuid5, NAMESPACE_URL

import db
from pymysql.err import IntegrityError

REASON_CODES = ("spam", "abuse", "privacy", "unsafe", "other")
ACTIONS = ("revoke", "restore", "view_metadata", "view_content", "notify_sent", "notify_failed")


def _serialize(row):
    item = dict(row)
    for key, value in item.items():
        if hasattr(value, "isoformat"):
            item[key] = value.isoformat(sep=" ", timespec="seconds")
    return item


def _request_fingerprint(idea_id, action, expected_version, reason_code, reason_text, internal_note):
    payload = [idea_id, action, expected_version, reason_code, reason_text, internal_note]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


def _request_matches(row, fingerprint):
    if not row or not row.get("snapshot_json"):
        return False
    snapshot = row["snapshot_json"]
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot)
    return snapshot.get("request_fingerprint") == fingerprint


def list_ideas(q=None, state=None, page=1, size=30):
    page = max(1, int(page or 1))
    size = min(100, max(1, int(size or 30)))
    clean = "".join(ch for ch in str(q or "").strip() if ch not in ("%", "_", "\\"))[:60]
    kw = ("%" + clean + "%") if clean else None
    params = [kw, kw, kw, state, state]
    where = (
        "(%s IS NULL OR (i.visibility<>'private' AND "
        "(i.title LIKE %s OR u.nickname LIKE %s))) "
        "AND (%s IS NULL OR i.moderation_state=%s)"
    )
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total FROM idea i LEFT JOIN app_user u ON u.id=i.author_id WHERE " + where,
                params,
            )
            total = cur.fetchone()["total"]
            cur.execute(
                "SELECT i.id, "
                "CASE WHEN i.visibility='private' THEN CONCAT('[private idea #', i.id, ']') ELSE i.title END AS title, "
                "i.category, i.status, i.visibility, "
                "i.moderation_state, i.moderation_reason_code, i.moderation_reason, "
                "i.row_version, i.moderated_at, i.author_id, u.nickname AS author_nickname "
                "FROM idea i LEFT JOIN app_user u ON u.id=i.author_id WHERE " + where +
                " ORDER BY i.moderated_at DESC, i.id DESC LIMIT %s OFFSET %s",
                params + [size, (page - 1) * size],
            )
            return [_serialize(row) for row in cur.fetchall()], total


def get_metadata(idea_id):
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT i.id, "
                "CASE WHEN i.visibility='private' THEN CONCAT('[private idea #', i.id, ']') ELSE i.title END AS title, "
                "CASE WHEN i.visibility='private' THEN '' ELSE i.tags END AS tags, "
                "i.category, i.status, i.visibility, "
                "i.moderation_state, i.moderation_reason_code, i.moderation_reason, "
                "i.row_version, i.moderated_at, i.moderated_by, i.author_id, "
                "u.nickname AS author_nickname, u.email AS author_email, i.created_at, i.updated_at "
                "FROM idea i LEFT JOIN app_user u ON u.id=i.author_id WHERE i.id=%s",
                (idea_id,),
            )
            row = cur.fetchone()
            return _serialize(row) if row else None


def get_viewable_content(idea_id):
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content FROM idea WHERE id=%s AND visibility IN ('public','friends')",
                (idea_id,),
            )
            row = cur.fetchone()
            return row["content"] if row else None


def list_audit(idea_id, limit=100):
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, action, from_state, to_state, reason_code, reason_text, "
                "internal_note, admin_id, admin_name_snapshot, before_version, "
                "after_version, ip, created_at FROM idea_moderation_log "
                "WHERE idea_id=%s ORDER BY id DESC LIMIT %s",
                (idea_id, min(500, max(1, int(limit)))),
            )
            return [_serialize(row) for row in cur.fetchall()]


def record_audit(idea_id, action, admin_id, admin_name, request_id=None,
                 reason_code=None, reason_text=None, internal_note=None,
                 from_state=None, to_state=None, before_version=None,
                 after_version=None, snapshot=None, ip=None, ua=None):
    if action not in ACTIONS:
        raise ValueError("未知审计动作")
    with db.connect() as conn:
        with conn.cursor() as cur:
            if request_id:
                cur.execute("SELECT id FROM idea_moderation_log WHERE request_id=%s", (request_id,))
                if cur.fetchone():
                    return False
            cur.execute(
                "INSERT INTO idea_moderation_log (idea_id,action,from_state,to_state,"
                "reason_code,reason_text,internal_note,admin_id,admin_name_snapshot,"
                "request_id,before_version,after_version,snapshot_json,ip,ua) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    idea_id, action, from_state, to_state, reason_code, reason_text,
                    internal_note[:1000] if internal_note else None, admin_id,
                    admin_name[:100], request_id, before_version, after_version,
                    json.dumps(snapshot, ensure_ascii=False) if snapshot is not None else None,
                    (ip or "")[:45] or None, (ua or "")[:500] or None,
                ),
            )
            conn.commit()
            return True


def moderate(idea_id, action, admin_id, admin_name, expected_version,
             reason_code, reason_text, internal_note, request_id, ip=None, ua=None):
    if action not in ("revoke", "restore"):
        raise ValueError("未知治理动作")
    try:
        request_id = str(uuid.UUID(str(request_id)))
    except (TypeError, ValueError):
        raise ValueError("request_id 需为 UUID")
    if reason_code not in REASON_CODES:
        raise ValueError("处置原因分类不在允许范围内")
    reason_text = str(reason_text or "").strip()
    if not 1 <= len(reason_text) <= 500:
        raise ValueError("作者可见原因需为 1-500 字")
    target = "revoked" if action == "revoke" else "active"
    fingerprint = _request_fingerprint(
        idea_id, action, expected_version, reason_code, reason_text, internal_note,
    )
    try:
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT snapshot_json FROM idea_moderation_log WHERE request_id=%s",
                    (request_id,),
                )
                existing = cur.fetchone()
                if existing:
                    if not _request_matches(existing, fingerprint):
                        return {"ok": False, "error": "request_id 已用于不同处置", "conflict": True}
                    return {"ok": True, "idempotent": True}
                cur.execute(
                    "SELECT author_id,status,visibility,moderation_state,row_version,content_hash "
                    "FROM idea WHERE id=%s FOR UPDATE", (idea_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                if row["moderation_state"] == target:
                    return {"ok": False, "error": "内容已处于目标状态"}
                if int(expected_version) != int(row["row_version"]):
                    return {"ok": False, "error": "版本已变化，请刷新后重试", "conflict": True}
                snapshot = {
                    "author_id": row["author_id"], "status": row["status"],
                    "visibility": row["visibility"], "content_hash": row["content_hash"],
                    "row_version": row["row_version"],
                    "request_fingerprint": fingerprint,
                }
                if action == "revoke":
                    cur.execute(
                        "UPDATE idea SET moderation_state='revoked', row_version=row_version+1, "
                        "moderation_reason_code=%s, moderation_reason=%s, moderated_at=NOW(), "
                        "moderated_by=%s WHERE id=%s",
                        (reason_code, reason_text, admin_id, idea_id),
                    )
                else:
                    cur.execute(
                        "UPDATE idea SET moderation_state='active', row_version=row_version+1, "
                        "moderation_reason_code=NULL, moderation_reason=NULL, moderated_at=NOW(), "
                        "moderated_by=%s WHERE id=%s", (admin_id, idea_id),
                    )
                cur.execute(
                    "INSERT INTO idea_moderation_log (idea_id,action,from_state,to_state,"
                    "reason_code,reason_text,internal_note,admin_id,admin_name_snapshot,"
                    "request_id,before_version,after_version,snapshot_json,ip,ua) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        idea_id, action, row["moderation_state"], target, reason_code,
                        reason_text, internal_note[:1000] if internal_note else None,
                        admin_id, admin_name[:100], request_id, row["row_version"],
                        int(row["row_version"]) + 1, json.dumps(snapshot, ensure_ascii=False),
                        (ip or "")[:45] or None, (ua or "")[:500] or None,
                    ),
                )
                conn.commit()
    except IntegrityError as exc:
        if not exc.args or exc.args[0] != 1062:
            raise
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT snapshot_json FROM idea_moderation_log WHERE request_id=%s",
                    (request_id,),
                )
                existing = cur.fetchone()
                if not existing:
                    raise
        if not _request_matches(existing, fingerprint):
            return {"ok": False, "error": "request_id 已用于不同处置", "conflict": True}
        return {"ok": True, "idempotent": True}
    return {"ok": True, "idempotent": False, "state": target, "author_id": row["author_id"]}
