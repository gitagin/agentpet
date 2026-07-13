# TASK-1202 Architecture Decision Record

- Status: Adopted — architecture contract only
- Date presented: 2026-07-12
- Owner: Coordinator
- Proposal:
  docs/adr/ADR-full-multi-agent-hybrid-rag.md
- Recommended option: Adopt
- User decision: Adopt
- Decision date: 2026-07-12 01:40:49 +08:00

## Decision requested

Choose exactly one option:

### Adopt — recommended

Accept the proposed role boundaries, deterministic control plane, typed state,
foreground and background budgets, retrieval truth, RRF contract, Reviewer
schema, exactly-once boundary, checkpoint policy proposal, evaluation
thresholds, and evidence-level claim gates as constraints for later tasks.

Adopt does not authorize implementation. In particular, it does not authorize:

- product-code changes;
- dependency installation, removal, or upgrade;
- schema changes or a migration;
- a concrete checkpointer or saver;
- real-provider calls, private-data transmission, or provider cost;
- real Vault/default database verification;
- high-risk whitelist or decision-expiry changes;
- destructive action tests;
- reranker enablement;
- L4 acceptance or publication.

Every item retains its later task boundary and Human Gate.

### Defer

Keep the proposal and evidence for later review. Do not treat the ADR as
approved and do not enter any implementation task whose dependency requires
TASK-1202 approval.

### Reject

Reject this architecture contract. Revert only the proposal and TASK-1202
status bookkeeping while preserving this decision record and verification
evidence. Do not touch pre-existing product changes.

## Coordinator recommendation

Adopt.

The proposal preserves the accepted fast path, FTS-first fallback, local privacy
boundary, deterministic action policy/executor assets, ledger, snapshots, and
sequential fallback. It corrects the current claim gaps without treating role
count as proof: model roles receive narrow typed contracts, deterministic code
retains permissions and side effects, citations require accepted evidence, and
quality claims require fixed metrics.

The hard foreground ceiling of two planning rounds, ten model calls, twelve
tool calls, 45 seconds, 32,000 aggregate input tokens, 8,000 aggregate output
tokens, and USD 0.10 estimated external cost is an upper safety bound. Default
enablement still requires the stricter p95, average cost, quality, and zero-
violation gates in the ADR.

## Exact authorization statement for Adopt

> Adopt the architecture, budgets, proposed checkpoint payload retention and
> deletion values, evaluation thresholds, and claim gates only. The checkpoint
> values become design constraints, not implementation authority. This decision
> does not authorize product-code changes, dependency installation, schema
> migration, real-provider calls, checkpointer selection, action-whitelist
> changes, real-Vault testing, L4 acceptance, or public release.

## Decision log

The user explicitly answered adopt. The Coordinator normalized it to Adopt
without expanding its authorization.

| Field | Value |
| --- | --- |
| Decision | Adopt |
| User wording | adopt |
| Recorded by | Coordinator |
| Recorded at | 2026-07-12 01:40:49 +08:00 |
| Resulting TASK-1202 state | Completed |
| Downstream implementation authorization | None |

## Rollback

- Adopt: no TASK-1202 rollback; later tasks still require their own permission.
- Defer: retain proposal and evidence, leave implementation blocked by the gate.
- Reject: revert only the ADR proposal and status bookkeeping; preserve this
  decision record.
