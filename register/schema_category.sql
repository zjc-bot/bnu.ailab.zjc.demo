USE school;

SET @col_exists = (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema='school' AND table_name='idea' AND column_name='category_legacy'
);
SET @sql = IF(@col_exists=0,
  'ALTER TABLE idea ADD COLUMN category_legacy VARCHAR(30) NULL COMMENT ''迁移前分类原值'' AFTER category',
  'DO 0');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE idea
SET category_legacy=COALESCE(NULLIF(category_legacy, ''), NULLIF(category, '')),
    category='math'
WHERE category='mat';

UPDATE idea
SET category_legacy=COALESCE(NULLIF(category_legacy, ''), NULLIF(category, '')),
    category=CASE category
      WHEN '人工智能' THEN 'ai'
      WHEN '教育技术' THEN 'edu'
      WHEN '生物信息' THEN 'bio'
      WHEN '可持续能源' THEN 'energy'
      WHEN '数学' THEN 'math'
      WHEN '材料与传感' THEN 'math'
      WHEN '其他' THEN 'other'
      ELSE 'other'
    END
WHERE category IS NULL OR category='' OR category NOT IN ('ai','edu','bio','energy','math','other');
