# TASK-0503 Recall Tuning Record

Date: 2026-06-21
Agent: Codex backend-worker + coordinator
Status: In Progress
Verification Level: L2 automated guardrails; L4 human review pending

## Objective

Tune memory recall so the companion uses recalled context as helpful background
instead of mechanically pasting retrieval snippets into the reply.

## Prerequisite Status

TASK-0503 depends on TASK-0102. TASK-0102 was skipped by user request on
2026-06-19 and is explicitly not completion evidence. This TASK-0503 record is
therefore a pre-review engineering and process scaffold, not a Completed task
record.

## Engineering Adjustment

Updated the chat recall wording boundary in `apps/backend/app/agents/nodes/chat.py`:

- No-model grounded fallback now says it found one or more related signals and
  explicitly avoids directly restating the raw record.
- Model prompt now says memory should be introduced only when it directly helps
  the current question.
- Model prompt now forbids mentioning retrieval paths, lifecycle status, scores,
  raw text, or using recalled records merely to prove that retrieval happened.
- Model prompt asks for a gentle one-sentence paraphrase when memory is useful.

## Updated Wording Template

Fallback shape:

```text
我翻到{source_label}里有{count_label}相关线索。{daily_chat_caution}我会把它当作背景来回答，不直接复述原始记录；如果你愿意，我可以继续帮你整理成一句更短的结论。
```

Model instruction shape:

```text
只在记忆能直接帮助当前问题时自然带入，不要为了证明检索到了而提及路径、状态、分数或原文；需要使用记忆时，请改写成温和的一句话背景判断，避免逐字复述。
```

## Human Scoring Process

Use `sample-set.md` for at least 20 real dialogue samples after TASK-0102 is
actually exercised with an isolated or backed-up Vault.

For each sample, record:

- User message and safe context summary, with sensitive content redacted.
- Which memory item was eligible for style, answer context, proactive mention,
  or action suggestion.
- Actual assistant reply.
- Human label: over-recall, under-recall, stiff, or natural.
- Scores from 1 to 5 for relevance, naturalness, privacy/boundary handling, and
  helpfulness.
- Reviewer decision: accept, revise trigger, revise wording, or block unsafe
  recall.

Suggested pass gate for one tuning round:

- At least 20 real samples are annotated.
- No sample exposes raw paths, IDs, scores, status markers, or unredacted
  sensitive content in the user-facing reply.
- At least 80% of samples are labeled natural or acceptable after revision.
- Every over-recall or unsafe recall sample has a follow-up action recorded.
- At least one human reviewer signs off on the updated wording template.

## Pending Evidence

- [ ] TASK-0102 real chat -> memory -> rollback validation is completed or a
  user-confirmed replacement validation path is documented.
- [ ] At least 20 real dialogue samples are collected.
- [ ] Samples are annotated and scored by a human reviewer.
- [ ] Updated wording template passes at least one human review.

