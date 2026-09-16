# Product Contract: Agent Pet

## Product identity

**Agent Pet** is a local personal **LLM Wiki and memory graph** for one Windows
user. The desktop pet is the entry point, not the product's only value. The
product value is a durable, reviewable record that can be reused in a later
conversation without hiding its source or silently keeping a mistake.

This is a local MVP. It is not a team knowledge base, an enterprise backend, a
cloud service, or a promise that a sleeping or powered-off PC is online.

## User problem

The product addresses a recurring workflow failure:

> A person explains the same project context repeatedly, cannot tell which
> model statements became long-term memory, and cannot safely correct or remove
> a wrong statement later.

Chat history alone does not provide a durable fact lifecycle. A plain notes
folder provides durable text but not a natural-language capture and evidence
review loop. Agent Pet connects those two surfaces while keeping deterministic
control over writes.

## Target users and non-users

| User | Job to be done | How they use the product | Explicit non-goal |
| --- | --- | --- | --- |
| Personal knowledge worker | Recover project context without repeating it | Chat, import a local source, review candidates, ask a cited question, correct or forget | No shared workspace or cross-device sync |
| Privacy-sensitive Windows user | Keep source material local and decide what leaves the machine | Bind an isolated Vault, enable local privacy mode for sensitive input, inspect evidence | Not an operating-system firewall; undetected ordinary messages may use the configured model |
| Internal single-employee pilot | Measure whether recall and correction reduce repeated explanation | Use a separate data directory for 7 days, record fixed-task baseline and anonymous feedback | No team rollout, employee surveillance, or general business claim |

## Core journey

```text
1. Start the local desktop app and configure a compatible model provider.
2. Chat or import a source; keep the original source immutable.
3. Extract typed candidates with evidence and a lifecycle status.
4. Confirm only low-risk, unambiguous candidates; isolate conflicts/sensitive data.
5. Bind entities and facts to a page-type-specific Wiki page and graph relation.
6. In a new conversation, retrieve one or two hops of authorized evidence.
7. Show citations and uncertainty; never answer from expired/forgotten evidence.
8. Correct, supersede, archive, or forget; verify the next recall uses the new state.
```

Every transition has a visible state and a user action. A candidate is not an
active fact; a graph edge is not proof; a Markdown page is not an authority for
permissions. A background suggestion is likewise not a memory: it waits in the
review queue, and accepting it is what writes one. Those distinctions are part
of the user experience.

## Why AI is necessary, and where it is forbidden

AI is useful for the parts that are genuinely linguistic and ambiguous:

- extracting an entity, preference, boundary, event, concept, source, page or
  decision from prose;
- proposing follow-up memory or organisation suggestions after a finished
  exchange — as review-queue proposals, never as writes: a suggestion is not a
  memory until the user accepts it;
- suggesting a match between an alias and an existing entity;
- planning a bounded evidence query from a natural-language question;
- synthesizing multiple cited facts into a readable page or answer.

The deterministic layer handles the parts where guessing would create damage:

- sensitive-content policy, authentication and confirmation;
- entity type/identity validation and controlled relation vocabulary;
- lifecycle transitions, recall permission, claim-before-effect, idempotency,
  authoritative read-back, receipt verification and rollback;
- Markdown path/hash checks, citation acceptance, Kuzu fallback and metrics
  aggregation.

Ordinary social chat may use a direct streaming model path. The evidence path is
deliberately bounded: when the orchestration graph is enabled, an Orchestrator
can dispatch at most one sequential read-only Retrieval Agent per round, then a
Synthesizer writes the single natural-language response. The graph is opt-in
(`use_negotiation`, off by default); the default path is the simple runtime
graph with the deterministic action planner, which never lets the model write
more than one response. This is a control decision, not a claim of autonomous
model governance.

The current lifecycle gate covers the primary task, post-reply memory/Wiki paths
and memory feedback. Profile actions, hygiene actions, retrospective reports and
continuity proposal creation still contain direct domain writes outside the
coordinator; the product must keep those paths marked `Partial` until they are
independently wrapped and recovered.

## Value hypothesis and measurement

The product is intended to improve three observable tasks, not to maximize
model calls:

1. **Context recovery**: time and turns needed to answer a fixed project
   question in a new session.
2. **Memory trust**: proportion of recalled facts with valid sources and the
   rate at which an incorrect fact is corrected and no longer recalled.
3. **Rework avoidance**: explicit user reports of repeated explanations and
   duplicate local actions.

The local metrics contract stores only event types, hashes, safe dimensions and
counts. It exposes numerators, denominators, sample size and evidence status;
it does not store raw chat text or secrets. Internal evaluation runners and
their generated reports are not part of the production source tree. Product
claims must be derived from a separately reviewed measurement run.
No business uplift is claimed until a preregistered 7-day single-user trial is
complete; broader claims require a separate multi-user study.

## Operational meaning of “24 hours”

For this desktop product, a 24-hour run tests resident process behavior:

- login-state startup and bounded sidecar restart;
- overdue reminder catch-up after a restart;
- action claim/receipt recovery without a duplicate local effect;
- memory/handle/backlog growth and Kuzu generation lag.

It does not mean the PC remains online during sleep or shutdown, and it does
not provide a hosted availability SLA. The current repository has a 20-cycle
packaged sidecar smoke, but no real 24-hour sample series. The status remains
`Partial` until that time-based evidence is recorded.

## Failure contract

| Failure state | Product response | User next action |
| --- | --- | --- |
| No evidence | Explain that no authorized source was found; return no confident fact | Add/import a source or ask a narrower question |
| Model offline or invalid output | Keep local data intact; mark the run/candidate failed with a stable code | Browse FTS/Wiki locally or retry the read-only step |
| Conflicting facts/entities | Keep both evidence chains isolated; block deterministic answer context | Choose the entity or correct one claim |
| Markdown conflict | Stop the page write and preserve the current file plus its hash: memory proposals and Wiki pages both compare the preview hash before writing | Inspect diff, retry with the latest revision, or abandon |
| Effect before receipt | Read the target by stable idempotency key; replay the receipt if uniquely verified | Wait for recovery or open manual review; never press a blind repeat button |
| Kuzu unavailable | Use the SQLite authority and show degraded projection status | Continue working and rebuild the projection later |
| Sidecar/notification failure | Persist the task; show recovery or display-unknown, not success | Restart/retry manually; check Windows permission |
| Sensitive content | Do not activate or project it into ordinary recall | Redact and store locally, or discard |

Unknown state is an explicit state. A visible activity row is not proof that an
OS notification was delivered, and a model-generated summary is not proof that
the underlying fact is true.

## Technology decisions

| Technology | Why it is here | Current boundary |
| --- | --- | --- |
| Electron | Windows tray, startup, notification and sidecar lifecycle with a preload trust boundary | Windows local MVP only |
| React/TypeScript + `@xyflow/react` | Typed desktop workspace and graph/evidence interaction | Visual and DPI gates are separate evidence |
| FastAPI/Pydantic/Uvicorn | Local API, validation and observable sidecar health | Not a cloud/high-concurrency service |
| LangChain/LangGraph | Provider/tool adaptation and bounded stateful orchestration | No unlimited or parallel agent swarm |
| SQLite | Authority for graph state, lifecycle, claims/receipts and metrics | Single-user local store |
| Markdown Vault | Immutable sources and portable Wiki body | External edits require hash reconciliation |
| FTS5 | Default deterministic retrieval/fallback | Lexical, not semantic proof |
| Kuzu | Rebuildable graph traversal projection | Never the authority; fallback is visible |
| Qdrant | Embedded local vector index for hybrid retrieval; a Qdrant server is not wired | The embedded client is the default vector backend whenever the bundled model is present; server mode is a separate, unshipped experiment |
| APScheduler/SQLAlchemy | Persisted reminders and recovery catch-up | Sleep/shutdown are offline |
| SSE | Streaming progress/citation/action status | Does not guarantee correctness |

## Release boundary

The current release is suitable for isolated local evaluation and a controlled
single-user MVP trial. It is not suitable for claims of enterprise tenancy,
generalized business uplift, hosted 24-hour availability, or universal answer
accuracy. The frozen audit baseline is `57/100`; the strict evidence score on
2026-08-11 is `62/100`. Three isolated L3 journeys passed on 2026-08-14, but
they have not yet received an independent whole-tier rescore, and required
Windows/L4/time gates remain Partial. A score above `84` requires real 24-hour
and 7-day evidence first.

## Design requirements

- The memory page uses `图谱 / 时间线 / 来源 / 维护`; desktop defaults to graph
  and a viewport of 600px or narrower defaults to timeline.
- Selecting a relation opens an evidence rail in this order: entity, relation,
  original source, Wiki page, lifecycle and correction record.
- Empty, no-evidence, offline, conflict, degraded and recovery states each have
  a concrete action; no decorative or non-functional button is acceptable.
- Keyboard focus, contrast, wrapping, reduced motion and 390/1280/1366/1920
  viewports are checked separately from typecheck/build.
