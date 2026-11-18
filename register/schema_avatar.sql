-- ============================================================
-- 用户头像字段迁移（幂等）
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
-- 幂等：IF NOT EXISTS 保证重复执行不报错。
-- ============================================================

USE school;

ALTER TABLE `app_user`
  ADD COLUMN IF NOT EXISTS `avatar_url` VARCHAR(255) NULL
  COMMENT '用户自定义头像访问路径，NULL 表示用默认头像'
  AFTER `nickname`;
