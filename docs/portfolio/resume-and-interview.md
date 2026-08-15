# Resume and Interview Wording

Status: evidence-bounded candidate wording. Replace only after the named
verification paths have been rerun and the contributor's actual role is known.

## Resume bullet (English)

Built a Windows-local personal LLM Wiki and memory graph that turns chat and
Markdown sources into evidence-backed entities, facts, relations and
page-type-specific Wiki content; wired a shared deterministic action lifecycle
for the primary task and post-reply memory/Wiki paths with claim-before-effect,
authoritative read-back, idempotent receipt replay and fail-closed recovery,
while keeping FTS as the default and Kuzu/Qdrant as rebuildable optional
projections. Other domain writes still have explicit direct-mutation gaps.
Current evidence is a local MVP baseline, not a general business-uplift result.

## Resume bullet (中文)

实现 Windows 本地个人 LLM Wiki 与记忆图谱：从对话/Markdown 来源抽取带证据的
实体、事实、关系并生成按页面类型组织的 Wiki；将主要任务与 post-reply memory/Wiki
副作用接入 claim -> effect -> 权威读回 -> verified receipt 生命周期，支持重复请求
重放和失败恢复；以 FTS 为默认检索，Kuzu/Qdrant 仅作可重建派生层。memory feedback、
profile、hygiene、retrospective 和 continuity proposal 写入仍有 direct-mutation 缺口。
当前是单用户 MVP 证据，不宣称通用业务提升。

## Interview answer: “Is this an API wrapper?”

The ordinary chat fast path is close to a model API call, and I say that plainly.
The project is more than that only when the user uses the durable loop: source
hash, typed candidate, confirmation, graph/Wiki binding, cited recall,
correction and forget. SQLite owns state and permissions, Markdown remains
portable, and a deterministic coordinator verifies side effects on the covered
task and post-reply memory/Wiki paths. A chat-only
demo would not justify the project; the evidence rail and failure paths are the
parts I would show.

## Interview answer: “Why AI?”

Forms and FTS are better for authorization, lifecycle and exact filtering. AI
earns its place at the language boundary: extracting a preference from prose,
suggesting an entity match, planning a bounded evidence query and synthesizing
multiple cited facts. The model never decides whether a fact is allowed to be
recalled or whether a file write succeeded.

## Interview answer: “What did the stack solve?”

- Electron supplies the Windows tray, resident sidecar and preload trust
  boundary; it does not create an availability SLA.
- React/TypeScript and `@xyflow/react` keep graph, timeline, sources and failure
  states in one typed workspace; a passing typecheck does not prove visual QA.
- FastAPI/Pydantic/Uvicorn provide the local authenticated contract and health
  boundary; they are not a cloud backend.
- LangChain adapts providers/tools, while LangGraph bounds stateful routing and
  SSE events; there is no unlimited or parallel Agent swarm.
- SQLite is the authority for entities, evidence, lifecycle, claims/receipts
  and metrics; Markdown is the portable source/Wiki body.
- FTS5 is the reliable default/fallback. Kuzu is a read-only rebuildable graph
  projection and Qdrant is an optional candidate experiment, neither a second
  fact source.
- APScheduler/SQLAlchemy persist reminders and catch up after a restart; SSE
  makes state visible but cannot improve answer correctness.

## Interview answer: “What is technically difficult?”

The hard part is crossing process and storage boundaries without lying about
state. A process can die after a Markdown effect but before a receipt; recovery
must read the target by a stable key and refuse to replay if the result is not
unique. Entity identity is also harder than similarity: same-name entities need
typed scope and user review, and contradictory claims must stay isolated.
Finally, a Kuzu generation can lag SQLite, so every graph result is re-authorized
against SQLite and falls back visibly.

## Interview answer: “What happens on failure?”

The UI distinguishes no evidence, provider offline, invalid structure, conflict,
write conflict, degraded projection, sidecar recovery and unknown notification
delivery. Each state has a next action: browse local evidence, retry a read-only
step, inspect a diff, confirm/correct/forget, rebuild Kuzu or ask for manual
recovery. Unknown is not rendered as success. The latest isolated fault matrix
is `15 Passed / 0 Failed / 3 Partial`: four passes use real isolated sidecar/API
paths and eleven use a deterministic backend fault harness. The three Partial
scenarios are packaged Electron sidecar crash, real Windows sleep/resume and
Windows notification-permission denial; harness passes are not packaged Electron evidence.

## Interview answer: “Is there a measured business result?”

There is no defensible uplift percentage yet. The current production FTS
baseline has 60 synthetic cases (Recall@5 macro `24.8/50`, no-evidence accuracy
`10/10`, false activation `0/10`); citation coverage is `0/0` because this evaluator
does not generate or judge answers, and Kuzu/fallback, lifecycle and LLM
ablation samples are zero or `not_run`. I would run a preregistered 7-day
single-user protocol with fixed tasks,
before/after denominators, explicit correction and repeated-explanation
feedback, then report the result and confidence limits. Until that exists, the
only honest claim is that the mechanisms are measurable and the business result
is unproven.

## Evidence links

- Runtime wiring: `apps/backend/tests/test_action_lifecycle_wiring.py`.
- Approval/replay/recovery: `apps/backend/tests/test_production_checkpoint_resume.py`, `test_production_action_recovery.py` and `output/verification/LLMWIKI-002/action-journey-report.json`.
- Graph authority/fallback: `apps/backend/app/services/memory_entity_graph.py` and `memory_graph_kuzu.py`.
- Metrics/evaluation: `output/verification/LLMWIKI-011/eval-20260814/report.json`.
- Fault/visual boundaries: `output/verification/LLMWIKI-013/faults/fault-matrix-report.md` and `output/verification/LLMWIKI-013/visual/visual-report.json` (development-browser automation only; packaged Electron/DPI/manual states remain open).
