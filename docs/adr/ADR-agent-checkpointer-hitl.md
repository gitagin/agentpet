# ADR: Agent Checkpointer and Human-in-the-Loop Resume

- Task: TASK-1103
- Status: Adopted - architecture contract only
- Date: 2026-07-12
- Scope: design and decision only; no dependency, migration, schema, or product-code change

## Decision summary

Recommendation: **Adopt conditionally**, subject to a separate user decision and
the implementation approvals required by TASK-1104 and TASK-1105.

The recommended direction is a small SQLite-backed checkpoint adapter owned by
the existing backend `MigrationRunner`, injected into the existing LangGraph
runtime. It must remain separate from business truth (`tasks`, memory, Wiki and
`agent_actions`) and must reuse TASK-1212's policy, executor, verifier and
idempotency contracts. This ADR does not authorize that implementation.

## 1. Why the current confirmation flow is insufficient

The current action pipeline can classify an operation as
`pending_confirmation` and expose a confirmation-shaped activity result, but the
graph is compiled without a checkpointer and there is no authenticated resume
contract. A process or sidecar restart therefore loses the in-flight graph
position. The following scenarios need durable pause/resume rather than a UI-only
confirmation:

1. A high-risk Wiki/Vault operation must remain zero-write while the sidecar is
   restarted.
2. A long-running tool call may be interrupted after policy approval but before
   the executor claims its idempotency key.
3. An SSE disconnect must not turn a still-pending decision into an implicit
   approval or a duplicate terminal event.
4. An expired or rejected decision must remain auditable without touching the
   target or business ledger a second time.
5. A duplicate or cross-run decision must be rejected deterministically.

Simple chat and low-risk automatic organization should keep their current fast
path and must not be forced through HITL.

## 2. Identity and lifecycle

| Identity | Meaning | Lifetime |
| --- | --- | --- |
| `thread_id` | Stable conversation/workflow scope | Existing conversation lifetime |
| `run_id` | One graph execution attempt | One foreground execution and its resume attempts |
| `checkpoint_id` | Immutable pause snapshot | Until terminal state plus retention window |
| `proposal_id` | TASK-1212 action proposal | One proposed side effect |
| `decision_id` | One approve/reject/expire decision claim | Single-use and bound to one checkpoint |
| `idempotency_key` | Effect identity used by the existing executor | Stable across retries and resume |

Checkpoint identity must also bind `graph_version` and `state_version`. A
checkpoint from another run, thread, graph version, or policy version is not
resumable.

## 3. Checkpoint state and explicit exclusions

The minimal typed state should contain:

- thread, run and checkpoint identifiers;
- current graph node and a bounded transition sequence;
- graph/state/policy versions;
- redacted action summary, normalized target class, risk tier and reversibility;
- proposal and idempotency identifiers;
- pending/approved/rejected/expired/cancelled status;
- created, updated, expiry and terminal timestamps;
- safe error code and public event cursor needed for SSE reconnect.

It must not contain session tokens, bearer headers, provider keys, private keys,
raw prompts, chain-of-thought, unredacted model output, complete tool payloads,
raw Vault excerpts, or renderer-held credentials. Business data remains in its
existing repositories; a checkpoint is recovery metadata, not long-term memory.

## 4. Storage, migration and crash semantics

SQLite remains the local source for checkpoint metadata. A future TASK-1104
migration must be the only mechanism that creates the checkpoint table and
indexes; startup must never issue an ad-hoc `CREATE TABLE` outside
`MigrationRunner`. The exact migration number and columns require a separate
approval before implementation.

The adapter must use a single-writer transaction for checkpoint status and
decision claims. The action effect must not be considered claimed until the
existing executor's idempotency claim is durable. Recovery rules are:

- crash before interrupt persistence: no side effect and no resumable decision;
- crash after pending checkpoint persistence: decision remains pending;
- crash after decision claim but before effect: executor idempotency claim decides
  whether the effect may run;
- crash after effect but before terminal projection: read-after-write verification
  returns the original receipt and does not execute again;
- corrupted or incompatible checkpoint: stable non-resumable error, business
  data preserved.

## 5. Privacy, authentication and data minimization

The backend owns checkpoint reads, writes and deletion. Electron main/backend
authentication remains the only resume boundary. Renderer receives only a safe
projection: action label, target summary, risk, reversibility, expiry and public
status. It never receives raw checkpoint state or the session token.

The adapter must redact before persistence, reject credential-shaped fields, and
apply the same local-privacy mode restrictions as the foreground chat path.

## 6. Consistency with existing repositories and events

- `agent_actions` remains the auditable action ledger and rollback record.
- `tasks`, memory, Wiki and diary stores remain business truth.
- A checkpoint may reference a proposal and receipt but must not replace either.
- SSE reconnect replays only an allowlisted public projection and a monotonic
  event cursor; it never replays tool arguments or raw state.
- Reflection jobs remain independent managed jobs and cannot resume through a
  foreground checkpoint.

## 7. Candidate state machine

```text
running
  -> pending_confirmation
  -> approved -> resuming -> completed | failed_recovery
  -> rejected -> cancelled
  -> expired  -> cancelled
```

Only one decision may transition a checkpoint out of `pending_confirmation`.
Duplicate decisions return the original terminal result. Stale, forged,
cross-run, cross-thread, cross-checkpoint and cross-policy decisions fail closed.
Approval revalidates policy, target and external state before the executor runs.

## 8. Retention, deletion, export and observability

The following are proposals for user approval, not adopted policy:

- pending checkpoints: retain for 24 hours, then mark `expired`;
- terminal checkpoint metadata: retain for 7 days for local audit;
- deletion: delete only checkpoint rows and public projections, never tasks,
  memory, Wiki files or `agent_actions`;
- export: provide redacted metadata only, never tokens or raw model/tool payloads;
- observability: record checkpoint status transitions, safe error codes, graph and
  policy versions, decision outcome and idempotency result.

The first interrupt whitelist is also pending approval. The conservative
candidate set is existing high-risk, confirmation-gated operations only:
explicit Vault binding, destructive Wiki operations, and other operations that
the current policy already classifies as requiring confirmation. Low-risk
automatic organization is excluded. No candidate is enabled by this ADR.

## 9. Options

See `output/verification/task-1103/option-scorecard.md` for the scored comparison
of a LangGraph-provided saver, a local adapter, and deferral. The local adapter
scores highest for this checkout because it follows the existing migration and
security boundaries without adding an unapproved dependency, while still
requiring TASK-1104 schema and persistence work.

## 10. Rollback, compatibility and test cost

Rollback disables checkpoint injection and returns to the existing confirmation
path. It must not delete checkpoint rows, business data or action ledger entries.
Old databases remain startable because no implementation migration is applied
until separately approved. Before implementation, tests must cover field
redaction, thread/run isolation, version mismatch, duplicate claims, crash points,
expiry, deletion scope, concurrent decisions, restart, SSE reconnect and three
isolated approve/reject runs.

## Human Gate

The user selected `Adopt` on 2026-07-12. This records the architecture
direction only; it does not authorize implementation, dependency installation,
schema migration, retention/deletion changes, or public claims.

The decision choices were:

- `Adopt`: authorize TASK-1104 planning within the separately approved dependency,
  schema, retention and deletion boundaries;
- `Defer`: keep the current confirmation path and leave TASK-1104/1105/1214
  Planned;
- `Reject`: do not pursue persistent checkpoint/HITL on this roadmap.

The decision is recorded before any dependency installation, migration or
checkpoint code change. TASK-1104 remains at its own approval gate.
