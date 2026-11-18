-- ============================================================
-- 账号安全 · 表结构
-- ============================================================

USE school;

CREATE TABLE IF NOT EXISTS `password_reset` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`    INT UNSIGNED NOT NULL,
  `token`      CHAR(64)     NOT NULL COMMENT '一次性重置令牌',
  `expires_at` DATETIME     NOT NULL,
  `used`       TINYINT      NOT NULL DEFAULT 0,
  `ip`         VARCHAR(45)  NULL,
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_token` (`token`),
  KEY `idx_user` (`user_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='密码重置令牌';

CREATE TABLE IF NOT EXISTS `login_log` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`    INT UNSIGNED NOT NULL,
  `ip`         VARCHAR(45)  NOT NULL,
  `ua`         VARCHAR(200) NULL,
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user` (`user_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='登录历史';
