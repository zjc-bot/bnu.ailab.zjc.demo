-- ============================================================
-- BNU AI Lab 注册系统 · 表结构
--
-- 设计要点：
--   1. real_name 不单独采集，注册时与 student 表比对后写入，
--      确保与官方名单一致，避免伪造
--   2. student_no 唯一，一个学号只能注册一个账号
--   3. email 唯一，且必须是 @mail.bnu.edu.cn
--   4. 验证码单独成表，支持过期与一次性消费
-- ============================================================

USE school;

CREATE TABLE IF NOT EXISTS `app_user` (
  `id`                INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `student_no`        VARCHAR(20)  NOT NULL COMMENT '学号，唯一',
  `real_name`         VARCHAR(50)  NOT NULL COMMENT '真实姓名，取自名单',
  `nickname`          VARCHAR(50)  NOT NULL COMMENT '平台昵称，唯一',
  `avatar_url`        VARCHAR(255) NULL COMMENT '用户自定义头像访问路径，NULL 表示用默认头像',
  `email`             VARCHAR(100) NOT NULL COMMENT '校内邮箱，唯一',
  `password_hash`     VARCHAR(255) NOT NULL COMMENT 'scrypt 哈希',
  `email_verified`    TINYINT      NOT NULL DEFAULT 0 COMMENT '邮箱是否已验证',
  `status`            ENUM('active','disabled') NOT NULL DEFAULT 'active',
  `privacy_agreed_at` DATETIME     NULL COMMENT '隐私条款同意时间',
  `created_at`        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                   ON UPDATE CURRENT_TIMESTAMP,
  `last_login_at`     DATETIME     NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_student_no` (`student_no`),
  UNIQUE KEY `uk_nickname`   (`nickname`),
  UNIQUE KEY `uk_email`      (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='注册用户';

CREATE TABLE IF NOT EXISTS `email_code` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `email`      VARCHAR(100) NOT NULL,
  `code`       CHAR(6)      NOT NULL COMMENT '6 位数字',
  `purpose`    VARCHAR(20)  NOT NULL DEFAULT 'register',
  `expires_at` DATETIME     NOT NULL COMMENT '过期时间',
  `used`       TINYINT      NOT NULL DEFAULT 0,
  `ip`         VARCHAR(45)  NULL,
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_email_purpose` (`email`, `purpose`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='邮箱验证码';

-- 应用账号授权（最小权限：只给需要的表）
-- GRANT SELECT, INSERT, UPDATE, DELETE ON school.app_user   TO 'studentapp'@'127.0.0.1';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON school.email_code TO 'studentapp'@'127.0.0.1';
-- GRANT SELECT ON school.student TO 'studentapp'@'127.0.0.1';
