-- ============================================================
-- 消息交互 v2：引用 / 转发 / 个人视图删除
--
-- 对应总纲 §9B：message 表加 4 列，支持引用、转发来源、
-- 双方各自视图的删除标志。幂等实现兼容 MySQL 8.0
-- （不支持 ADD COLUMN IF NOT EXISTS，那是 MariaDB 语法）。
--
-- 用法：随 deploy.py 的 schema*.sql 遍历自动执行，也可手工：
--   mysql -uroot -p school < schema_message_v2.sql
-- ============================================================

USE school;

-- quote_id：引用原消息 id。不设外键——原消息可被删除，
-- 展示时查不到就降级为「原消息已删除」占位。
SET @has_quote := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'message'
    AND COLUMN_NAME = 'quote_id'
);
SET @sql := IF(@has_quote = 0,
  'ALTER TABLE `message` ADD COLUMN `quote_id` BIGINT UNSIGNED NULL COMMENT ''引用的原消息 id'' AFTER `content`',
  'SELECT ''quote_id exists'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- deleted_by_a / deleted_by_b：会话双方各自的视图删除标志。
-- 单聊只有两方，两个位足够表达；无需额外删除表。
SET @has_dba := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'message'
    AND COLUMN_NAME = 'deleted_by_a'
);
SET @sql := IF(@has_dba = 0,
  'ALTER TABLE `message` ADD COLUMN `deleted_by_a` TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''user_a 是否已从自己视图删除'' AFTER `quote_id`',
  'SELECT ''deleted_by_a exists'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_dbb := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'message'
    AND COLUMN_NAME = 'deleted_by_b'
);
SET @sql := IF(@has_dbb = 0,
  'ALTER TABLE `message` ADD COLUMN `deleted_by_b` TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''user_b 是否已从自己视图删除'' AFTER `deleted_by_a`',
  'SELECT ''deleted_by_b exists'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- forward_from：转发来源会话 id，仅展示用，可空。
SET @has_ff := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'message'
    AND COLUMN_NAME = 'forward_from'
);
SET @sql := IF(@has_ff = 0,
  'ALTER TABLE `message` ADD COLUMN `forward_from` INT UNSIGNED NULL COMMENT ''转发来源会话 id，仅展示'' AFTER `deleted_by_b`',
  'SELECT ''forward_from exists'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 索引：quote_id 用于引用块批量回查原消息摘要
SET @has_idx := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'message'
    AND INDEX_NAME = 'idx_quote'
);
SET @sql := IF(@has_idx = 0,
  'ALTER TABLE `message` ADD KEY `idx_quote` (`quote_id`)',
  'SELECT ''idx_quote exists'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
