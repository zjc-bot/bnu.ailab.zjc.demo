-- ============================================================
-- AI 对话 · 表结构
-- ============================================================

USE school;

CREATE TABLE IF NOT EXISTS `chat_message` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`    INT UNSIGNED NOT NULL,
  `role`       ENUM('user','assistant') NOT NULL,
  `content`    MEDIUMTEXT NOT NULL,
  `emotion`    VARCHAR(20) NULL COMMENT 'assistant 回复附带的情绪标记',
  `tokens`     INT NOT NULL DEFAULT 0,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user_time` (`user_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='对话消息';

CREATE TABLE IF NOT EXISTS `ai_usage` (
  `id`       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`  INT UNSIGNED NOT NULL,
  `day`      DATE NOT NULL,
  `calls`    INT NOT NULL DEFAULT 0,
  `tokens`   INT NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_day` (`user_id`, `day`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='每日用量';

CREATE TABLE IF NOT EXISTS `ai_config` (
  `key_name`   VARCHAR(50) NOT NULL,
  `value`      MEDIUMTEXT NULL,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`key_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='AI 配置与人设';

INSERT IGNORE INTO `ai_config` (`key_name`, `value`) VALUES
  ('persona', '你是「小鲸」，BNU AI Lab 的导览员。\n- 蓝色长发、戴鲸鱼头套，傲娇但心软，爱吃白米饭\n- 称呼用户为「鱼片」\n- 说话简短自然，不用 Emoji，不用列表，像朋友聊天\n- 被叫「胖」会立刻反驳'),
  ('model', 'deepseek-flash'),
  ('daily_limit', '40'),
  ('history_turns', '12');
