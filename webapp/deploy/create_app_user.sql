-- ============================================================
-- 为 Web 应用创建最小权限数据库账号
--
-- 执行方式（在 ECS 上，用 MySQL root）：
--   mysql -uroot -p < create_app_user.sql
--
-- 执行前请把 CHANGE_ME_STRONG 换成强密码。
--
-- 权限设计：
--   只授予 school.student 一张表的 SELECT/INSERT/UPDATE/DELETE
--   不授予 DROP / ALTER / CREATE / GRANT / FILE / SUPER
--   即 Web 应用被攻破，也无法删库、改结构或读写服务器文件
-- ============================================================

CREATE USER IF NOT EXISTS 'studentapp'@'127.0.0.1'
  IDENTIFIED BY 'CHANGE_ME_STRONG';

-- 密码策略：如果是 8.0 默认的 caching_sha2_password，PyMySQL 需 cryptography 包
-- 如遇到兼容问题可改用下面这行（不推荐，安全性略低）：
-- ALTER USER 'studentapp'@'127.0.0.1' IDENTIFIED WITH mysql_native_password BY 'CHANGE_ME_STRONG';

GRANT SELECT, INSERT, UPDATE, DELETE ON school.student TO 'studentapp'@'127.0.0.1';

-- 明确拒绝越权（默认就是拒绝，这里写出来是为了让人看见）
-- 注意：MySQL 不支持显式 DENY 语法，靠"只授予需要的"实现

-- 限制连接数，防止应用被打爆时耗尽数据库连接
ALTER USER 'studentapp'@'127.0.0.1' WITH MAX_USER_CONNECTIONS 20;

-- 验证：应只看到 4 个权限
SHOW GRANTS FOR 'studentapp'@'127.0.0.1';
