USE school;

SET @sql = (SELECT IF(COUNT(*)=0,
  'ALTER TABLE idea ADD INDEX idx_author_status_updated (author_id,status,updated_at,id)', 'DO 0')
  FROM information_schema.statistics WHERE table_schema='school' AND table_name='idea' AND index_name='idx_author_status_updated');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @sql = (SELECT IF(COUNT(*)=0,
  'ALTER TABLE idea_favorite ADD INDEX idx_user_created (user_id,created_at,idea_id)', 'DO 0')
  FROM information_schema.statistics WHERE table_schema='school' AND table_name='idea_favorite' AND index_name='idx_user_created');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
