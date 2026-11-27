-- ============================================================
-- BNU AI Lab 注册系统 · 新增表：标签字典与 idea-标签关联（tag_dict / idea_tag）
--
-- 说明：
--   1. 本脚本为纯增量：新增 tag_dict / idea_tag 两表并回填历史标签关联，
--      不删除、不清空任何现有表，也不改写 idea.tags 或停用标签状态；
--   2. 可单独执行（如：mysql -u <user> -p < schema_tags.sql），
--      无需依赖任何迁移脚本；仅末尾 ALTER 依赖 schema_idea.sql 已建好 idea 表；
--   3. idea.tags 逗号串继续保留作兼容读，新标签体系的事实来源逐步切到关联表；
--   4. 末尾幂等 ALTER 仅把 idea.visibility 的默认值改为 'public'，
--      重复执行结果一致、不报错。
-- ============================================================

USE school;

CREATE TABLE IF NOT EXISTS `tag_dict` (
  `id`         INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '标签字典主键',
  `name`       VARCHAR(60)  NOT NULL COMMENT '标签显示名，如 小样本学习',
  `slug`       VARCHAR(60)  NOT NULL COMMENT '标签唯一标识 / 别名',
  `pinned`     TINYINT      NOT NULL DEFAULT 0 COMMENT '置顶：1 置顶，0 普通',
  `status`     ENUM('active','disabled') NOT NULL DEFAULT 'active' COMMENT '启用 / 停用',
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_slug` (`slug`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='标签字典（新增表，不影响现有表，可单独执行）';

CREATE TABLE IF NOT EXISTS `idea_tag` (
  `idea_id` BIGINT UNSIGNED NOT NULL COMMENT '关联 idea.id',
  `tag_id`  INT UNSIGNED    NOT NULL COMMENT '关联 tag_dict.id',
  PRIMARY KEY (`idea_id`, `tag_id`),
  KEY `idx_tag` (`tag_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Idea 与标签多对多关联（新增表，不影响现有表，可单独执行）';

-- 幂等：把 idea.visibility 默认值改为 public（MySQL 8.0 支持 ALTER COLUMN ... SET DEFAULT）。
-- 重复执行只会把默认值再次设为 'public'，结果一致、不报错。
-- 历史 idea.tags 仅回填关联，不重启停用标签，也不改写原字段。
INSERT IGNORE INTO tag_dict (name, slug)
WITH RECURSIVE tag_parts AS (
  SELECT id AS idea_id,
         CAST(REPLACE(tags, '，', ',') AS CHAR(255)) AS rest,
         CAST(NULL AS CHAR(255)) AS tag_name,
         1 AS part_no
  FROM idea
  WHERE tags IS NOT NULL AND tags <> ''
  UNION ALL
  SELECT idea_id,
         CASE WHEN LOCATE(',', rest) > 0
              THEN SUBSTRING(rest, LOCATE(',', rest) + 1) ELSE '' END,
         TRIM(CASE WHEN LOCATE(',', rest) > 0
                   THEN LEFT(rest, LOCATE(',', rest) - 1) ELSE rest END),
         part_no + 1
  FROM tag_parts
  WHERE rest <> '' AND part_no < 8
)
SELECT DISTINCT LEFT(tag_name, 60),
       LOWER(REPLACE(LEFT(tag_name, 60), ' ', '_'))
FROM tag_parts
WHERE tag_name IS NOT NULL AND tag_name <> '';

INSERT IGNORE INTO idea_tag (idea_id, tag_id)
WITH RECURSIVE tag_parts AS (
  SELECT id AS idea_id,
         CAST(REPLACE(tags, '，', ',') AS CHAR(255)) AS rest,
         CAST(NULL AS CHAR(255)) AS tag_name,
         1 AS part_no
  FROM idea
  WHERE tags IS NOT NULL AND tags <> ''
  UNION ALL
  SELECT idea_id,
         CASE WHEN LOCATE(',', rest) > 0
              THEN SUBSTRING(rest, LOCATE(',', rest) + 1) ELSE '' END,
         TRIM(CASE WHEN LOCATE(',', rest) > 0
                   THEN LEFT(rest, LOCATE(',', rest) - 1) ELSE rest END),
         part_no + 1
  FROM tag_parts
  WHERE rest <> '' AND part_no < 8
)
SELECT p.idea_id, d.id
FROM tag_parts p
JOIN tag_dict d ON d.slug=LOWER(REPLACE(LEFT(p.tag_name, 60), ' ', '_'))
WHERE p.tag_name IS NOT NULL AND p.tag_name <> '' AND d.status='active';

ALTER TABLE `idea` ALTER COLUMN `visibility` SET DEFAULT 'public';
