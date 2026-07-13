# ADR: Full Multi-Agent, Hybrid Retrieval, Claims, and Evaluation Contract

- Status: Adopted — architecture contract only
- Date: 2026-07-12
- Owner: Coordinator
- Decision recommendation: Adopt
- Required evidence: L2 architecture and contract evidence
- Implementation evidence created by this ADR: None
- Public-claim promotion created by this ADR: None

## 1. Decision boundary

This ADR proposes one target contract for the future foreground graph, background
reflection graph, hybrid retrieval path, action boundary, checkpoints, public
events, evaluation, and claims.

An Adopt decision accepts the architecture and its budgets as the design
constraint for later tasks. It does not authorize:

- a product-code change;
- dependency installation, removal, or upgrade;
- a SQLite schema change or migration;
- a checkpointer implementation or storage selection;
- a real chat, embedding, or reranker provider call;
- provider cost or transmission of private excerpts;
- use of a real Vault or the default local database in verification;
- a high-risk action whitelist change;
- a destructive action test;
- a public README, resume, screenshot, video, binary, or release claim.

Each item above retains its own Human Gate. A prior approval for one gate never
approves a later gate.

The user recorded Adopt on 2026-07-12 at 01:40:49 +08:00. TASK-1202 may close
as Completed after the decision evidence is recorded. Adoption approves this
architecture contract only; no implementation task may treat it as product,
dependency, migration, provider-cost, or publication authority.

## 2. Context and current-worktree truth

The accepted TASK-1201 baseline remains the source for the current architecture.
The following statements describe current evidence, not the target:

1. The checkout has a real standard LangGraph and a bounded negotiation
   LangGraph.
2. Simple social chat has a direct streaming fast path.
3. Dynamic negotiation delegates only to the existing Retrieval Agent and does
   not provide independent specialist fan-out.
4. Retrieval is FTS-first. Optional Qdrant/vector code is derived infrastructure,
   and Kuzu is a best-effort graph mirror.
5. Current hybrid ordering is static source/mode/raw-score ordering, not
   Reciprocal Rank Fusion.
6. Action planning and execution are deterministic Python even where the current
   registry uses an Agent label.
7. High-risk actions create pending ledger state, but there is no LangGraph
   interrupt/resume checkpoint flow.
8. The current registry lacks immutable tool allowlists, privacy classes, full
   call/token/cost budgets, safe trace policy, and declared fallbacks.
9. The post-reply pipeline is scheduled by a bare asynchronous task. Its stages
   are sequential and error-isolated, but the job is not persistently managed.
10. TASK-1203 replaced the old public reasoning stop-line with the L2
    allowlisted agent-trace.v1 contract. This remains current-checkout L2
    evidence; it is not packaged L3, live-provider, or L4 evidence.
11. Current AgentState and NegotiationState contain raw user text, excerpts,
    action parameters, arbitrary invocation output, and internal decisions.
    They are in-process state and are not safe checkpoint schemas.
12. The highest current migration observed by the audit is
    017_dual_track_memory.sql. This ADR does not reserve the next migration
    number.

Adopting a target contract does not turn any target capability into current
truth.

## 3. Decision

The adopted decision defines a deterministic control plane around bounded,
typed, model-backed roles:

~~~text
Deterministic Privacy and Intent Router
  |-- simple social chat --> Fast-Path Chat Agent --> Terminal Arbiter
  |
  '-- full path --> Supervisor Agent
        --> immutable read-only work
            |-- Vault Retrieval Agent
            '-- Structured Memory Agent
        --> Deterministic Evidence Merger and Acceptance Gate
        --> Analyst and Planning Agent
        --> Independent Reviewer Agent
            |-- pass
            |-- retry one named read-only branch
            |-- replan once inside the global budget
            '-- ask user or abstain
        --> Action-Proposal Agent, only when a side effect is requested
        --> Deterministic Policy Guard
            |-- deny
            |-- low-risk approval
            '-- high-risk durable pending confirmation
        --> Deterministic Idempotency Coordinator and Executor
        --> Read-Only Verifier Agent
        --> Synthesizer Agent
        --> Public Event Projector
        --> exactly one terminal event for the execution epoch

Foreground done
  --> Managed Reflection Job
  --> Reflection Agent
  --> Deterministic Policy Guard
  --> ledgered low-risk execution or pending human decision
  --> background terminal state
~~~

The control plane is authoritative for permissions, budgets, tool exposure,
side effects, event projection, and terminal arbitration. A model may propose
typed data but may not override those controls.

Simple social chat remains a deliberate fast path. The system must not invoke
additional roles merely to increase the visible Agent count.

## 4. Model-backed role contract

The roles below are logical roles. They may use the same approved provider or
physical model, but each must have its own role ID, prompt, input schema, output
schema, context boundary, timeout, budget, trace label, fallback, and immutable
tool allowlist. Sharing a provider does not justify a claim of independent model
instances.

All tool names in this ADR are capability names for a future registry contract.
They do not claim that matching implementation symbols exist today.

| Role | Sole responsibility | Typed input | Typed output | Tool allowlist | Explicitly prohibited |
| --- | --- | --- | --- | --- | --- |
| Fast-Path Chat Agent | Reply to router-proven social chat that needs no retrieval, action, conflict handling, or local-fact claim | FastChatInput | PublicReplyDraft | None | Planning, retrieval, side effects, local-fact claims, dispatch |
| Supervisor Agent | Produce and revise a bounded dependency plan over registered roles | SupervisorInput | DispatchPlan | None; the deterministic dispatcher executes the accepted plan | Domain conclusions, final evidence review, writes, direct tool invocation |
| Vault Retrieval Agent | Convert a validated VaultChannelPlan into bounded ChannelRequests and coordinate safe candidate metadata | VaultChannelPlan | EvidenceBatch | search_vault_fts; search_vault_vector only when its gate is active | Raw candidate excerpts, physical I/O implementation, query normalization, free-form variants, Vault writes, final answer, policy decisions |
| Structured Memory Agent | Convert a validated StructuredChannelPlan into bounded ChannelRequests and coordinate safe candidate metadata | StructuredChannelPlan | EvidenceBatch | search_active_memory; search_diary_objects; search_daily_chat; search_sqlite_graph | Raw candidate excerpts, physical I/O implementation, query normalization, promotion, deletion, mutation, final answer |
| Analyst and Planning Agent | Convert accepted evidence into claim IDs, support needs, contradictions, and an optional action intent | AnalysisInput | AnalysisPlan | None | Retrieval, citation creation, final policy, final answer, writes |
| Independent Reviewer Agent | Judge claim support, citation usability, contradiction, safety, and the next bounded control action | ReviewInput | ReviewDecision | None | Retrieval tools, excluded evidence, raw reasoning, side-effect authorization |
| Action-Proposal Agent | Convert an explicit user action intent into a typed, non-executing proposal | ActionProposalInput | ActionProposal | Optional read-only action_schema_lookup | Risk approval, write tools, execution, confirmation |
| Read-Only Verifier Agent | Compare a receipt-bound expected result with current authoritative state | VerificationRequest | VerificationResult | Only receipt-bound task, ledger, memory, or Vault reads | Repair, write retry, broader search, policy change |
| Synthesizer Agent | Produce the full-path user reply from reviewer-accepted claims, citations, policy outcomes, and receipts | SynthesisInput | PublicReplyDraft | None | Retrieval, citation invention, policy change, writes |
| Reflection Agent | After foreground done, derive typed diary, memory, continuity, and Wiki proposals from the completed exchange | ReflectionInput | ReflectionProposalBatch | None | Foreground blocking, direct writes, confirmation, credential access |

### 4.1 Role invocation ceilings

These per-role ceilings are subordinate to the smaller remaining global budget.
They are upper bounds, not a requirement to invoke every role.

| Role | Calls per foreground run or background job | Per-call hard timeout | Input ceiling | Output ceiling | Tool calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fast-Path Chat Agent | 1 | 30 s | 8,000 tokens | 2,500 tokens | 0 |
| Supervisor Agent | 2 | 10 s | 4,000 tokens | 1,000 tokens | 0 |
| Vault Retrieval Agent | 2, including one transient retry | 8 s | 4,000 tokens | 1,000 tokens | 2 per call |
| Structured Memory Agent | 2, including one transient retry | 8 s | 4,000 tokens | 1,000 tokens | 2 per call |
| Analyst and Planning Agent | 2, including one bounded repair | 10 s | 8,000 tokens | 1,500 tokens | 0 |
| Independent Reviewer Agent | 2, including review after the one repair | 10 s | 8,000 tokens | 1,500 tokens | 0 |
| Action-Proposal Agent | 1 | 10 s | 4,000 tokens | 1,000 tokens | 1 read-only lookup |
| Read-Only Verifier Agent | 1 | 8 s | 4,000 tokens | 1,000 tokens | 1 receipt-bound read |
| Synthesizer Agent | 1 | 15 s | 8,000 tokens | 2,500 tokens | 0 |
| Reflection Agent | 2 per managed job, including one transient retry | 15 s | 8,000 tokens | 2,000 tokens | 0 |

### 4.2 Role privacy, trace, and cost attributes

P2 means a role may receive only the explicitly approved private projection
needed for its schema; no role may receive P3 data. Per-role cost reservations
are subordinate to the lower remaining run/job ceiling.

| Role | Maximum input privacy | Public-safe trace label | Estimated cost reservation |
| --- | --- | --- | ---: |
| Fast-Path Chat Agent | P2 bounded user message | fast_chat | USD 0.02 |
| Supervisor Agent | P2 bounded intent projection | supervisor | USD 0.01 per call |
| Vault Retrieval Agent | P2 bounded approved query; P1 safe candidate metadata only | vault_retrieval | USD 0.005 per call |
| Structured Memory Agent | P2 bounded approved query; P1 safe candidate metadata only | structured_memory | USD 0.005 per call |
| Analyst and Planning Agent | P2 accepted evidence projection | analyst_planner | USD 0.01 per call |
| Independent Reviewer Agent | P2 filtered claims and accepted evidence | reviewer | USD 0.01 per call |
| Action-Proposal Agent | P2 explicit action intent and bounded parameters | action_proposal | USD 0.005 |
| Read-Only Verifier Agent | P2 receipt-bound expected/current projection | verifier | USD 0.005 |
| Synthesizer Agent | P2 accepted claims/citations/receipts | synthesizer | USD 0.02 |
| Reflection Agent | P2 bounded completed-exchange projection | reflection | USD 0.015 per call |

The registry must reject unknown roles, undeclared tools, a widened privacy
class, a missing fallback, or a request above the remaining budget with a
stable, safe reason code.

## 5. Deterministic component contract

| Component | Sole responsibility | Input and output | Must never be advertised as |
| --- | --- | --- | --- |
| Local Privacy and Sensitive Gate | Detect policy-sensitive input before any remote call and force a local route | Approved message reference to PrivacyDecision | Agent |
| Intent Router | Select fast chat, full read path, action path, clarification, or safe refusal | RouteInput to RouteDecision | Supervisor |
| Capability Registry | Hold the versioned role schemas, allowlists, privacy classes, budgets, trace policy, and fallbacks | Registry version and immutable capability records | Agent |
| Registry Dispatcher | Validate a DispatchPlan and launch only ready, allowed work | DispatchPlan to accepted WorkItems or stable rejection | Supervisor |
| Budget Manager | Reserve and debit rounds, calls, tools, time, tokens, context, and estimated cost | BudgetRequest to BudgetReservation | Agent |
| Query Normalizer and Scope Planner | Normalize query, time, entities, scopes, and bounded variants | Approved query reference to RetrievalPlan | Retrieval Agent |
| Retrieval Adapters | Execute FTS5, Qdrant, or authoritative SQLite reads | ChannelRequest to RetrievalCandidates | Retrieval Agent |
| Evidence Merger | Apply hard filters, stable deduplication, RRF, tie-breaks, and context budgets | Candidate batches to ordered candidates | Reviewer |
| Evidence Acceptance Gate | Produce accepted evidence envelopes and deterministic citation IDs | Ordered candidates to accepted/rejected envelopes | Reviewer |
| Policy Guard | Recompute action type, target, permission, risk, confirmation, and policy version | ActionProposal to PolicyDecision | Action-Proposal Agent |
| Idempotency and Ledger Coordinator | Create a stable key, atomically claim execution, return an existing receipt for duplicates, and reconcile recovery | Approved action to ExecutionClaim | Agent |
| Executor | Own the only write-capable adapter boundary | ExecutionClaim to ExecutionReceipt | Action Agent |
| Read-After-Write Adapter | Read only the exact receipt-bound target for verification | Receipt to current target projection | Repair Agent |
| Terminal Arbiter | Enforce one terminal event per execution epoch with first-terminal-wins semantics | TerminalCandidate stream to ForegroundTerminal | Synthesizer |
| Public Event Projector | Convert internal state to versioned, allowlisted public DTOs | Internal event to public event | Agent reasoning |
| Managed Reflection Job Runner | Deduplicate, time-bound, cancel, and recover background jobs | Foreground receipt to ReflectionJobState | Reflection Agent |
| Optional Checkpoint and HITL Manager | If separately approved, persist minimized control state and resume a durable decision | CheckpointState and HumanDecisionRecord | Business truth store |

No role receives a generic all-tools collection. The existing registry is the
only registry to extend in TASK-1208; a competing registry is forbidden.

## 6. Typed state and data classification

The detailed schema is frozen in
output/verification/task-1202/state-and-event-contract.md. The architecture
uses separate types rather than one arbitrary shared dictionary:

- RunEnvelope;
- BudgetState;
- DispatchPlan and WorkItem;
- RetrievalPlan and RetrievalCandidate;
- AcceptedEvidenceEnvelope;
- RenderedCitation;
- AnalysisPlan;
- ReviewDecision;
- ActionProposal;
- PolicyDecision;
- ActionControlState;
- ExecutionReceipt;
- VerificationResult;
- PublicReplyDraft;
- ForegroundTerminal;
- TerminalReceipt and TerminalOutboxEvent;
- ReflectionJobState and ReflectionProposalBatch;
- CheckpointState and HumanDecisionRecord.

State is classified before storage or projection:

| Class | Examples | Public event | Checkpoint |
| --- | --- | --- | --- |
| P0 public-safe | trace version, allowlisted role, phase, safe status, bounded counts, safe reason code | Allowed by versioned DTO | Allowed when needed |
| P1 local-control | run/message IDs, schema versions, plan/work IDs, node cursor, budget, ledger reference, pause/terminal state | Not public unless separately allowlisted | Allowed |
| P2 private-ephemeral | user text, approved recent turns, excerpts, draft claims, action parameters, reply text | Only the separately designed user-facing reply/citation projection | Never copied; checkpoint stores authoritative record references |
| P3 secret/forbidden | session token, Authorization, provider key, credential material, raw system prompt, raw reasoning, full tool arguments/output, stack trace, absolute private path | Never | Never |

AgentState.model_dump or an equivalent full-state dump must never be passed to
a saver, logger, public event, or Renderer.

## 7. Supervisor semantics

### 7.1 Planning

1. The deterministic router creates SupervisorInput from approved references,
   privacy class, requested outcome, registry version, and current BudgetState.
2. The Supervisor produces a versioned DispatchPlan containing stable work item
   IDs, role IDs, immutable input references, dependencies, expected output
   types, branch deadlines, and terminal conditions.
3. The deterministic registry dispatcher rejects cycles, unknown roles,
   unregistered tools, write access in read branches, privacy escalation,
   mutable shared inputs, or unreserved budget.
4. The Supervisor may plan only from the capability snapshot supplied in its
   input. It cannot inspect credentials, hidden tools, arbitrary files, or raw
   registry internals.

### 7.2 Dispatch and parallelism

- A work item starts only when its dependencies are complete and its budget is
  reserved.
- Parallel dispatch is allowed only for mutually independent read-only branches
  with immutable inputs and reducer-controlled outputs.
- Write-capable work is never parallelized.
- Reversed branch completion order must yield the same accepted evidence.
- Sequential read execution remains the mandatory fallback.
- Parallel mode stays disabled by default until TASK-1210 proves real temporal
  overlap, deterministic merge, bounded cancellation, no safety regression, and
  its pre-registered promotion threshold.

### 7.3 Retry and repair

- The entire foreground run has one shared repair budget.
- A transient read-only timeout or availability error may retry the same named
  branch once if its input, permission, and remaining budget are unchanged.
- A schema error, permission failure, policy denial, invalid tool, unknown role,
  sensitive-data block, or budget exhaustion is not retryable.
- A model-backed role may never retry a write.
- The Reviewer may request one named read-only retry or one replan, not both in
  an unbounded loop.
- A replan is the second and final Supervisor planning round.

### 7.4 Escalation

The graph asks the user a concise clarification or confirmation when:

- the requested scope or target is materially ambiguous;
- accepted evidence is insufficient for a requested local-fact answer;
- accepted evidence contains an unresolved material contradiction;
- policy requires high-risk confirmation;
- a proposed action changed between planning and execution;
- checkpoint recovery cannot prove whether a side effect occurred;
- the remaining budget cannot safely satisfy the requested outcome.

Escalation exposes only a safe summary and stable decision/reference ID. It
never exposes raw reasoning, prompts, hidden evidence, credentials, or full tool
parameters.

### 7.5 Termination

The Terminal Arbiter uses first-terminal-wins. Every execution epoch emits
exactly one of:

- done;
- error;
- cancelled;
- pending_confirmation.

Branch completion, reply_ready, negotiation_done, retry, and replan are
non-terminal events. A pending_confirmation epoch is a durable pause. A later
approved or rejected resume uses the same logical run ID and a new attempt ID
and epoch ID; that epoch also receives exactly one terminal. Once a logical run
has a final done, error, or cancelled receipt, it must never execute again.
User clarification is a normal bounded reply followed by done; it is not a
resumable pending_confirmation state.

The 45-second deadline measures active compute, not wall-clock pause time.
Before committing pending_confirmation, the Budget Manager reserves the
remaining model/tool/token/cost and active-compute budget needed for one
decision epoch. The pause has a separate seven-day expiry. Resume creates a new
per-epoch compute deadline from only that reservation; it does not reset global
run counters. If the reservation is absent or exhausted, no action executes and
the resume epoch fails closed.

A durable TerminalReceipt and its deterministic-ID TerminalOutboxEvent are
committed together in one authoritative local transaction under the unique
run_id/attempt_id/epoch_id claim. If an implementation cannot make both writes
atomic, the terminal is not considered committed. Restart republishes
unacknowledged outbox rows idempotently. Exactly-one terminal means exactly one
server-committed receipt per epoch. SSE transport is at-least-once and may
disconnect before delivery; clients deduplicate by event ID and reconnect can
replay the committed terminal. Fully consumed streams must observe exactly one
terminal.

After pending_confirmation:

- approval opens a decision epoch and ends in done, error, or cancelled;
- rejection opens a decision epoch, records decision/audit control state, makes
  zero business side-effect adapter calls, and ends in done with
  action_rejected;
- expiry atomically records decision/audit control state, makes zero business
  side-effect adapter calls, and ends the logical run as cancelled with
  confirmation_expired; the committed terminal is replayable on reconnect.

## 8. Global budgets

### 8.1 Fast path

| Budget | Ceiling |
| --- | ---: |
| Supervisor calls | 0 |
| Specialist calls | 0 |
| Model calls | 1 |
| Tool calls | 0 |
| Aggregate provider input | 8,000 tokens |
| Aggregate provider output | 2,500 tokens |
| Hard elapsed deadline | 30 s |
| Measured p95 promotion target | 10 s |
| Estimated external cost hard ceiling | USD 0.02 per run |

The fast path must leave immediately if routing discovers a local-fact claim,
retrieval need, contradiction, or side effect. It cannot silently make such a
claim without evidence.

### 8.2 Full foreground path

| Budget | Ceiling |
| --- | ---: |
| Planning rounds | 2: initial plan plus at most one replan |
| Supervisor calls | 2 |
| All model calls | 10 |
| Specialist dispatches | 8 |
| All tool calls | 12 |
| Tool calls by one role | 4 |
| Shared retry/replan repairs | 1 |
| Write execution claims | 1 |
| Approved context material before prompt expansion | 48,000 characters |
| Aggregate provider input | 32,000 tokens |
| Aggregate provider output | 8,000 tokens |
| Accepted prompt evidence | top 5, at most 2 per scope, initially at most 1,200 excerpt characters total |
| Hard elapsed deadline | 45 s |
| Measured full-path p95 promotion target | 25 s |
| Estimated external cost hard ceiling | USD 0.10 per run |

The cost value is a ceiling, not permission to spend it. Real-provider
evaluation or a new provider/data policy still requires its own Human Gate.
The elapsed ceiling is aggregate active compute across all attempts. Time spent
paused for confirmation is excluded, while every call/tool/token/cost counter
persists. A pending decision must hold an explicit resume reservation inside
these same ceilings.

### 8.3 Background reflection

| Budget | Ceiling |
| --- | ---: |
| Reflection model calls | 2, including one transient retry |
| Proposal candidates evaluated | 4 |
| Write execution claims | 4, each separately policy-checked and idempotent |
| Aggregate provider input | 16,000 tokens |
| Aggregate provider output | 4,000 tokens |
| Per-stage hard timeout | 15 s |
| Job hard elapsed deadline | 60 s |
| Estimated external cost hard ceiling | USD 0.03 per job |

Background work never extends the foreground terminal deadline. A background
failure is recorded in its own safe terminal state and does not rewrite the
already completed user reply.

### 8.4 Enforcement

- The Budget Manager reserves the maximum expected debit before dispatch.
- Reservation failure prevents dispatch.
- Actual calls, tool invocations, elapsed time, provider-reported tokens, and
  price inputs are debited as they occur.
- Missing provider usage or price data is recorded as unknown, never zero. The
  manager stops new dispatch and chooses the safe fallback.
- Expired branches are cancelled. Late results are ignored by stable work item
  ID and cannot mutate state.
- Budget exhaustion selects a safe answer, clarification, no-evidence result, or
  error. It never relaxes privacy, permission, citation, or action policy.
- Every timeout and failure-injection case must terminate within its hard
  ceiling.

## 9. Retrieval contract

### 9.1 Sources of truth

- Vault Markdown is the user-visible note truth.
- Authoritative SQLite records hold current chunk IDs, content hashes, scopes,
  active/deleted status, diary objects, structured memory lifecycle, recall
  permissions, graph facts, tasks, actions, and audit state.
- SQLite FTS5 is the accepted default retrieval base until later gates pass.
- Qdrant holds only a rebuildable vector generation keyed back to authoritative
  SQLite chunk IDs.
- Kuzu remains a rebuildable graph mirror and is not an initial query channel.
- Qdrant or Kuzu data with a missing, deleted, inactive, cross-Vault, stale, or
  hash-mismatched authoritative record cannot become evidence.

An indexed SQLite chunk is citable only when its index generation and content
hash are validated against the current Markdown source. When Markdown changed
after the last verified index sync, Markdown remains the user-visible truth,
the stale SQLite/Qdrant chunk is rejected as evidence, and a safe reindex is
scheduled. The system does not answer from either stale copy.

If the authoritative SQLite layer is unavailable, the system returns a stable
error or explicit safe no-evidence result. It must not answer from a derived
index alone.

### 9.2 Requested and effective modes

The target versioned retrieval policy supports:

- fts;
- vector;
- hybrid_rrf;
- hybrid_rrf_rerank;
- auto.

Unknown values fail with a stable code. They do not silently become hybrid.

Every result records requested_mode, effective_mode, requested_channels,
completed_channels, fallback_reason, corpus generation, and policy version.

The safe vector-health projection records semantic_available,
vector_available, embedding_configured, index_version, active_generation,
last_sync_status, and a bounded unavailability_reason. It contains no
credential, query, excerpt, or private path.

Auto selects only the newest mode that has passed all applicable lifecycle,
privacy, evidence, quality, latency, cost, and Human Gates. Before TASK-1205,
TASK-1206, and TASK-1207 pass, auto is equivalent to the accepted FTS-first
route.

Product-safe vector and hybrid modes fall back to FTS when a derived service
fails. Strict evaluation mode does not hide a channel failure behind fallback;
it records the failure so the requested mode can be measured honestly. TASK-1204
Mode Fts enables only the FTS candidate channel.

### 9.3 Candidate channels and RRF

Initial candidate channels are:

- FTS5 Vault chunks;
- Qdrant vector chunks, only from an active validated generation;
- authoritative active-memory SQLite results;
- authoritative diary SQLite results;
- authoritative daily-chat SQLite results;
- authoritative graph-fact SQLite results.

Each channel returns at most 40 candidates. Hard Vault, scope, permission,
lifecycle, sensitivity, generation, and current-hash filters run before fusion.
Duplicates inside a channel are removed by authoritative ID.

Initial RRF is frozen before tuning:

~~~text
rrf_score(document) =
  sum over contributing channels of
  1.0 / (60 + one-based rank in that channel)
~~~

- k is 60.
- Every initial channel weight is 1.0.
- BM25, cosine, activation, or provider raw scores are not directly added.
- The deterministic tie-break is the ordered approved_scopes index in
  RetrievalPlan, then best single-channel rank, then authoritative stable ID in
  lexical order. The planner orders explicitly requested scopes first in user
  order and appends permitted fallback scopes in the fixed order
  personal_memory, diary, daily_chat, wiki, vault_note, graph.
- Contributor channels, ranks, and score components are retained in local
  evaluation data.
- Fusion is independent of branch completion order.
- Results are deduplicated again by authoritative ID and current content hash.
- Retrieval evaluation uses top 10. Prompt assembly uses the final top 5.

RRF cannot become the default until TASK-1204 freezes the corpus and FTS
baseline, TASK-1205 proves vector lifecycle and fallback, TASK-1206 passes the
RRF metrics, and TASK-1207 proves evidence/citation acceptance.

### 9.4 Reranker

The reranker is disabled by default. If separately approved, it:

- consumes no more than the first 20 already accepted evidence envelopes;
- may only reorder that set;
- cannot add evidence or change permission, lifecycle, excerpt, citation ID, or
  authoritative identity;
- falls back deterministically to the RRF order on error or timeout;
- cannot receive private excerpts through a remote endpoint without an explicit
  provider/data-policy Human Gate.

It may be enabled only when nDCG@10 or citation precision improves by at least
0.05 absolute, Recall@10 regression is no greater than 0.02 absolute, the paired
bootstrap improvement 95% confidence interval has a lower bound of at least
zero, every safety-zero remains zero, and latency and cost stay inside this ADR.

### 9.5 Vector generation lifecycle

A vector generation identity contains:

- embedding provider;
- embedding model;
- dimensions;
- normalization;
- chunker version;
- corpus generation;
- privacy policy version;
- embedding transport class: local or remote-approved;
- indexed content privacy eligibility.

Lifecycle:

1. Create a new isolated generation in building state.
2. Backfill every eligible authoritative chunk.
3. Verify point count, authoritative chunk ID set, content hashes, Vault
   identity, and generation identity.
4. Mark the generation validated.
5. Atomically promote it to active.
6. Keep the prior active generation isolated for rollback.
7. Delete only an isolated derived generation after the approved retention
   point.

A model, dimensions, normalization, chunker version, content hash, Vault, or
generation mismatch requires reject/rebuild; generations are never mixed.
Corruption, missing points, duplicates, provider failure, or failed validation
keeps the old active generation. With no valid old generation, retrieval falls
back to FTS.

TASK-1205 must decide whether this needs a dependency, storage record, or schema
change at its own Human Gate. This ADR selects none.

### 9.6 Privacy and untrusted content

- Query planning receives only approved bounded conversation context.
- A local-privacy or sensitive-policy decision removes remote embedding and
  reranker channels before dispatch.
- Such a case must record zero remote calls, zero transmitted bytes, zero
  provider cost, and an effective local FTS/structured or explicit no-evidence
  result.
- Credentials are read only through the local credential boundary and never
  enter state, events, fixtures, evidence, or diagnostics.
- Telemetry excludes raw query text, prompt text, excerpts, replies, action
  parameters, credentials, and absolute paths.
- Retrieved Markdown is untrusted quoted data. It cannot select a tool, change a
  route, override a system or policy instruction, grant permission, or confirm
  an action.
- Remote reranking of private excerpts is disabled unless explicitly approved.

### 9.7 Fallbacks

| Failure | Required fallback |
| --- | --- |
| Query planner or model failure | Deterministic RetrievalPlan |
| Embedding key, dependency, provider, authentication, or timeout failure | FTS plus approved structured channels |
| Missing, stale, or corrupt Qdrant generation | Ignore derived points and use FTS |
| One vector/read branch failure | Merge remaining accepted branches within budget |
| Reranker failure | Original deterministic RRF order |
| Kuzu failure | Continue authoritative SQLite retrieval |
| All candidate channels empty while SQLite is healthy | Explicit no-evidence |
| Authoritative SQLite unavailable | Stable error; never answer from Qdrant/Kuzu alone |

Every fallback remains subject to privacy, permission, evidence, budget, and
single-terminal rules.

## 10. Evidence and Reviewer contract

### 10.1 Three-stage evidence model

RetrievalCandidate, AcceptedEvidenceEnvelope, and RenderedCitation are distinct
types.

An AcceptedEvidenceEnvelope contains at least:

- schema version;
- deterministic citation ID;
- authoritative record and chunk ID;
- source kind and requested scope;
- current content hash;
- permitted non-empty excerpt;
- lifecycle and recall permissions;
- confidence;
- contributing channels, ranks, and RRF components;
- vector generation when applicable;
- acceptance policy version.

Acceptance is fail-closed. A candidate is accepted only when:

- the authoritative record exists in the active Vault/database;
- scope matches the approved RetrievalPlan;
- content hash and generation are current;
- lifecycle is active, or is archived only when RetrievalPlan explicitly
  requests historical context; it is never deleted, forgotten, rejected,
  superseded, expired, unresolved-conflict, reverted, or wrong;
- can_answer_context is explicitly true;
- sensitive or inaccessible content is excluded;
- the excerpt is a bounded projection of the authoritative chunk;
- the system, not a model, generated the citation ID.

Only accepted evidence content or excerpts enter a model prompt or produce a
citation event. A RenderedCitation must reference an ID in the accepted set.
Candidate events are diagnostic-only and never rendered as citations.

Retrieval Agents are not an exception: their model prompts receive the approved
query plan and safe candidate IDs/ranks/status only, never an unaccepted
excerpt. Deterministic adapters and the Evidence Acceptance Gate materialize
candidate content out of band. An excerpt becomes model-visible only after its
AcceptedEvidenceEnvelope passes.

### 10.2 ReviewDecision

The Reviewer output is a strict review-decision.v1 object:

- schema_version;
- evidence_status: supported, insufficient, contradictory, or unsafe;
- decision: pass, retry, replan, escalate, or reject;
- supported_claim_ids;
- unsupported_claims with enum reason codes;
- usable_citation_ids;
- rejected_citations with enum reason codes;
- missing_evidence_needs;
- required_scopes;
- confidence from 0 through 1;
- next_permitted_action: synthesize, propose_action, retry_read, replan,
  ask_user, or abstain;
- optional one-time retry role and immutable input reference;
- safe_summary_code selected from a bounded enum and rendered through a fixed
  safe-text table.

It contains no raw reasoning.

Supported evidence can produce pass only when confidence is at least 0.80. A
lower-confidence result must escalate for clarification or reject to abstention;
it cannot silently pass.

pass plus a validated explicit action intent may select propose_action. This
only permits deterministic transition to Action-Proposal; it is not policy
approval or user confirmation.

Citation acceptance additionally requires that a citation:

- belongs to the current accepted envelope set;
- supports at least one explicit claim ID;
- preserves the relevant entity, date, identifier, negation, and uncertainty;
- does not use a merely related excerpt as support;
- is not contradicted by a higher-authority current source without explicit
  qualification.

The Reviewer has no tools, cannot view rejected/excluded raw content, cannot
create a citation, cannot alter an excerpt, cannot approve a side effect, and
cannot loosen policy. Reviewer failure falls back to a stricter deterministic
claim-support gate, user clarification, or abstention; it never widens evidence.

## 11. Side-effect and exactly-once contract

### 11.1 Ownership

- Model-backed roles emit typed proposals only.
- The deterministic Policy Guard recomputes action type, normalized target,
  canonical parameters, permission, risk, confirmation requirement, and policy
  version.
- The Policy Guard/coordinator derives validated precondition hashes,
  postcondition specifications, and verification outcomes from the canonical
  action schema plus an authoritative pre-read. Model-proposed expectations are
  not authoritative and cannot define verification success.
- Only the deterministic Executor owns write-capable adapters.
- The Verifier reads only the receipt-bound target and cannot repair it.

### 11.2 Lifecycle

~~~text
proposed
  -> policy_checked
      -> denied
      -> pending_confirmation
          -> rejected
          -> expired
          -> approved
      -> approved
  -> claimed
  -> executing
  -> applied
  -> verifying
  -> verified
      -> completed
  -> reconciling
      -> applied
      -> verified
      -> failed_recovery
~~~

No side effect may occur before approved. High-risk policy always selects
pending_confirmation before the first side effect.

claimed, executing, applied, verifying, reconciling, verified, completed, and
failed_recovery are persisted ActionControlState values advanced by compare-and-
swap. Recovery may move claimed, executing, applied, or verifying to
reconciling. Reconciliation may prove applied, prove verified, or stop at
failed_recovery; it never directly repeats the adapter.

### 11.3 Stable identity and execution claim

The backend derives a stable idempotency key from:

- schema version;
- source message ID;
- coordinator-assigned stable explicit-intent slot ID;
- action type;
- normalized target identity;
- canonical parameter hash.

Policy version and confirmation digest are stored in PolicyDecision but are not
part of the stable effect identity. On every resume, the coordinator first
looks up the existing effect key, then revalidates current policy. A policy
change cannot create a second key for the same effect. If revalidation changes
the target or canonical effect, the old proposal is denied and a new explicit
proposal and confirmation are required.

The coordinator preallocates proposal_id from source message ID and the stable
explicit-intent slot before invoking Action-Proposal. The model must echo it and
cannot create a new identity during retry or replan.
For Reflection, the stable identity uses job ID, source message ID, proposal
kind, and coordinator-assigned slot ordinal; a model retry cannot create a
second background effect identity.

Before execution, the ledger coordinator atomically claims the unique key.
Repeated dispatch, approval, reconnect, or resume returns the existing state or
receipt and never invokes the adapter again.

SQLite effects should commit the execution claim, business mutation, and receipt
in one transaction. Markdown effects use a target lock, expected pre-write hash,
rollback snapshot, deterministic post-write hash, atomic replacement, and
read-after-write verification. If a crash occurs after a possible filesystem
write but before its receipt, recovery compares authoritative state with the
expected post-write hash. A match records the existing application; a mismatch
or ambiguity enters failed_recovery and requires human resolution. It is never
blindly replayed.

An external non-idempotent adapter is forbidden until it provides a stable
idempotency/reconciliation contract.

Exactly-once is claimed only for adapters that satisfy this contract. It means
one stable key receives at most one adapter invocation and one reconciled
business outcome. When crash recovery cannot prove the outcome, the action
enters failed_recovery and the system makes no completed/exactly-once claim.

### 11.4 Confirmation and resume

- The backend creates an opaque decision ID bound to action digest, user
  context, policy version, and expiry.
- The Renderer sees only the opaque ID, action type, bounded target label, risk,
  expiry, and safe confirmation text.
- Approval, rejection, expiry, and repeated decisions are authenticated through
  the existing Electron main/backend boundary; the Renderer never receives the
  session token.
- Resume revalidates policy, target hash, permissions, expiry, existing receipt,
  and external state before claiming execution.
- Reject and expiry produce zero business side-effect adapter calls or business
  writes. Atomic decision, ledger, terminal, and audit-control records are
  required.
- Duplicate approval returns the prior receipt.
- The checkpoint references the action ledger ID; it does not duplicate the
  complete action payload.

## 12. Checkpoint, retention, deletion, and restart proposal

The user adopted these policy values as architecture constraints. This section
still does not select a LangGraph saver, dependency, table, schema, migration
number, or implementation task.

### 12.1 Minimized checkpoint

A checkpoint may contain P0/P1 control state only:

- graph, state, registry, policy, and event schema versions;
- run, attempt, epoch, plan, and work item IDs;
- immutable authoritative message/evidence/action record references;
- accepted and rejected evidence IDs, not excerpts;
- claim IDs, not draft prose;
- budget counters and deadline;
- safe trace cursor;
- action ledger/decision ID;
- pause, cancellation, and terminal state;
- timestamps and expiry.

It excludes credentials, tokens, Authorization, keys, system prompts, raw model
reasoning, raw user/reply text, recent turns, excerpts, full action parameters,
complete tool input/output, exception stacks, and absolute private paths.

### 12.2 Proposed retention

| State | Proposed retention |
| --- | --- |
| Running or read-only resumable checkpoint | 24 hours after last update |
| Pending confirmation | 7 days; expiry never implies approval |
| Completed, rejected, expired, error, or cancelled payload | Delete 24 hours after terminal state |
| Local capacity | At most 100 checkpoint payloads or 10 MB, whichever is reached first |
| Audit tombstone | Keep run/attempt/epoch IDs, the unique TerminalReceipt ID, terminal code, timestamps, policy version, and ledger reference according to the existing audit policy |

Capacity pressure evicts only terminal payloads first. It cannot evict a live
pending decision before expiry. Automatic deletion removes checkpoint and
decision payload only; it never deletes messages, tasks, memory, Wiki Markdown,
action ledger records, rollback snapshots governed by their own policy, or
business truth. Manual early deletion requires authenticated explicit user
confirmation.

Admission reserves payload bytes and one slot before a durable pause is
created. If 100 payloads or 10 MB would be exceeded and no terminal payload can
be evicted, the manager rejects the new durable pause, performs no business
side effect, and asks the user to resolve or explicitly delete existing pending
state. Live pending payloads never overflow the hard cap.

### 12.3 Restart

On restart the manager validates:

- graph/state/registry/policy versions;
- expiry;
- current terminal receipt;
- idempotency execution claim;
- authoritative message/action references;
- target and expected hashes for a possible side effect.

Pending confirmation is never auto-approved. A terminal run is never executed
again. Unknown tool state is verified before any decision. An incompatible,
corrupt, expired, or ambiguous checkpoint fails closed with a safe status; the
underlying message, task, memory, Wiki, and action ledger truth remains intact.

TASK-1103, TASK-1104, TASK-1105, and TASK-1214 must still execute their serial
Human Gates for concrete design, dependency/schema, cross-process restoration,
interrupt/resume, decision expiry, and action-whitelist acceptance.

## 13. Background reflection contract

Reflection begins only after a foreground done receipt. It does not run after
error, cancelled, or pending_confirmation.

- job_id is deterministic from parent message ID and reflection policy version;
- only one active job exists for that key;
- proposal IDs are coordinator-preallocated from job ID, source message ID,
  proposal kind, and stable slot ordinal before a model call; retries must echo
  the same IDs;
- job input uses authoritative message references and a bounded approved
  projection, not a foreground state dump;
- the Reflection Agent emits proposals and has no write tool;
- every proposal passes the same deterministic privacy and Policy Guard;
- low-risk approved writes use the same idempotency, ledger, snapshot, executor,
  and verification boundary;
- high-risk, sensitive, conflicting, or uncertain proposals become pending or
  denied and never block the foreground;
- each proposal has its own PolicyDecision, ActionControlState, ledger ID,
  idempotency key, and terminal result;
- stage timeout, cancellation, retry budget, and safe terminal state are
  explicit;
- restart never duplicates an already claimed proposal;
- background events are namespaced and cannot become foreground terminals.

The managed reflection job finishes its active compute within 60 seconds. A
high-risk proposal is detached as a durable pending action with its own
seven-day decision expiry; it does not keep the reflection job running or
freeze the job deadline. The job ends done_with_pending or partial with the
pending action IDs, and later decision epochs use the action contract. The
action ledger's complete ActionControlState is authoritative; the job snapshot
stores references and may be refreshed from that ledger.

## 14. Public event contract

agent-trace.v1 remains immutable for current role IDs. Adding target roles or
branch semantics requires an explicit agent-trace.v2 schema and compatibility
tests; new IDs must not be silently inserted into v1.

Public events may contain only:

- event schema version;
- run/attempt/epoch-safe ID;
- allowlisted role ID;
- phase and bounded status;
- branch-safe ID when applicable;
- bounded progress counts;
- stable safe reason code;
- accepted citation projection;
- bounded action confirmation projection;
- one terminal payload.

Public events exclude raw prompts, reasoning, user/private excerpts except the
separately accepted citation projection, full tool parameters/output,
credentials, Authorization, provider keys, stack traces, and absolute paths.

Trace sequence is not a replay or decision ID. Reconnect and resume use their
own stable IDs and deduplication contract.

## 15. Pre-registered evaluation contract

The complete frozen table and statistical definitions are in
output/verification/task-1202/evaluation-thresholds.md.

### 15.1 Corpus

TASK-1204 must create at least 60 fixed, versioned, non-private cases with the
specified slices:

- 10 exact keyword and identifier;
- 15 keyword-free semantic paraphrase;
- 8 Chinese conversational;
- 5 Chinese-English cross-expression;
- 7 temporal/date/entity constrained;
- 5 contradictory/stale/superseded;
- 5 permission/inactive/sensitive exclusion;
- 5 empty/adversarial/unanswerable.

Each case has a stable ID, public or synthetic fixture, query, relevant IDs,
excluded IDs, source scope, answerable label, tags, and non-private rationale.
The corpus, evaluator, configuration, and report are hashed before tuning.

### 15.2 Final retrieval and grounding gates

| Metric | Gate |
| --- | ---: |
| Inaccessible-memory leakage | 0 |
| Cross-Vault leakage | 0 |
| Fabricated citations | 0 |
| Local-fact claims with empty accepted evidence | 0 |
| Recall@5 | at least 0.80 |
| Recall@10 | at least 0.90 |
| Precision@5 | at least 0.80 |
| MRR@10 | at least 0.75 |
| nDCG@10 | at least 0.80 |
| Citation precision | at least 0.95 |
| Local-fact citation coverage | 1.00 |
| Grounded-answer faithfulness | at least 0.90 |
| No-evidence accuracy | 1.00 |
| Recall@10 for each answerable primary slice with relevant IDs | at least 0.80 per eligible slice |
| Keyword-free Recall@10 delta from FTS | at least +0.15 absolute |
| Exact-query Recall@10 regression from FTS | no more than 0.02 absolute |

TASK-1204 records the FTS baseline honestly even when it misses a final gate.
Thresholds do not move after results are observed.

The empty/adversarial/unanswerable slice has no Recall denominator when it has
no relevant IDs. It is gated by no-evidence accuracy 1.00 and the zero
fabrication, leakage, local-fact, and prompt-injection violations instead.

### 15.3 Multi-Agent, action, and failure gates

| Metric | Gate |
| --- | ---: |
| Deterministic route/role-selection accuracy | at least 0.95 |
| Valid plan schema and dependency graph | 1.00 |
| Invalid role/tool/privacy escalation rejection | 1.00 |
| Reviewer evidence-status classification accuracy on fixed cases | at least 0.95 |
| Reviewer control-decision accuracy on fixed cases | at least 0.95 |
| Deterministic scenario task success | at least 0.90 |
| High-risk writes before confirmation | 0 |
| Duplicate side effects | 0 |
| Writes by read-only roles or branches | 0 |
| Retrieved prompt-injection policy/tool changes | 0 |
| Foreground epochs with other than exactly one terminal | 0 |
| Failure samples ending outside the hard budget | 0 |
| Duplicate background reflection writes | 0 |

Parallel fan-out is enabled by default only if all safety gates remain zero and
either:

- deterministic scenario task success improves by at least 0.05 absolute with
  no p95 regression; or
- full read-path p95 improves by at least 20 percent with task-success
  regression no greater than 0.02 absolute.

Sequential fallback must remain accepted.

### 15.4 Latency and cost gates

- Fast path p95: at most 10 s; hard timeout 30 s.
- Full foreground p95: at most 25 s; hard timeout 45 s.
- Fast-path TTFT p95: at most 2.5 s, measured to the first user-visible reply
  token rather than a status/trace event.
- Full-path TTFT p95: at most 8 s by the same definition.
- Local orchestration overhead p95, excluding model/provider, embedding,
  retrieval adapter, reranker, and user pause time: at most 250 ms.
- SQLite FTS p95: at most 200 ms; hard timeout 500 ms.
- Structured local retrieval p95: at most 200 ms; hard timeout 500 ms.
- Local Qdrant search excluding embedding p95: at most 250 ms; hard timeout
  750 ms.
- Permission/filter/RRF/deduplication p95: at most 50 ms; hard timeout 200 ms.
- Approved embedding call p95: at most 2 s; hard timeout 5 s.
- Reranker incremental p95: at most 1.5 s; hard timeout 3 s.
- Hybrid RRF total p95: at most 3 s; hard timeout 5 s.
- Hybrid RRF plus reranker p95: at most 4.5 s; hard timeout 7 s.
- Provider/vector/reranker failure to FTS/no-evidence: hard timeout 5 s.
- Deterministic/local evaluation external cost: USD 0.
- External retrieval mean: at most USD 0.02 per query.
- External retrieval hard query ceiling: USD 0.05.
- Reranker incremental mean: at most USD 0.01 per query.
- One full approved corpus pass: at most USD 5.
- Approved five-run TASK-1215 provider campaign: at most USD 25.

The foreground/retrieval total deadline is the outer absolute active-compute
limit. Substage timeouts consume only the remaining outer budget and are not
additive extensions.

For five-run provider candidates, safety is evaluated on every individual run.
Quality and paired bootstrap comparisons first aggregate the five runs within
each case, then use the case as the resampling unit; repeated provider runs are
not treated as independent cases.

Real-provider runs require a separate Human Gate that freezes provider, model,
data classes, price basis, sample count, tokens, run count, and maximum cost.
Unknown provider usage or pricing fails the cost gate.

## 16. Evidence levels and public claims

| Evidence level | Permitted wording | Prohibited promotion |
| --- | --- | --- |
| L1 unit/static | A named parser, DTO, node, or deterministic component passed the listed unit/static checks in the named checkout | System-level multi-Agent, hybrid RAG, HITL, provider, package, or user-experience claims |
| L2 contract/integration | A named capability passed its fixed contract/integration suite in the current checkout, with configuration and fallback qualifications | Packaged desktop, real provider reliability, real Vault safety, cross-process recovery, or human usability |
| L3 isolated product path | A named capability worked through the real packaged/product path with isolated Vault/database/provider state, restart/failure coverage, machine, date, and run count | General user usability, untested providers/machines/data, or public release |
| L4 human usability | The named tester completed the fixed accepted scenario on the recorded build/date | Replacing L2 safety or quality metrics, generalizing to all users, or claiming release approval |

Current L2 wording that remains safe:

> The current checkout contains a real LangGraph-based multi-role workflow, a
> bounded retrieval-only negotiation path, a simple-chat streaming fast path,
> deterministic safety-controlled actions, an FTS-first local retrieval
> baseline with optional derived vector infrastructure, and an allowlisted
> agent-trace.v1 public trace contract.

It must be accompanied by these qualifications:

- independent target roles and parallel collaboration are not accepted;
- RRF, reranking, positive vector lifecycle, and measured hybrid quality are not
  accepted;
- persistent checkpoint/HITL resume is not accepted;
- evidence is current-checkout L2, not packaged L3, live-provider, or L4.

Adopting this ADR does not permit claims that the target roles already
collaborate, that hybrid RAG is calibrated, that fan-out is parallel, or that
HITL survives restart.

The terms enterprise-grade, production-grade, fully autonomous, self-healing,
zero hallucination, guaranteed accuracy, and guaranteed privacy are prohibited
unless a later task defines a measurable scope, passes the required L2/L3/L4
evidence, and the user separately approves the exact public wording in
TASK-1217. No evidence level automatically approves publication.

## 17. Dependency and Human Gates

| Gate | What must be explicitly approved | This ADR's effect |
| --- | --- | --- |
| TASK-1202 decision | Adopt, Defer, or Reject this target contract | Adopted 2026-07-12 01:40:49 +08:00; contract only |
| Dependency | Exact package and version installation/removal/upgrade | Not approved |
| Migration/schema | Concrete schema, current next migration number, compatibility, rollback, tests | Not approved |
| Checkpointer | Saver/dependency/storage choice and concrete retention implementation | Not approved |
| Provider/data/cost | Provider, model, transmitted data class, run count, token/cost cap, timeout | Not approved |
| Real state | Any test against a real Vault or default local database | Not approved |
| Action/HITL | High-risk whitelist, expiry, restart, decision, destructive test | Not approved |
| Reranker | Package/model/endpoint/paid service and private-excerpt policy | Not approved |
| L4/publication | Tester acceptance, screenshot/video/binary/resume/release wording | Not approved |

Future tasks preserve the declared sequence:

1. TASK-1204 freezes the corpus and FTS baseline.
2. TASK-1205 establishes optional vector lifecycle.
3. TASK-1206 implements and measures RRF and any candidate reranker.
4. TASK-1207 establishes accepted evidence and citation validation.
5. TASK-1208 extends the existing registry.
6. TASK-1209 establishes the Supervisor graph while preserving fast/sequential
   fallback.
7. TASK-1210 may add measured read-only fan-out.
8. TASK-1211 establishes Reviewer repair/escalation.
9. TASK-1212 establishes proposal/policy/executor/verifier and exactly-once
   action behavior.
10. TASK-1213 manages reflection.
11. TASK-1103 through TASK-1105 and TASK-1214 govern concrete persistent
    checkpoint/HITL approval and acceptance.
12. TASK-1215 owns unified failure, quality, latency, token, and cost gates.
13. TASK-1216 owns packaged L3 and fixed L4 demo evidence.
14. TASK-1217 owns exact public claims and release approval.

Only the task file's dependencies, status, allowed files, and Human Gates grant
permission to enter each task.

## 18. Consequences and tradeoffs

### Positive

- Model-backed reasoning is separated from permission, policy, execution,
  idempotency, and public projection.
- Every role has a narrow, testable responsibility and no implicit all-tools
  access.
- The current fast path, FTS-first fallback, local privacy behavior,
  deterministic action assets, ledger, snapshots, and sequential fallback are
  preserved.
- Retrieval quality claims become tied to a frozen corpus and fixed metrics.
- Candidate retrieval, accepted evidence, and rendered citations can no longer
  be conflated.
- Checkpoint state is minimized and separated from business truth.

### Costs and risks

- More schemas and gates increase implementation and test complexity.
- Independent Reviewer and Verifier calls add latency and provider cost.
- A 45-second hard budget may force abstention or clarification for complex
  requests.
- Strict fail-closed evidence rules may initially reduce answer coverage.
- Filesystem and database effects cannot share one transaction; ambiguous
  Markdown recovery must stop for human resolution.
- Vector generation management and cross-process HITL may require future schema
  or dependency changes that are not yet approved.

### Mitigations

- Preserve fast, FTS-only, sequential, and no-reranker fallbacks.
- Keep only one bounded repair cycle.
- Require measurement before enabling fan-out, vector auto mode, or reranking.
- Use deterministic fake/local evaluation before requesting provider cost.
- Keep each future migration, dependency, and public claim behind an explicit
  gate.

## 19. Alternatives considered

### Keep the current architecture unchanged

Rejected as the target because the current registry, evidence boundary,
side-effect recovery, background management, and Reviewer/HITL contracts do not
support the requested claims. The current path remains a rollback and baseline.

### Add more model roles without deterministic controls

Rejected because role count is not capability proof and would widen tool,
privacy, cost, and failure surfaces.

### Make the Supervisor the semantic planner and final reviewer

Rejected because one routing authority would plan, judge its own evidence, and
control termination. Planning, domain analysis, and independent review remain
separate.

### Make Qdrant or Kuzu authoritative

Rejected because user-visible Markdown and SQLite lifecycle records are the
auditable truth. Derived indexes must be disposable and rebuildable.

### Let models execute low-risk actions directly

Rejected because typed proposal, deterministic policy, idempotency, ledger,
snapshot, executor, and verification boundaries are required even for
automated low-risk work.

### Select a checkpointer and migration in TASK-1202

Rejected because dependencies, schema, retention implementation, compatibility,
restart, and rollback require later serial Human Gates and current migration
inspection.

## 20. Verification and acceptance

TASK-1202 verification checks only the completeness and consistency of this
proposal and the current MVP task matrix. It does not run product tests because
no product code changed; the task's required documentation checks are the ADR
keyword scan and MVP acceptance-gap validation.

The Coordinator's recommendation is Adopt:

> Adopt the architecture, budgets, proposed checkpoint payload retention and
> deletion values, evaluation thresholds, and claim gates only. The checkpoint
> values become design constraints, not implementation authority. This decision
> does not authorize product-code changes, dependency installation, schema
> migration, real-provider calls, checkpointer selection, action-whitelist
> changes, real-Vault testing, L4 acceptance, or public release.

The user recorded Adopt. The normalized decision and exact user wording are
preserved in docs/adr/ADR-full-multi-agent-hybrid-rag-decision.md and
output/verification/task-1202/user-decision.md.

## 21. Rollback

If the proposal is rejected, revert only:

- docs/adr/ADR-full-multi-agent-hybrid-rag.md;
- the proposal portion of
  docs/adr/ADR-full-multi-agent-hybrid-rag-decision.md;
- TASK-1202 status bookkeeping.

Preserve the user decision record and verification evidence. Do not touch any
pre-existing dirty or untracked product file.
