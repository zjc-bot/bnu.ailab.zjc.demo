-- ============================================================
-- BNU AI Lab 注册系统 · 新增表：研究成果数据（research_achievement）
--
-- 说明：
--   1. 本脚本为纯增量新增表，使用 CREATE TABLE IF NOT EXISTS，
--      已有表结构与数据不受影响；
--   2. 可单独执行（如：mysql -u <user> -p < schema_archive.sql），
--      无需依赖任何已有的迁移脚本；
--   3. 字段与前端「研究成果」展示数据一一对应。
-- ============================================================

USE school;

CREATE TABLE IF NOT EXISTS `research_achievement` (
  `id`           VARCHAR(20)  NOT NULL COMMENT '前端编号，如 P-01',
  `category`     VARCHAR(30)  NULL     COMMENT '分类：ai/edu/bio/energy/mat',
  `kind`         VARCHAR(20)  NULL     COMMENT '载体：poster/sheet/ticket/card/photo/note/journal/blueprint',
  `title`        VARCHAR(200) NOT NULL COMMENT '成果标题',
  `year`         VARCHAR(10)  NULL     COMMENT '年份，如 2025',
  `status`       VARCHAR(20)  NULL     COMMENT '状态：已发表/进行中/已结项',
  `summary`      TEXT         NULL     COMMENT '一句话摘要',
  `tags`         VARCHAR(255) NULL     COMMENT '标签，逗号分隔',
  `owner`        VARCHAR(100) NULL     COMMENT '负责人',
  `metric`       VARCHAR(60)  NULL     COMMENT '关键指标值',
  `metric_label` VARCHAR(120) NULL     COMMENT '关键指标名称',
  `method`       TEXT         NULL     COMMENT '展开详情：方法',
  `finding`      TEXT         NULL     COMMENT '展开详情：发现',
  `impact`       TEXT         NULL     COMMENT '展开详情：影响',
  `geom_x`       INT          NULL     COMMENT '桌面散落位置 x（可选）',
  `geom_y`       INT          NULL     COMMENT '桌面散落位置 y（可选）',
  `geom_w`       INT          NULL     COMMENT '桌面散落宽度 w（可选）',
  `geom_h`       INT          NULL     COMMENT '桌面散落高度 h（可选）',
  `geom_r`       FLOAT        NULL     COMMENT '桌面散落旋转角度 r（可选）',
  `geom_z`       INT          NULL     COMMENT '桌面散落层级 z（可选）',
  `sort_order`   INT          NOT NULL DEFAULT 0 COMMENT '展示排序，越小越靠前',
  `created_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                              ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_category` (`category`),
  KEY `idx_sort_order` (`sort_order`, `id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='研究成果数据（新增表，可单独执行）';
