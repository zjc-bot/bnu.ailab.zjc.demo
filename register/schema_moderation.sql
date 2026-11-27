USE school;

SET @sql = (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE idea ADD COLUMN moderation_state ENUM(''active'',''revoked'') NOT NULL DEFAULT ''active'' AFTER status',
    'DO 0')
  FROM information_schema.columns
  WHERE table_schema='school' AND table_name='idea' AND column_name='moderation_state'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql = (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE idea ADD COLUMN row_version BIGINT UNSIGNED NOT NULL DEFAULT 0 AFTER content_hash',
    'DO 0')
  FROM information_schema.columns
  WHERE table_schema='school' AND table_name='idea' AND column_name='row_version'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql = (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE idea ADD COLUMN moderation_reason_code VARCHAR(30) NULL AFTER row_version',
    'DO 0')
  FROM information_schema.columns
  WHERE table_schema='school' AND table_name='idea' AND column_name='moderation_reason_code'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql = (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE idea ADD COLUMN moderation_reason VARCHAR(500) NULL AFTER moderation_reason_code',
    'DO 0')
  FROM information_schema.columns
  WHERE table_schema='school' AND table_name='idea' AND column_name='moderation_reason'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql = (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE idea ADD COLUMN moderated_at DATETIME NULL AFTER moderation_reason',
    'DO 0')
  FROM information_schema.columns
  WHERE table_schema='school' AND table_name='idea' AND column_name='moderated_at'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql = (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE idea ADD COLUMN moderated_by INT UNSIGNED NULL AFTER moderated_at',
    'DO 0')
  FROM information_schema.columns
  WHERE table_schema='school' AND table_name='idea' AND column_name='moderated_by'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql = (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE idea ADD INDEX idx_moderation_public (moderation_state,status,visibility,created_at)',
    'DO 0')
  FROM information_schema.statistics
  WHERE table_schema='school' AND table_name='idea' AND index_name='idx_moderation_public'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS idea_moderation_log (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  idea_id BIGINT UNSIGNED NOT NULL,
  action ENUM('revoke','restore','view_metadata','view_content','notify_sent','notify_failed') NOT NULL,
  from_state ENUM('active','revoked') NULL,
  to_state ENUM('active','revoked') NULL,
  reason_code VARCHAR(30) NULL,
  reason_text VARCHAR(500) NULL,
  internal_note TEXT NULL,
  admin_id INT UNSIGNED NOT NULL,
  admin_name_snapshot VARCHAR(100) NOT NULL,
  request_id CHAR(36) NULL,
  before_version BIGINT UNSIGNED NULL,
  after_version BIGINT UNSIGNED NULL,
  snapshot_json JSON NULL,
  ip VARCHAR(45) NULL,
  ua VARCHAR(500) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_request_id (request_id),
  KEY idx_idea_created (idea_id,created_at),
  KEY idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Idea 内容治理追加审计，不复制正文';
