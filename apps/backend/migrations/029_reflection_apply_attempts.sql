-- 反思建议的落地重试预算。
--
-- 只看状态分不出两种失败:"生成时就失败"(这条建议从没执行过动作)和"执行失败"
-- (可能已经产生了部分效果)。前者重试就是全新执行,后者重试必须换尝试身份——
-- 动作账本会把已存的失败回执按原幂等键原样回放,同键重试等于按钮失效。
ALTER TABLE reflection_proposals ADD COLUMN apply_attempts INTEGER NOT NULL DEFAULT 0;
