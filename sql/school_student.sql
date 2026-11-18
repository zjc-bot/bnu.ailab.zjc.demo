-- ============================================
-- 学生表 student · 练手用
-- 目标库：school（MySQL 8.0+）
-- 可重复执行，不会报错
-- ============================================

CREATE DATABASE IF NOT EXISTS school
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE school;

-- --------------------------------------------
-- 学生信息表
-- --------------------------------------------
CREATE TABLE IF NOT EXISTS student (
  id          INT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '内部主键，自增',
  student_no  VARCHAR(20)   NOT NULL                COMMENT '学号，业务唯一键',
  name        VARCHAR(50)   NOT NULL                COMMENT '姓名',
  gender      ENUM('男','女','其他') NOT NULL DEFAULT '其他' COMMENT '性别',
  birthday    DATE          NULL                    COMMENT '出生日期',
  class_name  VARCHAR(50)   NULL                    COMMENT '班级',
  major       VARCHAR(80)   NULL                    COMMENT '专业',
  phone       VARCHAR(20)   NULL                    COMMENT '手机号',
  email       VARCHAR(100)  NULL                    COMMENT '邮箱',
  enroll_date DATE          NULL                    COMMENT '入学日期',
  created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_student_no (student_no),
  KEY idx_name  (name),
  KEY idx_class (class_name)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci
  COMMENT='学生信息表';

-- --------------------------------------------
-- 示例数据（可重复执行）
-- --------------------------------------------
INSERT IGNORE INTO student
  (student_no, name, gender, birthday, class_name, major, phone, email, enroll_date)
VALUES
  ('2023010101', '张一鸣', '男', '2005-03-12', '学前教育2301', '学前教育', '13800138001', 'zhang@example.com', '2023-09-01'),
  ('2023010102', '李思远', '女', '2005-07-25', '学前教育2301', '学前教育', '13800138002', 'li@example.com',   '2023-09-01'),
  ('2023010103', '王雨桐', '女', '2004-11-08', '学前教育2301', '学前教育', '13800138003', 'wang@example.com', '2023-09-01'),
  ('2023020201', '陈子涵', '男', '2005-01-19', '小学教育2302', '小学教育', '13800138004', 'chen@example.com', '2023-09-01'),
  ('2023020202', '赵明轩', '男', '2006-05-30', '小学教育2302', '小学教育', '13800138005', 'zhao@example.com', '2023-09-01');

-- --------------------------------------------
-- 验证查询
-- --------------------------------------------
SELECT * FROM student ORDER BY student_no;

-- 按班级统计人数
SELECT class_name, COUNT(*) AS 人数, ROUND(AVG(TIMESTAMPDIFF(YEAR, birthday, CURDATE())), 1) AS 平均年龄
FROM student
GROUP BY class_name
ORDER BY class_name;

-- 看表结构
SHOW CREATE TABLE student;
