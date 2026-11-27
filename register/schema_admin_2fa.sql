-- ============================================================
-- 管理后台二次认证：为 admin_user 增加 email 列（幂等，兼容 MySQL 8.0）
--
-- 背景：admin 白名单依赖 nginx / XFF 单一防线，一旦代理链变化即静默失效。
-- 叠加邮件验证码二次认证后，即使 IP 判定被绕过，仍需邮箱验证码才能登录。
--
-- MySQL 8.0 不支持 ADD COLUMN IF NOT EXISTS（MariaDB 语法），
-- 故用 information_schema 判断 + PREPARE 动态执行，重复执行安全。
-- 随 deploy 的 schema*.sql 遍历自动执行；也可手工：
--   mysql -uroot -p school < schema_admin_2fa.sql
-- ============================================================

USE school;

SET @has_col := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'admin_user'
    AND COLUMN_NAME = 'email'
);

SET @sql := IF(@has_col = 0,
  'ALTER TABLE `admin_user` ADD COLUMN `email` VARCHAR(191) NULL COMMENT ''二次认证接收邮箱'' AFTER `display_name`',
  'SELECT ''admin_user.email already exists'' AS msg'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
