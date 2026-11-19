-- ============================================================
-- 用户头像字段迁移（幂等，兼容 MySQL 8.0）
--
-- 背景：头像上传/裁剪/删除路由与前端渲染已上线（app.py / im.js /
-- profile.html），但 schema.sql 的 app_user 表最初漏了 avatar_url 列，
-- 导致 /home、/profile、好友列表、会话列表查询抛
-- Unknown column 'avatar_url'。
--
-- CREATE TABLE IF NOT EXISTS 对已存在的表不会补列，故单独提供本脚本。
-- 用法：随 deploy.py 的 schema*.sql 遍历自动执行，也可手工：
--   mysql -uroot -p school < schema_avatar.sql
--
-- 幂等实现：MySQL 8.0 **不支持** ADD COLUMN IF NOT EXISTS（那是 MariaDB
-- 语法），故用 information_schema 判断 + PREPARE 动态执行，重复执行安全。
-- 与 schema_chat_migrate.sql 的写法保持一致。
-- ============================================================

USE school;

SET @has_col := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'app_user'
    AND COLUMN_NAME = 'avatar_url'
);

SET @sql := IF(@has_col = 0,
  'ALTER TABLE `app_user` ADD COLUMN `avatar_url` VARCHAR(255) NULL COMMENT ''用户自定义头像访问路径，NULL 表示用默认头像'' AFTER `nickname`',
  'SELECT ''avatar_url already exists'' AS msg'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
