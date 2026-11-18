-- ============================================================
-- 对战游戏 · 终局归档
--
-- 设计要点：
--   1. 一步棋不落库（热态在内存），仅终局写一条结果
--   2. moves 存 JSON 着法序列，可复盘；长文本用 MEDIUMTEXT
--   3. 挂 conversation_id，与 IM 会话关联；不重复存双方 uid 之外的冗余
-- ============================================================

USE school;

CREATE TABLE IF NOT EXISTS `game_record` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `conv_id`       INT UNSIGNED NOT NULL COMMENT '关联会话（room_id）',
  `game`          VARCHAR(20) NOT NULL COMMENT '游戏类型，如 gomoku',
  `player_a`      INT UNSIGNED NOT NULL COMMENT '先手 uid',
  `player_b`      INT UNSIGNED NOT NULL COMMENT '后手 uid',
  `winner`        INT UNSIGNED NULL COMMENT '获胜 uid；和棋为 NULL',
  `reason`        VARCHAR(20) NOT NULL DEFAULT '' COMMENT 'five_in_row / resign / draw',
  `moves`         MEDIUMTEXT NULL COMMENT '着法 JSON 数组，供复盘',
  `steps`         INT NOT NULL DEFAULT 0 COMMENT '总步数',
  `created_at`    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_conv` (`conv_id`, `id`),
  KEY `idx_player_a` (`player_a`, `created_at`),
  KEY `idx_player_b` (`player_b`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='对局终局归档';
