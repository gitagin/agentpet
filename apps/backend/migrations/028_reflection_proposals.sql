-- 后台反思提案：模型回头看一轮对话后提出的记忆／整理建议。
--
-- 身份是内容派生的（proposal_kind + action_type + 归一化正文），刻意不含
-- source_message_id / agent_run_id：把每轮变化的标识放进身份，同一建议会在
-- 每轮变成一条新提案，用户拒绝过的建议必然复发。连续性子系统已经踩过这个坑
-- （见 009 之后 continuity.py 的 _proposal_hash 注释）。
CREATE TABLE IF NOT EXISTS reflection_proposals (
    id TEXT PRIMARY KEY,
    proposal_hash TEXT NOT NULL UNIQUE,
    proposal_kind TEXT NOT NULL,
    action_type TEXT NOT NULL,
    target_ref TEXT,
    content TEXT NOT NULL,
    confidence REAL NOT NULL,
    reversible INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    rejected_reason TEXT,
    error TEXT,
    applied_ref TEXT,
    source_conversation_id TEXT,
    source_message_id TEXT,
    agent_run_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reflection_proposals_status
ON reflection_proposals(status, created_at);

CREATE INDEX IF NOT EXISTS idx_reflection_proposals_source
ON reflection_proposals(agent_run_id, source_message_id);
