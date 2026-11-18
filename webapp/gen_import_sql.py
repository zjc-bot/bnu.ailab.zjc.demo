"""生成建表 + 导入 SQL，源数据来自 students_raw.csv。"""

import csv
import io

CSV = r"D:\MySQL\backup\students_raw.csv"
OUT = r"D:\MySQL\sql\import_students.sql"

# 场次序号 -> (标题, 日期, 开始, 结束, 地点)
SESSIONS = {
    1: ("场次1 时间：9.8晚上18:00～19:30 地点：电阶梯教室",
        "2026-09-08", "18:00:00", "19:30:00", "电阶梯教室"),
    2: ("场次2 时间：9.8晚上18:00～19:30 地点：生四",
        "2026-09-08", "18:00:00", "19:30:00", "生四"),
    3: ("场次3 时间：9.10上午10:00～11:30 地点：教四楼108",
        "2026-09-10", "10:00:00", "11:30:00", "教四楼108"),
    4: ("场次4 时间：9.11晚上18:00～19:30 地点：电子楼103",
        "2026-09-11", "18:00:00", "19:30:00", "电子楼103"),
    5: ("场次5 时间：9.12晚上18:00～19:30 地点：电子楼103",
        "2026-09-12", "18:00:00", "19:30:00", "电子楼103"),
    6: ("场次6", None, None, None, None),
}


def q(v):
    if v is None or v == "":
        return "NULL"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"


rows = list(csv.DictReader(io.open(CSV, encoding="utf-8-sig")))
print(f"读入 {len(rows)} 行")

lines = [
    "SET NAMES utf8mb4;",
    "USE school;",
    "",
    "-- ===== 重建结构 =====",
    "SET FOREIGN_KEY_CHECKS=0;",
    "DROP TABLE IF EXISTS student;",
    "DROP TABLE IF EXISTS `session`;",
    "SET FOREIGN_KEY_CHECKS=1;",
    "",
    """CREATE TABLE `session` (
  `id`         TINYINT UNSIGNED NOT NULL COMMENT '场次主键',
  `seq`        TINYINT UNSIGNED NOT NULL COMMENT '场次序号',
  `title`      VARCHAR(100) NULL COMMENT '原始标题',
  `held_date`  DATE         NULL COMMENT '活动日期',
  `start_time` TIME         NULL COMMENT '开始',
  `end_time`   TIME         NULL COMMENT '结束',
  `location`   VARCHAR(50)  NULL COMMENT '地点',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_seq` (`seq`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='活动场次';""",
    "",
    """CREATE TABLE `student` (
  `id`         INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '内部主键',
  `student_no` VARCHAR(20)  NOT NULL COMMENT '学号，唯一',
  `name`       VARCHAR(50)  NOT NULL COMMENT '姓名',
  `gender`     ENUM('男','女','其他') NULL COMMENT '性别（待补录）',
  `major`      VARCHAR(50)  NULL COMMENT '专业',
  `dorm_room`  VARCHAR(20)  NULL COMMENT '宿舍房间号',
  `session_id` TINYINT UNSIGNED NULL COMMENT '所属场次',
  `remark`     VARCHAR(200) NULL COMMENT '备注',
  `phone`      VARCHAR(20)  NULL COMMENT '手机（待补录）',
  `email`      VARCHAR(100) NULL COMMENT '邮箱（待补录）',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_student_no` (`student_no`),
  KEY `idx_name`    (`name`),
  KEY `idx_dorm`    (`dorm_room`),
  KEY `idx_major`   (`major`),
  KEY `idx_session` (`session_id`),
  CONSTRAINT `fk_student_session` FOREIGN KEY (`session_id`)
    REFERENCES `session` (`id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='学生名单';""",
    "",
    "-- ===== 场次 =====",
]

for seq, (title, d, st, et, loc) in SESSIONS.items():
    lines.append(
        f"INSERT INTO `session` (id,seq,title,held_date,start_time,end_time,location) "
        f"VALUES ({seq},{seq},{q(title)},{q(d)},{q(st)},{q(et)},{q(loc)});"
    )

lines.append("")
lines.append("-- ===== 学生 =====")

missing_name = 0
for i, r in enumerate(rows, 1):
    name = (r["name"] or "").strip()
    remark = (r["remark"] or "").strip()
    if not name:
        name = "（待补录）"
        remark = (remark + "；名单原表姓名缺失").lstrip("；")
        missing_name += 1
    lines.append(
        "INSERT INTO student (student_no,name,major,dorm_room,session_id,remark) VALUES ("
        f"{q(r['student_no'])},{q(name)},{q(r['major'])},{q(r['dorm_room'])},"
        f"{r['session_seq']},{q(remark)});"
    )

lines.append("")
lines.append("-- 校验")
lines.append("SELECT s.seq AS 场次, COUNT(*) AS 人数 FROM student st "
             "JOIN `session` s ON s.id=st.session_id GROUP BY s.seq ORDER BY s.seq;")

with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(lines) + "\n")

print(f"已生成 {OUT}")
print(f"  INSERT 条数 {len(rows)}，补齐姓名 {missing_name} 条")
print(f"  文件大小 {len(chr(10).join(lines).encode('utf-8'))} 字节")
print("\n--- 前 12 行 ---")
for ln in lines[:12]:
    print(" ", ln)
print("\n--- 学生记录样例 ---")
for ln in [x for x in lines if x.startswith("INSERT INTO student")][:2]:
    print(" ", ln)
