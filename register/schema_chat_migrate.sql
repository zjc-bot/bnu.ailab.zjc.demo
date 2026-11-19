-- ============================================================
-- 幂等迁移：为已有库给 friend_request 加 uk_pair 唯一约束
--
-- schema_chat.sql 已包含 UNIQUE KEY，仅对新库生效。
-- 既有库若已存在重复申请，直接 ALTER 会失败，需先清理：
--   每个 (from_id,to_id) 只保留 id 最小的一行（通常是首次申请）。
-- 可重复执行。
-- ============================================================

USE school;

DELETE FROM friend_request
WHERE id NOT IN (
  SELECT keep_id FROM (
    SELECT MIN(id) AS keep_id
    FROM friend_request
    GROUP BY from_id, to_id
  ) t
);

SET @has_uk := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'friend_request'
    AND INDEX_NAME = 'uk_pair'
);

SET @sql := IF(@has_uk = 0,
  'ALTER TABLE friend_request ADD UNIQUE KEY uk_pair (from_id, to_id)',
  'SELECT ''uk_pair already exists'' AS msg'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
