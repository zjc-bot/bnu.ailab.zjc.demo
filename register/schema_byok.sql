-- ============================================================
-- 用户自带 API Key
--
-- key_enc 用 SECRET_KEY 派生的 Fernet 密钥加密，
-- 数据库被拖走也解不开；key_hint 只存掩码用于界面显示。
-- ============================================================

USE school;

CREATE TABLE IF NOT EXISTS `user_ai_key` (
  `user_id`     INT UNSIGNED NOT NULL,
  `key_enc`     VARBINARY(512) NOT NULL COMMENT 'Fernet 密文',
  `key_hint`    VARCHAR(24) NOT NULL COMMENT 'sk-****abcd，仅用于显示',
  `base_url`    VARCHAR(200) NULL,
  `model`       VARCHAR(50) NULL,
  `verified_at` DATETIME NULL,
  `updated_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='用户自带的 API 凭据';
