# LLM Wiki Reconstruction Status

This file tracks implementation against the approved T0-T7 roadmap. It is
not a release acceptance certificate. Do not enable more aggressive automatic
compilation on the strength of the lifecycle tests below.

## Implemented Safety Slice

- A shared lifecycle policy is used by retrieval evidence compression, the
  chat context filter, the prompt memory assembler, and memory permission
  section assembly (including style hints).
- Editable Wiki frontmatter, including `sources`, cannot authorize a page.
  New external pages are quarantined; changed reviewed pages become stale.
- Reconciliation preserves forgotten bindings and invalidates bindings when
  the entire Wiki directory is removed, not only when one page disappears.
- Binding creation and updates cannot promote a forgotten page. Checks run
  inside the existing short SQLite write transaction.
- FTS and vector candidate hydration check the Wiki binding, indexed page
  hash, and editable file hash. Cache hits recheck Wiki authority. Graph source
  revision participates in the retrieval cache key.
- Development and sidecar build defaults use the backend `.venv`; an explicit
  `AGENT_PET_PYTHON` override is still supported.
- `requirements-win-py310.lock` pins the Windows/Python 3.10 dependency set,
  including build tools and test/vector/packaging dependencies. Local editable
  installation with `--no-deps --no-build-isolation` has been exercised.
- Archive lint, planning, writing, and receipt verification restore document
  citations through the existing retrieval service, scoped to the current
  vault and exact note/chunk/path/hash. The service rebuilds descriptions and
  permission fields, checks the editable source hash and sensitive-content
  policy, and reuses the configured candidate filter. It does not search for
  a plausible replacement when an identity/version fails.
- The runtime adapter persists normalized citations in action parameters;
  source authority is checked again during execution and receipt reads.
  Forged API references receive the existing 422 rejection contract.
- New query reports remain quarantined. Existing pages typed as `report`
  cannot enter factual retrieval solely on an active binding. Reports remain
  accessible in archive history. Verified references are explicitly distinct
  from a verified answer; no semantic truth assessment is claimed.
- Ingest confirmation no longer overwrites an existing source on a body-hash
  match. Source type, URI, body and non-compiler metadata must match; conflicting
  inputs are rejected without persisting a new run. A short `BEGIN IMMEDIATE`
  transaction serializes the comparison and insertion.
- Review and apply validate each persisted request against its source record,
  then use that request's title, content and source attributes. Malformed
  requests or missing recorded identity fields fail closed rather than acquiring
  default provenance. Run-specific compiler output does not rewrite source
  identity. Identical inputs retain the same source ID.
- Migration `030_wiki_source_vault_scope` adds a nullable source-to-vault foreign
  key. New confirmations assign it on the server in the source transaction.
  Historical rows remain unassigned; no active-vault inference or content-based
  ownership migration occurs.
- Ingest preview lookup, confirmation, review (including cached results), apply,
  and receipt readers check vault scope. Runtime review/apply check before and
  after action execution, so a terminal cached action cannot bypass the gate
  after switching vaults. Existing run/review IDs cannot be reassigned to
  another run or source identity.
- Memory closure checks source scope before preparing entities and on final
  source readback. Synthesis resolves raw roots within the same vault and only
  includes evidence associated with that source through evidence/candidate
  metadata. A matching text hash alone cannot import unrelated evidence.
  Synthesis source paths reuse `SafeMarkdownWriter` containment checks.
- The shared evidence policy defines the six provenance kinds and classifies
  existing ingress labels, with unknown labels failing closed for independent
  fact compilation. This is a classifier, not a complete persisted provenance
  ontology, truth assessment or permission decision.
- Agent ingest always records `assistant_output`, ignoring model-supplied
  origin labels such as `manual` and `user_message`. Preview, confirmation
  storage and review remain available. Without independently resolved roots,
  derived/unknown inputs cannot compile, apply, activate memory closure, or
  pass application receipt validation. Ordinary supported import labels and
  existing explicit-user memory extraction continue through their old workflow.
- Source readback and synthesis root resolution recheck stored source nature.
  Source-provenance candidates record the classified kind in existing metadata;
  client `verified` or `provenance_kind` metadata cannot override the gate.
- New automatic answer summaries are unverified reports, not source pages.
  Their text distinguishes conversation traceability from factual evidence.
  The reserved summaries directory (including old source-typed summaries)
  and report pages are excluded from factual retrieval and compilation evidence.
  Report paths are excluded even before their index is refreshed. Maintenance
  snapshot reads remain available to inspect these pages.
- File imports preserve identifiable exported Wiki/report provenance instead
  of relabeling it `file`. Folder imports containing identifiable derived pages
  are conservatively classified as derived as a whole. These can be previewed
  and stored but cannot become independent factual roots. The classifier uses
  existing Wiki identity metadata, report type and the reserved summary path;
  it cannot detect generated text with its identity deliberately removed.
- The packaged Wiki schema now classifies companion summaries as reports.
  A scoped `.gitignore` exception makes that canonical application resource
  eligible for version control; other `AGENTS.md` files remain ignored.
- New Wiki source entities and provenance candidates use source IDs as identity
  keys. Legacy hash-keyed records are reused only when recorded identity agrees;
  missing or conflicting attribution fails closed. Global source-hash uniqueness
  is still present, so distinct same-body source storage is NOT yet supported.
- Extraction candidate replay matches source ID as well as content hash.
  New extraction evidence IDs include source identity; extraction returns the
  exact evidence IDs produced. Legacy evidence IDs are reused only with matching
  recorded source ID/hash. Unknown legacy attribution stops replay instead of
  creating extra support.
- Wiki provenance annotation updates only evidence produced by the current
  extraction/binding, preserving other evidence attached to the same fact.
  A different existing fact-level attribution is preserved. Source-specific
  grounding requires an evidence row with the source ID/hash, not a body-hash
  match or fact metadata alone.
- Wiki source candidate creation disables the existing candidate upsert's
  reactivation behavior. Preparation rejects inactive source entities/candidates;
  finalization rechecks candidate lifecycle and entity identity inside the graph
  write transaction. Other candidate callers retain existing semantics.
- Synthesis resolves a source page through its active `documented_in` relation
  to an explicit source ID, not by looking up a hash copied into Markdown.
  It rechecks vault scope, source entity status/hash, stored original body,
  provenance kind and the root candidate identity/lifecycle. Multiple root
  bindings on one source page fail closed. An optional legacy body-hash marker
  must agree with the resolved source but cannot select it.
- Model-compiled source pages without a literal body-hash marker can now enter
  synthesis without recursing into their self-link. Synthesis evidence lookup
  uses the resolved source ID and excludes inactive candidate evidence.
  Root independence is still conservatively counted by distinct body hashes;
  this change does not claim independent authorship from different IDs.
- Compiler evidence reads now reuse the shared page gate with an explicit
  database/vault scope. A captured normalized body must match an active reviewed
  binding and the working copy. Direct reads do not require a completed search
  index; search callers retain their indexed-hash requirement.
- Compiler catalog entries come from reviewed bindings and validated page
  metadata, not editable `index.md` summaries or unbound filesystem titles.
  Invalid candidates are excluded before model selection. Selected context and
  catalog batches are rechecked around model calls, and ingest context is
  rechecked at confirmation and apply. Synthesis checks its source snapshots
  and existing target; a forgotten target cannot be rewritten by synthesis.
- Compiler snapshots retain exact byte hashes for write-conflict checks while
  normalizing BOM/newlines consistently with reviewed Markdown hashes. Reviewed
  pages remain readable while asynchronous indexing is pending. These checks
  do not implement the complete transitive root permission/expiry model.
- Compiler reads also reuse the synthesis root resolver to validate current
  dependencies: source ID/body/hash/vault, source entity and candidate lifecycle,
  provenance nature, parent bindings and dependency cycles. These checks run
  again through existing compiler pre/post-model and confirmation/apply gates.
  An active page binding cannot hide a forgotten or altered root.
- Root-only validation skips graph fact collection and graph construction, so
  reading compiler evidence cannot trigger legacy graph backfill. Synthesis
  retains its existing fact collection. `message:` entries in `sources` are
  trace references, never factual roots; a page with only these traces fails
  closed. Reviewed pages without resolvable roots are excluded from compilation.

The hash check is not immutable publication. It detects edits at the time of
each check; compiler rechecks can reject a result after a mid-call edit or
binding invalidation, but cannot retract content already sent to a model.
There is still a race between a successful check and a later read/write.
It also does not prove the truth of a claim or establish root provenance.
Ordinary notes retain their existing retrieval behavior. Existing Wiki pages
without a reviewed binding are deliberately excluded from factual retrieval;
indexing or adding frontmatter alone cannot migrate them to trusted status.

## T2 Ingest Publication

Migration 031 and `WikiGenerationStore` add per-vault staged manifests, shared
byte-hashed bodies, and an active generation pointer to the existing SQLite
database. Unchanged bodies are shared; only manifest references are copied.
Staging does not modify published manifests or editable Markdown. Promotion
uses the existing connection/transaction infrastructure, compares the base
generation, checks body integrity, invokes a required synchronous validation
callback, and commits pointer/status updates in one short transaction.
An explicit published generation can be read independently of a later head.
There is no history cleanup yet, so readers cannot lose bodies to this store.

Migration 032 adds per-page dependency records and a unique ingest-workflow
association. Successful ingest now captures verified written artifacts and their
transitive Wiki source pages through the existing compiler/root validators.
Each captured page records normalized dependency hashes, root entity IDs and a
fingerprint of the authoritative source/entity/candidate/binding/relation rows.
The generation store shares unchanged bodies and carries forward existing
manifest/dependency rows. Publication checks dependency presence, snapshot
version agreement and current database authority within its pointer transaction.
It does not read editable files or call a model in that validation callback.

The ingest workflow records pending/blocked/failed publication separately from
its existing working-copy apply result. A successful publication receipt, version
status and active pointer commit together. A saved staged generation can be
retried with `WikiPublicationService.publish_ingest` without rewriting Markdown;
already-published retries revalidate dependencies and reuse the generation.
No automatic recovery scheduler is registered yet. A changed base or invalid
dependency remains blocked; there is no automatic rebasing or authority upgrade.

This is a POST-APPLY SNAPSHOT INTEGRATION, not complete staged compilation.
The existing workflow still writes working files and bindings before snapshot
publication. An `applied` ingest response describes that existing operation,
not a promise that publication succeeded; publication details currently live
in the durable workflow result, not a new client field. Failed publication
does not roll back those files. The first manifest includes only the successful
ingest and its verified dependencies, not an implicit migration of the entire
legacy library. Old manifest pages without dependency records fail closed.

Chat and existing page-list/index reads have NOT switched to generations. Synthesis,
archive and direct editing do not yet publish versions. Retaining the old head
after revocation never grants permission to use its content as facts. Complete
live permission/expiry checks, projection fallback/migration, read leases,
compiler draft writes, working-copy sync, tombstones and safe retention remain
required before answering from snapshots. Root fingerprints are conservative
change detectors, not a full provenance/version ontology or semantic proof.

## T2 Pinned Search And Reading

Migration 033 adds shared body-hash-keyed SQLite FTS5 projections and per-generation
resolved link edges/readiness records. Staging builds projections from snapshot
bodies, reusing the existing CJK bigram tokenizer, escaped FTS query expansion,
Markdown chunks and graph link resolver. Unchanged bodies reuse their keyword
projection. Ambiguous title/slug aliases are not arbitrarily linked. Promotion
checks manifest/projection counts and missing FTS chunks before moving the head.
Older generations without readiness records are deliberately unavailable through
this reader until explicitly migrated; no mixed-version fallback is used.

`WikiSnapshotReader` provides internal pin/search/read primitives. A pin binds
both vault and published generation. Search joins its body projection through
that exact manifest, groups candidates by page and hydrates snippets from the
verified snapshot, not FTS text. Full-page and heading reads return version,
body-relative line locations, resolved outlinks and backlinks. Over-budget reads
raise an explicit error rather than silently truncating. Page and transitive
dependency access require a caller-supplied synchronous policy returning literal
True; current dependency stamps are checked before returning data. Links to
inaccessible pages are withheld. The editable working directory is not read.

The reader is exposed through the read-only page API and registered Agent tools
described below, but is NOT enabled in default chat routing. It deliberately rejects
changed dependency stamps, including otherwise valid older page revisions; full
old-version availability across reviewed updates needs versioned authority beyond
the current binding model. The query-node slice below adds model/send-boundary
revalidation, but no complete source expiry model, read lease/GC, relevance
evaluation or full Evidence Gate is implied. Candidate scans are bounded and
can underfill after filtering.
Vector/Kuzu projections are not used; missing keyword projections currently
fail closed rather than doing same-version brute-force fallback.

## T4 Read-Only Page API

`POST /api/wiki/pages/read` now exposes the existing pinned snapshot reader
under the application's normal session authentication. Input is a library-relative
path, optional generation/expected version, optional heading, and a 1-32000 character
budget (default 12000). It returns the snapshot generation/hash, title/body,
body-relative start/end lines, and authorized links/backlinks. The request
cannot select a different vault or open arbitrary filesystem paths.
Unknown/inaccessible snapshots use the same generic 403 contract; an expected
version mismatch uses 409, and section/budget errors use 422 without body content.
Read audits store only path/status or a bounded error code, not snapshot text.

The runtime dependency checks the current active vault and reuses compiler
evidence/root/sensitive-content validation. If a custom retrieval candidate
filter is installed, the whole page must have a matching indexed version and
every indexed chunk must pass that filter with its actual identity and content.
Missing/stale indexes and denied chunks fail closed. Parent pages are subject
to the same checks through the reader's authorization callback. This conservative
adapter intentionally also rejects unverified external edits; it does not claim
fully available historical reads across current working-copy changes.

OpenAPI, generated TypeScript types and the renderer proxy route artifact include
the endpoint. No UI page or chat routing behavior changed. Responses
do not yet expose full root-source/provenance objects or independent Evidence Gate
statuses; snapshot identity and successful access do not prove semantic truth.

## T4 Read-Only Agent Tools

`search_wiki_pages` and `read_wiki_page` are registered StructuredTools with
strict input schemas, existing timeout handling and typed observer results.
Search results explicitly have navigation-only status. Read inputs reuse the
API's path/version/section/budget contract; no vault selector, approval flag or
write operation is accepted. Tool descriptions classify document text as
untrusted content, not executable instructions or permission grants.

`RuntimeWikiReadAdapter` reuses the page API's actual reader factory and access
policy, runs synchronous reads in the existing thread-pool pattern, and pins
the first active generation per adapter instance. A lock serializes initial
pin selection. A supplied generation can only match that pin; a head switch
cannot repin the ongoing tool sequence. The adapter is injected into runtime
services and propagated into observed toolsets.

These tools are NOT in the default chat/retrieval allowlist yet. The independently
callable query node below adds citation transport and model/send revalidation;
default routing, checkpoint pin persistence and rollout are still required.
Adapter lifetime currently matches the runtime
instance; cancellation stops awaiting a read but does not forcibly kill its
read-only worker thread. No write authorization or automatic archive behavior
was expanded.

## T4 Query Node And Snapshot Citations

`wiki_knowledge_retrieval_node` composes the registered search/read tools into
candidate discovery, heading reads and existing citation events. Personal-only
source scope and local privacy restrictions prevent Wiki reads. Citations carry
generation, body hash, section and body-relative line locations through the
existing `MemorySearchResult` schema; its new optional fields are reflected in
OpenAPI and desktop generated contracts.

The node uses a 30-second reading/assessment deadline, a 12000-character context
budget and a bounded 24-candidate scan. It initially reads up to eight candidates;
subsequent reads are selected by the existing retrieval model from known
candidates and authorized outlinks/backlinks, with at most two hops and three
rounds. Eight is not a cumulative page limit. Diagnostics distinguish retrieved
and read pages, consumed characters and stop reason. Reading remains additive;
context replacement, deep mode and model-context-aware budget sizing are pending.

Snapshot citations are re-read and compared before citation events, before
model use and before sending the generated answer. Mixed generations, changed
authority, forged text or mismatched locations fail closed. Model-time root
revocation prevents sending the generated answer; already emitted citation
events cannot be recalled. The legacy archive restorer explicitly rejects
snapshot citations until a generation-aware archive adapter is available.

`WikiEvidenceGate` keeps authority, freshness, coverage, conflicts and budget as
independent typed fields in AgentState. Coverage/conflict judgments use strict
model output with subquestions, reasons and exact citation quotes. Quotes must
match accepted read content; model-selected paths must belong to the runtime
candidate/link set. The model cannot set authority or freshness. Missing models,
invalid output and unknown coverage do not produce a sufficiency claim.
Even valid quoted judgments remain fallible model assessments, not truth proofs.
Freshness is explicitly unknown until the new-source relevance watermark exists.
Conflicts and budget exhaustion can coexist.

Answer generation receives runtime gate limitations and untrusted advisory
subquestions/conflicts. It records the citations actually included by the
existing prompt assembler; missing assessed evidence downgrades coverage.
Model-produced advisory text is not inserted as trusted system instructions.
Gate state is internal AgentState data, not yet a public SSE/UI contract.

This node is independently callable for evaluation, NOT wired into default
retrieval routing. Indexed-note fallback is described below; database-only raw
sources, relevance-check watermarks, context replacement, full model budgets, checkpoint
pins, shadow execution and rollout remain outstanding.

## T4 Indexed-Note Fallback

The query node supplements insufficient, disputed or freshness-unknown Wiki
reads using the existing hybrid retrieval service restricted to `vault_note`.
The internal restriction has a separate cache key and never changes public
search scope defaults. Candidate restoration reuses vault/note/chunk/hash,
current file, lifecycle, sensitive-content and custom permission checks.
Wiki working-copy paths and identifiable exported derived documents are excluded.
The import adapter and fallback share the existing derived-document classifier;
it cannot identify model-generated text with its identity removed.

The runtime adapter pins the active vault on first fallback use and rejects a
later vault switch. It restores complete indexed chunks, not search snippets.
New references have a dedicated fallback retrieval mode; all existing Wiki
pre-model/send rechecks now also restore these references and compare identity
and exact text. Changes or revocations prevent sending the generated answer.
Search-stage denied candidates are filtered individually; a previously selected
reference failing subsequent restoration rejects that answer.

Fallback shares the remaining reading time and character budget. Whole chunks
that do not fit are reported as unread, not truncated. New notes invalidate a
prior coverage-complete assessment; known disputes remain and freshness stays
unknown. No compilation, archive or write is scheduled by this path.
After successful note supplementation, a final combined assessment reuses the
existing retrieval model, strict schema and exact-quote checks. It shares the
three-call assessment ceiling and 30-second reading deadline with Wiki reading;
exhaustion skips the assessment rather than starting an extra budget. Both Wiki
and note references are revalidated before and after this model call. Revocation
rejects citation emission, not merely the semantic result.

The combined input identifies retrieval mode, snapshot generation and content
hash without labeling ordinary notes as raw roots. Previous subquestions must
remain verbatim; previous disputes are retained even when omitted by the model.
Dispute resolution still requires a separate reviewed process. The final model
cannot request additional reads. Invalid output leaves coverage unassessed;
successful output remains a fallible semantic judgment and never changes
freshness from unknown.

Current limitations: missing Wiki reader/publication or a Wiki authority failure
does not start fallback; database-only raw sources are not searched; authoritative
raw-source provenance remains pending. Ordinary note access is not a declaration
that its claims are true. No real-model quality acceptance is claimed.

## T4 Source Observation Watermark

Publication capture stores a versioned corpus digest inside existing per-page
dependency JSON, without new tables or copied raw bodies. The digest covers
vault-scoped source identity/hash/type/update metadata and ordinary-note
identity/path/hash/status. Personal memory, Wiki working copies and foreign
vault notes are excluded from the note component. It detects insertions even
when timestamps coincide; it is not a timestamp maximum.

Snapshot observations recheck page authorization and read corpus metadata in a
short database transaction. Outcomes are baseline unknown, changed since capture,
or unchanged since capture. Old manifests without a baseline remain unknown;
unchanged pages carried into a newer generation retain their original baseline.
The runtime keeps the first observation for the query and checks again through
the existing pre-model/send validation path. A corpus change during the query
rejects the pending answer, even if its old root bindings still validate.
Model-visible state contains the observation status, not source identities,
paths or corpus digest.

This is a conservative database observation, NOT completed semantic freshness.
The baseline is taken before post-apply snapshot capture, not before compilation.
All freshness states remain unknown until relevance/coverage checks exist.
Unrelated same-vault changes may reject a query; raw-body edits without updated
version metadata, unindexed files and external filesystem changes are not
completely observed by this digest. Existing evidence checks remain necessary.
There is no automatic retry/recompile, persistent change queue, entity/topic
delta selection or public UI/API exposure. Corpus metadata scanning is linear
in the vault catalog; large-library performance has not been measured.

## T3 Read Intent And Write Boundary

The explicit-source matcher no longer treats a Wiki/knowledge-base/document
topic plus a question mark as a mandatory local search. It requires a local
source reference or search/location constraint. General technical questions
defer to semantic classification rather than requiring local evidence in the
offline route. Explicit project questions remain knowledge-scoped. Explicit
multi-source reads preserve their requested primary scopes through the existing
aggregation path; a personal-memory query is handled before memory-write patterns.

The foreground chat tool allowlist now contains only search and time tools,
independent of automatic Wiki organization settings. Wiki mutation uses the
existing action/proposal/policy path; this does not disable the separately
authorized post-reply pipeline. Narrow Wiki write-explanation/negation guards
also prevent those recognized phrases from becoming Wiki action commands via
the deterministic route or parsed classifier result.

This is not complete natural-language authorization. Source/negation patterns
remain conservative heuristics, the high-risk mutation branch and other action
types retain their existing policies, and semantic classification is fallible.
Explicit source sets now also reach the existing search tool wrapper in chat
and model-driven retrieval. `all` expands only into those named scopes; an
out-of-set narrow request fails before invoking retrieval. An empty explicit
set is invalid, not unrestricted. Responses reuse evidence filtering and are
deduplicated by scope/note/chunk. The text-tool compatibility fallback uses the
same wrapper rather than calling search with its default `all`.

Requests without an explicit set retain prior semantic scope behavior. This
change constrains calls, not backend source-label correctness or every alternate
retrieval entrypoint. Per-source top_k is retained during fan-out; it is not a
single global result budget. Live-model routing evaluation remains pending.
Default retrieval still uses the old query
path; the independently evaluated snapshot reader is not enabled by this change.

## T3 Answer Basis Contract

AgentState and terminal `done`/`reply_ready` SSE events carry an additive
`answer_basis` field: not_assessed, general_unverified, local_evidence_context,
insufficient_local_evidence or validation_failed. Default/legacy and streaming
paths without a completed grounding assessment remain not_assessed.
The label describes grounding availability, never factual verification.

The assembled-answer path uses the actual prompt evidence set, not merely
retrieved citations, to set local_evidence_context. Citation labels absent from
that set now fail validation. Grounding validation also uses the actual set.
Required local facts without evidence return the existing insufficiency response
before model invocation. Generic no-evidence validated responses are marked
general_unverified; tool-only and unassessed replies are not upgraded.

Migration 034 adds a conservative not_assessed default to message history
without promoting historical answers. Terminal persistence commits body,
status and normalized basis together; incomplete/failed statuses cannot retain
a local-evidence label. History reads also normalize unknown values and limit
assessed labels to completed assistant messages.

The renderer consumes terminal-event labels and restores them through daily
history. The existing answer-details summary and citation section display the
basis, including answers with no citations. A historical local-evidence label
describes context at generation time, not current source validity or factual
verification; missing historical citation details are stated explicitly.
Unknown and omitted values remain not_assessed. The renderer union reuses the
generated daily-history HTTP schema; SSE models themselves remain outside the
OpenAPI export. Streaming assessment and historical citation restoration are
not implemented by this slice.

## T7 Read-Only Shadow Evaluation Foundation

`services/wiki/shadow.py` provides an independently callable evaluator around
the existing Wiki query node. Chat now uses one app-owned runtime coordinator
with a saved opt-in checkbox in the existing automation settings panel. Its busy guard skips
overlapping calls rather than retaining a queue of user questions.

Admission requires explicit live opt-in, a knowledge-only semantic scope,
compatible explicit source constraints, no action plan, no local privacy flag,
and no suppressed post-reply retention. Stable run-ID hashing selects about
10%; run IDs and question hashes are not stored. The caller must provide a live
permission/foreground-idle predicate, rechecked around reads and model calls.
Permission loss cannot retract already submitted model input.

Evaluation builds fresh state without foreground answers, citations, personal
context or actions. It runs retrieval/assessment only, not the chat/archival or
action graph. Narrow wrappers expose page reads, note fallback and the configured
retrieval model; the original state is unchanged. The existing query budgets
remain, plus an outer 35-second timeout. This is not an OS-level read-only sandbox.

The existing SQLite `app_state` stores at most 20 reservations per UTC day,
including failed/interrupted attempts, across reopen. Random sample IDs are
unrelated to conversation IDs. An allowlisted metrics schema stores counts,
latency and independent Gate states, never questions, answers, paths, generation
IDs, quotations, exception text or model assessment reasons. Correctness stays
unknown; unavailable token usage stays null rather than being inferred from
character counts. No telemetry exporter is added.

Records older than seven days are pruned on store operations, startup, and the
existing 60-second chat-run cleanup loop. Cleanup runs off the event loop and
does not depend on Shadow being enabled. Failures produce a fixed warning
without exception data; later cleanup cycles retry. Logical record expiry does
not claim secure erasure of SQLite free pages or external backups.

The existing automation GET/PUT API persists `wiki_shadow_enabled` in app_state,
default false. Only JSON booleans are accepted; malformed/non-boolean persisted
values fail closed. An older client omitting the field preserves the saved
choice. Explicit false disables the saved opt-in. OpenAPI and generated desktop
contracts carry the additive field. The settings panel saves explicit booleans
through the existing settings hook and states sampling, additional configured
model calls, privacy pause and local retention. No automatic opt-in is added.

The authenticated settings-status response now includes a read-only seven-day
aggregate, never sample IDs, timestamps, paths, questions or model output.
Expired/future entries are excluded; invalid records are counted separately,
and an unreadable store reports unavailable rather than a fabricated zero.
Reading the aggregate does not prune or modify stored records. The UI labels
the scope as all local vaults, distinguishes completed/failed/interrupted/
unfinished reservations, and exposes coverage/conflict/budget counters.
Model calls, evidence characters and mean latency are explicitly limited to
completed samples. Tokens remain unrecorded and correctness unreviewed.

After a successful, fully finalized SSE response, the runtime coordinator offers
the actual terminal AgentState to the sampler. The runtime explicitly exposes
terminal state for both cloned streaming and graph/negotiation paths; the initial
HTTP state is not assumed to contain final routing or privacy decisions. Errors
and interrupted stream consumption do not submit a candidate. Only a minimal
query/semantic copy and numeric baseline citation count cross into background
evaluation; foreground answers and citations are not copied or persisted.

Active streams and pending unclaimed chats block new evaluations. New streams
and mutating HTTP requests preempt an existing evaluation. There is no queue or
restart replay of user questions. Live checks require the same vault/model
configuration, enabled opt-in, disabled privacy mode and idle foreground.
Only page/note readers and the configured retrieval model are constructed:
no action lifecycle, memory writer, archive workflow or chat model graph is
created for Shadow. Shutdown cancels and awaits the owned coroutine.

Preemption is cooperative cancellation, not an OS/resource priority guarantee.
An already running worker thread or remote model request may continue after its
awaiting task is cancelled; already submitted input cannot be retracted.
Cross-process exclusivity, shadow answer generation/comparison,
additional metrics and canary query rollout remain pending. The foreground
query path is unchanged; opt-in evaluates retrieval/Gate behavior only.

## Remaining Release Gates

| Task | Still Required |
| --- | --- |
| T0 | Fresh-environment reproduction, fixed labeled evaluation set, sidecar build verification, live model baseline |
| T1 | Complete persisted provenance/author/verification/permission model and dependency versions; root identity and cycle checks; non-document evidence restoration; all entrypoints and pre-model/pre-publish rechecks |
| T2 | Replace post-apply capture with compiler draft publication; wire other write entrypoints and pinned reader to runtime; complete versioned authority, projection fallback/migration, working-copy conflict handling, process-crash recovery, leases and safe retention |
| T3 | Cover streaming assessment; audit alternate retrieval scope entrypoints; evaluate semantic routing and action negation coverage; integrate validated snapshot query rollout |
| T4 | Extend page-read evidence payload; default query integration, checkpoint pins and database-only raw fallback; source relevance/coverage watermarks beyond corpus observation, adaptive context replacement/deep mode, gate SSE/UI exposure; snapshot-aware archive adapter |
| T5 | Role-aware chat adapter independent of diary; source-grounded compilation; page-shape review; all writes through publication |
| T6 | Durable incremental maintenance and repair state machine; invalidation propagation; bounded batches |
| T7 | Shadow answer comparison and missing metrics, cross-process exclusivity, manual rollout stages, legacy migration and remaining review UI integration |

Archive restoration currently supports indexed Markdown citations, not graph
fact IDs or diary-object IDs without indexed note/chunk identity. Those inputs
fail closed rather than being relabeled as raw documents. Missing hashes are
also rejected: old clients retain the response shape but not an implicit
authority upgrade. Full typed provenance, raw-source identity/permissions,
root deduplication and versioned dependencies remain P0 work. The report,
summary and Agent-ingest gates do not authenticate arbitrary pasted text or
identify every generated document. Manual ingress labels are not proof of
authorship; user statements are not proof of external facts. Enforcing that
distinction at claim level and through every graph/prompt surface is unfinished.
Derived inputs with valid roots still need a role-aware adapter that resolves
those roots rather than bypassing the independent-source gate.
Editable-file checks do not supply T2 atomic publication or eliminate races
between validation and filesystem writes.

The existing global `wiki_sources.source_hash` uniqueness constraint is still
present. Different origins or vaults with identical content are rejected, NOT
stored as independent source identities. The next identity migration must update
remaining hash-based page/relation evidence IDs, source artifact paths and
synthesis lookups together with the source schema. New source entity/candidate
keys and extraction evidence are ID-scoped, but that alone is insufficient.
Removing uniqueness alone would make remaining lookups ambiguous.
Historical sources without vault scope and requests that lack recorded identity
fields need explicit migration/review, not silent reconstruction. The workflow
scope checks do not establish complete root permissions throughout ordinary
retrieval, compiler related-page reads, all graph recall paths, or historical
active page bindings; those remain T1 release gates.

## Verification

2026-09-19 Shadow settings UI/summary slice: two new backend cases passed in
6.30 seconds, covering read-only aggregation, expiry, authentication, invalid
records and private-data exclusion. TypeScript no-emit checking passed.
OpenAPI/desktop contracts were regenerated. A temporary browser fixture used
the real AutomationSettingsCard and useSettings hook with a fake API: saving
on/off produced boolean true/false requests. Component screenshots were checked
at 390x844 and 1280x900; the narrow document width remained 390px. This was
component-level CSS/interaction verification, not the full Electron shell or a
real vault/model test. Temporary fixture files were removed. No prior backend
suites or broad regression ran.

2026-09-19 Shadow runtime slice: five new focused cases passed in 2.87 seconds,
then one new HTTP/SSE integration case passed in 5.30 seconds. Coverage includes
minimal-state scheduling, pending foreground exclusion, cancellation/shutdown,
live opt-in/privacy/vault/model revocation, clean-success-only stream handoff,
and actual terminal-state export for fast and graph paths. The HTTP case uses
fake runtime/model evaluation but real app lifecycle, settings and SSE wiring.
No prior suites, broad regression or live-model calls ran. Public schemas did
not change.

2026-09-19 Shadow settings/retention slice: three new focused cases passed in
6.72 seconds. A real app lifecycle/API case checks startup expiry, default-off,
explicit opt-in/out, legacy omission and HTTP rejection of a string boolean.
Other cases cover reopen, corrupt persisted settings and cleanup-loop retry
without private exception logging. OpenAPI/desktop contracts were regenerated.
No earlier query tests, broad regression or live-model calls ran.

2026-09-19 Shadow foundation slice: four new focused cases passed in 4.16 seconds.
Coverage includes opt-in/privacy/scope rejection, persisted daily quota and
seven-day pruning, real snapshot query isolation and metric redaction, and
busy/revoked execution. No previous tests, broad regression, frontend build or
live-model evaluation ran. Runtime scheduling and multi-process safety are not
covered or enabled.

2026-09-19 answer-basis history/display slice: three directly related cases
passed in 2.88 seconds: pre-034 migration/body preservation and rerun,
terminal-write/history roundtrip, and failed/unknown-value downgrade. Desktop
TypeScript checking and generated HTTP contract checking passed. Existing
persistence test wrappers accept the additive optional argument; those older
suites were not rerun. No broad regression, browser layout validation or
live-model evaluation ran.

2026-09-19 answer-basis slice: five directly related new cases passed in 2.51
seconds. They cover generic unverified output, actual versus unused prompt
evidence, rejected unused citation labels, no-evidence local requests and
conservative legacy terminal-event defaults. OpenAPI export and desktop HTTP
contract generation/check succeeded, but SSE models are outside that export
and no generated answer_basis type is claimed. `git diff --check` passed.
No broad regression, frontend rendering suite or live-model evaluation ran.
Existing state/event/Pydantic and prompt evidence APIs were reused; no new
dependency behavior or external-source claim was needed for this slice.

2026-09-19 mixed-source execution slice: five new focused cases passed across
two runs. The first run passed three guard cases before a test model omitted
the required local `ChatModelRunResult.raw_result` constructor field; after fixing
only that fixture, the two integration cases passed in 1.46 seconds. Coverage:
bounded all-scope expansion, pre-call denial, empty-set rejection, chat wiring
and text-tool fallback. No broad regression, frontend check or live-model
evaluation ran. `git diff --check` passed.

2026-09-19 routing boundary slice: six directly related tests passed in 1.42
seconds, plus the existing independent-Agent runtime path passed in 1.31 seconds.
Seven distinct cases cover general Wiki/RAG/document topics, explicit library
and project facts, personal versus mixed scopes, recognized negated/explanatory
Wiki writes, chat tool least privilege and retained explicit action workflows.
The prior technical-question test now asserts semantic fallback instead of
mandatory local retrieval; the runtime tool expectation no longer includes a
chat write tool. No broad regression, frontend suite or live-model evaluation ran.
`git diff --check` passed.

2026-09-19 source-observation slice: five new focused cases passed in 5.90
seconds; one unchanged-page carry-forward case passed in 2.60 seconds. Six
distinct cases cover same-timestamp source insertion, foreign/personal scope
exclusion, unknown legacy baselines, unauthorized-page rejection, new-note
arrival during answer generation, pre-query change diagnostics and preservation
of old page baselines across promotion. No broad regression, frontend suite or
live-model evaluation ran. Public HTTP schemas did not change.

2026-09-19 combined-assessment slice: five new focused cases passed in 3.55
seconds and one dispute-retention case passed in 2.06 seconds. Six distinct cases
cover combined citation mapping, unknown freshness, forged quotes, dropped
subquestions, revocation during reassessment, shared model-call limits and
simultaneous retained disputes/budget exhaustion. No earlier suite, broad
regression, frontend check or live-model evaluation was rerun. HTTP schemas did
not change.

2026-09-19 indexed-note fallback slice: five new focused cases passed in 3.65
seconds; an additional budget case passed in 2.53 seconds. Six distinct cases,
no broad regression. They cover Wiki/cache exclusion, exported derived notes,
permission denial, external edits, vault switching, answer-time revocation,
personal-scope isolation and whole-chunk budget handling. The first budget
assertion incorrectly assumed a large note was one chunk; it was corrected to
verify exact indexed chunks and total budget, without changing the splitter.
`git diff --check` passed. No HTTP model changed or frontend suite was rerun.

2026-09-19 evidence-assessment/supplementation slice: eight directly affected
cases passed in 5.56 seconds (four new gate cases and the four query-node safety
cases). Two additional cases passed in 2.33 seconds for third-hop rejection and
answer prompt gate propagation/actual-context tracking. A final missing-model
registry case passed in 2.13 seconds: eleven distinct cases, with no broad
regression. Coverage includes simultaneous conflict and budget
exhaustion, unknown freshness, forged quotes/read scopes/authority fields,
ninth-page supplementation, invalid-model output and prior revocation guards.
No live-model quality evaluation, context replacement or raw fallback is claimed.
No HTTP model changed; frontend regeneration/typecheck was not repeated.

2026-09-19 query-node slice: four directly related tests passed in 6.23 seconds.
They cover real snapshot citation construction, personal-only scope exclusion,
root revocation during answer generation blocking answer emission, and forged
snippet rejection before model invocation. OpenAPI and desktop contracts were
regenerated; `generate-api-contracts.mjs --check` passed. No broad regression,
full frontend typecheck or live-model evaluation ran. The archive rejection
branch has not received a dedicated new test in this slice.

2026-09-19 Agent read-tool slice: only four directly related cases ran, all
passing in 5.32 seconds. Actual StructuredTool invocations cover search/read
with snapshot versions and observer output without new workflow writes, refusing
model-selected repinning after a head switch, root forgetting between search
and read, forbidden vault/confirmation arguments, and absent-service rejection.
No broad suite, API regeneration or frontend suite ran; HTTP contracts did not
change. Default model routing remains unchanged.

2026-09-19 read-only API slice: only four directly related API safety cases ran,
all passing in 15.14 seconds. They exercise session authentication, versioned
heading reads, version mismatch, arbitrary-path rejection, forgotten roots,
generic unavailable-generation errors, and actual existing chunk-filter
denial/allow behavior. OpenAPI was exported using the existing isolated exporter;
desktop generated types and proxy routes were regenerated, and
`generate-api-contracts.mjs --check` passed. No previous compiler/publication/
reader suite, frontend full typecheck or broad regression was rerun.

2026-09-19 pinned reading/projection slice: six new reader cases passed in
5.46 seconds. One additional pin/head-switch test and the directly affected
publication missing-page test passed in 3.25 seconds: eight distinct cases.
Coverage includes candidate/body/link generation consistency, reading snapshots
instead of external edits, draft invisibility, cross-vault rejection, version
mismatch, forgotten roots and live access denial, section positions and explicit
read-budget errors, missing projection rejection, retained pins after a head
switch and shared projection reuse. The missing-page assertion now expects the
earlier projection completeness gate to reject it. No broad backend/frontend
regression or live-model evaluation was run; HTTP contracts were not changed.

2026-09-19 T2 ingest integration: five directly related tests passed in
6.81 seconds. They cover end-to-end ingest publication and idempotent receipts,
multi-page version switching with old snapshot retention, source forgetting
between stage and promotion, interrupted publication recovery without file
rewrites, and missing dependency-page rejection. The recovery test was then
strengthened to inject an SQL abort at the publication-receipt update AFTER
pointer/status changes; that single case passed in 2.10 seconds, verifying all
three roll back and a retry updates the same durable receipt. This is five
distinct cases, not six, and not a process-kill/power-loss test. No previous
large suite or frontend suite was rerun. `git diff --check` is the final
whitespace check; live-model, migration recovery and full acceptance remain
outstanding.

2026-09-19 T2 storage foundation: only `test_wiki_generations.py` ran, with
6 passing cases in 3.14 seconds. Tests cover staged invisibility, retained old
reads and body deduplication, failed validation, an injected SQL abort AFTER the
pointer update (rollback verified after reopening), two concurrent publishers
with one winner, cross-vault/path isolation, damaged body rejection and async
validator rejection. The SQL abort is not a process-kill/power-loss simulation;
full publication crash injection and production validator integration remain
outstanding. No broad backend/frontend regression ran.

2026-09-19 compiler root-lifecycle slice: 12 directly related cases passed
in two final targeted runs (8 in 11.59 seconds; 4 in 5.65 seconds). These cover
forgotten roots behind active source/concept pages, changed vault/body/nature,
read-only root validation, forgetting during model execution and before
confirmation/apply, cycles, trace-only provenance, successful existing synthesis
root resolution, and the reviewed catalog. No broad regression was run.
The initial attempts exposed mixed `message:`/page references and indirect graph
construction during fact collection; implementation was corrected without
relaxing the root or read-only assertions. Full-suite and live-model acceptance
remain outstanding.

2026-09-19 compiler-read gate: 26 focused compilation/provenance tests passed
(23.43 seconds). After adding the synthesis target guard, two synthesis tests
passed (2.87 seconds), one overlapping the first run: 27 distinct passing cases.
Coverage includes inactive bindings, unreviewed catalog metadata, direct reads
without indexing, BOM/CRLF hashes, invalidation during selection/compilation and
before confirmation/apply, and forgotten synthesis targets. The first attempt
used `revoked` for a page-binding fixture, which migration 021 correctly rejects;
the fixture now uses supported `forgotten`/`stale`/`quarantined` states. No schema
constraint was relaxed. `git diff --check` passed. Per the requested smaller
test scope, no full backend suite, frontend checks or live-model evaluation ran.

2026-09-19 root-resolution regression: 102 passed, one skipped (64.49 seconds)
across source scope, workflows, compilation and provenance. The first ten new
root-resolution tests passed (8.58 seconds), covering compiled pages without
hash markers, inactive candidates, changed raw bodies/hashes, vault scope,
entity hash mismatch and duplicate page paths. This is scripted-model/local
validation, not live-model acceptance or a full-suite result.
Final root-resolution/identity/closure/archive-recovery/action-lifecycle run:
73 passed (45.01 seconds), including all 13 root-resolution tests after adding
body-hash impersonation, multiple active root bindings and candidate type mismatch.
The multiple-binding fixture explicitly supplies durable evidence because the
graph service correctly quarantines evidence-free relationships. No assertion
or authority check was relaxed. `git diff --check` passed. These suites overlap.

2026-09-19 source-binding identity regression: 159 passed, one skipped
(79.72 seconds), covering extraction, candidates, closure, provenance, compilation,
workflows, scope and ingest identity. A preceding combined attempt stopped at
135 passed and one skipped when the archive POST in
`test_wiki_workflow_api_writes_and_audits` returned 400. Its isolated rerun passed
(7.41 seconds), and the subsequent combined run passed. The intermittent 400
cause is unresolved; response-body diagnostics were added without changing
the assertion or weakening authority checks. This is not a full-suite pass.
After the final identity test additions, source-binding, entity-graph, memory
lifecycle and public-graph tests passed 49 cases (40.27 seconds), including
18 source-binding identity cases. Desktop API contracts/hook lint/TypeScript
checks also passed. Test suites overlap and their counts are not additive.

2026-09-19 provenance/compilation/workflow regression: 290 tests passed, one
skipped in the isolated environment (182.60 seconds). It includes the new
provenance classifier, forged tool labels, source metadata self-assertions,
derived input storage without activation, exported file/folder handling,
summary writes/recovery, reflections and post-reply execution. A subsequent
provenance-only run passed 29 tests including source-nature readback and
synthesis rechecks. Final targeted regression after the last catalog/path
change passed 117 tests (34.43 seconds), covering provenance, evidence policy,
compiler, FTS/hybrid retrieval and Wiki Agent runtime. These suites overlap;
their counts must not be added as distinct tests. These are
deterministic/scripted-model tests, not live-model semantic acceptance.

The earlier combined run had 262 tests passed, one skipped in the isolated
environment (138.60 seconds), covering authority, archive, workflows, recovery,
retrieval, permissions, prompts, compilation, migration and public graph contracts.
This includes 31 lifecycle/reconciliation cases, 23 archive authority cases,
21 ingest identity cases, and 16 passing vault-scope cases. The scope tests cover
cross-vault runs, cached reviews and receipts, API terminal-result replay after a
vault switch, copied source pages, unrelated same-hash evidence, unknown legacy
ownership, foreign-key enforcement and migration failure rollback.
The directory-symlink containment test was skipped because this Windows host
did not permit creating the symlink; that filesystem case is not verified here.
`pip check`, desktop `npm run typecheck` (API contracts, hook lint, TypeScript),
and `git diff --check` also passed; an earlier `node --check` passed.
Desktop typecheck was rerun successfully after the provenance changes.
Starlette reports an upstream AnyIO deprecation warning.

The latest full-suite attempt used `--maxfail=1` and stopped after 339 passing
tests at `test_fix_backlog_p0.py::test_forcibly_terminated_process_is_recovered_on_real_app_restart`.
Its child process did not signal readiness within the existing 10-second limit;
the run took 570.84 seconds. An unchanged isolated rerun passed in 10.68 seconds.
The cause of the full-run timeout is unresolved; no timeout was relaxed and no
passing full-suite claim is made. A previously reported graph-detail fixture
failure was corrected to create the page it binds, and focused checks pass.
The remaining full suite, fresh-environment reproduction, frozen sidecar build,
and live-model acceptance have NOT been verified.

Run from the repository root using the isolated interpreter:

```powershell
apps\backend\.venv\Scripts\python.exe -m pip check
apps\backend\.venv\Scripts\python.exe -m pytest apps/backend/tests/test_wiki_evidence_policy.py -q
apps\backend\.venv\Scripts\python.exe -m pytest apps/backend/tests/test_wiki_ingest_source_identity.py -q
apps\backend\.venv\Scripts\python.exe -m pytest apps/backend/tests/test_wiki_source_scope.py -q
apps\backend\.venv\Scripts\python.exe -m pytest apps/backend/tests/test_wiki_provenance.py -q
apps\backend\.venv\Scripts\python.exe -m pytest apps/backend/tests -q
node --check apps/desktop/electron/sidecar.js
```

The safety tests cover inactive lifecycle states across prompt surfaces,
external source-field forgery, repeated edits, forgotten-page replay, a
missing Wiki directory, unreviewed indexed pages, and cached retrieval after
edit/deletion/invalidation. They do not replace the roadmap's generation
crash-injection, permission, provenance, or live-model acceptance tests.

## External Verification

Access date: 2026-09-19. No repository data was sent to these sources.

For Shadow runtime cancellation, the web tool returned no usable content and
an invalid interim citation was corrected. Command-line HTTPS fetched the
official [Python 3.10 asyncio task documentation](https://docs.python.org/3.10/library/asyncio-task.html).
`Task.cancel()` requests coroutine cancellation via CancelledError; it does not
prove immediate termination of remote requests or worker threads. Applied to
the local CPython 3.10.7 runtime using retained task references and awaited
shutdown. The focused preemption/stream cases above verify local behavior;
remote cancellation and resource-priority guarantees remain unverified.

For the Shadow opt-in field, command-line HTTPS retrieved the official
[Pydantic standard-library type documentation](https://docs.pydantic.dev/latest/api/standard_library_types/)
after the web tool returned no usable content. Its strict-boolean rule permits
only booleans rather than coercing strings/numbers. Applied to the locked
Pydantic 2.13.5 environment; focused tests verify request and persisted-value
behavior. The existing asyncio lifecycle and app_state patterns were reused,
without adding a scheduler, dependency upgrade or model invocation.

For Shadow metrics, the web tool returned no usable content; an invalid interim
citation was explicitly corrected. Command-line HTTPS then successfully fetched
the official [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html).
This unversioned guidance informs exclusion of sensitive application data from
logs; it does not certify anonymization. The implementation reuses local
Python 3.10, Pydantic, app_state and SQLite 3.37.2 transaction patterns. The four
focused cases above verify the stored-field boundary and local execution
isolation, not an end-to-end privacy certification.

For migration 034, fresh retrieval of the SQLite ALTER TABLE documentation
returned no usable web content and command-line HTTPS timed out. No fresh
official verification is claimed. The additive-column migration reuses the
existing migration runner and SQLite 3.37.2 environment; the focused legacy
migration and persistence tests above verify this checkout's behavior.

For mixed-source tool execution, the web tool returned no usable content.
Command-line HTTPS subsequently retrieved the official OWASP Authorization
Cheat Sheet on 2026-09-19; the invalid interim citation was corrected. Its
unversioned per-request authorization guidance is applied to the allowed source
set before tool execution. Existing StructuredTool and evidence-filter patterns
were reused on the locked environment; the five focused cases validate the
local boundary, not all alternate entrypoints.

For T3 chat tool separation, command-line HTTPS retrieved the official OWASP
Authorization Cheat Sheet on 2026-09-19 after the web tool returned no content.
The invalid interim citation marker was corrected. Its unversioned least-privilege
guidance supports separating read tools from mutation capabilities; it does not
validate heuristic language classification. Existing LangChain tools, classifier
schemas and action lifecycle were reused without dependency changes. Seven
focused local tests above validate this checkout's limited behavior.

For source observations, the SQLite isolation web request returned no usable
content and command-line HTTPS timed out after 12 seconds. An interim claim
of successful fresh verification and its invalid citation were explicitly
corrected. No fresh external verification is claimed. Implementation reuses the
checkout's existing scoped-session/explicit BEGIN pattern on SQLite 3.37.2;
no new SQLite API, schema migration or cross-model transaction is introduced.
Six focused local cases above verify the limited behavior. Semantic freshness,
complete race freedom and broad durability remain unverified.

For combined reassessment, the web tool returned no usable document; a subsequent
command-line HTTPS request retrieved the official OWASP Authorization Cheat
Sheet on 2026-09-19. An invalid interim citation marker was explicitly corrected.
The unversioned per-use authorization guidance applies to pre/post-model
restoration of both evidence types. Model invocation, JSON extraction and schema
validation reuse the locked Python 3.10 checkout; the six focused cases above
validate local behavior, not semantic correctness.

For indexed-note fallback, command-line HTTPS retrieved the official OWASP
Authorization Cheat Sheet on 2026-09-19 after an empty web-tool result. Its
unversioned per-request authorization guidance applies to server-side citation
restoration and final answer rechecks. Existing hybrid retrieval, thread-pool
and SQLite APIs were reused on the locked Python 3.10 environment; six focused
local cases verify this limited boundary, not a complete provenance migration.

For the semantic gate, command-line HTTPS retrieved the official OWASP LLM
Prompt Injection Prevention Cheat Sheet linked below on 2026-09-19 after the
web tool returned no content. Its unversioned guidance on least privilege,
untrusted retrieved content and deterministic tool validation is applied to
server-owned read candidates and exact-quote validation. Model calls, JSON
extraction and Pydantic validation reuse the locked checkout's existing APIs;
the focused gate tests above exercise these boundaries. This does not establish
semantic truth or guarantee resistance to all prompt injection.

For query-node citation revalidation, command-line HTTPS again retrieved the
official OWASP Authorization Cheat Sheet on 2026-09-19. Its unversioned
per-request guidance is applied at each snapshot use and answer emission.
The implementation reuses existing tool, model and event contracts on the
locked Python 3.10 environment; the four focused cases above validate this
limited boundary, not complete authorization or semantic correctness.

For Agent tool wiring, the OWASP authorization guide was retrieved again by
command-line HTTPS on 2026-09-19; the web tool returned no document. Its
unversioned per-request checking guidance applies to each search/read, not just
the initial version pin. LangChain tool construction and timeouts reuse this
checkout's locked existing patterns, verified by the four real StructuredTool
invocation tests above. No new third-party API behavior is assumed.

For the read-only API, command-line HTTPS successfully retrieved the official
OWASP Authorization Cheat Sheet linked below, including deny-by-default and
per-request checks. This is unversioned security guidance, applied here to
active-vault scope, per-page/parent access and whole-page chunk authorization.
The web tool returned no usable document. No FastAPI/dependency API was invented
or upgraded; route/dependency/response patterns reuse local FastAPI 0.141.1 code
and are exercised by the four API tests above.

For migration 033, the FTS5 web-tool request returned no document and command-line
HTTPS to `https://www.sqlite.org/fts5.html` timed out. An intermediary claim of
successful fresh verification was corrected. FTS configuration, CJK splitting,
query quoting, `MATCH` and `bm25` usage reuse this checkout's existing note
retrieval implementation; the new scoped joins and counts were exercised by
the eight local cases above on the locked SQLite 3.37.2 environment. No fresh
official-source verification or relevance/performance improvement is claimed.

For the T2 storage foundation, fresh web-tool retrieval of SQLite isolation
returned no usable content; HTTPS requests to both `www.sqlite.org/isolation.html`
and `sqlite.org/isolation.html` timed out on 2026-09-19. Fresh external verification
was unavailable. The implementation reuses this checkout's existing
`BEGIN IMMEDIATE`/scoped-session pattern and prior SQLite isolation verification
below; it introduces no dependency upgrade or multi-file transaction claim.
The six local storage checks validate the limited behavior on SQLite 3.37.2,
not complete durability certification. During the subsequent ingest integration,
web-tool isolation retrieval was again empty, and a fresh HTTPS request to
`https://www.sqlite.org/foreignkeys.html` timed out. Migration 032 reuses the
nullable-reference form already verified for migration 030 and the existing
foreign-key-enabled connection setup. The local ingest tests exercise actual
dependency insertion/cascade and transaction rollback on SQLite 3.37.2; fresh
external verification remains unavailable. Snapshot-based answering stays
disabled while the post-apply ingest adapter is integrated.

- [Python 3.10 pathlib](https://docs.python.org/3.10/library/pathlib.html):
  `resolve` resolves filesystem paths; `is_relative_to` is a lexical check.
  Resolve before checking containment. Applied to editable Wiki reads.
- [SQLite isolation](https://www.sqlite.org/isolation.html): committed database
  writes are isolated across connections; `BEGIN IMMEDIATE` reserves a write
  transaction. Reused `MemoryEntityGraphStore._write_scope`, not a filesystem
  transaction. Forgotten binding mutation is covered by regression tests.
- [pip repeatable installs](https://pip.pypa.io/en/stable/topics/repeatable-installs/):
  exact pins include transitive dependencies; artifact hashes provide a
  stronger guarantee than version pins. A version list is not a reproducible
  binary-build claim.
- [pip build isolation](https://pip.pypa.io/en/stable/reference/build-system/):
  isolated build dependencies are separate from runtime dependencies; disabling
  isolation requires provisioning build dependencies explicitly. Verify the
  setup command locally before marking T0 complete.
- [OWASP authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html):
  deny by default and check object access on each request, including guessed
  identifiers. This is framework-independent guidance, applied to current
  vault identity/version restoration and receipt rechecks. Local archive
  tests cover forged IDs, cross-vault references, changed sources, rejected
  candidate filters, sensitive text, derived reports and revoked evidence.

Earlier web-tool queries returned no usable content and command-line HTTPS requests
timed out. On 2026-09-19 the in-app browser successfully retrieved the official
[SQLite ALTER TABLE documentation](https://www.sqlite.org/lang_altertable.html).
It specifies a NULL default when adding a REFERENCES column with foreign keys
enabled. Migration 030 uses that additive form without rebuilding a table,
disabling constraints or guessing existing ownership. The isolated CPython 3.10
runtime reports SQLite 3.37.2. Local migration tests cover legacy row retention,
foreign-key enforcement, reruns, and rollback after an injected statement failure.
The complete identity/table-rebuild migration is still pending.

The same browser also retrieved the
[Python 3.10 multiprocessing documentation](https://docs.python.org/3.10/library/multiprocessing.html#contexts-and-start-methods)
on 2026-09-19. `spawn` starts a new interpreter and must import the target module;
the local test imports application modules before creating its recovery fixture.
This makes startup timing a diagnostic lead, not proof of the observed timeout's
cause. Local runtime: CPython 3.10.7. No process-recovery implementation or test
timeout was changed on this hypothesis.

The OWASP authorization guide was retrieved again by command-line HTTPS on
2026-09-19 before the source-binding changes. Its deny-by-default/per-request
validation guidance applies independently of dependency versions; local tests
exercise exact source identity, inactive-candidate replay and finalization.
A fresh SQLite isolation fetch timed out; no migration or new SQLite behavior
was implemented on an unverified assumption. The identity-table migration remains
pending.
It was successfully fetched again for source-page root resolution on
2026-09-19. Applied the same version-independent deny-by-default principle to
missing/ambiguous database bindings and per-use source lifecycle rechecks;
no third-party API or dependency version changed.
The guide was retrieved again by command-line HTTPS for compiler-read gating
on 2026-09-19 (web-tool retrieval returned no content). Applied its same
unversioned per-access validation guidance to compiler catalog metadata,
captured page bodies, and post-model/confirmation/apply checks. Local focused
tests verify these boundaries on the locked Python 3.10 environment; the guide
does not establish race-free publication or full root-provenance correctness.
It was also retrieved on 2026-09-19 for the compiler root-lifecycle extension.
The same unversioned deny-by-default/per-access guidance applies to a derived
page's dependencies, not only its own binding. The local resolver and locked
Python 3.10 environment, rather than a new dependency API, implement this rule.
The twelve focused cases above verify this limited boundary; permissions,
expiry semantics, bounded dependency traversal and immutable publication remain
separate release work.

On 2026-09-19 command-line HTTPS successfully retrieved the official
[OWASP LLM Prompt Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html).
This is an unversioned living security guide, not a framework API specification.
Its agent/tool guidance calls for least-privilege scopes and deterministic
validation; model guardrails do not replace those controls. Applied here by
assigning Agent ingress identity in server code and checking source nature
before factual compilation/activation, not by asking the model to declare
itself trustworthy. Local regression tests cover spoofed origin labels,
claimed verification metadata, legacy summaries, compilation re-entry and
normal original-material imports. No dependency API or version was changed
on the basis of this guidance.
