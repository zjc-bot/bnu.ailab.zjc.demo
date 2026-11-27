-- ============================================================
-- BNU AI Lab 注册系统 · 新增表：Idea 社区数据层（Phase 1）
--
-- 说明：
--   1. 本脚本仅新增 5 张表，全部使用 CREATE TABLE IF NOT EXISTS，
--      不修改、不删除任何现有表，现有表结构与数据不受影响；
--   2. 可单独执行（如：mysql -u <user> -p < schema_idea.sql），
--      无需依赖任何已有的迁移脚本；
--   3. idea.author_id → app_user.id（逻辑关联，物理外键省略，
--      以免与既有库的字符集/引擎/导入顺序产生耦合）；
--   4. idea_ai_job 为 AI 异步任务留痕表，本阶段仅建表，不写数据。
-- ============================================================

USE school;

CREATE TABLE IF NOT EXISTS `idea` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `author_id`     INT UNSIGNED    NOT NULL COMMENT '作者，关联 app_user.id',
  `title`         VARCHAR(200)    NOT NULL COMMENT '标题，1-200 字',
  `content`       MEDIUMTEXT      NULL     COMMENT '正文，1-20000 字',
  `category`      VARCHAR(30)     NULL     COMMENT '固定分类：ai/edu/bio/energy/math/other',
  `category_legacy` VARCHAR(30)   NULL     COMMENT '迁移前分类原值',
  `tags`          VARCHAR(255)    NULL     COMMENT '标签，英文逗号分隔，最多 8 个',
  `status`        ENUM('draft','published','archived') NOT NULL DEFAULT 'draft',
  `visibility`    ENUM('public','friends','private')   NOT NULL DEFAULT 'friends',
  `moderation_state` ENUM('active','revoked') NOT NULL DEFAULT 'active',
  `like_count`    INT             NOT NULL DEFAULT 0 COMMENT '点赞数（由 idea_like 同步）',
  `favorite_count` INT            NOT NULL DEFAULT 0 COMMENT '收藏数（由 idea_favorite 同步）',
  `comment_count` INT             NOT NULL DEFAULT 0 COMMENT '评论数（由 idea_comment 同步）',
  `ai_category`   VARCHAR(30)     NULL     COMMENT 'AI 分类结果',
  `ai_summary`    TEXT            NULL     COMMENT 'AI 摘要',
  `ai_tags`       VARCHAR(255)    NULL     COMMENT 'AI 标签，逗号分隔',
  `content_hash`  CHAR(64)        NULL     COMMENT '正文 SHA-256，用于去重/判定内容变更',
  `row_version`   BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `moderation_reason_code` VARCHAR(30) NULL,
  `moderation_reason` VARCHAR(500) NULL,
  `moderated_at`  DATETIME        NULL,
  `moderated_by`  INT UNSIGNED    NULL,
  `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                  ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_author` (`author_id`),
  KEY `idx_status_vis` (`status`, `visibility`),
  KEY `idx_moderation_public` (`moderation_state`,`status`,`visibility`,`created_at`),
  KEY `idx_author_status_updated` (`author_id`,`status`,`updated_at`,`id`),
  KEY `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Idea 社区帖子（新增表，可单独执行）';

CREATE TABLE IF NOT EXISTS `idea_favorite` (
  `user_id`    INT UNSIGNED    NOT NULL COMMENT '收藏者，关联 app_user.id',
  `idea_id`    BIGINT UNSIGNED NOT NULL COMMENT '被收藏的 idea，关联 idea.id',
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`, `idea_id`),
  KEY `idx_idea` (`idea_id`),
  KEY `idx_user_created` (`user_id`,`created_at`,`idea_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Idea 收藏关系（新增表，可单独执行）';

CREATE TABLE IF NOT EXISTS `idea_like` (
  `user_id`    INT UNSIGNED    NOT NULL COMMENT '点赞者，关联 app_user.id',
  `idea_id`    BIGINT UNSIGNED NOT NULL COMMENT '被点赞的 idea，关联 idea.id',
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`, `idea_id`),
  KEY `idx_idea` (`idea_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Idea 点赞关系（新增表，可单独执行）';

CREATE TABLE IF NOT EXISTS `idea_comment` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `idea_id`    BIGINT UNSIGNED NOT NULL COMMENT '所属 idea，关联 idea.id',
  `user_id`    INT UNSIGNED    NOT NULL COMMENT '评论者，关联 app_user.id',
  `parent_id`  BIGINT UNSIGNED NULL     COMMENT '父评论 id，NULL 表示顶层评论',
  `content`    TEXT            NOT NULL COMMENT '评论正文',
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_idea` (`idea_id`, `id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Idea 评论（新增表，可单独执行）';

CREATE TABLE IF NOT EXISTS `idea_ai_job` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `idea_id`    BIGINT UNSIGNED NOT NULL COMMENT '关联 idea.id',
  `user_id`    INT UNSIGNED    NOT NULL COMMENT '发起人，关联 app_user.id',
  `task_type`  ENUM('classify','summarize','dedup','recommend') NOT NULL COMMENT '任务类型',
  `model`      VARCHAR(100)    NULL     COMMENT '使用的模型名',
  `prompt_key` VARCHAR(50)     NULL     COMMENT '提示词模板标识',
  `input_hash` CHAR(64)        NULL     COMMENT '输入内容 SHA-256',
  `output_json` JSON           NULL     COMMENT '结构化输出',
  `status`     VARCHAR(20)     NULL     COMMENT 'pending/running/done/failed',
  `error`      TEXT            NULL     COMMENT '失败原因',
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_idea_user` (`idea_id`, `user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Idea AI 任务留痕（新增表，可单独执行）';
