-- ============================================================
-- 即时通讯：好友 + 单聊
--
-- 设计要点：
--   1. 好友关系双向存两行，查询无需 OR
--   2. 会话用 (user_a, user_b) 唯一索引，小 id 在前，杜绝重复会话
--   3. 未读数靠 message.read_at 为空计数，不额外建表
-- ============================================================

USE school;

CREATE TABLE IF NOT EXISTS `friend_request` (
  `id`         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `from_id`    INT UNSIGNED NOT NULL,
  `to_id`      INT UNSIGNED NOT NULL,
  `note`       VARCHAR(100) NULL,
  `status`     ENUM('pending','accepted','rejected') NOT NULL DEFAULT 'pending',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `handled_at` DATETIME NULL,
  PRIMARY KEY (`id`),
  KEY `idx_to_status` (`to_id`, `status`, `created_at`),
  KEY `idx_from` (`from_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='好友申请';

CREATE TABLE IF NOT EXISTS `friend` (
  `id`         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`    INT UNSIGNED NOT NULL,
  `friend_id`  INT UNSIGNED NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_pair` (`user_id`, `friend_id`),
  KEY `idx_friend` (`friend_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='好友关系（双向各存一行）';

CREATE TABLE IF NOT EXISTS `conversation` (
  `id`          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_a`      INT UNSIGNED NOT NULL COMMENT '较小的用户 id',
  `user_b`      INT UNSIGNED NOT NULL COMMENT '较大的用户 id',
  `last_msg_id` BIGINT UNSIGNED NULL,
  `last_at`     DATETIME NULL COMMENT '最后一条消息时间，用于列表排序',
  `created_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_pair` (`user_a`, `user_b`),
  KEY `idx_b` (`user_b`, `last_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='单聊会话';

CREATE TABLE IF NOT EXISTS `message` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `conv_id`    INT UNSIGNED NOT NULL,
  `sender_id`  INT UNSIGNED NOT NULL,
  `content`    TEXT NOT NULL,
  `read_at`    DATETIME NULL COMMENT '为空表示未读',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_conv` (`conv_id`, `id`),
  KEY `idx_unread` (`conv_id`, `read_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='单聊消息';
