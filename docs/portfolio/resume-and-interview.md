# Resume and Interview Wording

Status: candidate wording pending final user approval.

## Resume bullet

Built and evaluated a local-first Electron/FastAPI AI companion with a bounded
LangGraph multi-role workflow, FTS-backed cited retrieval, deterministic
side-effect policy and idempotency, and persistent human approval for high-risk
actions; kept optional hybrid/reranker candidates disabled when a frozen
60-case quality gate failed no-evidence requirements.

## Interview summary

The main design choice was to separate probabilistic roles from deterministic
control. Agents can retrieve, analyze, review, propose, verify, synthesize, and
reflect, but they cannot authorize their own side effects. Policy, execution,
ledger claims, budgets, and terminal ownership are deterministic. SQLite and
Markdown hold authoritative state; vector infrastructure is rebuildable.

## Expected challenges

- Why not enable hybrid by default? Semantic recall improved, but no-evidence
  accuracy failed the frozen gate, so the safer FTS path remained default.
- Is parallelism always enabled? No. Only independent read branches may use the
  opt-in gate; sequential fallback remains the default.
- Is HITL native LangGraph interrupt? The product uses a persisted,
  authenticated pending-action checkpoint boundary. Public wording must not
  claim a second native saver or raw graph-state exposure.
- What is human verified? The user confirmed the narrowed desktop functional
  paths. Provider, packaged executable, and DPI evidence remain unclaimed.

The wording above describes repository evidence and should be adapted to the
actual contributor's role before external use.
