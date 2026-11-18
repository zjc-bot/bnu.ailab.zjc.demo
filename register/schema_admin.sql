-- ============================================================
-- 管理后台 · 表结构
--
-- admin_user 与 app_user 完全分离，互不复用密码与会话
-- access_log 记录页面访问，用于统计访问人群
-- ============================================================

USE school;

CREATE TABLE IF NOT EXISTS `admin_user` (
  `id`            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `username`      VARCHAR(50)  NOT NULL,
  `password_hash` VARCHAR(255) NOT NULL,
  `display_name`  VARCHAR(50)  NULL,
  `last_login_at` DATETIME     NULL,
  `last_login_ip` VARCHAR(45)  NULL,
  `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='管理员账号';

CREATE TABLE IF NOT EXISTS `access_log` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `ip`         VARCHAR(45)  NOT NULL,
  `method`     VARCHAR(8)   NOT NULL,
  `path`       VARCHAR(200) NOT NULL,
  `status`     SMALLINT     NOT NULL DEFAULT 0,
  `ua`         VARCHAR(200) NULL,
  `referer`    VARCHAR(200) NULL,
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_created` (`created_at`),
  KEY `idx_ip`      (`ip`, `created_at`),
  KEY `idx_path`    (`path`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='访问日志';
