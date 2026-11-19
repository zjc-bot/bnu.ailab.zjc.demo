-- ============================================================
-- 对战游戏增强：持久化离线邀请 + AI 对手标识
-- 依赖：schema_game.sql；MySQL 8.0。全部语句可重复执行。
-- ============================================================

USE school;

CREATE TABLE IF NOT EXISTS `game_invite` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `conv_id`    INT UNSIGNED NOT NULL COMMENT '会话 id，同时作为 PvP 房间 id',
  `game`       VARCHAR(20) NOT NULL,
  `from_id`    INT UNSIGNED NOT NULL,
  `to_id`      INT UNSIGNED NOT NULL,
  `status`     ENUM('pending','accepted','declined','expired') NOT NULL DEFAULT 'pending',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `handled_at` DATETIME NULL,
  PRIMARY KEY (`id`),
  KEY `idx_to_status` (`to_id`, `status`, `id`),
  KEY `idx_room_pending` (`conv_id`, `to_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='持久化对战邀请，接收方上线后可读取';

-- AI 使用 ai:whale 特殊玩家 id。PvP uid 转字符串后语义不变。
-- conv_id 允许为空：PvE 没有好友会话，归档以 player_a 记录真人玩家。
ALTER TABLE `game_record`
  MODIFY COLUMN `conv_id` INT UNSIGNED NULL COMMENT '关联会话（room_id）；PvE 为 NULL',
  MODIFY COLUMN `player_b` VARCHAR(32) NOT NULL COMMENT '后手 uid 或 ai:whale',
  MODIFY COLUMN `winner` VARCHAR(32) NULL COMMENT '获胜 uid、ai:whale；和棋为 NULL';

-- 记录 AI 难度，便于战绩解释与后续平衡调整；幂等加列，兼容 MySQL 8.0。
SET @has_difficulty := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'game_record'
    AND COLUMN_NAME = 'ai_difficulty'
);
SET @sql := IF(@has_difficulty = 0,
  'ALTER TABLE `game_record` ADD COLUMN `ai_difficulty` VARCHAR(10) NULL COMMENT ''AI 难度'' AFTER `game`',
  'SELECT ''ai_difficulty exists'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
