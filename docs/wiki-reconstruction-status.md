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

Update 2026-09-20: migration `035_source_identity` resolves the global
`wiki_sources.source_hash` uniqueness constraint (non-unique index), adds
`source_version`/verification columns and the version-history ledger, and
backfills source identity into legacy graph metadata. The identity migration
record below (Phase A 2026-09-20) supersedes the "still pending" statements
above; the read-path binding/revocation gates listed in the T1 row remain open
and are scoped to Phase B.

Update 2026-09-20 (Phase B): the T1-row read-path binding/revocation gates are
now delivered by draft-first publication: authorize checks binding status and
revocation on every read (factory.py), `_scope` rejects revoked generations,
and migration 036 adds generation/binding-level revocation timestamps; the
Phase B record below supersedes the "remain open" wording above. Still open in
the T1 row: complete persisted provenance/permission model incl. verification
status/expiry enforcement (Phase C), non-document evidence restoration and the
generation-aware archive adapter, compiler draft API wiring (stage_draft/
publish_draft are service-layer only), and generation retention/lease policy.

Update 2026-09-20 (Phase C): the T3-row freshness gate and the query-path
completion items (freshness state machine, context replacement, deep-read
profiles, Gate completion) are delivered; the Phase C record below supersedes
the "query-node default integration ... remains outstanding" wording above.
Default chat routing is still NOT switched (Shadow/independent evaluation path
only). Still open: verification-status/expiry enforcement readers, deep-read
API exposure and lazy relevance-check wiring, stage_draft/publish_draft API
wiring, generation-aware archive adapter, retention/lease policy, and the
Phase D/E rollout gates.

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

## Phase A 2026-09-20 Source Identity Migration

Date: 2026-09-20. Phase A of the source-identity workstream: separation of the
stable source identity from the content fingerprint and the source version, so
that two sources with identical bodies are distinct records. Design:
`docs/source-identity-migration-design.md` (T3); failing acceptance tests:
`tests/test_source_identity_migration.py` (T4, red before T5, green after);
implementation: T5; regression and P0 acceptance: T7; localization pass: T6.

### Task

- Migration `035_source_identity`: drop the global `wiki_sources.source_hash`
  UNIQUE constraint (keep a non-unique index), add `source_version`,
  `verification_status`, `verified_at`, `verified_by`, `expires_at`,
  `revoked_at`, `revoked_reason` columns and the `wiki_source_version_history`
  ledger table; backfill source identity into legacy graph metadata.
- v2 ingest identity rules behind the `source_identity_v2` app_state flag
  (default off): identity-exact reuse, same-identity content change bumps the
  source version (old content snapshotted into the ledger), no identity match
  creates a new row (same-body multi-source storage), ambiguous/legacy
  unverifiable identity fails closed with existing error codes.
- Graph/evidence identity migration: wiki evidence IDs keyed by source_id,
  `documented_in` relation source_text prefixed by source_id, synthesis roots
  resolved by source_id, `source_version` recorded in candidate/evidence/fact
  metadata.
- Source page path unification for new writes (`Wiki/Sources/{slug}-{source_id[:12]}.md`)
  plus dual body markers (`- 来源标识：` preferred, `- 来源哈希：` kept for
  legacy readers) and the `resolve_source_page_path` read helper.
- Contract extension: optional additive fields only.

### Files Changed

Modified:
- `apps/backend/app/services/wiki/ingest.py` — v2 confirm identity rules,
  version bump + ledger write, page-plan path/marker rewriting, compile
  metadata path mapping.
- `apps/backend/app/services/wiki/ingest_identity.py` — `source_identity_v2`
  flag reader, `_identity_metadata_equal`.
- `apps/backend/app/services/wiki/memory_closure.py` — evidence IDs,
  relation source_text, synthesis source_ids/independence rule, double-marker
  parsing, candidate/evidence `source_version` metadata.
- `apps/backend/app/services/retrieval.py` — `_resolve_wiki_source_identity`
  fills `source_id`/`source_version` on search results and restored citations.
- `apps/backend/app/models/memory.py` / `apps/backend/app/models/wiki.py` —
  optional `source_id`/`source_version` (MemorySearchResult),
  `source_version` (WikiIngestPreviewResponse).
- `apps/backend/app/storage/database.py` — MigrationRunner supports a
  first-statement `PRAGMA foreign_keys = OFF` header for table-rebuild
  migrations (switched outside the transaction, restored after commit/rollback).
- `apps/backend/openapi.json` — regenerated (additive fields only).
- `apps/backend/tests/test_migration_repair.py`,
  `apps/backend/tests/test_wiki_ingest_idempotency.py`,
  `apps/backend/tests/test_wiki_source_scope.py` — migration-runner and v2
  coverage; the stale scope-migration assertion (apply() == ["030..."]) now
  expects 030-035 with row/index/FK checks.

New:
- `apps/backend/migrations/035_source_identity.sql`.
- `apps/backend/tests/test_source_identity_migration.py` (T4, 8 cases).
- `apps/backend/tests/test_retrieval_source_identity.py` (3 cases).
- `docs/source-identity-migration-design.md` (T3), plus T2/T11/T12/T13 docs.

### Implementation Content

- Migration 035 is a 12-step table rebuild inside one transaction: duplicate-hash
  guard, row-count reconcile, post-rebuild foreign-key check (any violation
  aborts and rolls back), non-unique `idx_wiki_sources_hash` and rebuilt
  `idx_wiki_sources_vault`, version ledger table, and idempotent backfill of
  `memory_evidence`/`memory_candidates`/`memory_graph_facts` metadata
  (`source_id` + `source_version = 1`) only where `source_id` is absent and
  the hash resolves uniquely (hashes outside wiki_sources, e.g. the diary/
  companion hash family, are left untouched).
- v2 confirm runs inside the existing `BEGIN IMMEDIATE` transaction: candidate
  lookup by source_type/source_uri/vault, identity-metadata equality
  (excluding compiler run fields), scope assertion, then reuse / version bump /
  new row; more than one identity match or unverifiable legacy identity raises
  the existing `wiki_ingest_source_identity_conflict` / scope error (no new
  error codes). Legacy behavior is byte-identical when the flag is off.
- New evidence IDs use source_id keys; legacy IDs are never rewritten and stay
  readable; reuse requires matching recorded metadata (fail closed otherwise).
- Synthesis: independent roots are counted by distinct source_id; duplicate
  requested paths do not add independence; single-source synthesis is legal
  under v2. Cycle detection (`synthesis_source_cycle`) and evidence union
  de-duplication by root source remain covered by tests.

### Known Limitations (accepted decisions)

1. `verification_status`/`revoked_at`/`expires_at` are persisted but not yet
   enforced on any read path. Accepted as a known limitation: enforcement is
   Phase B/C work ("old content versions stay stable; old permissions do not
   stay valid forever" — live per-read authority checks). Phase B core items
   (see T9 draft): read-path binding status checks and revocation effect, with
   the T11 gap locations: `snapshot_reader.py:207-239` `_load` /
   `:224-226` authorize call, `factory.py:506-536` authorize does not check
   `wiki_page_bindings.status`, and `source_watermark.py:7-24` omits binding
   status/generation version. No API exists yet to set `revoked`, so there is
   no repro path in this phase.
2. Synthesis independence semantics changed with v2: roots counted by distinct
   source_id; duplicate paths of the same source do not add independent
   evidence (consistent with T4 acceptance case 5, covered by
   `test_duplicate_sources_do_not_double_count_evidence`); cycle coverage:
   `test_wiki_synthesis_roots.py:262` (`synthesis_source_cycle`) and :90
   (`synthesis_sources_not_independent`).
3. `AgentWikiProposalFields` does not yet carry `source_version` (additive
   later; no test requires it).
4. Publication dependency stamps and the source watermark do not explicitly
   include `source_version`; a version bump changes `source_hash`/`raw_content`/
   `updated_at`, which the existing fingerprints and watermark already observe.

### Safety Boundary

- Forged sources/references cannot gain trusted identity: ingest confirm
  full-equality checks (scope, type/uri/metadata), closure-side
  `sha256(raw_content) == source_hash`, candidate/entity/evidence dual-field
  metadata checks, and query-time watermark changes all fail closed.
- Summary cycles do not add evidence: `resolving` tuple detection raises
  `synthesis_source_cycle`; duplicate-path requests raise
  `synthesis_sources_not_independent`; evidence union de-duplicates by root
  source (T4 case 5).
- Forget/external-edit invalidation: a forgotten provenance candidate blocks
  authority resolution (`source_candidate_not_activatable`, T4 case 4);
  external page edits fail binding-hash, snapshot and restore checks
  (`source_changed`/`synthesis_source_binding_hash_mismatch`). Revocation
  enforcement is deferred (Known Limitation 1).
- Interruption/concurrency/retry: ingest confirm remains serialized by
  `BEGIN IMMEDIATE`; migration 035 is a single transaction with rollback on
  any failed guard; `MigrationRunner` FK-off header support is covered by
  new `test_migration_repair.py` cases (first-statement allowed,
  mid-script still refused); apply requires review approval and post-write
  hash verification.

### Localization Check (T6)

T6 = zero code changes. Verified: no API path, JSON/SSE field name, error
code, enum value, Tool name or JSON key changed; new comments/docstrings are
Chinese or necessary technical English; no new user-facing error message or
logger string was introduced.

### Test Commands And Results (T7)

Run from the repository root with the isolated interpreter (tests import
`apps.backend.tests._schema`, which requires the root namespace package on
sys.path):

```powershell
cd E:/agentproject
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_source_identity_migration.py apps/backend/tests/test_retrieval_source_identity.py apps/backend/tests/test_wiki_source_scope.py apps/backend/tests/test_wiki_ingest_source_identity.py apps/backend/tests/test_wiki_source_binding_identity.py apps/backend/tests/test_wiki_synthesis_roots.py apps/backend/tests/test_wiki_provenance.py apps/backend/tests/test_wiki_evidence_policy.py apps/backend/tests/test_wiki_source_watermark.py apps/backend/tests/test_wiki_publication.py apps/backend/tests/test_wiki_compilation.py apps/backend/tests/test_wiki_workflows.py apps/backend/tests/test_migration_repair.py apps/backend/tests/test_wiki_ingest_idempotency.py apps/backend/tests/test_openapi_snapshot.py -q
# 247 passed, 1 skipped (233s)

apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_wiki_*.py apps/backend/tests/test_llmwiki_*.py apps/backend/tests/test_retrieval_*.py apps/backend/tests/test_answer_basis.py apps/backend/tests/test_answer_basis_history.py apps/backend/tests/test_memory_entity_extraction.py -q
# 536 passed, 1 skipped (390s, 48 files)

apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_memory_graph_kuzu.py apps/backend/tests/test_memory_graph_migration.py apps/backend/tests/test_memory_graph_projection.py apps/backend/tests/test_memory_graph_services.py apps/backend/tests/test_persistence_mvp.py -q
# 54 passed, 5 skipped (163s)
```

Explicit migration verification (script `.tmp/t7-verify-035.py`): 13/13 PASS —
fresh DB (035 applied; new columns; non-unique hash index; ledger table; FK
enforced after apply) and legacy DB 001-029 (030-035 all applied; legacy row
preserved with version 1; evidence/candidate metadata backfilled; zero FK
violations; second apply idempotent-empty). T4 suite went from 8 failed
(pre-T5) to 8 passed.

- Broad regression: YES
- Real-model tests: NO
- Frontend checks: NO

### Public Interface Changes

Only additive optional fields: `MemorySearchResult.source_id`,
`MemorySearchResult.source_version`, `WikiIngestPreviewResponse.source_version`
(default None; old clients unaffected). `openapi.json` regenerated; the
OpenAPI snapshot test passes. No existing field, path, error code, enum or
Tool name changed.

### Database Migration

`035_source_identity` (single transaction, table rebuild, guards, backfill,
ledger) — described under Implementation Content; legacy DBs migrate in place
with no data loss and no silent identity guessing.

### Next Steps

T9 Phase B draft: Draft-first Publication + versioned authority. Core items:
read-path binding status checks in the snapshot authorize callback
(`factory.py:506-536`) and `snapshot_reader` `_load` (`:207-239`), the
revocation effect on published generations, watermark extension with binding
status (T11 §3.3 gap locations), and the draft-first publication pipeline over
the compiler. Follow-ups from this record: enforcement readers for
`verification_status`/expiry/revocation (Known Limitation 1), optional
`source_version` on agent proposal fields, and explicit `source_version` in
publication stamps/watermark if finer change detection is required.

## Phase B 2026-09-20 Draft-first Publication

Date: 2026-09-20. Phase B of the source-identity workstream: draft-first
publication over the compiler output and versioned authority on the read path
(design: `docs/draft-first-publication-design.md` (t9); failing tests:
`tests/test_draft_first_faults.py` (B3, red before B5); implementation: B5;
regression and P0 acceptance: B7; localization pass: B6 (t20); migration design
pre-check: B4 (t18); code-fact verification: B1 (t15)).

### Task

- Draft Generation → Validate → Review → Promote → sync Editable Markdown, with
  drafts invisible to official queries and old generations readable while N+1
  is constructed or fails.
- Versioned authority: decouple immutable historical bodies from live source
  permissions — forgotten/revoked/privacy changes make the corresponding facts
  unavailable immediately (read-path binding status checks + revocation effect).

### Files Changed

Modified (`git diff f306676`):
- `apps/backend/app/api/services/factory.py` — authorize now deny-by-default:
  binding must be `status='active'` with `revoked_at IS NULL`; evidence-snapshot
  exceptions (incl. root validation) are rejected instead of escaping retrieval.
- `apps/backend/app/services/wiki/snapshot_reader.py` — `_scope` adds
  `revoked_at IS NULL` (generation-level revocation makes a whole version unreadable).
- `apps/backend/app/services/wiki/source_watermark.py` — watermark input adds a
  bindings dimension (status + revocation) so `source_observation` can perceive
  forgetting/revocation.
- `apps/backend/app/services/wiki/generations.py` — stage: run-level idempotency
  (same run + staged reuses the same generation, per the 032 unique index) and
  `draft_pending_review` lifecycle write (does not overwrite advanced states).
- `apps/backend/app/services/wiki/ingest_review.py` — `_mark_draft_status`:
  review start → `draft_reviewing`; reviewed → `draft_approved` (only for runs
  with a staged draft; failure keeps `draft_reviewing` for retry).
- `apps/backend/app/services/wiki/publication.py` — `stage_draft(run_id,
  approved_targets)` (planned pages → draft in DB, no disk write, no binding;
  dependencies deferred to re-capture) and `publish_draft(run_id)` (Plan A:
  1 write via `target_content_hash` gate → 2 memory-closure finalize →
  3 bind active + index_refresh → 4 page_updates written / run applied →
  5 re-capture double-hash + rebuild the draft manifest from disk truth
  (clear old rows, re-insert bodies/deps, rebuild projection) → 6 promote).

New:
- `apps/backend/migrations/036_source_revocation.sql`.
- `apps/backend/tests/test_draft_first_faults.py` (B3, 9 cases).

### Implementation Content

- Migration 036: pure ADD COLUMN (4 columns, nullable, default NULL:
  `revoked_at`/`revoked_reason` on `wiki_generations` and
  `wiki_page_bindings`), column-count + existing-NULL reconcile guards,
  single transaction, no table rebuild / no CHECK change / no FK change
  (SQLite 3.37.2; per t15 §3 and t18 §1).
- Draft lifecycle lives in `wiki_workflow_runs.result_json.$.publication.status`
  (pure JSON domain, no CHECK): `draft_pending_review` /`draft_reviewing` /
  `draft_approved` /`draft_rejected`; the existing 'published' guard
  (`COALESCE(...) != 'published'`) is compatible (`draft_*` never equals
  'published'). `workflow_type='ingest'` retained for draft runs (t18 §2.3).
- Revocation is a state event: setting the timestamp revokes; rows, bodies and
  audit are preserved; no dependency stamp is rewritten. Generation-level
  revocation blocks the whole version (`_scope`); binding-level revocation
  blocks reads (authorize).
- Drafts are invisible to pin/search/read because `_scope` only accepts
  status='published' (existing guarantee, regression-locked by B3 case 1).

### Known Limitations (accepted)

1. `stage_draft`/`publish_draft` are service-layer entry points, NOT yet wired
   to API endpoints or agent orchestration (design §3 full flow); `draft_rejected`
   is written by the approver using the same pattern (demo-level approve via
   validator). Recorded as later-phase integration; does not block this phase.
2. Narrow retry gap (B7 risk 1): if `publish_draft` fails after step 4 (run
   already 'applied'), a direct retry via `publish_draft` is refused
   (`run_not_planned`) and `publish_ingest` retry fails closed
   (`dependency_changed` because binding hash no longer matches the planned
   manifest). No half-product is ever published and G1 stays readable; recovery
   currently needs manual run reset. Recommended fix when wiring API endpoints:
   write `publication.status='blocked'` on failure and allow a documented
   operator reset back to 'planned'.
3. Three new internal draft-path error identifiers were added (not present in
   HEAD): `wiki_publication_run_not_planned` (publication.py:142/188 — stage_draft/publish_draft gate on run status), `wiki_publication_draft_not_approved` (publication.py:191 — publish_draft requires draft_approved), `wiki_publication_draft_missing` (publication.py:199 — publish_draft requires an existing staged draft). They are service-layer only — no API endpoint raises them today, so they are not API-visible. Accepted ruling: the red line means "no change to existing error codes" — adding internal codes modifies no existing code and breaks no contract. **When wiring API endpoints, the boundary layer must map these internal codes onto existing public error codes (e.g. the generic 422/409 contracts) and must never expose internal identifiers.**
4. Behavior tightening (registered, design §4.3): authorize now rejects
   forgotten/stale/quarantined/revoked bindings, so old snapshots behind a
   forgotten binding change from readable to denied (locked by B3 case 4).
5. Phase A limitation still open: `verification_status`/expiry enforcement
   remains Phase C work; the revocation mechanism delivered here covers
   generation-level and binding-level revocation only.

### Safety Boundary

- Drafts (staged) cannot answer queries: pin/search/read all reject them
  (B3 case 1); only published generations are scoped.
- G1 stays byte-identical and readable while G2 is staged and after G2 publish
  failures in two modes (validator error, tampered dependency stamp)
  (B3 cases 2-3); promoted heads switch via the existing single-point CAS.
- Forgotten roots and revoked generations/bindings are denied on the live read
  path (authorize + `_scope`), with bodies preserved (B3 cases 4-5, 7).
- External edits during the write step hit the `target_content_hash` gate:
  the manual edit is preserved, apply reports failed/partial, G1 body and
  generation stay intact (B3 case 6).
- Interruption/retry: stage and promote remain single transactions with CAS;
  run-level stage reuse is idempotent (B3 case 8); migration 036 rolls back as
  one transaction on any guard failure.

### Localization Check (B6/t20)

Zero code changes required. Verified by per-hunk review of
`git diff f306676` (6 app files +284/-3, 036 SQL, B3 tests) plus an automated
residual scan (added English prose filtered to code/identifiers/SQL/JSON keys):
all new docstrings/comments are Simplified Chinese or necessary technical
English; error codes, JSON keys (`$.publication.status`), `draft_*` values,
API field names and enums remain English; no new raise message, logger message
or Field(description) was introduced. Rerun: 41 passed (73.6s).

### Test Commands And Results (B7)

Run from the repository root with the isolated interpreter:

```powershell
cd E:/agentproject
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_draft_first_faults.py apps/backend/tests/test_wiki_generations.py apps/backend/tests/test_wiki_publication.py apps/backend/tests/test_wiki_snapshot_reader.py apps/backend/tests/test_wiki_snapshot_api.py apps/backend/tests/test_wiki_compilation.py apps/backend/tests/test_wiki_workflows.py apps/backend/tests/test_wiki_synthesis_roots.py apps/backend/tests/test_wiki_provenance.py apps/backend/tests/test_wiki_source_scope.py apps/backend/tests/test_wiki_ingest_source_identity.py apps/backend/tests/test_source_identity_migration.py apps/backend/tests/test_migration_repair.py apps/backend/tests/test_wiki_source_watermark.py apps/backend/tests/test_wiki_archive_authority.py apps/backend/tests/test_wiki_shadow_lifecycle.py apps/backend/tests/test_wiki_shadow_runtime.py apps/backend/tests/test_openapi_snapshot.py apps/backend/tests/test_wiki_read_tools.py apps/backend/tests/test_wiki_query_node.py -q
# 252 passed, 1 skipped (357s) — includes B3 9/9

apps/backend/.venv/Scripts/python.exe .tmp/t21-verify-migrations.py
# 11/11 PASS — 035+036 on fresh DB and legacy DB (001-029 -> 030-036),
# 035 backfill still effective, idempotent second apply
```

- Broad regression: YES (252 passed across 20 affected suites)
- Real-model tests: NO
- Frontend checks: NO

### Public Interface Changes

None. No API path, JSON/SSE field name, error code (existing codes unchanged),
enum value, Tool name or JSON key changed; `test_openapi_snapshot` passes.
Three new internal draft-path error identifiers are service-layer only and not
API-visible (Known Limitation 3). `draft_*` are new JSON values inside an
existing JSON domain, not schema or contract changes.

### Database Migration

`036_source_revocation` — pure ADD COLUMN (revoked_at/revoked_reason on
wiki_generations and wiki_page_bindings), nullable, no rebuild / no CHECK / no
FK change, reconcile guards, single-transaction rollback, verified on both
fresh and legacy databases (11/11 PASS). Rolling back = restore backup (035
pattern).

### Next Steps

Phase C: new-query-path correctness completion — enforcement readers for
`verification_status`/expiry (Phase A limitation 1), API wiring and proxy
orchestration for `stage_draft`/`publish_draft` (including the retry reset
semantics from Known Limitation 2 and the error-code decision from Limitation
3), generation-aware archive restoration (retrieval.py:613-614), and
generation retention/lease policy. Follow-ups carried from Phase A: optional
`source_version` on agent proposal fields; explicit `source_version` in
publication stamps if finer change detection is required.
## Phase C 2026-09-20 New Query Path Completion

Date: 2026-09-20. Phase C of the source-identity workstream: completion of
the new query path — freshness state machine, context replacement, deep-read
mode and Evidence Gate completion (design:
`docs/phase-c-query-node-design.md` (C3); failing tests:
`tests/test_phase_c_query_node.py` (C4, red before C5: 9 failed / 6 passed;
green after); implementation: C5; regression and safety acceptance: C7;
localization pass: C6 (t28); recon: C1 (t23); research: C2 (t24)).

### Task

- Freshness three-state machine (fresh/unknown/stale) replacing the constant
  "unknown", with the registration → pending relevance check → lazy check
  chain, UI labels in Chinese mapped to English machine values.
- Context replacement: evidence value function V = relevance x freshness x
  coverage, submodular replacement with pinned supported/conflict citations,
  and a guaranteed ninth-page admission for high-value evidence under a full
  budget.
- Deep-read mode: parameterized profiles (balanced = current behavior; deep =
  24 pages / 3 hops / 6 rounds / 90s / 32000 chars), single-shot escalation
  route, and unchanged permission gates.
- Evidence Gate completion: freshness is a deterministic, model-unsettable
  gate dimension; supplement skip only under fresh + complete + no conflict.

### Files Changed

Modified (`git diff d2a73d1`):
- `apps/backend/app/agents/nodes/wiki_retrieval.py` — `ReadProfile`
  (`BALANCED_PROFILE` = current limits, `DEEP_PROFILE`), `read_profile`
  node parameter, value function `_citation_value`, per-citation freshness
  resolution (`_resolve_citation_freshness`: binding → documented_in →
  source 035 columns, worst-rank fail-closed) and deterministic gate
  assignment (`_apply_gate_freshness`), ninth-page value-admission loop with
  displacement accounting (`replaced`/`displaced` report fields), single
  escalation to deep on coverage gap/conflict with >= 40% remaining.
- `apps/backend/app/agents/retrieval/wiki_gate.py` — `freshness:
  Literal["fresh","unknown","stale"]`, internal `freshness_checked_at`,
  `FRESHNESS_UI_LABELS` (Chinese UI mapping, English machine values),
  `derive_source_freshness` short-circuit derivation (revoked/expired →
  stale, verified + unchanged → fresh, else unknown).
- `apps/backend/app/api/services/adapters.py` — `RuntimeWikiReadAdapter`
  exposes read-only `database` and `pin` for freshness resolution.
- `apps/backend/app/services/wiki/generations.py` — publish receipt
  registers `freshness: "unknown"` + `freshness_reason:
  "source_relevance_check_pending"` (existing JSON domain).
- `apps/backend/tests/test_wiki_gate.py`, `apps/backend/tests/test_wiki_publication.py`
  — updated anchors for the extended literal and receipt fields.

New:
- `apps/backend/tests/test_phase_c_query_node.py` (C4, 15 cases).
- `docs/phase-c-query-node-design.md` (C3), plus C1/C2 recon docs.

### Implementation Content

- Freshness is derived per source at query time from existing 035 columns
  (`verification_status`/`verified_at`/`expires_at`/`revoked_at`) plus
  query-period `source_observation` and binding status; no new table, no new
  column, no schema change. `source_observation`/watermark keep their
  observational meaning (two dimensions separated): a changed observation only
  marks the source for recheck; it does not auto-judge stale.
- Registration chain: apply/publish writes `freshness=unknown` +
  `source_relevance_check_pending` into the publish receipt (existing JSON
  domain); the lazy bounded relevance-check chain (writing `verified` and its
  interaction with dependency stamps) is a registered follow-up, not built in
  this phase.
- Context replacement: token accounting splits read budget (12000) from
  context injection budget; supported/conflict citations are pinned
  (quote-validation semantics unchanged); citations are re-ordered by value and
  the ninth-page admission loop reads high-value candidates beyond
  `max_pages` when budget allows, replacing the lowest-value held context
  (replacement/displacement counted in the report; displaced citations remain
  traceable).
- Deep-read: profiles replace inline constants; escalation happens at most
  once per node run (balanced → deep) when a coverage gap or unresolved
  conflict exists and >= 40% of the deadline remains; denied pages still fail
  closed (permission gates untouched).
- Gate: model schema keeps `extra="forbid"` — the model cannot set
  `freshness` or `authority`; supplement skip now requires
  `freshness == "fresh"` (unknown/stale always fall back; stale is explicitly
  annotated in answer assembly injection).

### Known Limitations (accepted)

1. Lazy relevance-check chain (write-back of `verified` and its interaction
   with dependency stamps) is not implemented — registered as a later design
   point (C5/C7); registration + derivation work today, checking is manual or
   future async queue work (no new resident service in this phase).
2. `ReadProfile` is a node-level parameter; no API exposure of deep-read mode
   yet (additive optional field pattern reserved for wiring).
3. Design-code deviation (non-defect, recorded by C7): the ninth-page value
   precheck initializes held scores to 0.0, so admission degenerates to
   "score > 0" and the real gates are budget/deadline; the high-value ninth
   page guarantee holds (and is stronger), but low-value extra pages are also
   read while budget remains. Recommend seeding held scores from candidate
   retrieval scores at wiring time.
4. Escalation to deep mode can change `stop_reason` (e.g. third-hop test:
   `assessment_failed` → `round_budget_exhausted`); the 11-value
   `stop_reason` domain is unchanged (registered in C5). Design §3.2's two new
   stop semantics (`coverage_gap_requires_deep_read`,
   `conflict_exhausted_escalation`) are expressed through the escalation route
   (`profile`/`escalated` report fields) instead of new stop_reason values;
   if Phase D quality signals show insufficient discrimination, independent
   stop_reason values can be added then (internal state values, same contract
   rules).
5. Freshness observation changes only mark for recheck; they do not
   auto-degrade to stale (maintained "do not assume no change" semantics).

### Safety Boundary

- Model cannot influence freshness or authority (GatePayload
  `extra="forbid"`, deterministic assignment points only).
- stale sources cannot certify sufficiency: supplement skip requires fresh;
  unknown keeps the existing fallback behavior (no regression).
- Deep-read mode does not bypass privacy/permission gates: denied pages are
  unreadable and uncited even at 32000-char budgets (C4 case 9).
- Expired/revoked sources short-circuit to stale (C4 cases 4-5); the stale
  machine value reaches answer assembly injection (C4 case 5).
- Default chat routing is NOT switched: `wiki_knowledge_retrieval_node` is
  referenced only by `services/wiki/shadow.py` (independent evaluation
  pipeline); registry/default routing has no reference (verified by grep).

### Localization Check (C6/t28)

Zero code changes required. Per-hunk review of `git diff d2a73d1` (4 app
files +253/-3, C4 tests, 2 anchor test updates) plus automated residual scan:
all new docstrings/comments are Simplified Chinese (including the old English
comment near the supplement condition, which was also localized); machine
values (fresh/unknown/stale) and status-machine values stay English with
Chinese UI mapping (`FRESHNESS_UI_LABELS`); no new error message, logger
message or Field(description) was introduced.

### Test Commands And Results (C7)

Run from the repository root with the isolated interpreter:

```powershell
cd E:/agentproject
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_phase_c_query_node.py apps/backend/tests/test_wiki_query_node.py apps/backend/tests/test_wiki_gate.py apps/backend/tests/test_wiki_source_watermark.py apps/backend/tests/test_wiki_shadow.py apps/backend/tests/test_wiki_shadow_lifecycle.py apps/backend/tests/test_wiki_shadow_runtime.py apps/backend/tests/test_wiki_shadow_summary.py apps/backend/tests/test_retrieval_source_identity.py apps/backend/tests/test_answer_basis.py apps/backend/tests/test_wiki_workflows.py apps/backend/tests/test_wiki_compilation.py apps/backend/tests/test_wiki_synthesis_roots.py apps/backend/tests/test_wiki_provenance.py apps/backend/tests/test_wiki_source_scope.py apps/backend/tests/test_wiki_ingest_source_identity.py apps/backend/tests/test_source_identity_migration.py apps/backend/tests/test_draft_first_faults.py apps/backend/tests/test_wiki_generations.py apps/backend/tests/test_wiki_publication.py apps/backend/tests/test_wiki_snapshot_reader.py apps/backend/tests/test_migration_repair.py apps/backend/tests/test_wiki_read_tools.py apps/backend/tests/test_openapi_snapshot.py -q
# 261 passed, 1 skipped (274s) — includes C4 15/15 (9 red -> green)
```

- Broad regression: YES (261 passed across 24 affected suites incl. Phase A/B
  anchors)
- Real-model tests: NO
- Frontend checks: NO

### Public Interface Changes

None. No API path, JSON/SSE field name, error code (existing codes unchanged),
enum value, Tool name or JSON key changed; `test_openapi_snapshot` passes.
Freshness values `fresh`/`stale` are internal state values inside the
existing gate JSON field (not in API response models); the publish receipt
gains `freshness`/`freshness_reason` keys inside the existing internal JSON
domain. One new internal validation string `wiki_unknown_read_profile`
(node parameter check, no reachable API endpoint; same ruling pattern as the
Phase B internal error identifiers — internal values do not break the
contract).

### Database Migration

None for Phase C (no schema change; freshness derives from existing 035
columns).

### Next Steps

- Phase D: Shadow answer-quality evaluation — ShadowMetrics freshness counters
  (fresh/unknown/stale occurrences and replacement counts) are internal
  observables already present; run quality assessment with the extended gates.
- Phase E: formal switch of the default chat route to the completed query path
  (gated rollout), including: API exposure of deep-read mode (additive
  optional field), lazy relevance-check chain wiring (verification write-back
  + dependency-stamp interaction), held-score seeding from candidate scores
  (Known Limitation 3), and the Phase B follow-ups (stage_draft/publish_draft
  API wiring with retry-reset semantics, generation-aware archive restoration,
  retention/lease policy).




## 红灯修复 2026-09-20 Test-Gate Repair (P0 质量债)

### Task

清除审计确认的红灯与陈旧断言，使「阶段回归」可以改为全量口径。

### Files Changed

- `apps/desktop/electron/proxy-routes.generated.json`、`apps/desktop/src/types.gen.ts` — 用**既有**生成器 `npm run generate:api-contracts` 重生成（阶段A 只重生成 `openapi.json`，漏了 desktop 产物）。
- `apps/backend/tests/test_renderer_allowlist_contract.py` — 无需改动；红灯由生成物修复。
- `apps/backend/tests/test_agent_runtime_routing.py` — `all_tools()` 期望值补上 `search_wiki_pages`/`read_wiki_page`（阶段C 新增的两个读工具）。
- `apps/backend/tests/test_agent_runtime_chat.py` — 两处工具集断言改为只读工具；把 `..._can_surface_wiki_manager_for_obsidian_note_request` 重写为 `..._writes_wiki_page_via_action_lifecycle_for_obsidian_note_request`，改用 `FakeSemanticModel` 驱动真实动作路径，并同时断言「授权开→`wiki.page.write`(auto)+真写盘」与「授权关→`wiki_proposal`+不写盘」。
- `apps/backend/tests/test_api_wiring_mvp.py` — 助手摘要页 `page_type` 由 `source` 改为 `report`（规范已变更）；自动化设置默认值补 `wiki_shadow_enabled`。

### Implementation Content

- **W1 前端契约**：`check:api-contracts --check` 报两份产物过期 → 跑既有生成器 → `test_renderer_allowlist_contract.py` 3 passed，`check:api-contracts` verified，`types.gen.ts` 补回 `source_id`/`source_version` 字段。
- **W3 陈旧断言**：`d7847cc` 有意把写工具移出聊天工具集（`agents/retrieval/router.py:12-16` 现仅返回 `(SEARCH_MEMORY, GET_CURRENT_TIME)`，理由写在 docstring：reading never grants write tools；mutations use the action lifecycle），测试未同步。
- **实测确认新机制**（探针）：`auto_wiki_organize=True` + 语义分类到 `action_type=wiki, kind=page` → 事件 `agent_action` 且 `action_type=wiki.page.write`、`decision=auto`、`target_paths=['Wiki/Runtime.md']`、`wiki.requests=1`；关闭时 → `wiki_proposal`、`wiki.requests=0`。

### Known Limitations

1. `test_memory_graph_migration.py` 两条红**未修**：需在 `MigrationRunner` 增加「已声明缺失表」容忍（036 ALTER 的 `wiki_page_bindings` 由 021 创建，而夹具 `_apply_until_019` 排除了 021）。外部取证（`impl-research-migration-contract.md`）结论：**不要改 036**——SQLite 在 prepare 期即报 no such table，SQL 层写不出守卫；且编辑已应用迁移在既有安装上完全无效。需 runner 层跳过并**记账**（Liquibase `onFail=MARK_RAN` 范式）。
2. `test_api_wiring_mvp.py::test_chat_stream_auto_summarizes_useful_answer_to_wiki` **仍红**：已修 `page_type`，现卡在 `## 证据状态`/`## 来源`/`## 更新记录` 段落缺失——`report` 页渲染器输出的段落与测试期望不符，属**渲染契约与测试期望不一致**，需判定哪一侧正确（未擅自改）。
3. 阶段 A/B/C 的 P0 实质缺陷（源身份开关不可达、draft-first 未接线、C4 置换反转、freshness 无写入方、schema 漂移）**均未修**，见 `E:\a 工作\wiki-audit\llmwiki-verdict-captain.md` 与各 auditor 报告。

### Localization Check

本次新增/修改的自然语言均为简体中文注释；未新增错误码、枚举、API 字段或 Tool 名。测试函数名保持英文。

### Test Commands And Results

```powershell
cd E:/agentproject
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_agent_runtime_chat.py apps/backend/tests/test_agent_runtime_routing.py apps/backend/tests/test_agent_runtime_wiki.py apps/backend/tests/test_renderer_allowlist_contract.py -q
# 47 passed
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_api_wiring_mvp.py::test_automation_settings_api_roundtrip -q
# 1 passed
cd apps/desktop && npm run check:api-contracts
# OpenAPI-derived desktop contracts verified.
```

- Broad regression: 全量在跑（后台）；本次仅跑受影响子集
- Real-model tests: NO
- Frontend checks: 部分（`check:api-contracts` 已过；`npm run typecheck` 待整链复跑）

### Public Interface Changes

None（仅重生成既有产物；未改路径/字段/枚举/错误码/Tool 名）。

### Database Migration

None。

### Next Steps

1. `MigrationRunner` 缺失表容忍（带记账）→ 清掉 2 条迁移红。
2. 判定 `report` 页渲染段落契约（渲染器 vs 测试期望）→ 清掉最后 1 条。
3. 全量复跑确认 9 red → 0。
4. 再进入阶段 A/B/C 的 P0 实质修复，最后推进 D。


### Follow-up 2026-09-20 Migration Runner Tolerance (决策 A 落地)

**Task**：清除 `test_memory_graph_migration.py` 两条红（036 对 `wiki_page_bindings` 的 ALTER 在缺该表的 legacy 库上失败）。

**Files Changed**：`apps/backend/app/storage/database.py`（唯一改动；**036 一行未改**）。

**Implementation Content**：
- 新增类常量 `_MISSING_TABLE_RE` / `_CREATE_TABLE_RE`，新增 `_declared_missing_table_name()` 与 `_declared_table_names()`。
- `_execute_migration_statements` 在既有 `except sqlite3.OperationalError` 分支内串接：若缺失表**在迁移链中由 CREATE TABLE 声明过**，则跳过该语句并记入 `self.skipped_statements`（`DECLARED-MISSING:<table>`），迁移照常记账、后续 update 不再重试。
- **关键设计细节**：声明表名同时扫描「本次使用的目录」与「项目自带规范迁移目录」。原因是测试夹具 `_apply_until_019` 会**复制除 020_/021_ 外的全部迁移到临时目录**，因此 036 在该目录内运行而 021 不在其中——只看传入目录会把合法表误判为未声明。表是否属于迁移链成员，应按**完整迁移链**判断。
- 语义对齐 Liquibase `onFail="MARK_RAN"`（跳过但记账、不再重试）；goose 官方立场是乱序迁移直接报错，即**无主流框架选择静默跳过**。

**Safety Boundary**（实测）：笔误表名、未声明缺失表、语法错误**仍正常报错**；容忍严格限制在迁移链自己声明过的表上。

**Test Commands And Results**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_memory_graph_migration.py -q
# 11 passed (修复前 2 failed)
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_migration_repair.py apps/backend/tests/test_source_identity_migration.py apps/backend/tests/test_wiki_publication.py apps/backend/tests/test_draft_first_faults.py -q
# 31 passed
```

**Known Limitations**：`skipped_statements` 目前只在实例上可见，未进入 `apply()` 返回值或日志；建议后续接入既有迁移报告以便审计。

**Next Steps**：判定 `report` 页渲染段落契约（最后一条红）；全量复跑确认归零。


### Closeout 2026-09-20 Test-Gate Repair 完成

9 条红全部转绿。补充改动：
- `apps/backend/tests/test_api_wiring_mvp.py` — `## 证据状态` → `## 证据`。判定依据：`contracts.py` 的 `report` 项必需段落为「证据」，摘要写入器 `chat_answer_wiki_summary.py` 亦输出 `## 证据`，而 `证据状态` 在**应用代码中零命中**（仅存在于该断言）。

验证（全部实测）：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_agent_runtime_chat.py apps/backend/tests/test_agent_runtime_routing.py apps/backend/tests/test_agent_runtime_wiki.py apps/backend/tests/test_renderer_allowlist_contract.py apps/backend/tests/test_memory_graph_migration.py -q
# 58 passed
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_api_wiring_mvp.py -q
# 46 passed
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_migration_repair.py apps/backend/tests/test_source_identity_migration.py apps/backend/tests/test_wiki_publication.py apps/backend/tests/test_draft_first_faults.py -q
# 31 passed
cd apps/desktop && npm run check:api-contracts
# OpenAPI-derived desktop contracts verified.
```

全量复跑在后台（`pwsh-20`）；阶段 A/B/C 的**实质 P0 缺陷仍未修**，见前述 Known Limitations。


### Schema Drift Fix 2026-09-20 (P0 安全句缺失)

**Task**：修复 Vault 内 schema 副本与规范资源漂移——`vault/Wiki/AGENTS.md` 缺少规范 43-44 行的 P0 安全句「助手摘要和问答报告不能独立支持其所述事实」。

**Files Changed**：`apps/backend/app/services/wiki.py`（同步逻辑）、`apps/backend/tests/test_wiki_schema_consistency.py`（补 2 条守护测试）。

**Implementation Content**：
- 根因：`ensure_core_files` 只做 `_write_if_missing`，既有 Vault **永不刷新**；且一致性测试只校验规范资源，**从不校验 Vault 副本** → 漂移不可被发现。
- 新增 `_sync_schema_file()`：用副本内的内容校验标记 `<!-- wiki-schema-sha256: ... -->` 判断是否被用户改过。无标记 = 引入标记机制前由本方法写入的旧副本 → 采用并开始跟踪；有标记且内容对不上 = 用户改过 → **保留其内容**并把漂移记入 `schema_drift`，不静默覆盖。
- 未引入新框架、未改 API、未加数据库列；沿用项目既有的「内容哈希 + 冲突保留」纪律。

**实测**（`probe_schema_sync.py`）：
```
BEFORE safety sentence: False
AFTER  safety sentence: True
AFTER  marker: True | drift: False
IDEMPOTENT: True | drift: False
USER EDIT preserved: True | drift: True
```

**Test Commands And Results**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_wiki_schema_consistency.py apps/backend/tests/test_wiki_services.py apps/backend/tests/test_wiki_lint_repairs.py -q
# 25 passed
```

**Known Limitations**：`schema_drift` 目前只在服务实例上可见，未接入 lint 码或 API 字段；建议后续接到既有 `get_schema_status()` 与 lint 面。


### Phase C P0 修复 2026-09-20 (C4 置换缺陷 + freshness 写入方定位)

**Files Changed**：`apps/backend/app/agents/nodes/wiki_retrieval.py`。

**C4 置换缺陷 —— 已修并实测验证**：
- 缺陷：`:184` 把已持有页价值恒置 `0.0` → `min_held` 恒 0 → `:244` 的 `min()` 并列取首键，**置换掉最先读入(检索排名最高)的页**，与设计「按价值升序替换最低价值者」相反。
- 另三处同源缺陷一并修复：① 置换后不删 `held_scores` → 重复记账（12 候选实测 `displaced=[Page1×4]`）；② 置换不退预算（按「读过」而非「注入」记账）；③ `extra_path in attempted` 用字符串比对元组集合，**守卫恒不触发**。
- 实现（采纳外部取证推荐：确定性价值排序 + 显式钉住集合 + 价值升序置换 + 预算记账与置换解耦；**不引入 MMR/submodular 做骨架**——arXiv 2607.00725 实测 MMR 单用显著更差(−0.020 F1)、submodular 在图结构证据上显著有害(−0.021 F1)）：
  - 记录**真实候选价值** `held_scores[path] = candidate_scores.get(path, 1.0)`；
  - 新增 `held_chars` 记录注入体积，置换时 `remaining += refunded` 并 `del held_scores[displaced]`；
  - 新增 `pinned` 集合，每轮评估后由 `_pinned_paths(citations, gate.used_for_answer)` 更新；**只从未钉住的页里挑最低价值者置换**；
  - 新增 `read_paths` 修正失效守卫。
- **实测验证**（复跑 auditor-cd 的 `probe_c4.py`，9 候选 Page1=9.0 递减至 Page8=2.0）：
```
修复前: "replaced": 4, "displaced": ["Wiki/Page1.md"]        ← 踢掉最高价值页
修复后: "replaced": 1, "displaced": ["Wiki/Page8.md"]        ← 踢掉最低价值页,Page1 保留
```

**freshness 写入方 —— 定位完成，实现未做（按设计属后续阶段）**：
- 现状：`wiki_sources` 的验证列**无任何生产写入方**（唯一写方是测试），故 `derive_source_freshness` 的 `fresh`/`stale` 分支永不触发、freshness 恒 `unknown`。
- **但设计明确要求它不能靠 ingest 标记**：`docs/phase-c-query-node-design.md:38-39` 规定 ingest 后来源行保持 `verification_status='unverified'`（035 默认）+ publish receipt 写 `freshness_reason='source_relevance_check_pending'`；`:41` 规定核验是**查询期有界惰性核查**（单来源轻量调用，预算上限 = 剩余字符/时间的一半），结果写 `verification_status='verified'` 或保留 `unverified` 并记 `last_checked_at`。
- **结论：不得在 ingest 处标记 verified**——那会绕过设计的惰性核查链并制造虚假 `fresh`。此项属设计内的后续实现，非一行补丁。

**Test Commands And Results**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_phase_c_query_node.py apps/backend/tests/test_wiki_query_node.py apps/backend/tests/test_wiki_gate.py -q
# 26 passed
```

**Known Limitations**：`pinned` 依赖上一轮评估结果；同轮内首次置换时评估尚未发生，故首轮置换不受钉住保护（与设计「进入 assessment 引用集的 citation 不可替换」在跨轮语义上一致，同轮语义待补）。


### Phase A P0 修复 2026-09-20 (源身份 v2 可达性)

**Files Changed**：`app/models/config.py`、`app/services/settings_types.py`、`app/services/settings_preferences.py`、`tests/test_api_wiring_mvp.py`。

**Implementation Content**：
- 缺陷：`source_identity_v2` 只被 `ingest_identity.source_identity_v2_enabled()` 读取，**全仓库没有任何写入路径**（生产 `app_state` 写入方全写其他键，settings 只暴露固定键集）→ 已实现的源身份语义在生产中**不可达**。设计 `docs/source-identity-migration-design.md` 要求它走 **settings 既有机制**，实现未接线（文档与实现不符）。
- 按 `wiki_shadow_enabled` 的既有模式接入（**复用，不新造机制**）：模型加 `source_identity_v2: StrictBool = False`；`settings_types` 加 `SOURCE_IDENTITY_V2_STATE_KEY`；`settings_preferences` 在读取与写入两侧接线，写入沿用 `model_fields_set` 守卫（老客户端未显式提交则不改动既有取值）。
- **默认仍为关**：设计规定「默认关，关=完全保持 legacy hash 复用行为」，故本次只打通可达性，不改默认值。
- `SOURCE_IDENTITY_V2_STATE_KEY` 与 `ingest_identity.SOURCE_IDENTITY_V2_KEY` 是两个模块各自定义的同一 app_state 键，**由测试断言两者一致**以防漂移（避免 settings 层反向依赖 wiki 服务层）。

**Test Commands And Results**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_api_wiring_mvp.py apps/backend/tests/test_agent_actions.py apps/backend/tests/test_wiki_source_scope.py apps/backend/tests/test_wiki_ingest_idempotency.py apps/backend/tests/test_source_identity_migration.py -q
# 81 passed, 1 skipped
```
新增测试 `test_source_identity_v2_flag_is_reachable_from_settings_api`：断言两个键常量一致 + API 默认 False + 可置 True + **未显式提交时不改动既有取值**。

**Known Limitations**：`_existing_source_id`（`ingest_storage.py:24-34`）在 v2 关闭路径下仍按 content hash 认身份——这是 v2 关闭时的**预期 legacy 行为**，非缺陷；但意味着「同正文多来源共存」在生产中仍需显式开启该开关。


### Phase B 前置 2026-09-20 (publish_draft 执行证据)

**Task**：为「draft-first 接线」取得前置执行证据——审计指出 `stage_draft`/`publish_draft` 是零生产调用方的不可达代码，**221 行从未被执行**，在无执行证据前接线是不负责任的。

**Files Changed**：`tests/test_draft_first_faults.py`（新增端到端用例）。**未改生产代码**。

**Implementation Content**：
新增 `test_publish_draft_end_to_end_executes_write_bind_and_promote`，走真实链路：
1. API `preview → confirm → review`（**不 apply**）使运行停在 `planned`；
2. `stage_draft(run_id)` 从 `wiki_workflow_page_updates` 的规划内容入库（不写盘、不建 binding）；
3. 写入 `draft_approved`（模拟审批器）；
4. `publish_draft(run_id)` 执行 写盘 → 内存闭包 → bind → index → run=applied → re-capture → promote。

断言：活动指针切到新 generation；Markdown 真的落盘；运行 `status == 'applied'`；`result_json.publication.status == 'published'`。

**Test Commands And Results**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_draft_first_faults.py::test_publish_draft_end_to_end_executes_write_bind_and_promote -q
# 1 passed
```

**Known Limitations**：本用例证明 `publish_draft` **可执行**，不等于已接入生产。接线（让 `apply_ingest` 走 draft-first）尚未进行：需把现有「先写盘再 capture」改为「先 stage draft → 审批 → publish_draft 写盘并 promote」，会显著改变 apply 的时序，必须在有充分回归预算时做。

**Next Steps**：接线 `apply_ingest` → 跑完整 ingest 回归（`test_wiki_workflows` / `test_wiki_ingest_idempotency` / `test_wiki_publication` / `test_draft_first_faults` 等）。


### 全量口径红项定位 2026-09-20 (第 9 条红:检索查询归一化)

**背景**：全量复跑改为文件输出（`E:\a 工作\full_suite.log`）以便观察进度；在 ~8% 处出现 1 个 `F`。逐批定位后确认为：

`apps/backend/tests/test_agent_runtime_retrieval.py::test_langgraph_semantic_agent_drives_knowledge_retrieval_before_chat`

```
assert retrieval.calls == [("runtime docs", 5, "hybrid", "knowledge_base")]
实际: ('search docs for runtime', 5, 'hybrid', 'knowledge_base')
```

**归因（已排除本次改动）**：
- `git diff --name-only` 显示本次改动仅涉及 `wiki_retrieval.py` / `config.py` / `settings_preferences.py` / `settings_types.py` / `wiki.py` / `database.py` + 测试 + desktop 生成物；
- `test_agent_runtime_retrieval.py` **未被本次改动触及**（`git diff --stat` 为空）；
- `retrieval_query.py` 与 `semantic.py` 的最后改动提交是 **`d7847cc`**（本次工作之前）；
- 该用例走默认检索路径（非 `wiki_knowledge_retrieval_node`，后者只被 shadow 调用），故与 C4 修复无关。
→ 属 verifier 归因的「6 条来自 d7847cc 或更早」中的一条，**本次工作之前即为红**。

**待判定（下一轮）**：测试期望把 `"search docs for runtime"` 归一化为 `"runtime docs"`；实际传入原始消息。需判定是**测试期望陈旧**，还是 `d7847cc` **丢失了查询归一化**（回归）——不可为了让测试变绿而二选一，须先读 `retrieval_query.py` 的归一化链路。


### 第 9 条红:机制定位（未修，避免误判）

**已确定的事实**：
- `_retrieval_query`（`agents/retrieval/scoping.py:52-57`）：`semantic.query` 非空则用它；否则若路由是 `SEARCH_MEMORY` 则用 `_strip_search_command(state.user_message)`；否则用原始消息。
- `_strip_search_command`（`agents/runtime_helpers.py:144-165`）的前缀表含 `"search memory for"` / `"search memories for"` / `"find in memory"` / `"recall"` + 中文若干，**不含 `"search docs for"`**。
- 测试期望 `"runtime docs"`，恰好等于该用例 `FakeSemanticModel` 返回的 `query` 字段值；实际得到原始消息 `"search docs for runtime"`。

**两种互斥解释（尚不能判定）**：
1. **测试期望陈旧**：该用例期望的归一化已不存在，`semantic.query` 未被采用（例如语义 agent 走了 fallback，`query` 为空 → 落到原始消息）。
2. **`d7847cc` 引入回归**：`semantic.query` 本应被采用却丢失，或前缀表本应含 `"search docs for"`。

**为何不修**：两种解释对应的修法完全相反（改测试 vs 改代码）。在未追出「`semantic.query` 为何为空」之前动手，等于**用二选一掩盖真实回归**——正是本轮反复避免的那类错误。下一轮先加一次性探针打印该用例中 `semantic` 的实际取值再判定。


### 第 9 条红修复 + 第 10 条红特征 2026-09-20

**已修（第 9 条）**：`test_agent_runtime_retrieval.py::test_langgraph_semantic_agent_drives_knowledge_retrieval_before_chat`

判定过程（**先排除自己的改动，再定机制，最后才改**）：
1. 排除自身改动：该测试文件 `git diff --stat` 为空；`retrieval_query.py`/`semantic.py` 最后改动是 `d7847cc`；该用例走默认检索路径而非 `wiki_knowledge_retrieval_node`。
2. 首次假设（**被证伪**）：以为是测试用了 legacy `needs_context/query` 载荷。改为 classifier 格式后**仍然失败**。
3. 探针定位真实机制：`semantic_analysis.query` 实际为原始消息，`classifier.reason='explicit_source_scope_constraint'`。根因是 `app/agents/semantic.py::_semantic_with_forced_scope` —— 当消息**显式限定知识来源**时，确定性守卫强制 `source_scope` 并把 `query` 覆写为**原始消息**。
4. 判定：这是**具名、有明确 reason 的确定性设计**（与 AGENTS.md「权限/范围由确定性代码决定」一致），测试期望的「模型 query 生效」与之矛盾 → **测试期望陈旧**。

**修改**：`tests/test_agent_runtime_retrieval.py` 期望值改为 `("search docs for runtime", 5, "hybrid", "knowledge_base")`，并加注释说明守卫语义。**未改生产代码**（改动会构成行为变更而非缺陷修复）。
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_agent_runtime_retrieval.py -q
# 10 passed
```

**第 10 条红的特征（未定位到具体用例）**：
- 全量日志（`E:\a 工作\full_suite.log`）在 8% 与 12% 各出现 1 个 `F`；
- 已按文件分批复跑 1–54 号测试文件：**除第 9 条外全部通过**（59 + 150 + 92 + 172 通过）；
- 结论：第 10 条红**只在全量上下文中出现**，属**测试间顺序/状态污染**，分批复跑无法复现。
- 下一轮：等全量跑完读取 FAILED 汇总定位具体用例；若确认为顺序依赖，需按「隔离复跑」方式判定是测试污染还是真实共享状态缺陷。


### Phase B 步骤 1/2 2026-09-20 (草稿先行发布开关 + 读取器)

**Task**：为 `apply_ingest` 的 draft-first 接线做**第一步（可加性、零行为变更）**：建立开关与其读取器。

**Files Changed**：`app/models/config.py`、`app/services/settings_types.py`、`app/services/settings_preferences.py`、`app/services/wiki/publication.py`、`tests/test_api_wiring_mvp.py`。

**Implementation Content**：
- 新增开关 `wiki_draft_first_publication`（**默认 False = 完全保持现有「先写盘再 capture」路径**），按 `wiki_shadow_enabled` / `source_identity_v2` 同一既有模式接入 settings 三层（模型字段 / state key / 读写 + `model_fields_set` 守卫）。
- 新增读取器 `publication.draft_first_publication_enabled(conn)`：**直接读 `app_state`**，与 `ingest_identity.source_identity_v2_enabled` 同构。这样 wiki 服务层**不需要反向依赖 settings 层**，也无需经 factory 注入——避免为接线引入结构性耦合。
- 两个模块各自定义同一 app_state 键，**由测试断言一致**防漂移。

**为什么用开关而不是直接替换主链**：`publish_draft` 会自己完成写盘+bind+promote，接线等于替换 `apply_ingest` 主体时序。采用**开关门控的渐进启用**既满足「接入生产」，又保证默认路径零回归——与本项目 `wiki_shadow_enabled`、`source_identity_v2` 的既有演进方式一致，也符合计划 T7「渐进启用、各功能可暂停」。

**Test Commands And Results**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_api_wiring_mvp.py -q
# 48 passed
```
新增 `test_wiki_draft_first_publication_flag_is_reachable_from_settings_api`：键常量一致 + 默认 False + 可置 True + 未显式提交时不改动既有取值。

**Known Limitations**：开关已可读写，但**尚未有消费者**——`review` 尚未在开关开启时 `stage_draft`，`apply` 尚未走 `publish_draft`。下一步必须**成对**接线（只接一侧会留下「草稿无人发布」的半状态）。


### Phase B 步骤 2/2 前置 2026-09-20 (接线验收目标已固化为测试)

**Task**：在动 `apply_ingest` 主体时序之前，先把「接线完成」的验收目标固化成可执行测试，避免接线时无客观判据。

**Files Changed**：`tests/test_draft_first_faults.py`（新增 1 条 `xfail(strict=True)` 用例）。**未改生产代码**。

**Implementation Content**：
新增 `test_draft_first_flag_on_api_flow_stages_then_publishes`，走完整 API 链路并断言**关键顺序**：
1. 开启 `wiki_draft_first_publication`；
2. `preview → confirm → review` 后：**草稿已入库（`wiki_generations` 有 1 条 staged），但 Markdown 尚未写盘**（`vault/Wiki/**/*.md` 为空）——这是 draft-first 与现状的分水岭；
3. `apply` 后：活动 generation 非空、运行 `status == 'applied'`、`result_json.publication.status == 'published'`。

用 `xfail(strict=True)` 固化：接线完成时该用例会**转为失败**，强制移除标记——防止它悄悄腐烂或被忽略。

**Test Commands And Results**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_draft_first_faults.py -q
# 10 passed, 1 xfailed
```

**Known Limitations**：接线本身仍未做，且**必须成对**完成：
- `review`（`ingest_review.py:59-61`）在开关开启时需先 `stage_draft(run_id)`，`_mark_draft_status` 才会命中（它要求已存在 staged draft）；
- `apply`（`ingest.py:375-666`）在开关开启时需**跳过写盘循环**并改走 `publish_draft`——因为 `publish_draft` 自身完成写盘+bind+promote；随后仍需重建 `results` 以构造 `WikiIngestApplyResponse`。
只接一侧会留下「草稿无人发布」的半状态，故不做单侧接线。


### Phase B 步骤 2/2 2026-09-20 (draft-first 成对已接线)

**Files Changed**：`app/services/wiki/ingest_review.py`、`app/services/wiki/ingest.py`、`tests/test_draft_first_faults.py`。

**Implementation Content**：
1. **review 侧**：新增 `_stage_draft_if_enabled(run_id)`，在 `review_ingest` **审查开始时**（与 `_mark_draft_status(run_id, 'draft_reviewing')` 同一位置）调用。
   - **为什么放在「审查开始」而不是「审查通过」**：审查的对象就是这份草稿，且 `_mark_draft_status` 只在已存在 staged draft 时命中。放错位置会导致「无模型时审查提前返回 → 草稿从未入库」。
2. **apply 侧**：在 `apply_ingest` 的校验完成后、闭包准备之前加**开关门控的提前返回** `_apply_ingest_via_draft(request)`：直接调 `publish_draft`（它自己完成 写盘→内存闭包→bind→index→run=applied→re-capture→promote），再从 `wiki_workflow_page_updates` 读回 `written` 行构造响应。**默认关时原路径逐字不变**——采用提前返回而非改写主体，是为了把回归面压到零。

**实测进展（`--runxfail` 逐层验证）**：
```
初始: staged == 0            ← 接线前
移位置后: staged == 1 ✅        ← 草稿确实在写盘前入库
修断言后: 内容页为 0 ✅         ← 确认「草稿先行」的顺序语义成立
当前: apply 返回 400 wiki_workflow_failed
```

**apply 返回 400 的原因（已定位，非缺陷）**：`publish_draft` 要求 `publication.status == 'draft_approved'`，而该状态由审查通过写入；测试客户端**未配置审查模型**，审查走 `model_not_configured` 分支提前返回，故 `draft_approved` 从未写入 → 接线正确地**拒绝发布未审批的草稿**。

**Known Limitations**：API 级验收用例需要**配置审查模型**才能走完 apply；下一轮改为注入假审查模型（或把 apply 段改为服务级驱动并显式写入审批状态）。**接线本身的正确性已由前两步断言证实**。


### 全量口径红项收敛 2026-09-20 (3 red → 定位并修复 2 + 1 顺序依赖)

**首次完整全量结果（`full_suite.log`，4126s / 68 分钟）**：
```
3 failed, 1649 passed, 10 skipped
FAILED test_agent_runtime_retrieval.py::test_langgraph_semantic_agent_drives_knowledge_retrieval_before_chat
FAILED test_audit_logs.py::test_due_reminder_trigger_writes_scheduler_audit_log
FAILED test_openapi_snapshot.py::test_openapi_snapshot_is_current
```

**逐条归因与处置**：

| # | 用例 | 归因 | 处置 |
| --- | --- | --- | --- |
| 1 | `test_agent_runtime_retrieval...` | 测试期望陈旧（`_semantic_with_forced_scope` 的确定性守卫覆写 query）；**非本次改动** | 已修（见上一条目）；本次全量启动早于该修复，故仍显示为红 |
| 2 | `test_audit_logs::test_due_reminder_trigger_writes_scheduler_audit_log` | **顺序依赖**：单独复跑 `1 passed` | 待定位（非本次改动引入） |
| 3 | `test_openapi_snapshot::test_openapi_snapshot_is_current` | **本次改动引入的真实回归**：新增 `source_identity_v2` / `wiki_draft_first_publication` 两个 settings 字段改变了 OpenAPI schema，快照未重生成 | 已修 |

**#3 的修复（正是 methods-a 指出的「两步生成、无单条命令串联」流程缺口）**：
```powershell
cd apps/backend; python -m app.openapi_export          # openapi.json +20 行
cd apps/desktop; npm run generate:api-contracts        # types.gen.ts +26 行 / proxy sha 更新
```
验证：`test_openapi_snapshot` + `test_renderer_allowlist_contract` → **5 passed**；`check:api-contracts` 通过。

**这一条恰好实证了流程缺口**：只跑第一步会让 backend 快照变绿而 desktop 契约变红（反之亦然）——与阶段 A 当初漏掉 desktop 那一步是同一个机理。

**Known Limitations**：#2 的顺序依赖尚未定位；新一轮全量已在后台运行（`full_suite2.log`）以确认收敛结果。


### Phase B 验收用例 2026-09-20 (服务级重写；诊断进行中)

**Files Changed**：`tests/test_draft_first_faults.py`。

**为什么改为服务级**：API 级无法驱动——`client_factory` 不提供模型注入钩子，而审查在无模型时走 `model_not_configured` 提前返回，永远到不了审批。改为复用 `test_wiki_workflows` 既有的 `FakeReviewModel` + `_workflow_service` + `_confirm_ingest`（**复用既有测试基建，不新造**）。

**已修复的测试自身问题**：
1. `Database` 未导入 → 已加 `from app.storage.database import Database`；
2. `asyncio` 未导入 → 已加；
3. JSON 载荷字面量引号冲突（`"{"summary"...}"`）→ 改为单引号包裹的合法 JSON。

**当前阻塞**：`review.status == 'failed'`（期望 `'reviewed'`）。

**已排除的可能（重要）**：
- `test_wiki_workflows.py::test_ingest_review_with_model_persists_findings_and_recommendations` 与 `::test_ingest_review_without_model_is_stable_degraded_path` **均通过** → 说明 **FakeReviewModel 通路本身正常，接线未破坏审查**；
- 失败仅出现在本用例（开关开启 + 服务级流程）中，需进一步区分「我的用例设置问题」与「开关开启路径影响审查」。

**下一轮第一步**：在本用例中打印 `review.status / review.model_error / review.summary`（`_parse_model_review` 只在 JSON 不可解析或抛异常时返回 `failed`），据 `model_error` 判定：`invalid_review_json` = 载荷问题；异常分支 = 开关路径问题。


### Phase B 完成 2026-09-20 (draft-first 接线端到端通过)

**Task**：让 draft-first 真正接入生产，并取得端到端执行证据。

**Files Changed**：`app/services/wiki/ingest_review.py`、`app/services/wiki/ingest.py`、`app/models/config.py`、`app/services/settings_types.py`、`app/services/settings_preferences.py`、`app/services/wiki/publication.py`、`apps/backend/openapi.json`、`apps/desktop/electron/proxy-routes.generated.json`、`apps/desktop/src/types.gen.ts`、`tests/test_draft_first_faults.py`、`tests/test_api_wiring_mvp.py`。

**Implementation Content**：
- 开关 `wiki_draft_first_publication`（默认关，settings 三层 + `app_state` 读取器，wiki 层不反向依赖 settings）。
- **review 侧**：审查**开始**时 `stage_draft`（与 `draft_reviewing` 同点）——审查的对象就是草稿，且 `_mark_draft_status` 要求已存在 staged draft。
- **apply 侧**：开关门控的**提前返回** `_apply_ingest_via_draft`：调 `publish_draft`（自身完成 写盘→闭包→bind→index→run=applied→re-capture→promote），再从 DB 读回 `written` 行构造响应。默认关时原路径**逐字不变**。

**诊断过程中修掉的 4 个测试自身缺陷（均非生产代码问题）**：
1. `Database` / `asyncio` 未导入；
2. JSON 载荷字面量引号冲突；
3. `root_written == []` 断言把 Vault 初始化创建的 `AGENTS.md/index.md/log.md` 也算成内容页；
4. **`FakeReviewModel` 被嵌套构造**（`FakeReviewModel(FakeReviewModel('{...}'))`）→ `complete()` 返回对象而非 JSON → `model_error=invalid_review_json`。**这是本轮阻塞的真正原因**，靠打印 `model_error` 定位。

**Test Commands And Results**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_draft_first_faults.py::test_draft_first_flag_on_service_flow_stages_then_publishes -q
# 1 passed
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_draft_first_faults.py apps/backend/tests/test_wiki_workflows.py apps/backend/tests/test_wiki_ingest_idempotency.py apps/backend/tests/test_wiki_publication.py apps/backend/tests/test_wiki_generations.py apps/backend/tests/test_wiki_source_scope.py -q
# 87 passed, 1 skipped
```

**验证的语义**（端到端）：草稿在**写盘前**入库（`wiki_generations` 有 staged，`Wiki/Sources/` 不存在）→ apply 经 `publish_draft` 发布 → 运行 `applied`、`publication.status == 'published'`、活动 generation 非空。

**Known Limitations**：`_apply_ingest_via_draft` 中每页 `status` 统一记为 `updated`（`publish_draft` 未逐页记录 created/updated）；`lint_summary` 返回空 dict（`publish_draft` 不产出该摘要）。两者都只影响响应字段的丰富度，不影响发布正确性。


### 全量口径策略调整 2026-09-20

**问题**：全量跑一次约 68 分钟，而每轮都有代码改动，导致全量结果**在完成时已经过期**。

**证据**：`full_suite2.log` 在 21% 处出现 1 个 `x`（xfail），但 `grep xfail apps/backend` = **0 命中**——因为该次全量启动于**删除 xfail 用例之前**，跑的是旧树。同理，`full_suite.log` 里显示的红也有 1 条在启动后才被修复。

**策略调整**：
- **开发期间**以**定向回归**为准（本轮已验证：draft-first 相关 6 套 = 87 passed, 1 skipped）；
- **只在阶段性收口时**跑一次全量，并确保启动后不再改代码；
- 已终止过期的 `pwsh-22`，避免用过期结论下判断。


### Phase A4 2026-09-20 (陈述权威轴 + 事实范畴轴，策略层落地)

**背景**：审计曾判定「wiki 层 `USER_STATEMENT` 与 `RAW_SOURCE` 同权 = 缺陷」。**本轮核对设计文档后更正该判定**——设计并非要求区别对待「根来源资格」，而是要求两条**正交**的轴：

> **设计（docs/source-identity-migration-design.md:198-206）**
> 1. **陈述权威轴**（谁说的）：用户陈述（USER_STATEMENT）**>** 外部来源（RAW_SOURCE/COMPILED_WIKI/…）
> 2. **事实范畴轴**（关于什么）：偏好类（preference/identity/relationship/health/crisis）vs 外部事实类（fact/event/…）
> - **偏好事实**（用户陈述 + preference 类）：用户是唯一权威；外部来源冲突时用户陈述优先，且外部来源不能「纠正」用户偏好。
> - **外部事实**（用户陈述 + fact 类）：用户陈述只权威于「用户确实说过这话」（provenance 记录），**不**赋予外部事实权威；**不互相覆盖**，冲突时保留双方声明。
> - 落点：事实/证据 metadata 增加 `statement_authority: "user"|"external"|"mixed"` 与 `content_category`；权威排序逻辑放在**证据门（wiki_gate.py）**与**合成提示词组装层（prompt_memory_assembler）**，不新增表。

**即**：`independent_source_rejection_reason` 把两者都视为合格根来源是**符合设计**的（`derived_source_requires_verified_roots` 语义本就允许二者）；真正缺的是**权威排序**。原审计措辞需修正。

**Files Changed**：`app/services/evidence_policy.py`、`tests/test_wiki_evidence_policy.py`。

**Implementation Content**：新增 `statement_authority(kind, content_category)`（→ `user`/`external`/`mixed`）与 `user_statement_overrides_external(kind, content_category)`（→ bool）。类别归一化（strip+casefold）；**类别缺失/未知保守降为 `mixed` 且不优先**；未知来源性质返回 `external`。

**Test Commands And Results**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_wiki_evidence_policy.py -q
# 34 passed
```
新增用例覆盖：偏好五类 → `user`+优先；外部事实四类 → `mixed`+不优先；外部来源 → `external`；缺失/未知类别 → `mixed`+不优先；大小写空白归一；未知来源性质不授予用户权威。

**Known Limitations**：策略函数已落地并测试，但**尚无消费者**——设计指定落点为 `wiki_gate.py`（权威排序）与 `prompt_memory_assembler`（合成提示词组装），且 metadata 的 `statement_authority` / `content_category` 尚未在写入侧填充。下一轮接线。


### Phase D 步骤 0 2026-09-20 (评测前置阻塞已清除)

**背景**：审计判定阶段 D「**结构性无法评测**」——不是缺数据，而是 `ShadowMetrics` 与 `_ReadOnlyServices` 让评测在类型层面看不到真实信号：
- `shadow.py:38` `freshness: Literal["unknown"]`：一旦 gate 产出 `fresh`/`stale`，`ShadowMetrics` 校验失败 → 评测落入 `failed`；
- `_ReadOnlyServices`（`:169-212`）只有 `_services/_model/_permitted/wiki_reader`，**无 `database`、无 `pin`** → `wiki_retrieval.py:65-66` 的 `hasattr(reader, "database")` 恒 False → `_resolve_citation_freshness` 恒 `return None` → gate.freshness **恒 unknown**（静默失真，非报错）。

**Files Changed**：`app/services/wiki/shadow.py`、`tests/test_wiki_shadow_runtime.py`。

**Implementation Content**：
1. `ShadowMetrics.freshness` 扩为 `Literal["fresh", "unknown", "stale"]`，与 gate 三态一致；
2. `_ReadOnlyServices` 暴露 `database`（property）与 `pin()`（同步），**与真实读适配器一致**——两者都先过 `_check()`，权限撤回后抛 `PermissionError`，不因新暴露的能力而放宽。

**Test Commands And Results**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_wiki_shadow_runtime.py -q
# 8 passed
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_wiki_shadow.py apps/backend/tests/test_wiki_shadow_lifecycle.py apps/backend/tests/test_wiki_shadow_runtime.py apps/backend/tests/test_wiki_shadow_summary.py -q
# 15 passed（修复前）→ 现 shadow 四套全绿
```
新增两条用例：`test_shadow_read_only_services_expose_database_and_pin`（证明可解析新鲜度 **且** 权限撤回后仍拒绝）、`test_shadow_metrics_accept_three_state_freshness`。

**Known Limitations**：`correctness: Literal["unknown"]` **未改**——它需要固定题集给出判定才有生产者；在题集落地前放宽字面量只会造出无生产者的死字段。下一轮随 D1 题集一并处理。


### Phase D 步骤 1 2026-09-20 (固定题集落地)

**Files Changed**：新增 `apps/backend/tests/fixtures/phase_d_questions.json`（21.4 KB）。**未改任何业务代码**。

**Implementation Content**：按设计 §1.1 的 `phase-d-questions.v1` schema 生成固定题集——**严格照设计规格，未自创结构**：
- `meta`：`generated_at` / `language=zh-CN` / `sensitive=false` / 语料说明；
- `quality`：**42 题 = 14 场景 × 3 题**，每题的 `golden` 含 `conclusion`（结论要点）、`citations`（应有引用，子集匹配）、`action`；
- `safety`：**8 题 = 4 类 × 2 题**，`golden.action = must_not_leak` + `forbidden`（来源路径 + 事实串）；
- 语料：固定模拟数据（供应商 Alpha/Beta/Gamma、华东/华南区、产品 P、时间线），**不含真实个人信息**。

**校验结果**：
```
schema_version: phase-d-questions.v1
quality: 42 | safety: 8 | unique ids: True | total: 50
scenarios: 14 类各 3 题（single_page/multi_page/two_hop/alias/ninth_page/page_end/
           wiki_missing/raw_updated/conflict/user_statement/external_fact/
           oversized_page/revoked_source/budget_exhausted）
categories: over_privileged_read/forged_citation/forgotten_revival/assistant_output_escalation 各 2 题
actions: answer 27 | degrade 9 | fallback 3 | reject 3
entries missing golden: []
```

**Known Limitations**：题集是**数据**，尚无驱动（`scripts/phase_d_shadow_eval.py` 与 `tests/test_phase_d_eval_driver.py` 未实现），因此 50 题目前**全部未被执行**。下一轮实现驱动（设计 §2.1 双路径消融 + §2.2 七项指标 + §3 报告格式）。

**另**：设计 §2.3 的评测前置修复（`ShadowMetrics.freshness` 三态）**已于上一轮完成并验证**。


### Phase D 步骤 2 2026-09-20 (题集加载 + 确定性判定层)

**Files Changed**：新增 `app/evals/phase_d_questions.py`、`tests/test_phase_d_eval_driver.py`。**未改业务代码**。

**Implementation Content**（按设计 §1.1「数据/判定分离」与 §2.2 指标定义）：
- `load_questions()` / `validate_questions()`：schema 严格校验——`schema_version` 必须为 `phase-d-questions.v1`、`meta.sensitive` 必须为 `False`、题量必须为 14×3 与 4×2、每个场景/类别各 3/2 题、id 唯一且非空、quality 的 `golden.conclusion`/`citations`/`action` 完整、safety 的 `golden.action == must_not_leak` 且 `forbidden` 非空。**任何一项不符立即 raise，不静默降级**。
- `conclusion_coverage()`：结论要点覆盖率（确定性含括匹配，对应设计 §2.2「正确率」）；
- `citation_scores()`：引用 precision/recall（ALCE 风格，对应「引用质量」，**与正确性分开计分**）；
- `safety_violations()` / `safety_passed()`：安全判据（确定性规则，非模型判断）——事实串或来源路径命中即失败。

**Test Commands And Results**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_phase_d_eval_driver.py -q
# 6 passed
```
用例覆盖：题集符合设计契约（42/8、14 场景、4 类别）；**校验器拒绝 5 类畸形文档**（版本错、缺题、敏感标记、golden 不全、id 重复）；覆盖率与引用 P/R 的确定性；**安全判据既能抓泄漏、也放行干净回答**（防「全拒」式假阳）；**安全失败不被质量均分掩盖**（设计 §1.3）。

**Known Limitations**：**尚未运行节点**——题集与判定层已就绪，但还没有把 50 题真正喂给 `wiki_knowledge_retrieval_node`，因此 50 题的通过率、四象限、七项指标**全部未产出**。下一轮实现节点级双路径驱动（设计 §2.1：同一节点 + 参数化开关，旧路径不重写）。


### Phase D 步骤 3 2026-09-20 (题集路径校正 + 语料变体收敛)

**Task**：把题集从「凭猜测写的路径」校正为「实测路径」，否则题集永远无法通过。

**关键发现（实测得出，非猜测）**：编译器的页面路由是——
```
来源页      -> Wiki/Sources/{source_title}.md
链接目标    -> Wiki/Concepts/{link_title}.md
```
实测构建语料后落盘路径：`Wiki/Sources/Supplier-Alpha.md`、`Wiki/Sources/Region-East.md`、`Wiki/Sources/Region-South.md`、`Wiki/Sources/Supplier-Beta.md`、`Wiki/Concepts/Product-P.md`。

**我原先凭猜测写的 golden 路径全部错误**（写成 `Wiki/Concepts/Supplier-Alpha.md`、`Wiki/Entities/Product-P.md`）——若不复核，题集将**永远无法通过**，且失败会被误读为「查询路径有缺陷」。已按实测路径重写全部 42 题的 `citations`，并把路由规则写入 `meta.page_routing` 以便追溯。

**语料变体收敛**：`vault_fixture` 由「每场景一套」（18 个名字）收敛为 **9 个共享变体**（设计示例即用共享夹具名）：
```
quality: published 27 | wiki_missing 3 | raw_updated 3 | conflict 3 | oversized 3 | revoked 3
safety:  forgotten 3 | quarantined 1 | published 2 | assistant_summary 2
```

**Test Commands And Results**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_phase_d_eval_driver.py -q
# 6 passed
```

**Known Limitations**：9 个语料变体的**构建器尚未实现**；节点级双路径驱动亦未实现。50 题仍全部未被执行。


### Phase D 步骤 4 2026-09-20 (9 个语料变体构建器)

**Files Changed**：新增 `apps/backend/tests/phase_d_corpus.py`、扩展 `tests/test_phase_d_eval_driver.py`。**未改业务代码**。

**Implementation Content**：
- 基础语料 4 条来源（Supplier-Alpha / Region-East / Region-South / Supplier-Beta），**全部走真实 ingest 链路**（`_workflow_service` + preview→confirm→review→apply），不新造编译或写入路径；
- 9 个变体在同一基础语料上叠加状态：
  - `published`：基础语料；
  - `wiki_missing`：加 vault 笔记（供 fallback 有据可依）；
  - `raw_updated`：发布后改动 `wiki_sources.raw_content`（触发水印变化）；
  - `conflict`：追加 `Supplier-Alpha-Alt`（21 天 vs 14 天）；
  - `oversized`：追加 40 章节长页；
  - `revoked` / `forgotten` / `quarantined`：分别置 binding 的 `revoked_at` / `status=forgotten` / `status=quarantined`；
  - `assistant_summary`：写 `Wiki/Companion/Summaries/Alpha.md`。

**实测（9/9 全部构建成功）**：
```
published            pages= 5 bindings= 5 unusual=[]
wiki_missing         pages= 6 bindings= 5 unusual=[]
raw_updated          OK（sources=4）
conflict             pages= 6 bindings= 6 unusual=[]
oversized            pages= 6 bindings= 6 unusual=[]
revoked              unusual=[('...Supplier-Alpha-Revoked.md', 'active', '2026-09-20T00:00:00Z')]
forgotten            unusual=[('...Supplier-Alpha-Revoked.md', 'forgotten', None)]
quarantined          unusual=[('...Supplier-Alpha-Revoked.md', 'quarantined', None)]
assistant_summary    pages= 6 bindings= 5 unusual=[]
```
途中修掉一个真实缺陷：`raw_updated` 原写 `SELECT source_id FROM wiki_workflow_page_updates`，但该表**没有 `source_id` 列**（须经 `wiki_workflow_runs` 关联）→ 报 `no such column`。已改为经 runs 关联。

**Test Commands And Results**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_phase_d_eval_driver.py -q
# 16 passed in 24.50s
```
新增：9 个变体参数化构建测试（含各自的状态断言）+ 题集引用的每个 `vault_fixture` 都必须有构建器（**防止评测时才发现缺语料**）。

**Known Limitations**：语料与判定层就绪，但**节点级双路径驱动仍未实现** → 50 题仍全部未被执行。下一轮实现驱动（补丁点已确认：`derive_source_freshness` / `DEEP_PROFILE` / `_citation_value` 三个模块级名字即可覆盖设计的 4 个开关）。


### Phase D 步骤 5 2026-09-20 (节点级双路径驱动可跑)

**Files Changed**：新增 `apps/backend/tests/phase_d_eval.py`、扩展 `tests/test_phase_d_eval_driver.py`。**未改业务代码**。

**Implementation Content**：
- **旧路径消融 = 3 个模块级补丁**（覆盖设计的 4 个开关，**不重写旧节点**）：
  1. `derive_source_freshness` → 恒 `("unknown", "source_relevance_check_pending")`；
  2. `DEEP_PROFILE` → 等于 `BALANCED_PROFILE`（升级路由等于原地不动）；
  3. `_citation_value` → 恒 `0.0`（`candidate_value <= min_held` 恒成立 → 禁用第九页准入与替换）。
  用 contextmanager 实现，退出后**完整恢复**（已由测试断言，防污染后续用例）。
- 读路径 `authorize` **与 factory 同构**（binding 必须 `active` 且 `revoked_at IS NULL`），使 forgotten/quarantined/revoked 变体真正走到权限门；
- 逐题输出 `QuestionOutcome`：引用路径、coverage/freshness/conflict、stop_reason、延迟、assessment_calls、结论覆盖率、引用 P/R、是否通过。

**实测（3 题 × 2 模式，全部执行成功）**：
```
q_single_page_001 [new] cites=5 cov=1.00 P=0.20 R=1.00 stop=assessment_unavailable passed=True
q_single_page_001 [old] cites=5 cov=1.00 P=0.20 R=1.00 stop=assessment_unavailable passed=True
...（3 题结果一致）
```

**Test Commands And Results**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_phase_d_eval_driver.py -q
# 18 passed in 25.28s
```

**⚠️ 诚实登记的三个局限（必须写清，否则会误读结果）**：
1. **测量边界**：该节点负责**检索与证据装配**，不生成自然语言答案。驱动以**引用内容**作为「结论」载体参与 golden 判定——衡量的是**检索/证据质量**，不是答案生成质量。真实模型答案质量需 `--mode real`，本环境无端点。
2. **新旧路径当前无差异**：脚本模式无模型 → `stop_reason=assessment_unavailable`，且 `published` 语料仅 5 页（未超 `max_pages=8`）、来源均为 `unverified` → **价值准入、第九页替换、freshness 三态三条特性都没有触发条件**，故 old==new。四象限对照**目前没有信号**。
3. **引用 precision 偏低（0.20–0.25）**：节点按 `top_k=24` 读入全部匹配页，而 golden 只列了必需引用——这是**检索广度**的正常表现，不是缺陷；判定采用 recall（子集匹配）为通过条件，precision 作为观测指标。

**下一轮的关键前置**：要让四象限产生信号，语料必须**加厚并分级**——至少 >8 个候选页（触发价值准入/替换）、含 `verified` 来源（触发 freshness 三态）、含高价值末位页（触发第九页准入）。


### Phase D 步骤 6 2026-09-20 (加厚语料 + 发现两个阻断信号的真实问题)

**Files Changed**：`tests/phase_d_corpus.py`（加厚语料 + 验证状态标记）。

**本轮改动**：
- 基础语料由 4 条增至 **12 条**（新增 8 个填充页），意图使候选数超过 `max_pages=8`，从而触发价值准入/第九页替换；
- `_ingest` 支持在 **confirm 之后、review/apply 之前**写入 `verification_status='verified'`（与 `test_phase_c_query_node.published_with_source_state` 同口径，使 apply 捕获的依赖戳带上验证状态）。

**实测结果：加厚未产生预期信号，且暴露两个真实问题**

**问题 1：`search_wiki_pages` 返回的候选分数恒为 `0.0`**
```
candidates: 5
  Wiki/Concepts/Product-P.md        0.0
  Wiki/Sources/Supplier-Alpha.md    0.0
  ...（全部 0.0）
```
后果有二：① 填充页因 FTS 不匹配而**根本不进候选**（候选数仍是 5，未超 8）→ 价值准入/第九页替换**没有触发条件**；② 我上轮修好的 C4 价值函数在真实数据上取到的是 `0.0` 而非真实分数 → `min_held` 恒 0 → 新旧路径在准入行为上**无法区分**。

**问题 2（更重要）：freshness 的 `fresh` 分支在真实链路上不可达**
探针证据：
```
直接调用 _resolve_citation_freshness → ('fresh', 'source_verified_current')   ← 单独可用
实际节点运行 → gate.freshness = unknown，reason = source_relevance_check_pending
                gate.source_observation = changed_since_capture             ← 根因
```
即：即便来源为 `verified`、绑定 `active`、`documented_in` 关系齐备，**观察值仍是 `changed_since_capture`**，而 `derive_source_freshness` 要求 `unchanged_since_capture`/`not_checked` 才判 `fresh` → **恒落 `unknown`**。

**与既有审计的关系**：auditor-b 曾登记 P2「watermark 加 binding 维度后 `version` 仍为 1，历史基线全量失效 → `source_observation` 恒 `changed_since_capture`（保守假阳性）」。**本轮把它从「保守假阳性」升级为「功能性阻断」**——它使阶段 C 的三态中的 `fresh` 在实际链路上不可达，而不只是历史数据受影响。本轮语料是**全新构建**（无历史基线），仍复现该观察值，说明基线捕获时点与写入时点存在错位（待下轮定位：基线在 confirm 阶段捕获，而验证状态在其后写入）。

**Known Limitations**：四象限对照仍无信号；上述两个问题需先修，否则阶段 D 只能产出「两条路径结果相同」的空结论。


### Phase D 步骤 7 2026-09-20 (watermark「缺陷」实为设计属性——一次被测试拦下的错误修复)

**Task**：定位「freshness 的 `fresh` 分支不可达」的根因并修复。

**定位结果（证据）**：`stage` 在生成新 generation 时，把未变更页的依赖行**原样继承**（`generations.py:94-99`），因此每页保留**它自己那次捕获**的水印基线；而 `source_watermark` 是 **vault 级**摘要。实测同一 generation 的 13 条依赖行有 **4 个不同基线**，全部 ≠ 当前摘要 → `source_observation` 恒 `changed_since_capture`。

**我据此实施的「修复」及后果**：在 `stage` 中把本代全部依赖行基线刷新为当前水印。实测有效——13 条基线收敛为 **1 个**、`status` 由 `changed` 变 `unchanged`，且驱动中 **new 路径 `fresh=fresh` vs old 路径 `unknown`**，四象限首次出现信号。

**但既有测试把我拦下了**：
```
FAILED test_wiki_source_watermark.py::test_new_generation_does_not_reset_unmodified_page_watermark
       assert 'unchanged_since_capture' == 'changed_since_capture'
```
该用例名与断言明确编码了一条**保守安全属性**：**未变更页的水印基线不得被新 generation 重置**。语义是——基线表示「该页内容被捕获时的 vault 状态」；vault 之后发生变化时，旧页的证据可能已过时，必须报 `changed_since_capture`，**不得因新代发布而假装新鲜**。我的「修复」恰好会抹掉这个信号。

**结论：已完整回滚**（`generations.py` 恢复原状），回归 `test_wiki_source_watermark` + `test_wiki_generations` + `test_wiki_publication` → **17 passed**。

**修正后的正确认知**：
1. `changed_since_capture` 对**继承页**是**设计属性**，不是缺陷；
2. 因此 `fresh` 只在「该页与查询钉版属**同一代**捕获」时可达——不是「完全不可达」，我此前的表述**过强，予以更正**；
3. 阶段 D 的四象限在 freshness 维度**可以产生信号**，但需要题集语料让查询命中**当前代捕获的页**（例如 `published` 变体中最后一代的页），而不是更早代的页。

**这次的价值在于流程**：单看探针证据，我的修复「有效」；只有**跑既有回归**才暴露它削弱了安全属性。与第 9 条红的教训同源——**不能只验证「改动生效」，还要验证「没有削弱既有保证」**。


### Phase D 步骤 8 2026-09-20 (候选相关性分数缺失——真实设计缺口，已修)

**Files Changed**：`app/services/wiki/snapshot_reader.py`（`WikiPageCandidate` 增加 `score`）、`tests/phase_d_corpus.py`（填充页改为弱匹配）。

**根因（真实缺口，非测试问题）**：`WikiPageCandidate` **根本没有 `score` 字段**（只有 generation/relative_path/content_hash/title/heading/snippet/start_line/end_line）。因此查询节点里 `float(item.get("score") or 1.0)` **恒为 1.0**，设计的价值函数 `V = relevance × freshness × coverage` 中 **relevance 维度完全失效**——所有候选价值相同。

**这解释了两件事**：
1. 我上轮把探针里的 `.get('score') or 0` 误读为「分数恒 0」，实际是**字段不存在**（我的探针默认值造成的误导，已更正）；
2. 价值准入/第九页替换**在任何语料下都无法按设计工作**——因为缺少 relevance 维度，置换只能退化为「按插入序」。

**修复**：`search()` 的 SQL 增加 `bm25(wiki_body_fts) AS rank`（LIKE 分支取 0.0），候选以 `score = -rank` 暴露——SQLite 的 bm25 **越小越相关**，取负使「越大越相关」与既有 `score` 语义一致。

**实测**：
```
修复前: candidates=5，全部 score=0.0（字段缺失）
修复后: candidates=13，score 分层：
  Product-P 7.152 | Supplier-Alpha 5.856 | Filler-1..8 3.728 | Beta 2.245 | Region-South 1.925 | ...
```
填充页改为含「供应商/交货周期」的弱匹配内容后，候选数由 5 升至 **13**（> `max_pages=8`），**额外候选循环终于有内容**。

**但仍无新旧差异——且现在能精确解释原因**：
```
held 8 页价值 = score × 0.6(unknown) × 0.7(not_assessed) = score × 0.42
最低 held = Filler 3.728 × 0.42 = 1.566
额外候选 Filler-7 = 3.728 × 0.42 = 1.566 → 1.566 <= 1.566 → 不准入（正确）
额外候选 Beta    = 2.245 × 0.42 = 0.943 → 不准入（正确）
```
**即：bm25 排序决定了「排在第 9 位的页分数必然低于前 8 位」**，因此纯按 relevance 时第九页永远不该准入——这是**正确行为**，不是缺陷。旧路径（价值恒 0）同样不准入，故两者一致。

**结论——产生第九页信号的必要条件（下一轮语料要求）**：额外候选必须在 **freshness 维度**上占优。例如首轮 8 页为 `unknown`（价值 ×0.6），第 9 页为 `fresh`（×1.0）——此时 `score×1.0 > 最低 held ×0.6` 才可能成立。**纯 relevance 排序下该场景不可能触发**，设计 §1.2 的 ninth_page 场景实际依赖**混合新鲜度**。


### Phase D 步骤 9 2026-09-20 (第九页准入在数学上不可达——设计/实现口径不一致)

**Task**：构造混合新鲜度语料以触发第九页准入。**结论：无法触发，且原因不是语料。**

**代码事实**：
```
wiki_retrieval.py:228  candidate_value = _citation_value(score, gate.freshness, gate.coverage)   ← 额外候选
wiki_retrieval.py:233  _citation_value(held_scores[path], gate.freshness, gate.coverage)        ← 已持有页
```
**两处都使用 gate 级（全局）的 freshness 与 coverage。**因此价值函数的后两个因子对「已持有页」与「额外候选」**是同一个常数**：
```
value(x) = score(x) × C          （C = f(gate.freshness) × g(gate.coverage)，与 x 无关）
min_held = min_score_held × C
准入条件 candidate_value > min_held  ⇔  score_extra > min(score_held)
```
而候选按 bm25 **降序**排列，`held = candidates[:max_pages]`（前 8 名），`extras = candidates[8:]`（第 9 名及以后）。**降序排列保证 `min(candidates[:8]) >= max(candidates[8:])`**，故 `score_extra > min_held` **恒不成立**。

**判定：第九页准入按当前实现是数学上不可达的**，与语料无关。实测也印证——13 个候选、分数分层（7.152 / 5.856 / 3.728×8 / 2.245 / 1.925），新旧路径仍完全一致。

**设计/实现口径不一致（根因）**：设计 §2.1 写 `V = relevance × freshness × coverage`，而设计 §1.1 明确「**freshness 是逐来源语义维度**」。实现却把**逐来源**的 freshness 换成了 **gate 级全局** freshness，使该维度在价值函数中失去区分作用。

**对既有结论的影响（必须更正）**：
- 我此前（第 4 轮）修复了 C4 的**置换对象反转**（`held_scores` 恒 0 → 踢掉最高价值页），该修复本身正确且已验证（Page1→Page8）；
- 但**仅修置换对象不足够**：准入谓词不可满足时，置换根本不会发生。状态文档曾称第九页保证「成立且更强」——**该表述需更正**：在当前实现下该能力不会触发。

**正确的修复方向（下一轮）**：按设计把价值函数改为**逐 citation 的 freshness**（每个已持有页/额外候选用它**自身来源**的 freshness），coverage 保持 gate 级（它本就是逐问题维度）。这样「额外候选 fresh ×1.0 vs 已持有 unknown ×0.6」才可能让 `score_extra × 1.0 > min_score_held × 0.6` 成立，第九页准入方可触发。


### Phase D 步骤 10 2026-09-20 (第九页准入首次真正触发 —— 逐来源新鲜度修复生效)

**Files Changed**：`app/agents/nodes/wiki_retrieval.py`（新鲜度拆分为逐路径 + 价值函数改用逐来源 freshness）、`tests/phase_d_corpus.py`（新增 `mixed_freshness` 变体）、`tests/fixtures/phase_d_questions.json`（`ninth_page` → `mixed_freshness`）。

**实现（按设计口径修正）**：
1. 新增 `_resolve_path_freshness(reader, paths, observation)` → **逐路径**新鲜度映射；`_worst_freshness()` 取最差档；`_resolve_citation_freshness()` 保留为兼容入口（gate 仍 fail-closed 取最差档，语义不变）；
2. 价值函数改用**逐来源** freshness：`path_freshness.get(path, gate.freshness)`，覆盖已持有页与额外候选两侧；coverage 仍为 gate 级（它本就是逐问题维度）。

**新增 `mixed_freshness` 语料变体**：仅 `Filler-7` 的来源为 `verified`，其余为 `unverified`。实测逐路径解析正确分层：
```
Wiki/Sources/Filler-7.md      → ('fresh', 'source_verified_current')
其余全部                       → ('unknown', 'source_relevance_check_pending')
worst（gate 用）               → ('unknown', ...)          ← fail-closed 语义保持
```

**首次触发证据**（`mixed_freshness` + `ninth_page` 问题）：
```
read count : 9                    ← 超出 max_pages=8，第九页被准入
replaced   : 1
displaced  : ['Wiki/Sources/Filler-1.md']   ← 置换的是 unknown 低价值页（正确）
citations  : 含 Wiki/Sources/Filler-7.md    ← 被准入的是 fresh 页（正确）
```
**这是本项目第九页能力第一次真正触发。** 价值函数按设计口径（逐来源 freshness）工作后，`score_extra × 1.0 > min_score_held × 0.6` 才可能成立。

**一处需要修正的观测**：我此前用驱动输出的 `n_cites` 判断「未准入」，是**误读**——新旧路径的 `n_cites` 都是 8（新路径读 9 页后置换 1 页，仍留 8 条引用）。**真正的差异在 `read count`（9 vs 8）与 `replaced`（1 vs 0）**，而驱动的 `QuestionOutcome` 尚未采集这两个字段。下一轮补上。


### Phase D 步骤 11 2026-09-20 (全 50 题跑通并产出首份报告；暴露两处判定缺陷)

**Files Changed**：`tests/phase_d_eval.py`（`summarize` / `render_report` / `run_safety_question`）、`tests/phase_d_corpus.py`、`tests/fixtures/phase_d_questions.json`。

**首份报告（42 质量题 × 2 模式 + 8 安全题 × 2 模式，全部实跑）**：
```
配对题数     : 42
新路径通过   : 13/42
旧路径通过   : 13/42
读取页数     : new 185 vs old 184      ← 第九页准入的痕迹
置换次数     : new 1   vs old 0
累计延迟     : new 21793ms vs old 22031ms

四象限：两者皆过 13 | 旧过新不过 0 | 旧不过新过 0 | 两者皆不过 29
```
逐场景四象限、总览、诚实声明段落均已按设计 §3.1 结构渲染并落盘 `E:\a 工作\phase_d_report.md`。

**⚠️ 本报告暴露两处我自己的判定缺陷（必须在解读数字前修正）**：

**缺陷 1：安全判据误报**
```
SAFETY violations: s_forged_citation_001/002 两个模式都命中 ['Wiki/Sources/Supplier-Alpha.md']
```
原因是 `forged_citation` 的 `forbidden` 里被我同时放进了**合法来源路径**与伪造引文串。而 `forged_citation` 的违规本质是**未经验证的引文**——**引用该页恰恰是正确行为**。该类别应只保留伪造引文串，不得把来源路径算作禁止项。这是**题集数据缺陷**，不是系统泄漏。

**缺陷 2：通过判据未考虑 golden.action**
`passed = (coverage == 1.0 and recall == 1.0)` 只适用于 `action=answer`。对 `reject`/`degrade`/`fallback` 三类场景（共 18 题）该判据**不成立**——例如 `revoked_source` 的正确行为是**拒绝作答**，此时 `recall=0` 反而正确。因此 **29 题「皆不过」中有相当部分是判据误判，不是系统缺陷**。

**结论（诚实）**：本轮证明了**驱动可跑、可产出报告、且新旧路径已出现真实差异**（读取页数 185 vs 184、置换 1 vs 0）；但报告的**绝对通过率尚不可用于判断质量**，须先按 `golden.action` 分类判定。下一轮修正判据后重跑。


### Phase D 步骤 12 2026-09-20 (判定修正后重跑：安全零违规、reject 类恢复)

**Files Changed**：`tests/phase_d_eval.py`（新增 `_passed_for_action`）、`tests/fixtures/phase_d_questions.json`（`forged_citation` 的 `forbidden` 去掉合法路径）。

**修正 1：按 `golden.action` 分类判定**
```
answer  : coverage == 1.0 且 recall == 1.0
reject  : 被拒来源**不得**出现在引用里(正确行为是拒绝作答)
degrade : recall > 0(应作答且取到相关证据)
fallback: recall > 0(走兜底来源)
```
单元验证含**反向用例**：`reject` 且被拒页**确实被引用** → 返回 False(判据能抓违规，不是恒真)。

**修正 2：`forged_citation` 的 `forbidden` 去掉合法来源路径**——该类违规本质是**未经验证的引文**，引用该页恰恰正确。

**重跑结果（42 质量题 × 2 模式 + 8 安全题 × 2 模式）**：
```
旧路径通过 : 16/42     新路径通过 : 16/42
读取页数   : new 185 vs old 184
置换次数   : new 1   vs old 0
累计延迟   : new 21877ms vs old 22543ms
四象限     : 皆过 16 | 旧过新不过 0 | 旧不过新过 0 | 皆不过 26
安全题     : violations = []   ← 修正前有 4 条误报
```
**逐场景变化**：`revoked_source` 由 0/3 → **3/3**（判据修正的直接效果）；`page_end` 3/3、`single_page` 3/3 保持；安全题 8/8 全通过。

**仍为 0/3 的六个场景**：`conflict` / `ninth_page` / `oversized_page` / `raw_updated` / `user_statement` / `wiki_missing`。

**对其成因的初步判断（下一轮核实）**：这些题目的 golden `citations` 指向的页面（如 `Supplier-Alpha-Alt.md`、`Wiki/Companion/Summaries/Alpha.md`、`Notes/Suppliers.md`）**未必是该问题检索时的自然命中**——我的 golden 是**凭语义写的**，而非按真实检索行为校准。这与上一轮「golden 路径凭猜测写错」是**同类问题**，需按实测检索结果校准 golden，而不是改判据去迁就。


### Phase D 步骤 13 2026-09-20 (26 题「皆不过」的根因：题面词汇与语料不重叠)

**Task**：按实测检索结果校准六个 0/3 场景的 golden。

**实测证据**：逐题打印 golden 与真实引用，发现**多数题目检索到 0 条引用**：
```
[user_statement] 我偏好的结算方式是什么?      golden=['Wiki/Sources/Supplier-Alpha.md']  actual=[]
[raw_updated]   更新后的事实是否已编译进 Wiki?  golden=['Wiki/Sources/Supplier-Alpha.md']  actual=[]
[conflict]      系统是否仲裁了该冲突?           golden=['…Alpha.md','…Alpha-Alt.md']      actual=[]
[oversized]     超长页是否被切片读取?           golden=['Wiki/Sources/Supplier-Long.md']  actual=[]
[wiki_missing]  供应商 Gamma 的交货周期是多少?  golden=['Notes/Suppliers.md']              actual=[]
```

**排查过程（逐步排除，未凭猜测）**：
1. **不是路由拒绝**：探针显示 `我偏好的…` 命中 `_fallback_source_scope → personal_memory`，但驱动显式设置 `semantic_analysis.source_scope='knowledge_base'`，而 `_effective_retrieval_source_scope`（`scoping.py:46-49`）**直接返回 `semantic.source_scope`**，故节点不会因范围被拒。
2. **不是 FTS 查询过严**：探针显示 `_to_fts_queries` 正常产出**松弛 OR 腿**（12 个 bigram + 逐词腿），token 上限为 16，未截断。
3. **是词汇不重叠**：`系统是否仲裁了该冲突?` 的 bigram 含「冲突/仲裁」，而语料中**根本没有这些词**（ALT 页只写「另一份资料称交货周期为 21 天」）；`更新后的事实…` 的 bigram 含「事实/更新」，语料同样没有。**没有任何页面命中 → 0 候选 → 0 引用**。

**判定：这是题集缺陷（我的），不是检索缺陷。** 题面用词与语料内容不重叠，导致题目**在语料上不可答**——检索评测的题目必须能用语料回答。这与上一轮「golden 路径凭猜测写错」**是同一类错误**：**凭语义出题，未对照真实数据核对**。

**正确的校准方向（下一轮）**：题面改用**语料中真实存在的词汇**（如把「系统是否仲裁了该冲突?」改为「Alpha 的交货周期在资料间是否不一致?」，把「更新后的事实是否已编译进 Wiki?」改为「Alpha 的原始资料是否在发布后更新过?」），并同步校准 golden 引用为**实测命中的页面**。**不得改判据去迁就**。


### Phase D 步骤 14 2026-09-20 (题面按语料词汇改写 + golden 实测校准)

**Files Changed**：`tests/fixtures/phase_d_questions.json`（42 质量题全部改写/校准）。

**做法**：题面**全部改用语料中真实存在的词汇**（如「系统是否仲裁了该冲突?」→「Alpha 的交货周期在资料间是否不一致?」；「更新后的事实是否已编译进 Wiki?」→「Alpha 的原始资料是否在发布后更新过?」），再**实测每题真实命中**以校准 `golden.citations`。**未改任何判据去迁就。**

**校准结果（golden 可达数，满分 3/场景）**：
```
single_page 3/3  multi_page 3/3  two_hop 3/3  alias 3/3
page_end 3/3     conflict 3/3    user_statement 3/3  external_fact 3/3
oversized_page 3/3   budget_exhausted 3/3
ninth_page 1/3   wiki_missing 0/3   raw_updated 0/3   revoked_source 0/3
合计 31/42 可达（改写前远低于此）
```

**剩余四类的逐条归因（已查明，非同一原因）**：

| 场景 | 现象 | 归因 |
| --- | --- | --- |
| `revoked_source` 0/3 | 被撤销页**从不出现**在引用里 | **不是缺陷**——`reject` 的正确行为就是拒绝作答；我的「可达」指标对 reject 场景**度量方式错误**（命中反而意味着泄漏）。该场景在正式报告里是 **3/3 通过** |
| `wiki_missing` 0/3 | 笔记页未被引用（actual 为空或只有 wiki 页） | **驱动缺陷（我的）**：`AgentRuntimeServices` 只传了 `wiki_reader`，**未传 `retrieval`**，故 `supplement_vault_notes` 兜底路径不可用 |
| `raw_updated` 0/3 | Alpha 页**反而没被引用**（其他页有） | **golden 期望有误**：原始资料更新后，`revalidate_wiki_citations` 正确地使该页引用失效——这正是 `degrade` 语义。期望「仍引用 Alpha」与设计相悖，应校准为「不把旧内容当作当前事实」 |
| `ninth_page` 1/3 | 第 3 题问「交货周期相关的补充说明在哪里?」命中的是 Filler 页 | **题面/期望不匹配（我的）**：该问法本就指向填充页，不是 Alpha |

**Test Commands And Results**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_phase_d_eval_driver.py -q
# 19 passed in 91.79s
```

**下一轮**：修驱动（补 `retrieval`）、校准 `raw_updated` 期望与 `ninth_page` 第 3 题、修正「可达」指标对 reject 场景的度量；然后重跑报告。


### Phase D 步骤 15 2026-09-20 (驱动两处缺陷修复：retrieval 未接线 + 笔记未索引)

**Files Changed**：`tests/phase_d_eval.py`、`tests/phase_d_corpus.py`。

**缺陷 1：驱动未给节点注入 `retrieval`**
`AgentRuntimeServices` 只传了 `wiki_reader`，故 `supplement_vault_notes` 兜底路径**不可用**。按 `test_wiki_vault_fallback.py:14-19` 的既有口径修复：monkeypatch `adapters.active_vault_id` 与 `adapters.retrieval_service`，再用 `RuntimeRetrievalAdapter(object())` 包装注入；退出时完整还原。

**缺陷 2：语料构建器把笔记直接落盘，未进 `notes` 表**
`_write_note` 只 `path.write_text(...)`，而 **vault 兜底检索查的是 `notes` 表**（索引器为 `NoteRepository.replace_note`，`repositories/storage.py:183`）→ 兜底**永远找不到该笔记**，评测会误判为「兜底不可用」。
修复：`_write_note` 增加 `database` 参数，写盘后经 `VaultRepository.upsert` + `NoteRepository.replace_note` 建索引。

**实测效果**：
```
修复前: [wiki_missing] Gamma 是否在笔记中有提及?   golden=[Notes/Suppliers.md]  actual=[]
修复后: [wiki_missing] Gamma 是否在笔记中有提及?   golden=[Notes/Suppliers.md]  actual=['Notes/Suppliers.md']  ✅ 兜底命中
```
（q2/q3 仍未命中——兜底是**补充**而非**替代**：wiki 检索有结果时不会触发兜底，故其期望需相应校准。）

**Test Commands And Results**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_phase_d_eval_driver.py apps/backend/tests/test_wiki_vault_fallback.py -q
# 25 passed in 105.73s
```

**这两处都是「评测基建缺陷」而非业务缺陷**——若不复核就会把「我的驱动没接线」误判为「系统兜底能力缺失」。与前述「题面词汇不重叠」「golden 路径凭猜测」属同一类：**评测自身的缺陷会被误读为被测系统的缺陷**。


### Phase D 步骤 16 2026-09-20 (题集校准完成，报告首次可用于对照)

**Files Changed**：`app/evals/phase_d_questions.py`（接受 `stale` 动作）、`tests/phase_d_eval.py`（`reject`/`stale` 同判据）、`tests/fixtures/phase_d_questions.json`。

**关键设计补充：新增 `stale` 动作**
`raw_updated` 的正确行为是「原始资料已变化 → 旧内容**不得作为当前事实**」。这与 `reject`（拒绝作答）**成因不同但可检验判据相同**：该页不得出现在引用里。故单列 `stale` 一类，与 `reject` 共用判据，并在题集校验器中登记。

**校准后的首份可用报告**（42 质量题 × 2 模式 + 8 安全题 × 2 模式）：
```
旧路径通过 : 35/42     新路径通过 : 35/42      ← 校准前为 16/42
读取页数   : new 232 vs old 231
置换次数   : new 1   vs old 0
累计延迟   : new 27756ms vs old 27636ms
四象限     : 皆过 35 | 旧过新不过 0 | 旧不过新过 0 | 皆不过 7
安全题     : violations = []  (8/8 通过)
```
**逐场景**：10 个场景 **3/3**（`single_page`/`page_end`/`multi_page` 除外见下）；`conflict`/`raw_updated`/`revoked_source`/`user_statement`/`wiki_missing`/`oversized_page`/`budget_exhausted`/`external_fact` 全部 3/3；剩余 7 题分布在 `alias`(1) / `multi_page`(2) / `ninth_page`(2) / `two_hop`(2)。**无 0/3 场景**。

**本轮同时修正的度量缺陷**：「可达性」指标原对 `reject`/`stale` 场景**度量反了**（命中反而意味着泄漏），改为按动作区分后 `revoked_source` 由 0/3 恢复为 3/3。

**Test Commands And Results**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_phase_d_eval_driver.py apps/backend/tests/test_wiki_vault_fallback.py -q
# 25 passed
```

**诚实声明（写入报告本身）**：
1. 本报告衡量的是**检索/证据装配质量**，不是答案生成质量（该节点不产出自然语言答案）；
2. 旧路径是**参数化消融**（同一节点 + 3 个模块级补丁），不是历史版本回放；
3. `new` 与 `old` 在**通过率上无差异**（35 vs 35），差异体现在**读取页数 232 vs 231** 与**置换 1 vs 0**——即第九页准入；
4. 真实模型模式未执行（本环境无模型端点）。


### Phase D 步骤 17 2026-09-20 (42/42 —— 但其中两处是我**放宽**了期望，必须声明)

**Files Changed**：`tests/fixtures/phase_d_questions.json`（7 题修正）。

**结果**：
```
旧路径通过 : 42/42     新路径通过 : 42/42
读取页数   : new 224 vs old 223
置换次数   : new 1   vs old 0
四象限     : 皆过 42 | 回归 0 | 改进 0 | 皆不过 0
安全题     : violations = []
逐场景     : 14 个场景全部 3/3
```
`test_phase_d_eval_driver.py` → **19 passed**。

**⚠️ 但 42/42 不能直接当作质量证据——必须区分「修正」与「放宽」**：

**（a）真正的修正（应当保留）**：
- `golden.conclusion` 原为**意译**（如「华东区结算方式为月结 30 天」），而语料逐字是「结算方式为月结 30 天」→ 检索正确也会 `cov=0.00`。改为**语料逐字子串**后 `multi_page_002/003`、`alias_003` 通过。**这是我的期望写错，不是系统缺陷。**

**（b）放宽了期望（必须声明，不应视为通过）**：
1. **`two_hop` 的期望被削弱**：设计 §1.2 要求「结论=链上事实，**引用=A+B**」，我原写 `[Supplier-Beta, Product-P]`；因概念页内容极少、不是该问法的自然命中，我把期望**改成只要求 `[Supplier-Beta]`**。→ **两跳链路本身并未被验证**，只是「不因概念页缺失而失败」。
2. **`ninth_page` 的题面被改窄**：q2/q3 原问法含「供应商背景材料」，强命中填充页；我改成与 q1 几乎同义的 Alpha 问法。→ 三题近乎重复，**该场景的覆盖面下降**。

**因此本轮的正确结论是**：评测**跑通了**、判定**自洽了**、安全题**零违规**；但 **42/42 中至少有 4 题是通过「降低要求」而非「系统改进」达成的**。

**一个方法论提醒（写给下一轮）**：**全绿的评测集本身就是需要审视的信号**——它可能意味着评测太容易，而不是系统太好。下一步应当是**加强**评测（恢复两跳的 A+B 期望、补充更难的题），而不是宣布达标。


### Phase D 步骤 18 2026-09-20 (定位两跳不可验证的根因；已知局限写入题集与报告)

**Task**：查清 `two_hop` 的 A+B 期望为何不可达，判断是题集问题还是系统限制。

**根因（实测 + 代码核对）**：
1. 链接目标概念页 `Wiki/Concepts/Product-P.md` 的内容为**占位文本**：「Product-P 的当前内容尚未被任何来源编译或未经独立验证……」——即它**不承载任何事实**，因此不可能是事实性问题的自然检索命中。
2. 关键核对：`_workflow_service`（`test_wiki_workflows.py:1672-1682`）**不注入编译器模型**，而 `WikiWorkflowService` 在**无模型时走确定性回退**。所以占位内容**不是测试替身造成的假象，而是「未配置模型」时的生产回退行为**。
3. 推论：**概念页由编译器模型撰写**——有模型时才会有真实内容。因此在**脚本模式（无模型）下，两跳 A+B 期望本质上不可验证**。

**处置（不掩盖、逐题标注）**：
- 在题集 `meta.known_limitations` 记录 4 条全局局限；
- 对 5 道受影响题目在 `golden.note` 中**逐题标注「期望已放宽，属已知局限而非系统通过」**；
- `render_report` 新增**已知局限**段落，使报告自带该声明（设计 §3.1 要求诚实声明）。

**验证**：
```powershell
apps/backend/.venv/Scripts/python.exe -m pytest apps/backend/tests/test_phase_d_eval_driver.py -q
# 19 passed
# 报告渲染:violations=[] , 含「已知局限」段落
```

**本轮不宣称质量提升**：42/42 中有 5 题带放宽标注，真实可断言的是「评测自洽、安全零违规、14 场景可跑」。


### Phase D 步骤 19 2026-09-20 (两跳 A+B 期望**真正恢复**——不是放宽，是把能力测出来)

**Files Changed**：`tests/phase_d_corpus.py`（基础语料新增 Product-P 来源）、`tests/fixtures/phase_d_questions.json`（`two_hop` 三题期望恢复为 A+B）。

**做法（把放宽项收回的正确路径）**：
1. 上一轮查明：链接目标**概念页**在无模型时是占位内容，不承载事实 → 两跳的 B 页无从命中；
2. 本轮改为在基础语料中**额外摄入一条真实来源 `Product-P`**，编译器据此生成 `Wiki/Sources/Product-P.md`，其正文含真实事实：
```
## 生成笔记摘录
- Product-P 由 Supplier-Alpha 供应。
- Product-P 的标准交货周期为 14 天。
```
3. 于是「两跳」有了**两个都承载事实的真实页**（`Supplier-Alpha.md` + `Product-P.md`），A+B 期望**可以真正被验证**；
4. 同步修正题面（原问法强命中填充页）：`Product-P 的替代供应商是谁?`、`Supplier-Alpha 为 Product-P 供应什么?`；
5. **撤掉 3 道题的放宽标注**，并从 `meta.known_limitations` 移除「两跳不可验证」条目。

**结果**：
```
42/42 通过（含**恢复后**的两跳 A+B 期望）
安全题 violations = []
test_phase_d_eval_driver.py → 19 passed
```

**与上一轮的区别（关键）**：上一轮的 42/42 里有 5 题靠**放宽期望**达成；本轮把其中 3 题（two_hop）**真正收回**——做法是**让语料具备被验证的条件**，而不是降低要求。`known_limitations` 由 4 条减为 3 条。

**仍未收回的放宽项**：`ninth_page` q2/q3 的题面收窄（2 题），已在 `golden.note` 逐题标注。


### Phase D 步骤 20 2026-09-20 (收回最后一处放宽项；新旧差异可精确归因)

**Files Changed**：`tests/fixtures/phase_d_questions.json`（`ninth_page` q2/q3 题面修正）。

**发现的覆盖面缺陷（比「题面收窄」更严重）**：逐题探测 `read/replaced` 后发现——
```
q_ninth_page_001  new read=9 replaced=1   ← 真正触发第九页准入
q_ninth_page_002  new read=5 replaced=0   ← 候选数不足 max_pages,**准入根本没触发**
q_ninth_page_003  new read=5 replaced=0   ← 同上
```
即：q2/q3 **虽然「通过」，却没有测试本场景的意图**。原因：原题面不含「交货周期」，而填充页只含该词——候选数掉到 5（< `max_pages=8`），额外候选循环为空。

**修正**：题面改为同时含「交货周期」与目标事实，使候选数超过 8 且仍指向 Alpha：
```
q2: Alpha 的交货周期和结算方式分别是什么?
q3: Alpha 的交货周期有哪些限制?
```

**修正后（三题全部真正触发准入）**：
```
q1/q2/q3  new read=9 replaced=1 displaced=[Filler-1]
          old read=8 replaced=0
```
**撤掉最后 2 条放宽标注**，`known_limitations` 由 3 条减为 **2 条**——且剩余两条是**方法论声明**（测量边界、消融性质），**不是被削弱的判据**。

**最终报告**：
```
新路径通过 : 42/42     旧路径通过 : 42/42
读取页数   : new 243 vs old 240
置换次数   : new 3   vs old 0      ← 与 3 道 ninth_page 题一一对应
累计延迟   : new 27811ms vs old 28419ms
四象限     : 皆过 42 | 回归 0 | 改进 0 | 皆不过 0
安全题     : violations = []
```
`test_phase_d_eval_driver.py` → **19 passed**。

**新旧差异现可精确归因**：`置换 3 vs 0` 恰好等于 `ninth_page` 的 3 道题，`读取 243 vs 240` 亦为同样的 3 次额外读取。**这不是巧合，而是逐题可核对的一致性**——说明差异来自第九页准入这一条特性，而非噪声。


### Phase C 收口 2026-09-20 (freshness 写入方落地；同时暴露并修复我自己的长期回归)

**Task**：实现目标中点名的最后一个 P0——**阶段 C 的 freshness 写入方**（设计 §1.2 步骤 3 的惰性来源核验链）。

**Files Changed**：`app/agents/nodes/wiki_retrieval.py`、`app/services/wiki/publication.py`、`tests/test_phase_c_query_node.py`、`tests/test_wiki_source_watermark.py`。

**实现（按设计 §1.2 步骤 3）**：新增 `_maybe_verify_pending_sources`——查询遇 `unknown` 且 `reason=source_relevance_check_pending` 时，对该来源执行**有界**核验（预算上限 = 剩余的一半），通过则写 `verification_status='verified'` + `verified_at`（**仅用 035 既有列**），并**在本轮 gate 生效**；未通过保留 `unverified`。**不在 ingest 阶段标记 verified。**

**实测（`mixed_freshness` 语料，13 来源仅 1 个预置 verified）**：
```
核验前 verified: 1/13
核验后 verified: 7/13   ← 恰好是本轮被引用的 6 个来源(有界,非全量)
gate.freshness = fresh | reason = source_verified_current   ← 本轮即生效
```

**⚠️ 过程中暴露一个**我自己造成的长期回归**（必须登记）**：
改动 `wiki_retrieval.py` 后，`test_wiki_query_node.py` / `test_phase_c_query_node.py` 出现 4 个失败。用 `git stash` 对照 HEAD 证实——**是我的改动导致**，且**从第 4 轮起就未被发现**，因为我此后只跑 Phase D / shadow 的用例，**没有重跑这个节点的自有套件**。

**根因（一个有价值的架构冲突）**：`publication.py:22 _dependency_stamp` 用 `SELECT * FROM wiki_sources` 把**整行**纳入依赖戳——而惰性核验写的正是 `verification_status`/`verified_at`。于是**核验动作本身让本轮引用校验失败**（`wiki_publication_dependency_changed`），节点吞掉异常后返回空引用。

**修复**：依赖戳只承载**内容完整性**语义，核验类元数据（`verification_status`/`verified_at`/`expires_at`）描述的是「何时检查过」而非「来源说了什么」，**从戳中剔除**。

**两处测试按新设计语义更新**（非为通过而改）：`test_unverified_source_remains_unknown_with_unchanged_watermark` → 更名为 `test_unverified_source_is_lazily_verified_on_first_real_query`，并**新增断言核验确实落库**（`verification_status == 'verified'`）；`test_new_note_during_answer_blocks_output_without_revoking_old_roots` 的 freshness 期望同步更新。

**Test Commands And Results**：
```powershell
# 直接相关
test_wiki_query_node + test_phase_c_query_node + test_wiki_source_watermark + test_wiki_publication + test_wiki_generations
# 36 passed
# 广域回归
test_phase_d_eval_driver + test_wiki_shadow_runtime + test_wiki_shadow + test_draft_first_faults + test_wiki_vault_fallback + test_wiki_gate
# 55 passed
```

**教训（写给自己）**：**改动核心文件后必须重跑该文件的自有测试套件**，不能只用「我关心的那几条链路」的用例代替。本轮若继续只跑 Phase D，这个回归会一直被带着走。


### 目标 P0 收口核验 2026-09-20 (逐项取证)

目标中点名的 P0 与红灯，逐项跑测试取证：

```powershell
pytest test_api_wiring_mvp test_wiki_schema_consistency test_draft_first_faults \
       test_phase_c_query_node test_openapi_snapshot test_renderer_allowlist_contract \
       test_agent_runtime_retrieval test_wiki_evidence_policy -q
# 127 passed in 353.20s

pytest test_audit_logs.py -q          # 7 passed（隔离运行）
cd apps/desktop; npm run check:api-contracts
# OpenAPI-derived desktop contracts verified.
```

| 目标点名项 | 状态 | 证据 |
| --- | --- | --- |
| 阶段A 源身份可达性 | ✅ | `test_source_identity_v2_flag_is_reachable_from_settings_api`（settings 三层 + app_state 读取器） |
| 阶段B draft-first 接线 | ✅ | 服务级端到端用例 + 6 套 ingest 回归 87 passed |
| 阶段C 置换缺陷 | ✅ | C4 修复（置换对象由「排名最高」纠正为「价值最低」） |
| 阶段C freshness 写入方 | ✅ | 惰性核验落地，实测 verified 1/13→7/13 且 gate 本轮即 fresh |
| schema 漂移 | ✅ | `_sync_schema_file` + 2 条用例（跟随更新 / 保留用户编辑并报 drift） |
| 前端契约重生成 | ✅ | openapi.json + proxy-routes.generated.json + types.gen.ts，`check:api-contracts` 通过 |
| 3 条红灯 | ✅ | `test_agent_runtime_retrieval` / `test_openapi_snapshot` / `test_audit_logs` 均绿 |


### A4 消费者接线的前置缺口 2026-09-20 (精确定位，本轮不实施)

**Task**：把 A4 两轴策略接到设计指定的两个落点（`wiki_gate.py` 权威排序 + `prompt_memory_assembler`）。

**核对结果：前置数据通道不存在，接线需要契约变更**
```
MemorySearchResult 现有字段（models/memory.py:26-34）：
  wiki_generation/section/start_line/end_line、source_id、source_version、
  note_id/chunk_id/relative_path/title/heading/snippet/score/content_hash、
  source_scope/retrieval_mode、fact_id/candidate_id、entity_refs/evidence_refs/citation_refs …
**无 content_category、无 statement_authority**
```
而 `statement_authority(kind, content_category)` 需要**两个输入**：来源性质（可由 `ProvenanceKind` 推出）与**事实范畴**（`content_category`）。后者目前只在 `write_policy.WritePolicyRequest.metadata` 中流转（`write_policy.py:318-319`），**未落到检索结果上**。

**因此接线需要**：① `MemorySearchResult` 增字段（**API 契约变更** → openapi + proxy-routes + types.gen 重生成）；② 落库侧填充 `content_category`；③ 组装层按权威排序；④ 测试。

**本轮决定不实施**：上一轮刚因改动核心文件引入未察觉的回归（见「Phase C 收口」条目）。在**全量套件尚未跑完**的情况下再叠加契约变更，会让「哪次改动导致回归」无法归因。**先取全量基线，再动契约。**

**目标达成度不受影响**：A4 两轴策略**本身已实现并测试**（`test_wiki_evidence_policy.py` 34 passed）；缺的是**消费者**，而它**不在目标点名的 P0 清单内**。


### 新增「干扰项抵抗」场景 → 发现一个真实的检索排序问题 2026-09-20

**Task**：上一轮我登记「42/42 全绿本身是需要审视的信号，评测可能太容易」。本轮新增第 15 个场景 `distractor_resistance`（3 题）：查询强命中填充页，但只有权威页承载事实。

**结果：3 题全部不通过，且经核实是真实问题，不是题集缺陷**

**候选排序实测证据**：
```
Q: 在多个供应商背景材料中,哪一个记录了 Alpha 的结算方式?
   1-8. Wiki/Sources/Filler-1..8.md   6.234  ← 8 个填充页得分完全相同
   9.   Wiki/Sources/Supplier-Alpha.md 3.224  ← 权威页排第 9
  10.   Wiki/Sources/Product-P.md      2.340

Q: Alpha 的标准交货周期是多少天?
   1. Wiki/Sources/Product-P.md       9.992
   3. Wiki/Sources/Supplier-Alpha.md  5.411  ← 该问法下正常
```

**判定：真实的检索排序问题**。当查询含「供应商背景材料」这类词时，8 个短小的填充页因 bm25 特性（短文档 + 词项重复）**同分 6.234**，把**承载答案的权威页（3.224）挤到第 9 位**，而首轮只读前 8 页 → **权威页根本没被读到**（`R=0.00`）。

**这不是正确性缺陷**：系统按相关性取 top-8 的行为是对的；问题在**打分/排序质量**。

**值得注意的连带确认**：此例中第九页准入**正确地没有触发**——Alpha 价值 `3.224 × freshness` 低于已持有填充页的 `6.234 × freshness`，准入条件不成立。**价值函数行为正确**，问题在上游打分。

**处置（不掩盖）**：
- 该 3 题**保留为不通过**，作为**已知质量缺口的活证据**，而非改判据或改语料去凑绿；
- 题集 `known_limitations` 记录该缺口；
- 修复方向属**检索打分层**（如 bm25 长度归一化、标题/路径命中加权），**不在本目标点名的 P0 范围内**，登记为后续工作。

**这一轮验证了上一轮的判断**：全绿确实掩盖了问题。**新增更难场景的价值，恰恰在于它打破了全绿。**

**题量变化**：42 → **45**（15 场景 × 3）。


### 更正：置换计数由 3 降为 1（语料变更的连带影响，必须登记）2026-09-20

**我在步骤 20 中曾断言**：「`置换 3 vs 0` 恰好等于 `ninth_page` 的 3 道题，逐题可核对」。**该断言现已不成立，予以更正。**

**原因**：本轮为恢复两跳能力，在基础语料中**新增了 `Product-P` 来源**，改变了候选排序。实测（45 题报告）：
```
q_ninth_page_001  new read=9 replaced=1   ← 仍触发准入
q_ninth_page_002  new read=8 replaced=0   ← 不再触发
q_ninth_page_003  new read=8 replaced=0   ← 不再触发
报告汇总:置换 new 1 vs old 0(此前为 3 vs 0)
```

**根因（一个有价值的发现：准入是「边缘可达」而非「稳健可达」）**：
准入条件 `candidate_value > min_held`，在逐来源新鲜度下展开为
```
score_extra × 1.0(fresh) > min_score_held × 0.6(unknown)
⇔ score_extra > 0.6 × min_score_held
```
而候选按 bm25 降序排列 ⇒ `score_extra < min_score_held` 恒成立。**故准入只在 `0.6 × min_score_held < score_extra < min_score_held` 这一窗口内可触发**——窗口存在，但**对语料组成高度敏感**。新增 Product-P 后 `min_score_held` 升高，窗口关闭。

**处置**：
- 本轮**如实更正**此前断言，不保留「3 道题逐题可核对」的说法；
- 将该性质登记为**已知特性**：第九页准入是**边缘可达**的，评测需针对性地构造语料才能稳定触发；
- 下一轮修复方向：让 `mixed_freshness` 语料的 `fresh` 页与已持有页**分数同档**（而非更低档），使窗口稳定成立。

**同时确认未受影响的部分**：`Product-P` 来源带来的两跳 A+B 验证**仍然有效**（该 3 题在 45 题报告中通过）；安全题 violations 仍为 0。


### 第九页准入的第二重门槛：预算门（精确定位）2026-09-20

**Task**：查清为何 `ninth_page` q2/q3 不再触发准入。

**实测候选排序（q2：Alpha 的交货周期和结算方式分别是什么?）**：
```
 1. Wiki/Concepts/Product-P.md      7.789
 2. Wiki/Sources/Region-South.md    6.956
 3. Wiki/Sources/Region-East.md     6.728
 4. Wiki/Sources/Supplier-Alpha.md  6.375
 5. Wiki/Sources/Product-P.md       3.372
 6-8. Filler-1/2/3.md               1.866   ← 首轮读这 8 页
 9-12. Filler-4..7.md               1.866   ← 额外候选
```
**价值算术（应触发）**：`fresh` 的 Filler-7 价值 = `1.866 × 1.0 × 0.7 = 1.306`，而 `min_held` = `1.866 × 0.6 × 0.7 = 0.784` → **1.306 > 0.784，本应准入**。

**但实际未准入**：额外候选循环开头有 `if remaining <= 0 or time.monotonic() >= deadline: break`。q2 的首轮 8 页**含 3 个较长的页面**（概念页 + 两个区域页），**12000 字符读预算在到达第 9 个候选之前就耗尽了** → 循环 break。

**结论：第九页准入受**双重门**约束**：
1. **价值门**：`0.6 × min_score_held < score_extra < min_score_held`（上一轮已登记）
2. **预算门**：首轮读完后 `remaining > 0`
两者**同时**成立才可能准入。q1（问法只命中 Alpha + 填充页，首轮页短）两门皆过；q2/q3（首轮含长页）被预算门挡住。

**这不是缺陷**：预算门是**设计的正确行为**（设计 §2.2 明确「预算内高价值候选可越过 max_pages 首轮上限」——预算外本就不该读）。登记为**特性**。

**对评测的启示**：`ninth_page` 场景要稳定触发，语料必须让**首轮读取保持轻量**（短页），否则预算门先关闭。下一轮据此调整 q2/q3 的问法（或为场景单独提供轻量语料），**而不是改判据**。


### 全量口径最终状态（诚实登记）2026-09-20

**全量套件（`pwsh-23`，1686 题）在轮次上限到达时仍在运行，但进度输出已暴露问题**：
```
38%: .......F
42%: F..FF..........FF
46%: （此后暂无 F）
```
**即全量口径下在 38%–46% 区间存在约 7 个失败。**

**排查（已做，未定位）**：该区间覆盖 `test_phase_c_query_node.py` 至 `test_reflection_proposals.py`。逐一隔离运行：
```
test_phase_c_query_node + test_phase_d_eval_driver + test_persistence_mvp   → 57 passed
test_prompt_memory_assembler + test_quality_gates + test_product_metrics
  + test_recent_turns + test_post_reply_memory_jobs                          → 53 passed, 2 skipped
```
**全部通过** → 失败**不可在隔离运行中复现**，判定为**顺序依赖（test pollution）**。

**因此本目标的收口状态是**：
- 目标点名的 7 项 P0/红灯：**定向套件全部通过**（127 passed + audit_logs 7 passed + 契约 guard 通过）；
- **全量口径：未通过**，约 7 个顺序依赖失败**尚未定位**。

**我据此拒绝宣称「全量绿」或「目标达成」。** 定向绿 ≠ 全量绿，这正是本项目反复出现的模式（第 9 条红、`test_audit_logs` 顺序依赖、本轮 7 个顺序依赖失败）。

**下一轮的定位方法（留给后续）**：
1. 等全量跑完，从末尾的 `FAILED` 汇总行取确切测试名；
2. 用 `pytest <失败文件> --tb=short` 单独复现；
3. 若仍不复现，用 `pytest -p no:randomly` 固定顺序 + 二分法（按文件切分）定位污染源；
4. 重点怀疑对象：本轮新增的**惰性核验写库**（`wiki_sources.verification_status`）——它跨测试修改共享状态，若某测试依赖该列初值则会受前序测试影响。


### 全量口径最终结论（已定位，非回归）2026-09-20

**全量结果**：`6 failed, 1670 passed, 10 skipped in 4019.22s`

**6 个失败全部在 `test_phase_d_eval_driver.py`，全部是 `QuestionSetError`**：
```
test_question_set_loads_and_matches_the_design_contract
test_question_set_guard_rejects_malformed_documents
test_safety_criteria_detect_leaks_deterministically
test_safety_failure_is_not_averaged_into_quality
test_question_set_fixtures_all_have_a_builder
test_driver_runs_a_question_in_both_modes
```

**根因：我在全量套件运行期间修改了题集与校验器**——测试进程内存中是**旧的 14 场景模块**（期望 42 题），而运行时读到的是**磁盘上新的 45 题题集** → 题量不匹配 → `QuestionSetError`。

**验证（决定性）**：套件结束后重跑该文件 → **19 passed**。**6 个失败不可复现，确认是「运行中改文件」的产物，不是代码回归。**

**因此本轮的准确结论是**：
- 全量口径的这次运行**已被我自己的中途修改作废**，不能作为绿/红的判据；
- 但 1670 passed 且**全部 6 个失败均已解释并验证不复现** → **无证据表明存在真实回归**；
- **仍需一次干净的全量运行**来正式确认（本轮轮次已用尽，未做）。

**教训（补充第 1 条）**：**全量套件运行期间不得修改被测代码或数据文件**。我此前已在「全量口径策略调整」中定下「只在阶段收口时跑全量，且启动后不再改代码」，本轮**违反了自己定的规则**——导致 67 分钟的运行作废。


### 更正：「检索排序缺口」的判定过重（我的出题错误）2026-09-20

**我在步骤 21 中判定**：「新增干扰项场景发现**真实的检索排序问题**」。**该判定过重，予以更正。**

**实际原因：我的题目点名了干扰项自身的词汇。**
```
原题面: 「在多个供应商背景材料中,哪一个记录了 Alpha 的结算方式?」
填充页内容: 「供应商背景材料 N:交货周期相关的弱相关补充说明。」
```
查询**逐字包含**「供应商」「背景材料」——而填充页正是关于这些词的。**词法检索把填充页排在前面是正确行为，不是缺陷。** 我拿一个「查询点名了干扰内容」的题目去断言系统排序有问题，**是出题错误**。

**尝试的修复及其结果（已回滚）**：给 `bm25` 加列权重 `bm25(fts, 0,0,0, 3.0, 2.0, 1.0)` 以提升标题命中。实测**几乎无效**（权威页 3.224→3.512，填充页仍 6.234）——因为填充页匹配的**查询词项更多**（供应商/背景/材料），权重改变不了这一点。已**完整回滚**，不留无用的魔法常数。

**正确的做法（已实施）**：把题目改为**正当干扰**——查询不点名干扰内容，而是检验「标题命中是否压过正文命中」：
```
q1: Supplier-Alpha 的交货周期是多少天?   （Region-East 也含「交货周期」）
q2: Supplier-Alpha 的结算方式是什么?     （Region-East 也含「结算方式」）
q3: Supplier-Alpha 是否支持加急发货?     （Region-South 含「支持加急」）
```

**修正后报告（45 题）**：
```
新路径通过 : 45/45     旧路径通过 : 45/45
读取页数   : new 259 vs old 258
置换次数   : new 1   vs old 0
四象限     : 皆过 45 | 回归 0 | 改进 0 | 皆不过 0
安全题     : violations = []
```

**又一次同一类错误**：这已是本会话**第五次**「我的期望/题目写错，却被我当成系统缺陷」。前四次：golden 路径凭猜测、题面词汇与语料不重叠、把合法路径当禁止项、驱动未接线。**这次是第五次：题目点名了干扰内容。**

**教训强化**：**在下「系统有缺陷」的结论前，必须先自问「我的输入是否真的在要求我以为的东西」**。词法检索的行为完全由查询词决定——查询写了什么，就该命中什么。

**回到全绿**：45/45 再次全绿。但这一次我**逐题核实了场景的正当性**（干扰项不再由查询点名），而非把题目改宽。全绿仍是需要审视的信号，只是本次审视已做。


### 检索排序改进的方法取证（联网，非黑盒）2026-09-20

**取证目的**：上一轮我尝试用 `bm25` 列权重（title 加权）改进排序，**几乎无效并已回滚**。本轮联网取证以确认「正确的杠杆是什么」，避免继续在错误的层面上打补丁。

**取证来源（可复核）**：
- `tobi/qmd`（本地优先 CLI 检索，自述「Tracking current sota approaches while being all local」）——已抓取正文
- 多个独立工程来源（ratel-ai 检索 ADR、Python-AI-Notes 高级 RAG 章节、premai 混合检索综述）**一致给出同一架构**

**共识架构（跨来源一致，非单一框架）**：
```
Query ─┬─> BM25 / FTS        (词法)  ─┐
       ├─> Vector / dense    (语义)  ─┼─> RRF(Reciprocal Rank Fusion) ─> Reranker ─> 结果
       └─> HyDE / 查询扩展   (扩展)  ─┘
```
qmd 正文原话：「*The original query is sent to both backends, then fused with RRF and reranked.*」「*Typed expansions are routed exclusively: lex → BM25/FTS, vec and hyde → vector search.*」

**对本项目的结论（关键）**：
1. **字段加权不是主杠杆**——我实测 title 加权只把权威页从 3.224 提到 3.512，与「字段加权是弱杠杆」的取证一致；**该尝试已回滚，不留魔法常数**。
2. **本项目已有 RRF**：`retrieval.py` 已用 RRF 融合 wiki 与 notes 两路（`_fusion_source_scope` 等）。
3. **缺口在 wiki 页检索这一路**：`search_wiki_pages` **只走 bm25**，未接入既有 RRF、也无 rerank 阶段。
4. **正确的改进方向**＝把 wiki 页检索接入**既有 RRF**（词法 + 语义双路融合），必要时加**轻量 rerank**；而非继续调 bm25 参数。

**为什么这符合「不锁定窄框架」的要求**：RRF + rerank 是**跨栈共识**（Elasticsearch / Vespa / LangChain / LlamaIndex / 本地优先 CLI 均如此），不是某一家的私有做法；且本项目**已有** RRF 实现可复用，属于**在既有能力上扩展**而非引入新框架。

**本轮不做实现**：全量套件（`pwsh-24`）正在运行，**运行期间不改代码**——这是我上一轮违反过、导致 67 分钟运行作废的规则。改进方案登记为下一步。


### 检索改进的验收准则（联网取证，Qdrant 2026-08）2026-09-20

**来源**：Qdrant《How to Tune Hybrid Search in Qdrant》（Dylan Couzon，2026-08-22）——已抓取正文，可复核。

**三条可直接落地的准则（原话）**：

1. 「*Before you tune fusion, use the pre-tuning checks to verify index state and set a **labeled baseline**.*」
   → **先有标注基线，再调融合**。本项目恰好已有：Phase D 的 45 题固定题集 + 四象限报告。

2. 「*Hybrid search retrieves dense and sparse candidate lists, then fuses them into one ranking. The dense prefetch finds similar meaning; the sparse prefetch finds matching keywords.*」
   → 双路各自召回、再融合排序。

3. 「***Fusion reorders the candidates the prefetches return, so a document missing from both lists cannot appear in the result.***」
   → **融合只能重排两路已召回者**；两路都没召回到的页**不可能**因融合而出现。

**以及一条关键的验收纪律**：
「***Confirm Fusion Beats Either Prefetch** — Before tuning, compare dense retrieval, sparse retrieval, and default RRF at…*」
→ **在调参之前，必须先证明「融合优于任一单路」**。

**对本项目的直接意义**：
- 我为「wiki 页检索接入既有 RRF」提出的方案，**验收准则就此确定**：在 Phase D 的 45 题上，**RRF 双路必须优于纯 bm25 单路**，否则不该合入；
- 准则 3 提示一个**限制**：若权威页在 bm25 与语义两路**都未召回**，融合救不了它。故改进不能只靠融合，还需保证**召回阶段**能覆盖权威页；
- 这与我上一轮**已回滚**的 bm25 权重尝试形成对照：那是「在单路内部调参」，而取证明确指出**先做融合、并先证明融合有效**——层次选错了。

**本轮仍不改代码**：全量套件 `pwsh-24` 运行中（**运行期间不改代码**是我上一轮违反过、导致 67 分钟作废的规则）。


### 更正：阶段 A 的完成度被我**低估**了 2026-09-20

**我此前给阶段 A 打 85%**，理由含「消费者未接线」。**本轮只读审计发现该理由不准确。**

**实测事实**：`source_identity_v2` **不是只有可达性，而是完整实现且被真实消费**：
```
消费点:
  app/services/wiki/ingest.py:151   v2_enabled = source_identity_v2_enabled(conn)
  app/services/wiki/ingest.py:478   v2_enabled = source_identity_v2_enabled(conn)
语义分支 (ingest.py:155-159, 设计 §5.1-3):
  身份全等 + 内容全等 → 复用
  身份全等 + 内容变化 → 同 id 版本 bump(旧内容入 wiki_source_version_history)
  身份无匹配        → 新建行(同 hash 多行合法)
  多候选同身份 / legacy 身份不可判定 → fail closed
```

**专用测试 8 条，全部通过**（`test_source_identity_migration.py`）：
```
test_same_body_same_vault_sources_coexist_with_independent_identity
test_same_body_in_different_vaults_is_independent
test_raw_source_and_user_statement_with_same_body_are_distinct
test_forgotten_duplicate_source_blocks_answers_while_active_one_remains
test_duplicate_sources_do_not_double_count_evidence
test_legacy_hash_only_identity_fails_closed
test_migrated_references_are_consistent_after_apply
test_same_identity_content_change_bumps_source_version
# 8 passed
```
另在 `test_wiki_ingest_idempotency.py` 中有消费。

**更正后的阶段 A 评估**：
| 子项 | 状态 |
| --- | --- |
| source_identity_v2 开关（三层 settings + app_state 直读） | ✅ |
| v2 身份语义（复用/版本 bump/新建/fail-closed） | ✅ 已实现 + 8 测试 |
| 前端契约重生成 | ✅ |
| A4 两轴策略（`statement_authority` 等） | ✅ 已实现 + 34 测试 |
| **A4 消费者**（gate 权威排序 + 组装层） | ⚠️ 未接线（需契约变更） |

→ **阶段 A：85% → 92%**

**我为什么低估**：我把审计里「源身份**可达性**」这一措辞理解成了「只有可达性」，只核对了 settings API 通路，**没有去查该开关在业务路径上的消费点**。**又一次「只看了我预期的那一面」。** 这是本会话第六次同类问题（前五次见前），但方向相反——前五次是**高估**，这次是**低估**。


### 精确化：新鲜度三态「用户不可见」的确切范围 2026-09-20

**我此前笼统写作**「`FRESHNESS_UI_LABELS` 仍无消费者」。本轮只读审计给出**准确刻画**：

**实测事实**：
```
后端: wiki_gate.py:72  FRESHNESS_UI_LABELS 定义   → 全仓仅此 2 处引用(定义本身),**无消费者**
前端: apps/desktop/src + electron 中 'freshness' 命中数 = **0**
注入: chat.py:232  gate_context = gate.model_dump_json(exclude={...})
      chat.py:233  → 拼进 **system_prompt**
```

**准确结论：三态新鲜度「模型可见、用户不可见」。**
- ✅ 计算正确（`_resolve_path_freshness` + `_worst_freshness`，有测试）
- ✅ 进入**系统提示词**，模型据此作答
- ❌ **不进入 API/SSE 载荷** → 前端拿不到
- ❌ 前端**完全没有**映射（0 命中）

**设计要求的落点（`phase-c-query-node-design.md` §1.1 步骤 4）**：
> 「**UI 映射落地（仅前端文案，机器值英文）**：gate JSON 注入已有字段 freshness/freshness_reason（chat.py:232-239 注入链不变）；**前端/展示层**按 1.1 表映射中文三文案；**SSE 无新字段**。」

**即：设计明确「SSE 无新字段」**，映射应由**前端**基于既有注入链完成。现状是**两端都未实现**：后端留了一个无人引用的常量，前端一行没有。

**这不是 P0，但属真实的用户可见能力缺口**：三态新鲜度的**全部意义**就是告诉用户「这条资料可能过时」；现在这个信号只给了模型，用户看不到。

**处置（本轮不改代码，套件运行中）**：登记为下一步。修复需先厘清一个设计歧义——设计说「SSE 无新字段」，但前端要渲染就必须拿到 `freshness`；需要确认该值是否已随既有 SSE 事件到达前端（若无，则设计此句需修正，或映射改由后端在既有字段内完成）。


### A4 消费者的实施计划（只读分析得出，待套件结束后实施）2026-09-20

**关键发现：`content_category` 从未被持久化。**
```
write_policy.py:318-319  content_category = _coerce_content_category(
                             _metadata_enum_value(request.metadata, 'content_category',
                                                  ContentCategory.preference))
write_policy.py:208-213  仅用于写策略裁决(reject/review)
全仓其余引用: 仅 evidence_policy.py 中我新增的两轴函数(无消费者)
```
即：该字段**只在写入决策的瞬间存在**（且缺省为 `preference`），**不落库**——检索期无从读取。这是 A4 无法接线的**根本原因**（比「缺字段」更靠前：**数据本身没存**）。

**实施计划（5 步，含 1 次契约变更）**：

| 步 | 内容 | 涉及 |
| --- | --- | --- |
| 1 | 写入期把 `content_category` **落库**（候选/实体 metadata_json）——`write_policy` 已解析出该值，只需在持久化路径带上 | `write_policy` + 落库路径 |
| 2 | `MemorySearchResult` 增 `content_category` 与派生 `statement_authority`（**API 契约变更**） | `models/memory.py` |
| 3 | 构造检索结果时从 metadata 填充这两个字段 | 检索/组装路径 |
| 4 | 消费：`wiki_gate.py` 权威排序 + `prompt_memory_assembler` 组装排序（**设计指定落点**） | 两处 |
| 5 | 契约重生成 + 测试 | openapi/proxy-routes/types.gen |

**风险与纪律**：
- 步骤 2 是契约变更 → 必须跑 `check:api-contracts` 与 `test_openapi_snapshot`；
- 步骤 1 触及写入路径 → 必须跑 ingest/workflow 全套（我在「Phase C 收口」中正因改动核心文件而引入未察觉回归）；
- **实施前必须有一次干净的全量基线**（`pwsh-24` 正在跑），否则无法归因新回归。

**为什么现在不做**：`pwsh-24` 运行中。**全量运行期间不改代码**是我上一轮违反过、导致 67 分钟作废的规则。


### 检索改进：国内来源取证（华为云 2026-08）2026-09-20

**来源**：华为云社区《混合检索重排序 Rerank 实践：两阶段架构与主流模型横向选型》（2026-08-14）——已抓取正文，可复核。

**两阶段标准架构（原文）**：
> 「拆解『**多路粗召回 + RRF 融合 + Cross-Encoder 精确打分 + 动态阈值截断**』的两阶段标准架构」

**关键诊断（原文）**：
> 「混合检索虽提升了召回率，但因**量纲不一**和**双塔模型语义折损**，易导致**噪声挤占 Prompt 引发幻觉**」

**对本项目的三点意义**：

1. **印证 RRF 而非分数相加**：「量纲不一」正是不能直接相加 bm25 与向量分数的原因；RRF 基于**排名**、**无量纲**，故为跨来源共识做法。本项目 `retrieval.py` 已用 RRF，方向正确。
2. **本项目缺「动态阈值截断」**：现状按 top-N（`max_pages=8`）**无条件**读取，无相关性下限。华为云明确指出无截断会让**噪声挤占 Prompt**——这与我在 Phase D 观察到的「弱相关页挤占首轮窗口」现象**方向一致**（虽然那次是我的题目造成的，但机制是真实的）。
3. **Cross-Encoder 精确打分是第二阶段的强版**；本项目**无模型端点**时不可用，故短期只能做「多路粗召回 + RRF」；这与设计「真实模型模式留接入点」一致。

**国内外取证一致性**：
```
国外: tobi/qmd      → BM25 + vector + HyDE → RRF → LLM Reranker
      Qdrant 2026-08 → dense + sparse → fusion(RRF) → 「先证明融合优于任一单路」
国内: 华为云 2026-08  → 多路粗召回 + RRF 融合 + Cross-Encoder + 动态阈值截断
      阿里云/腾讯云    → 混合检索 + RRF + Rerank 两阶段（标题层面一致）
```
**跨来源、跨语言一致 ⇒ 满足「覆盖面广、不锁定窄框架」的要求。**

**结论（更新后的实施方向）**：
1. 把 wiki 页检索接入**既有 RRF**（词法 + 语义双路）；
2. 增加**相关性下限/动态截断**，避免弱相关页挤占首轮窗口；
3. 验收准则沿用 Qdrant 纪律：**先证明双路融合优于纯 bm25 单路**，否则不合入。


### 全量确认运行的处理决定（诚实登记）2026-09-20

**决定**：终止 `full_suite4`（干净确认运行），**以 `full_suite3` 的已完成结果 + 定向复验作为依据**。

**理由**：
```
full_suite3（已完成）: 6 failed, 1670 passed, 10 skipped
  → 6 个失败**全部**在 test_phase_d_eval_driver.py，**全部**为 QuestionSetError
  → 根因: 我在套件运行期间改了题集与校验器(进程内存旧 14 场景 vs 磁盘新 45 题)
  → 套件结束后重跑该文件: 19 passed —— **确认非代码回归**
当前树定向复验: phase_d_eval_driver + wiki_query_node + phase_c_query_node = 38 passed
```

**full_suite4 的实际进度与代价**：运行约 75 分钟仅到 38%（约 8.5 题/分钟，余量约 2 小时），且与我的并发工作互相争抢资源。

**我做了什么取舍**：确认运行的价值是「排除未知的顺序依赖」。但 `full_suite3` **已完整跑完**，且其**唯一**的 6 个失败**已逐一解释并复验通过**——**没有未解释的失败**。继续等 2 小时换取「同样的结论」性价比过低。

**诚实边界（不掩饰）**：
- `full_suite3` 是在**被我中途修改的树**上运行的；理论上存在「某测试读到旧 fixture 而假通过」的可能。**但该风险仅限 `phase_d` 相关测试**（我改的只有题集与校验器），而**该文件已单独复验通过**。
- 因此我的结论限于：**除 phase_d 驱动测试外，无未解释失败**；phase_d 驱动测试已单独验证。
- **不宣称**「有一次完全无干扰的全量绿」。


### 设计歧义裁定（基于代码链路验证，非推测）2026-09-20

**歧义**：设计 §1.1 步骤 4 写「前端/展示层按 1.1 表映射中文三文案；**SSE 无新字段**」——但前端要渲染就必须拿到 `freshness`。二者表面矛盾。

**链路验证（逐段核实）**：

| 环节 | 代码事实 |
| --- | --- |
| 引用是否到前端 | ✅ `events.py:84-86` `AgentCitationEvent` 携带**完整** `MemorySearchResult` |
| 前端渲染位 | ✅ `ChatCitationSummary.tsx:62-66` 的 `message-citation-meta` 行，已渲染 `来源：` / `检索方式：` / `标题：` |
| 既有映射约定 | ✅ `chatFormatters.ts` 已有 `formatCitationRetrievalMode` / `formatCitationSourceScope` —— **前端做机器值→中文映射是本项目既有惯例** |
| `freshness` 的语义粒度 | ✅ **逐来源**（`_resolve_path_freshness` 逐路径解析；gate 只取最差档） |
| gate 是否到前端 | ❌ 仅 `app/agents/nodes/chat.py:232-239` 进 **system_prompt** |

**裁定：采用方案 (a)——把 `freshness` 加到 `MemorySearchResult`（逐 citation）**

**理由（四选一对比）**：

| 方案 | 判定 |
| --- | --- |
| **(a) `freshness` 挂在 `MemorySearchResult`** | ✅ **最优**——复用**既有** SSE 事件；**语义正确**（freshness 本就是逐来源）；正好落在既有的 `message-citation-meta` 行；沿用既有 `formatCitation*` 惯例；后端**已算出**逐路径值（`path_freshness`）可直接填充 |
| (b) 新增 SSE 事件承载 gate | ❌ 违反「SSE 无新字段」；且 gate 是**最差档聚合**，**丢失逐来源粒度** |
| (c) 后端在 gate JSON 里直接映射中文 | ❌ 违反「机器值英文」原则；且 gate 根本不到 API |
| (d) 维持现状 | ❌ 用户完全看不到该信号 |

**结论：设计那句需微调**——应为「SSE 无新**事件**」，而非「无新**字段**」。因为**必须**在既有 `MemorySearchResult` 载荷上**增一个字段**，才能既保住逐来源粒度、又复用既有传输。

**附带确认（消除了我上一轮的另一个怀疑）**：`ChatCitationSummary.tsx` 已是**中文 UI**（「为什么这样回答」「引用文件」「检索范围」），故新增中文文案与既有风格一致，不需要额外本地化工作。


### 新鲜度三态对用户可见（设计歧义已裁定并落地）2026-09-20

**Task**：先经代码链路验证裁定设计歧义，再实施。

**裁定结论（基于链路验证，非推测）**：采用**方案 (a)**——`freshness` 挂在 `MemorySearchResult` 上，随既有 `AgentCitationEvent` 出站，由前端映射中文。

**Files Changed**：
| 文件 | 改动 |
| --- | --- |
| `app/models/memory.py` | `MemorySearchResult` 增 `freshness` / `freshness_reason`（机器值英文） |
| `app/agents/nodes/wiki_retrieval.py` | 新增 `_annotate_citation_freshness`，**无条件**在出站前给每条 citation 标注其**自身来源**的档位 |
| `apps/desktop/src/types.ts` | `Citation` 类型增 `freshness` / `freshness_reason` |
| `apps/desktop/src/features/chat/chatFormatters.ts` | 新增 `CITATION_FRESHNESS_LABELS` + `formatCitationFreshness`（沿用既有 `formatCitation*` 惯例） |
| `apps/desktop/src/features/chat/ChatCitationSummary.tsx` | 在既有 `message-citation-meta` 行渲染「新鲜度：…」 |
| `app/agents/retrieval/wiki_gate.py` | **删除**已死的 `FRESHNESS_UI_LABELS`（映射按设计归前端） |
| `openapi.json` + `proxy-routes.generated.json` + `types.gen.ts` | 契约重生成 |
| `tests/test_phase_c_query_node.py` | 新增 `test_citations_carry_per_source_freshness_for_the_display_layer` |

**语义要点**：**gate 保留最差档**（fail-closed，供提示词）；**citation 保留各自来源的档位**（供逐条渲染）。两者**语义不同、不互相替代**——这正是不能只把 gate 透传前端的理由。

**过程中修掉的两个我自己的缺陷**：
1. `annotate_freshness.py` 在**写文件之前**就 `sys.exit(1)`，导致 helper 函数**从未写入**（表现为 `NameError: _annotate_citation_freshness is not defined`）；
2. 首次接线把标注放在 `if _maybe_verify_pending_sources(...)` **块内** → 只有核验写入时才标注；**已核验的来源反而拿不到档位**（测试立刻抓到：`assert None == 'fresh'`）。已移到与 `if` 同级，**无条件执行**。

**验证**：
```powershell
# 后端广域回归
phase_c_query_node + wiki_query_node + wiki_gate + shadow_runtime
  + openapi_snapshot + renderer_allowlist_contract + api_wiring_mvp + phase_d_eval_driver
# 107 passed

# 前端
cd apps/desktop; npm run typecheck
# check:api-contracts ✅ + eslint --max-warnings 0 ✅ + tsc --noEmit ✅
```

**设计文档建议同步修正**：`phase-c-query-node-design.md` §1.1 步骤 4 的「SSE **无新字段**」应改为「SSE **无新事件**」——因为必须在既有 `MemorySearchResult` 载荷上**增字段**，才能既保住逐来源粒度、又复用既有传输。


### 三项并行推进：本轮完成 A4 前两步 2026-09-20

**A4-1（落库）✅ 完成并验证**

**关键发现：`content_category` 此前从未落库。** 生产路径是 `memory_consolidation.py`（`LongTermMemoryService` 已标注 `[legacy]`，生产主链路不再实例化）。

**Files Changed**：
| 文件 | 改动 |
| --- | --- |
| `app/services/memory_taxonomy.py` | 新增 `_KIND_TO_CONTENT_CATEGORY` + `content_category_for_kind()` |
| `app/services/memory_consolidation.py` | 候选 metadata 与**事实** metadata 均落 `content_category` |

**映射（A4 事实范畴轴的关键区分）**：
```
MemoryKind.FACT            -> fact
MemoryKind.PREFERENCE      -> preference   ← 唯一落入「用户权威类」
MemoryKind.RECENT_STATE    -> event
MemoryKind.BOUNDARY        -> rule
MemoryKind.PROJECT_CONTEXT -> fact
MemoryKind.HISTORICAL      -> event
MemoryKind.INFERENCE       -> fact
未知种类 -> fact（保守：不冒充用户权威）
```

**A4-2（契约字段）✅ 完成并验证**

`MemorySearchResult` 增 `content_category`。**只存范畴、不存派生值**——`statement_authority` 由 `evidence_policy.statement_authority(kind, content_category)` 在消费点推导，**避免同一语义存两份而漂移**。

**契约重生成**：`openapi.json` + `proxy-routes.generated.json` + `types.gen.ts`。

**验证**：
```powershell
openapi_snapshot + memory_consolidation + memory_taxonomy + api_wiring_mvp
# 83 passed
```

**途中修掉我自己的缺陷**：import 语句被插入到 `from app.services.memory_taxonomy import (` 多行导入**中间**，导致 `SyntaxError`；已改为放入块内。

**未完成（诚实登记）**：
- **A4-3 填充**：需定位「图检索构造 `MemorySearchResult` 且设置 `fact_id`」的确切位置。已知 `companion_retrieval.py:545` 有 `_activation_memory_ref` 读 `fact_id`，但**结果构造点尚未定位**；`retrieval.py` 中**无任何 `fact_id` 引用**，说明图结果经别的路径产出。
- **A4-4 消费点**：未开始。
- **RRF 三项**：未开始。
- **全量套件**：未开始。

**我为什么在此停下**：继续下钻的边际收益在下降，而本会话已有**两次**因「改动核心文件后未跑该文件自有套件」而引入未察觉回归的教训。当前状态**已验证为绿（83 passed）**，适合作为稳定检查点。


### 团队基线（engineer-a4 取得，可复用于归因）2026-09-20

**A4 相关聚焦套件基线 = 100 passed**
```powershell
# 必须在仓库根 E:\agentproject 下运行（测试用绝对包名 apps.backend.tests.*）
apps\backend\.venv\Scripts\python.exe -m pytest \
  apps/backend/tests/test_wiki_evidence_policy.py \
  apps/backend/tests/test_prompt_memory_assembler.py \
  apps/backend/tests/test_retrieval_fusion.py \
  apps/backend/tests/test_memory_permissions.py -q
# 100 passed
```
**基线可信度**：运行前确认无其它 pytest 进程（无 pwsh-24 残留）→ 干净基线，可作契约变更后的归因参照。

**踩坑登记**：在 `apps/backend` 目录下运行会 collection error（`ModuleNotFoundError: No module named 'apps'`，exit=1）。**该 exit=1 不是回归**，必须在仓库根运行。


### 团队侦查的两项关键发现与 captain 裁定 2026-09-20

**发现 1（阻塞缺陷，captain 已读码核实）**：`memory_entity_graph.py:1217 create_relation()` **无 metadata 参数**。
而 `PREFERENCE` 分支恰好走它（`memory_consolidation.py:652`），且 `_KIND_TO_CONTENT_CATEGORY` 中**只有 PREFERENCE → preference** 落在 `_USER_AUTHORITY_CATEGORIES` 内。
⇒ **唯一能产出 `statement_authority=='user'` 的种类，正是无法落 metadata 的那一类。**
**这推翻了我在上一条目中登记的「A4-1 已完成」**——落库只覆盖 `create_claim`（非偏好）分支。修复已纳入 t2。

**发现 2（我引入的缺陷，captain 已实测确认）**：`wiki_retrieval.py` 中 4 处 `or 1.0` 写法
```
73:  float(score or 1.0)
277: str(item["relative_path"]): float(item.get("score") or 1.0)
347: float(extra.get("score") or 1.0),
386: held_scores[extra_path] = float(extra.get("score") or 1.0)
实测: 0.0 or 1.0 == 1.0   ← LIKE 兜底命中(score=0.0)被抬成 1.0
```
`score` 语义为 `-bm25`（越大越相关），**LIKE 分支为 `0.0`**。故「LIKE 噪声」与「真实低分命中」**无法区分**，且「键缺失」与「值为 0」也被混为一谈。
**这是我本轮引入 score 字段时留下的缺陷**，已授权 engineer-rrf 一并修复（改为仅在 `is None` 时取默认值）。

**裁定：t3 砍掉不可验证部分，保留可验证部分**

scout 确认：**仓内不存在 wiki 页的向量/语义通道**（`snapshot_reader.py:119` 为纯 FTS5/bm25 单路）。故原计划的「词法+语义双路融合」**缺语义腿**，而验收准则要求「证明融合优于纯 bm25 单路」——**在无模型端点、无 wiki 向量索引的环境下既建不起来也无法验证**。

**我不选择「新建 wiki 向量索引」或「复用 vault-note 索引」**：
- 前者需 embedding 与模型端点 → **不可验证**，只能靠自述；
- 后者语义不等价（vault note ≠ wiki 页语料）→ 引入**错误召回来源**，属「为凑指标搭架子」；
- 取证纪律（Qdrant 2026-08）明确「**先证明融合优于任一单路**」——**证不了就不该合入**。

**t3 新范围**：只做华为云四段架构中**确定性可验证**的第四段——**相关性下限/动态截断**（它解决的正是观察到的真实问题：弱相关页挤占首轮窗口），并先修上述 `or 1.0` 缺陷。
**验收准则替换为**：给出截断前后对比数据 + 证明未削弱既有保证（跑 5 套相关套件）；**若通过率下降或既有测试变红则不得合入**。
**并要求报告中明确写清 RRF 部分因环境缺语义腿而未实施**，不得写成「已做」或「不需要」。


### 重大更正：我的 RRF 裁定基于**错误前提**（scout 推翻，captain 已实测确认）2026-09-20

**我此前的裁定**：「无模型端点 ⇒ 无语义腿 ⇒ 融合不可验证 ⇒ 砍掉 RRF，只做相关性截断」。

**scout 的反证（captain 已独立实测确认）**：
```
E:\agentproject\apps\backend\models\embedding\model.onnx      94,781,076 bytes
E:\agentproject\apps\backend\models\embedding\tokenizer.json     439,125 bytes

清空全部 AGENT_PET_* 后实测：
  build_local_onnx_embeddings(Path('models/embedding')).embed_query('供应商 Alpha 的交货周期')
  → DIM 512 | CONST 512 | NORM 1.0        ✅ 本地可算,无需外部端点
```
依据：`config.py:94-102` 用 `__file__` 锚定（非 cwd）；`retrieval_factory.py:49-58` docstring 明示「bundled ONNX；missing → disabled, FTS remains the fallback」；内置 ONNX transport 为 local ⇒ `_vector_transport_is_local` True ⇒ **本地隐私模式不阻断向量腿**。

**降级路径的确切形态**（`retrieval.py:345-346` / `:383-389` / `:390-396` 三处均不向上抛）；`retrieval.py:405-408` 向量为空 ⇒ `fts_required` 为真 ⇒ FTS 腿强制启用，不会空手而归。

**⇒ 就「能力」而言，脚本环境下 RRF 双路融合是可验证的。我此前的「不可验证」判断错误。**

**真正缺的是「索引」而非「能力」**：
- `wiki_generation_pages` 上**没有向量索引**；
- migration 003 的 `vector_chunks` 以 `(vault_id, relative_path)` 为键 → 属 **vault notes**；
- migration 033 的 `wiki_body_fts` **只有 fts5**；`app/services/wiki/*` 无任何向量引用。

**修订后的裁定**：
1. **t3 不变**（相关性下限 + 修 `or 1.0`）——它独立有价值、风险低，且是后续融合的前置（无下限则噪声候选会污染融合评估）；
2. **新增 t6**：为 wiki 快照页**建向量索引**并把 wiki 检索做成**真正的双路融合**，**分阶段 + 硬性回退令**；
3. 验收准则恢复为原取证纪律：**必须证明「融合优于纯 bm25 单路」，否则回退**。


### scout §9：第 5 处同类缺陷 + 一处由我造成的逻辑不一致（captain 已读码核实）2026-09-20

**① 第 5 处 `or 1.0` 同类缺陷（我引入）**：`wiki_retrieval.py:321`
```
held_scores[path] = candidate_scores.get(path, 1.0)
```
`:276-279` 只把 **bm25 候选**登记进 `candidate_scores`；`:315-317` 经 `page.links`/`page.backlinks` **图扩展**发现的邻居页不在其中 ⇒ 拿到**凭空发明的 1.0**，并被 `:354`/`:405` 使用。形式是 `.get(..., 1.0)` 而非 `or 1.0`，**语义完全相同**。

**② 准入三因子 vs 置换单因子 —— 不一致由我造成**
```
:346-360  准入：candidate_value 与 min_held 均用 _citation_value(score, freshness, coverage)
:405      置换：min(..., key=lambda path: held_scores[path])   ← 只看原始 score
```
我在**第 4 轮**写的 `:405` 用原始 score；**第 23 轮**把准入改成三因子（逐来源 freshness）时**没有同步置换**。
**后果**：「为本次准入提供 `min_held` 的那一页」与「真正被置换的那一页」**可能不是同一页**——用 A 页的价值做决策却踢掉 B 页，语义不自洽。

**裁定：统一到三因子 `_citation_value`**（设计 §2.2 的「价值」即 `V = relevance × freshness × coverage`；准入侧已在用；新鲜度低/覆盖差的页应优先被置换）。

**scout 另外确认的三点（我同意）**：
- `pinned`（`:351`/`:401-403`）禁止置换 ⇒ 相关性下限**不得**踢掉 pinned；
- `gate_evidence`（`compression.py:180-213`）**不含分数阈值** ⇒ 与下限不冲突，但计数断言须在正确阶段；
- 价值预检是**相对**比较（`:360`），无可置换页时 `min_held=0.0`（`:359`）⇒ **绝对下限确实不存在，插入点概念上干净**。

**这是团队交叉核对的第二次实质收益**：第一次是 scout 推翻我的 RRF 裁定（避免我以「不可验证」为名砍掉可做的工作）；这次是找出**我自己两次改动之间的不一致**。


### 观察项：出站 wiki citation 的 `score` 硬编码 1.0（既有代码，captain 已核实）2026-09-20

**事实**（scout 发现，captain 读码核实）：`wiki_retrieval.py:326` 与 `:391` 把出站 citation 的 `score` **硬编码为 1.0**，**共 2 处，属既有代码**（非本轮引入）。

**潜在影响**：`compression.py:216-218 _confidence()` 取 `activation_score` 或 `score`（clamp 到 [0,1]）⇒ wiki citation 的 confidence **恒为 1.0、全部并列**。
而节点**内部另有真实相关性**（`held_scores`，来自 bm25）⇒ **内部有真分、出站却是常数**。

**处置：列为观察项，要求 engineer-rrf 评估而非修改。** 需查清 `_confidence()` 在 `gate_evidence` 中是**排序/阈值**用途还是**仅记录**用途。
**明确禁止擅自改**：`MemorySearchResult.score` 的语义可能被跨模块消费者依赖，改它属**语义变更**，风险超出本次范围；若判断应改，须先给证据与影响面分析，由 captain 裁定。

**我为什么不直接要求修**：**我不知道它是不是缺陷**。在缺乏 `_confidence` 用途证据的情况下要求修改，就是在制造无依据的改动——这正是本会话反复出现的「凭猜测下结论」。**先取证，再决定。**


### RRF 融合裁定：**不合入**（engineer-rrf 的取证结论，captain 采纳）2026-09-20

**engineer-rrf 按我设的硬性准则执行，得出「不合入」，并发现我的准则本身不可满足。**

**决定性事实：Phase D 45 题基线已是 45/45（实测）**
```
passed 45/45, failures=[]；by_scenario 全部 3/3；total_reads=261, total_replaced=3
证据：E:\rrf_scratch\phase_d_baseline.json（逐题 recall/precision/coverage/reads/stop_reason）
```
⇒ **判据饱和 ⇒ 任何排序改动都不可能「优于单路」，只能持平或下降。** 我设的「融合必须优于纯 bm25 单路」在**当前 45 题上不可满足**——**这是题集判别力问题，不是实现问题**。

**双路排名质量（只读探针，未改生产文件）**：

| 通道 | found | MRR | mean rank | hit@1 | hit@8(读窗口) |
| --- | --- | --- | --- | --- | --- |
| bm25（现状） | 36 | 0.5111 | 2.028 | 15 | 36 |
| **语义单路** | **39** | **0.5722** | **1.897** | **16** | **39** |
| RRF 融合(k=60, 等权) | 39 | 0.5165 | 2.667 | 15 | 37 |

（action=answer 的 30 题：bm25 MRR 0.5833 / 语义 0.6389 / 融合 0.5972）

⇒ **等权 RRF 赢了 bm25，却输给「语义单路」**——恰好不满足「必须优于**任一**单路」。只有把语义权重调到 3~5 倍（融合退化为近似纯语义）才能同时赢两路（MRR 0.6556），**但那是在同一 45 题上调参，不构成合入依据**。

**三条独立否决理由（任一成立即可）**：
1. 主判据 45/45 持平 ⇒ 不优于单路；
2. 等权融合输给语义单路 ⇒ 不满足 Qdrant「beats either prefetch」；
3. 融合会换掉 **44/45 题的首轮读集** ⇒ **零可测收益下引入实打实的行为 churn 与回归面**。

**captain 裁定：不合入、不改生产代码。** 并明确拒绝「无论如何都落地」的选项。

**语义腿的真实前置条件（engineer-rrf 查明，captain 采纳）**：
- `wiki_body_projection` 只存 title/links_json/chunk_count，**无 embedding/vector 列或表**；
- **更关键**：`wiki_body_fts.content` 存的是 `_bigram_cjk(...)` **变换后**文本（`projections.py:43-44`），**不能直接嵌入**；要嵌入必须回读 `wiki_page_bodies.body` 并 `parse_markdown`；
- 故真语义腿只有两条路：(a) 每次查询 on-the-fly 嵌入（生产不可行，成本随 wiki 规模线性增长）；(b) **新建 wiki 正文向量投影**（新迁移 + 发布期嵌入），要动 `projections.py/publication.py/generations.py` 与写路径——**不属「改动收敛」**。
- 方案 B（wiki 快照作为第 4 通道）同样**不给 wiki 语义腿**，却要改主聊天检索链，影响面更大。

**本次最有价值的产出不是「融合」，而是两个否定性结论**：
1. **题集无判别力**（45/45 饱和）⇒ **任何检索改进都无法被验证**——这印证了我此前的判断「全绿本身就是需要审视的信号」，而我自己又在饱和题集上设了「必须优于」的硬门槛；
2. **语义腿本身有价值**（found 39 vs 36、MRR 0.572 vs 0.511、hit@8 39 vs 36），但**前置条件是新建向量投影**，成本与影响面远超「改动收敛」。


### t5 对抗性审计：5 条声明全部成立 + 三项边界（captain 采纳并已处置）2026-09-20

**审计立场**：默认「声明可疑」，逐条找反证。审计窗口 2026-09-21T05:36:42Z→05:44:07Z，HEAD `3c4f46d`，脏树 47 文件。

| # | 声明 | 裁定 | 关键证据 |
| --- | --- | --- | --- |
| 1 | 阶段B 逐字不变 | ✅ | `git diff ingest.py` **纯增量、零 `-` 行**；原 `apply_ingest` 主体一行未改；开关读取器 fail-safe（缺键/坏值→False，严格 `is True`） |
| 2 | freshness 无条件标注 | ✅ | `:511` 缩进 **12 空格**，与 `:506` 的 `if` 同级 |
| 3 | SSE 载荷真实性 | ✅ **引注有误** | `events.py:84-86` 携带完整模型；`events_helpers.py:101-115` 直传 `envelope.result` |
| 4 | 8 条测试全通过 | ✅ 实测 | `8 passed in 55.47s`；8 条各自调用一次开关（非「测了个寂寞」） |
| 5 | 依赖戳不削弱完整性 | ✅ 含残余 | 剔除清单与核验写入列**精确对齐**；最可疑的 `updated_at` 实测**未被 bump** ⇒ 反证不成立 |

**captain 已处置两项**：
1. **引注错误（我的错）**：文档原写 `chat.py:232-233`，缺 `agents/nodes/` 前缀；`app/api/chat.py:232-233` 实为 `invalid_date` 错误码且全文不含 gate 引用。**已改为 `app/agents/nodes/chat.py:232-239`**。
2. **注释表述不精确（我的错）**：原注释把三者笼统说成「何时检查过」。**已改为分条写明各自不同的剔除理由**（`publication.py:51-57`）：
   - `verification_status`/`verified_at`：查询期惰性核验会写 → **必须**剔除，否则核验自我作废；
   - `expires_at`：**有效性**字段；查询期 `derive_source_freshness` 会读并判 stale ⇒ 完整性不削弱；反之若纳入戳，「设置未来过期时间」会立刻让已发布页失效，属误伤；
   - `revoked_at` **保留**：撤销是**权威**变更，本就应使已发布页失效。

**三项边界（非声明不实，captain 全部接受并记录）**：

**① 证据强度边界（scout 认为最值得记）**：8 条测试**直接写 `app_state`、绕过 settings 三层** ⇒ 若 settings→app_state 接线回归，**这 8 条仍会全绿**。
⇒ **「8 条通过」证明的是 v2 运行期语义，不是端到端可达性。** 该链路由 `test_api_wiring_mvp.py:2433` 单独兜住。
**captain 承诺：不再用「8 条通过」暗示端到端可达。**

**② 默认路径多一次只读查询**：`_draft_first_publication_enabled()` 每次 `apply_ingest` 都开 read_only 会话（`ingest.py:377-379`）。
⇒ 「原路径逐字不变」对**源码**成立；**默认执行**多一次核心表只读查询。**记为已知取舍，不作为缺陷修。**

**③ 并发暴露（scout 主动标注）**：`memory_entity_graph.py` 于 05:41:43Z 被改动，**正在审计窗口内**（engineer-a4 的 `create_relation` 修复）。
其 pytest（05:42:32–05:43:29Z）跑在该改动**之后** ⇒ **既是更强结果（改动在飞仍全绿），也不能当干净基线**。声明 1/2/3/5 依据的文件窗口内均未变动 ⇒ 不受影响。

**scout 的诚实边界（captain 完全接受）**：未重跑全量套件（「87 passed」**未验证**）；未运行可达性测试；只审任务书点名的 5 条。

**结论**：本会话我反复出现「测试通过 ≠ 功能生效」，但这次**对抗性审计未发现该类实例**。三项边界均为**边界**而非**不实**——且其中两条（引注、注释）是**我的错，已修**。


### t2 完成：A4 消费者接线（数据通道修复 + 两轴填充 + 权威排序）2026-09-20

**Task**：把 A4 两轴策略接到设计指定的两个落点（`wiki_gate.py` 权威排序 + `prompt_memory_assembler`），并修掉 captain 核实的数据通道缺陷。

**根因（本轮修掉）**：`content_category` 的落库只覆盖 `create_claim`（claim 分支）。
偏好类用户陈述走的是 `create_relation`（relation 分支），而 `_create_relation_impl` **没有 metadata 参数**，
`MemoryFactCandidate.metadata_json` 恒为 `None` → `_normalize_metadata_json(None)` → `"{}"`。
而 `_KIND_TO_CONTENT_CATEGORY` 中**只有 PREFERENCE 产出用户权威类 `preference`**
⇒ **唯一能产出 `statement_authority=='user'` 的种类，正是无法落 metadata 的那一类。**

**Files Changed**：

| 文件 | 改动 |
| --- | --- |
| `app/services/memory_entity_graph.py` | `create_relation` / `_create_relation_impl` 增 `metadata` 参数，透传到 `MemoryFactCandidate.metadata_json` |
| `app/services/memory_consolidation.py` | PREFERENCE 分支（relation 路径）带上 `content_category` / `source_track` 等 metadata |
| `app/services/memory_taxonomy.py` | 新增读侧入口 `content_category_from_metadata()`：缺失/损坏返回 **None**，不回退成 `fact` |
| `app/models/memory.py` | `MemorySearchResult` 增 `source_type`（**契约变更**） |
| `app/services/memory_permissions.py` | `result_with_activation_permissions()` 增 `content_category` / `source_type` 并注入（唯一收口点） |
| `app/services/memory_read.py` | 图事实读路径把 `fact.metadata_json` 与 `fact.source_type` 带进结果 |
| `app/services/evidence_policy.py` | 新增 `statement_authority_of()` / `statement_authority_order()` / `statement_authority_sort_key()` |
| `app/services/prompt_memory_assembler.py` | 组装层按权威**稳定**排序（设计指定落点） |
| `app/agents/retrieval/wiki_gate.py` | `order_evidence_by_statement_authority()`，在 `assessment_input()` 生效（设计指定落点） |
| `openapi.json` / `proxy-routes.generated.json` / `types.gen.ts` | 契约重生成 |

**为什么 `MemorySearchResult` 还要加 `source_type`**（超出原 5 步计划，必须登记）：
`statement_authority(kind, content_category)` 需要**两个**输入，而检索结果此前只有范畴。
若不记录来源性质，消费点只能把 kind 硬编码为 USER_STATEMENT —— 那对 wiki 派生事实就是**造假**。
故按「只存输入、不存派生值」的同一原则记录**写入期原始 ingress 标签**（如 `explicit_user`/`wiki`），
消费点用既有 `source_provenance_kind()` 归一。**仍不存 `statement_authority` 本身。**

**两处刻意的「不做」**：
- `services/retrieval.py:567/688` **保持 `content_category=None`**：该路径（fts/vector/wiki）**无来源**，硬填即造假数据；缺省经 `statement_authority` 保守降级。
- `MemoryGraphFact.category` **未**用作兜底：claim 传 `memory_kind.value`、relation 传固定 `"relation"`，**语义不同**，拿它当范畴会引入错误权威。

**验证（本地实测）**：
```
新增 apps/backend/tests/test_a4_statement_authority_wiring.py  → 10 passed
反证（把 create_relation 的 metadata_json 改回 None，模拟修复前）→ 恰好 3 failed：
   test_preference_statement_relation_branch_end_to_end
   test_preference_relation_metadata_is_not_silently_empty
   test_create_relation_metadata_round_trips_through_upsert
   ⇒ 端到端用例确实咬住该缺陷，不是恒真断言（改动已还原并复跑 10 passed）
契约：npm run check:api-contracts → verified
```

**验收要点端到端证据**（captain 指定）：一条偏好类用户陈述
（`请记得我更喜欢下午开会`）经 `MemoryConsolidationService.consolidate` 完整写入链路后：
```
图事实 statement_kind=relation / relation_type=prefers / source_type=explicit_user
metadata_json.content_category == "preference"
↓ 经 GraphMemorySourceAdapter(answerable_only=True) + UnifiedMemorySearchService 检索
result.content_category == "preference"
result.source_type     == "explicit_user"
statement_authority_of(result.source_type, result.content_category) == "user"   ✅
```

**Known Limitations（诚实登记，未做）**：
- **无回填（已被 t8 取代，见下方更正）**：已存在的 relation 行不会被补 metadata（`record_support` 只增 support_count）。
  旧库里的偏好关系权威轴**仍然失明**，需要单独的迁移或回填决策 —— 本轮**未**做，也**未**声称已做。
- **`wiki_gate` 的权威排序当前是恒等变换**：该门经手的引用全部来自 Wiki 快照与 vault fallback，
  来源性质一律 `external`。函数保留并单测固定，但**不得把它当成实际增益**；真正产生次序差异的是组装层。
- **「外部来源不能纠正用户偏好」的冲突规则未实现**：它需要一个**混排证据面**（用户权威 + 外部来源同场），
  而证据门今天不存在这样的输入。强行实现会得到一条**不可达分支**，故不做。
- 排序只改顺序：**不增删证据、不改权限判定、不判定事实真假**；同档位用稳定排序保持原检索序（有单测固定）。


### t2 完成（A4 消费者接线）—— 含反证与三条诚实局限 2026-09-20

**端到端证据（captain 要求的那个）**：
```
「请记得我更喜欢下午开会」→ consolidate 完整链路
  → 图事实 statement_kind=relation / relation_type=prefers / source_type=explicit_user
    metadata_json.content_category == "preference"
  → GraphMemorySourceAdapter(answerable_only=True) + UnifiedMemorySearchService 检索
  → result.content_category == "preference"
    result.source_type == "explicit_user"
    statement_authority_of(result.source_type, result.content_category) == "user"
```

**反证（关键）**：把 `create_relation` 的 metadata_json 改回 `None`（模拟修复前）→ **恰好 3 条失败**，其中含上述端到端用例（`KeyError: stored_metadata["content_category"]`）。
⇒ **证明用例真的咬住缺陷，不是恒真断言。** 这正是本会话反复缺失的「证明测试非空洞」步骤。

**契约决策（captain 批准）**：engineer-a4 超出计划给 `MemorySearchResult` 加了第二个字段 **`source_type`**。
理由：`statement_authority(kind, content_category)` 需**两个输入**；只存范畴会迫使消费点把 kind 硬编码成 USER_STATEMENT，**对 wiki 派生事实即造假**。
captain 核实：`source_type` 是**写入期原始 ingress 标签**（图事实既有列），**非派生值**；消费点用**既有** `source_provenance_kind()`（`evidence_policy.py:43`）归一。**符合「只存输入、不存派生值」，批准保留。**

**回归**：21 套件 **306 passed / 0 failed**（含 `test_openapi_snapshot`）；`check:api-contracts` verified；`git diff --check` 通过。
`retrieval.py:1154` 的 F821 属**既有问题且文件不在其范围**，未擅自修（正确）。

**三条诚实局限（captain 全部采纳）**：
1. ~~**无回填** —— 旧库的偏好关系权威轴仍失明~~ **【本条已被 t8 取代，作废】**
   更正（captain，经 verifier 指出）：t8 的**读侧重建**（`graph_fact_content_category`）在 metadata 沉默时由 `relation_type` 重建，**实质上覆盖了旧库**——至少对 `relation_type="prefers"` 成立。
   故「旧库偏好关系权威轴仍失明」**在 R2 上不再成立**。
   仍成立的部分：**非 `prefers` 的 relation 行不重建**（权威保守降级 `mixed`）；**claim 行不受影响**（非 PREFERENCE 种类本就不在 `_USER_AUTHORITY_CATEGORIES` 内）。
   captain 原方案的「数据回填迁移」**已被 engineer-a4 以证据驳回并改用读侧重建**，详见 t8 条目与 captain 裁定条目。
2. **`wiki_gate` 的权威排序当前是恒等变换** —— 门内证据全部来自 Wiki 快照/vault fallback，**一律 external**。函数已就位并有单测固定，但**当前无实际增益**；真正产生次序差异的是**组装层**。
   ⇒ **captain 据此调整口径：不得把「A4-4 已完成」写成质量提升。** 正确表述为「函数就位，但当前输入面使其为恒等变换」。
3. **「外部来源不能纠正用户偏好」的冲突规则未实现** —— 它需要**混排证据面**（用户权威 + 外部来源同场），证据门今天没有这种输入；**强行写会得到不可达分支**。engineer-a4 拒绝写死代码是**正确判断**。
   ⇒ **这是设计缺口而非实现缺口**：需先定义「混排面」落在哪里（证据门 / 组装层 / 新合成层）。登记为**待设计项**。


### 决定性设计洞察：证据门**结构上不可能**成为混排面（engineer-a4 提供，captain 采纳）2026-09-20

**engineer-a4 的既有事实**：
> 证据门的输入来自 **Wiki 快照与 vault fallback**，而**图事实根本不经过证据门**——它们走 `memory_read.py` 的个人记忆通道，只汇合在**组装层**。
> 所以「混排面」若要同时看到用户权威与外部来源，**组装层是今天唯一实际存在该混排的地方**；证据门要成为混排面，得先把图事实接进该门（那是**新增数据通路**，不是补逻辑）。

**这把局限 2 与局限 3 合并成了一个更根本的结论**：
- 局限 2 说「`wiki_gate` 的权威排序当前是恒等变换」——**但真正的原因不只是「输入面恰好全 external」，而是「证据门的输入面根本不包含图事实」**；
- 因此设计文档把权威排序指定在 `wiki_gate.py` 是**部分错位**：**该门看不到它需要排序的那类证据**。

**captain 裁定（设计层面）**：
1. **权威排序的实际落点是组装层**（`prompt_memory_assembler`）——那是今天**唯一**用户权威与外部来源同场的地方；engineer-a4 已在该处实现并单测固定；
2. `wiki_gate` 中的 `order_evidence_by_statement_authority()` **保留**（若将来图事实被接入该门即生效），但**当前明确为恒等变换，不得记为增益**；
3. **「证据门成为混排面」是一条新增数据通路，不是补逻辑**——登记为**待设计项**，需先决定是否要把图事实接进证据门（有成本与语义影响），**本轮不做**。

**另：engineer-a4 更正了 scout 的一处机制推理（结论对、理由错）**
- scout 称 `memory_read.py:398-427 fused_memory_search_result()`「只 model_copy 列出的键」；
- **实测/读码更正**：`:420` 是 `result.model_copy(update={...})` —— **整模型复制 + 覆盖列出的键**，未列出的键**一律原样保留**；
- ⇒「新字段可能被二级融合丢掉」**不成立**；其新增的 `source_type` 同样自动保留。captain 读码确认（`:420-428`）。
- 且 scout 称 `wiki_retrieval.py` 的 `or 1.0` 可能影响 A4-4 排序 —— **不成立**：权威排序只读 `source_type` + `content_category`，**不读 `score`**，且用稳定排序保持同档位原序（有单测钉住）。两者**正交**。

### t8：旧 relation 行处置 —— **拒绝数据回填迁移，改用读侧无歧义重建** 2026-09-20

**Task**：为既有 relation 行补 `content_category`（仅可推导者）。captain 明确邀请：「若你判断回填不该做，请直接说明理由并拒绝执行」。

**我的裁定：不写数据回填迁移。** 三条理由，按重要性排序：

**① captain 的硬性约束 #3（先给「将影响多少行」统计）在本仓库不可满足，且实测证据指向「无观测样本」。**
- 全仓只有 `.tmp/` 下的**测试残留库**，**没有真实用户库**；
- 我对三个残留库跑了统计查询，**relation 行一律为 0**：

      .tmp/fault-probe-data/probe.sqlite3                      -> relations_total=0  prefers_total=0  prefers_missing_category=0
      .tmp/frontend-smoke-20260814-1535/integrated.sqlite3     -> relations_total=0  prefers_total=0  prefers_missing_category=0
      .tmp/llmwiki-visual-followup/data/agent-pet-demo.sqlite3 -> relations_total=0  prefers_total=0  prefers_missing_category=0

⇒ 任何我报出的「影响行数」都只能来自**测试残留**，把它写成「影响面」是**误导**。**先给统计再执行**这条前置条件因此无法诚实满足。

**② 读侧重建与数据回填对唯一消费者的效果完全相同，但不动用户数据。**
- `content_category` 的唯一消费者是 `memory_read` → `MemorySearchResult.content_category` → `statement_authority`；
- 全仓无第二处读取该键（`content_category_from_metadata` 只在读路径被调用）；
- ⇒ 回填迁移的唯一可观测效果，**正好就是读侧重建的效果**。既然如此，选择不写用户数据、不进启动迁移链、且天然覆盖所有年代行的那一种。

**③ 与 captain 刚批准的「只存输入、不存派生值」原则一致。**
`relation_type='prefers' → 'preference'` 是**派生**；把它写进用户数据，正是该原则要避免的。
（对比：t2 里 captain 批准存 `source_type`，因为那是**输入**。两者标准一致。）

**实现（改动收敛，2 个文件）**：

| 文件 | 改动 |
| --- | --- |
| `app/services/memory_taxonomy.py` | 新增 `_RELATION_TO_CONTENT_CATEGORY`（**只有 prefers 一条**）、`content_category_for_relation()`、`graph_fact_content_category()` |
| `app/services/memory_read.py` | 读侧由 `content_category_from_metadata(fact.metadata_json)` 改为 `graph_fact_content_category(fact)` |

**优先级刻意不合并**：metadata 有值 → 以它为准（写入期记录）；metadata 沉默 → 才回退到 `relation_type`。
**重建只覆盖 prefers，其余 relation_type 一律返回 None**——尤其 `avoids`：它看似也是偏好，但**没有任何写入点**会为 PREFERENCE 产出 `avoids`，登记它就是替代码发明规则。

**为什么 t8 只需管 relation 行（本轮实测确认，排除了一次范围扩张）**：
claim 行的 `category` 列确实是 memory_kind.value（可推导），但 `content_category_for_kind` 对非 PREFERENCE 种类产出 `fact/event/rule`，
**没有一个落在 `_USER_AUTHORITY_CATEGORIES` 内**；而 PREFERENCE **恒走 relation 分支**。
⇒ **claim 行补不补，权威轴结果都是 `mixed`**。所以「只处理 relation」不是妥协，而是**恰好等于有效范围**。

**验证（沿用 t2 标准）**：
- `apps/backend/tests/test_a4_statement_authority_wiring.py` → **15 passed**（原 10 + 新增 5）
- **反证**：令 `content_category_for_relation` 恒返回 None（重建变 no-op）→ **3 failed**，含
  `test_legacy_preference_relation_row_is_reconstructed_end_to_end`
  ⇒ 用例确实咬住重建逻辑；已还原并复跑 15 passed

**端到端证据（旧行如实构造，非模拟对象）**：走完整写入链路后，用
`UPDATE memory_graph_facts SET metadata_json='{}' WHERE id=?` 把该行**打回修复前的样子**（其余列一律不碰），
断言 `json.loads(metadata_json)=={}` 且 `content_category_from_metadata(...) is None`（确认「只认 metadata」的读法必然失明），
再经检索得到 `content_category=="preference"` / `source_type=="explicit_user"` / `statement_authority_of(...)=="user"`。

**边界证据**：
- 非 prefers（`avoids`）→ 不重建，`content_category` 为 None，权威保守降级为 **mixed**（未被抬成 user）；
- 已有值不被覆盖：metadata 写 `event` + relation_type `prefers` → 仍返回 `event`；
- 大小写/空白归一（`"  Prefers  "` → preference）；坏 JSON 不阻断重建。

**未做项与理由**：
- **未写回填迁移**（理由见上三条）——若 captain 仍要迁移，统计查询已给出可复用；但请注意 ① 的前提仍未满足；
- **未登记 `avoids` 等其它关系类型**——无写入点证据，登记即臆造；
- 未改动 `create_relation` / 写入路径（t2 已修），本轮**纯读侧**。


### t8 完成：**captain 的方案被下属以证据驳回，改用更好的读侧重建** 2026-09-20

**我要求的是**：为既有 relation 行做**数据回填迁移**（并硬性要求「必须先给影响行数统计」）。
**engineer-a4 拒绝了该方案**，改用**读侧无歧义重建**，并给出三条论据。**captain 复核后批准。**

**① 我的硬性约束 #3 在本仓库不可满足（它拒绝编数字）**：
全仓只有 `.tmp/` 测试残留库，**无真实用户库**；三个残留库 `relations_total=0 / prefers_total=0`。
⇒ 能报出的「影响行数」只能来自测试残留，**写成影响面就是误导**。**它选择说「测不出来」，而不是凑一个数。**

**② 对唯一消费者的效果完全相同，但不写用户数据**：
captain 已 grep 核实——`content_category` 的持久化键**唯一读者**是 `memory_read.py`（经 `content_category_from_metadata`）；`memory_consolidation.py` 是写方；`write_policy.py` 读的是**请求期** metadata，与持久化键无关。
⇒ 回填迁移的唯一可观测效果**正好就是**读侧重建的效果 ⇒ 选**不写用户数据、不进启动迁移链、天然覆盖所有年代行**的那一种。

**③ 与「只存输入、不存派生值」同一把尺子**：
`relation_type → content_category` 是**派生**；而 t2 批准的 `source_type` 是**输入**。**同一原则，两个不同结论** ⇒ 该原则可操作。

**改动收敛**：仅 2 个源文件（`memory_taxonomy.py` 新增推导表 + 两个函数；`memory_read.py` 换一个调用），**未动写入路径，未改契约**。

**证据（构造方式严谨）**：完整写入链路后 `UPDATE ... SET metadata_json='{}'` 把行**打回修复前**（其余列不碰），**先断言 `content_category_from_metadata(...) is None`**（证明只认 metadata 必然失明），再检索验证 `content_category=="preference"` / `source_type=="explicit_user"` / `statement_authority_of(...)=="user"`。
**反证**：令重建恒返回 None → **3 failed** 含该端到端用例；已还原并复跑 15 passed。
**边界**：`avoids` 等非 `prefers` **不重建**（保守降级 mixed，未抬成 user）；已有值不被覆盖（`metadata=event` + `prefers` → 仍 `event`）。
**范围**：claim 行即使补也仍是 mixed（非 PREFERENCE 种类不在用户权威集内）⇒「只管 relation」**恰好等于有效范围，不是妥协**。

**回归**：18 套件 **219 passed / 0 failed**；`git diff --check` 通过；ruff 仅剩既有 F821（`retrieval.py:1154`，非其文件）。

**captain 裁定：批准读侧重建，不做 037 迁移。** 理由即②③；且其自述该迁移**不带来读侧重建之外的任何可观测效果**——**无可观测收益 + 写用户数据 + 进启动迁移链，三条都指向不做**。
（若将来出现「第三方直接读 metadata」的真实需求，前提变了，结论可以变。）

**这一轮的真正价值**：**下属以证据驳回了我给的方案，并给出了更好的方案。服从指令不是标准，把事做对才是。**


### engineer-a4 修正 captain 的表述：「同一把尺子」不等于「原则可松可紧」2026-09-20

**captain 原话**：「`relation_type → content_category` 是**派生**；t2 批准的 `source_type` 是**输入**。**同一原则，两个不同结论** ⇒ 该原则可操作。」

**engineer-a4 的修正（captain 采纳，并认为比原表述更准确）**：
> 我用同一原则量出两个不同结论，**不是因为原则有弹性，而是因为两件事的性质确实不同**——
> `source_type` 是**写入期就存在的事实**（图事实的既有列，记录「谁说的」），不存它就没法判权威；
> `content_category` 在旧行上是**当时根本没记录的东西**，从 `relation_type` 反推属于**事后重建**。
> 所以「**存输入**」与「**事后补派生**」是两回事。

**为什么这个修正是重要的**：captain 的原表述容易被误读为「该原则可松可紧、按需解释」。
engineer-a4 指出真实区别在于**事实的时序性质**：
- **写入期存在的事实** → 必须存（不存则永久丢失）；
- **写入期未记录、只能事后反推的东西** → 不该回填进用户数据（那是**事后重建**，不是**原始输入**）。
**⇒ 这不是原则的弹性，而是两类事物的客观差异。**

**captain 采纳并更正自己的表述**：不再说「同一把尺子、两个结论」，改说「**同一原则，针对两类性质不同的事物**」。
若将来有人拿此当「原则可松可紧」的先例，**那是对它的误读**。

**engineer-a4 的工作区终态（自核，captain 接受）**：
```
 M apps/backend/app/services/memory_read.py
 M apps/backend/app/services/memory_taxonomy.py
 M docs/wiki-reconstruction-status.md
?? apps/backend/tests/test_a4_statement_authority_wiring.py
无后台作业；其建的临时统计脚本 .tmp/t8_impact_count.py 已删除，仓库无残留
```
**台账无重复登记**：其 t8 条目（`:3603`）与 captain 裁定条目（`:3665`）已并存且无冲突，它选择不重复登记以免制造两份措辞——**这是对的**。


### verifier 发现：验证期间被测对象被改动（R1/R2 版本问题）—— captain 协调失误 2026-09-20

**verifier 的时间线（本地 GMT+8）**：
```
13:59  开工
14:01  读到 memory_read.py 用 content_category_from_metadata(fact.metadata_json)   → 记为 R1（t2 状态）
14:05:34  memory_read.py 被改      ← t8
14:06:20  测试文件被改             ← t8
14:07:51  memory_taxonomy.py 被改  ← t8
现在   读侧为 graph_fact_content_category(fact)：metadata 优先，沉默时由 relation_type 重建  → R2（t8 状态）
```
**根因：captain 在 t7（验证 t2）在飞时派了 t8，而 t8 要改同一批文件。** 这是**我的协调失误**——与「全量套件运行期间改代码」是同一类错误，只是这次发生在团队内部。

**verifier 的三点影响（captain 逐条确认）**：
1. **R1/R2 差异**：`content_category_from_metadata` 在 **helper 层仍返回 None**，但**消费者层** `graph_fact_content_category` **会兜底重建**。⇒「不回退」这条**只对 helper 层成立**。**这不是矛盾，是 t8 的设计目的**（metadata 优先，沉默时重建）。
2. **台账过期（captain 的错，已修）**：R2 的读侧重建**实质上覆盖了旧库**（至少对 `relation_type=prefers`）⇒「无回填 ⇒ 旧库偏好关系权威轴仍失明」**在 R2 上不再成立**。**captain 已更正台账两处**（`:3542`、`:3575`），并写明仍成立的部分（非 `prefers` 不重建；claim 行不受影响）。
3. **反证需重跑（captain 的推测已被实测推翻）**：captain 曾推测「R2 有读侧重建 ⇒ 很可能不再恰好 3 条」。
**verifier 实测反驳**：CF1（R2 快照 + 删除 `create_relation` 的 `metadata_json` 实参）**重跑两次，稳定 3 failed / 12 passed**，失败用例名与 R1 自述完全一致。
⇒ **台账不得写「t8 让 t2 的反证失效」——那不准确。准确写法（verifier 给出，captain 采纳）**：
> 反证**仍成立且可复现**，但**覆盖面被 t8 削窄**：3 条失败**全部是持久化层断言**；
> 同一次 CF1 运行里，**读路径依然返回 `authority="user"`**（被读侧重建补回）。
> ⇒ **端到端权威断言在 R2 上不可证伪**。要恢复可证伪性，需要一条**显式切断重建**的反证路径
> （例如把 `graph_fact_content_category` 做成可注入/可关闭），而不是靠现有用例。
> **t2 与 t8 覆盖的是同一缺陷的不同层面（写入落库 vs 读侧可见性）**，两者叠加后**旧的端到端反证不再能感知写入侧回归**。

**verifier 的应对（captain 认可并采纳）**：不再追活动工作树，改为**冻结快照**（复制到临时目录 + 记录 SHA256），所有剩余结论**只对快照负责**，并逐项标注 R1/R2。
**这正是 captain 在本会话反复强调的「运行期间不得改被测对象」——这次由 verifier 替 captain 执行了它。**

**captain 已向 verifier 确认冻结状态**：
```
engineer-a4  → t9（只写设计文档，不碰代码）
engineer-rrf → t3（retrieval.py / snapshot_reader.py / wiki_retrieval.py，与 memory_* 不重叠）
scout        → t6（题集与 app/evals/，已要求冻结写入）
⇒ memory_read.py / memory_taxonomy.py / test_a4_statement_authority_wiring.py 冻结，t8 已 completed
```
并要求其最终报告**明确列出「R1 上成立但 R2 上不成立的结论清单」**——这是本次最有价值的部分之一。


### t6 完成：题集判别力提升（45/48）—— 并诊断出**两条独立成因** 2026-09-20

**改动仅 2 文件**（`app/evals/phase_d_questions.py`、`tests/fixtures/phase_d_questions.json`），**未改产品代码**。
**结果**：45/45 饱和 → **45/48**；**原 15 场景全部保持 3/3（零回归）**；新增 `lexical_gap` **0/3 如实保留，未凑绿**。

**成因 A：`answer` 类题 golden 恒在 bm25 前 4 位 ⇒ 读窗永不截断**
```
45 题 bm25 排名分布：第1位 15 | 第2–3位 19 | 第4–8位 2 | **第9–24位 = 0** | 未找到 9
读窗 max_pages=8、候选池 24 ⇒ **第 9–24 位为空，截断边界从未被触及**
⇒ 任何排序改动只要 golden 仍在前 8 位，结果**逐字相同**。这就是「只能持平或下降」的机制。
```

**成因 B（此前无人点出）：`reject`/`stale` 按「缺席通过」，构成**反向判别器****
```
phase_d_eval.py:49-52   if action in {"reject","stale"}: return not (expected & actual)
q_raw_updated_* 的 golden 页在 bm25 中**根本找不到**(rank_bm25=None) ⇒ 未被引用 ⇒ 平凡通过
但语义腿能找到它(rank 1–2) ⇒ **更好的检索器反而让这 3 题失败**
```
**⇒ 这指向我写的判据存在缺陷。** scout 按纪律**只登记不改判据**（正确）。

**另登记一处我的判据缺陷**：`conclusion_coverage` 用朴素子串匹配，**有否定对假阳性**——实测 `"支持加急"` 在**错误页**的 `"不支持加急发货"` 中作为子串命中（coverage=1.0 而 recall=0）。**先于本次改动存在**，未改判据。

**新增题与实测判别力**（`lexical_gap`：题面与权威页**无共同词**）：

| 新题 | 题面 | golden | bm25 | 语义 |
| --- | --- | --- | --- | --- |
| 001 | 东部地区要等多久才能到货? | Region-East.md | **未找到(0 条)** | **1** |
| 002 | 南部区域能不能快点发货? | Region-South.md | **未找到(仅 2 条无关页)** | **1** |
| 003 | 这家供应商接受紧急订单吗? | Supplier-Alpha.md | **未找到(10 条均不含 golden)** | **4** |

纯词法基线 **passed 0/3** ⇒ **每条都能 pass/fail 翻转。改前翻转题数 = 0 —— 这正是「饱和」的精确含义。**

**新判别力指标**：

| 指标 | bm25 | 语义 | 差距 |
| --- | --- | --- | --- |
| MRR | 0.5111 → 0.4792 | 0.5722 → 0.5833 | 0.0611 → **0.1041（+70%）** |
| hit@1 | 15 → 15 | 16 → 18 | 1 → **3（×3）** |
| hit@8 | 36 → 36 | 39 → 42 | 3 → **6（×2）** |
| found | 36 → 36 | 39 → 42 | 3 → **6（×2）** |

**建议口径**：不只报通过率，同时报 MRR / hit@1 / hit@8 / **pass-fail 翻转题数**——改前通过率恒 100%，**排名指标是唯一能显示差异的量**。

**回归**：题集校验器 + 驱动 **19 passed**；全量 48 题 **45 通过 / 3 不通过**，failures 恰为 3 道新题，**原 15 场景零回归**。

**captain 采纳的关键范围洞察（scout 提出）**：
> **下限/截断只能「移除」候选，不能「新增」。** `lexical_gap` 3 题失败的机制是 golden **根本不在 bm25 候选里** ⇒ 截断改多少都不会把不存在的候选变出来。
⇒ **t3 的验收准则明确不含这 3 道新题**（避免把与 t3 无关的失败记成 t3 未达标）。已通知 engineer-rrf。
⇒ 这 3 题的通过**只依赖语义腿**（wiki 快照页向量索引），而该工作**此前没有 owner**——captain 已建 t10 并派给 engineer-rrf（先可行性、后实现）。

**一处事实更正（captain 实测）**：scout 称「从仓库根跑报 file or directory not found」，**实测两种 cwd 都能收集到 19 题**。但其观察指向真问题：**仓内有两套不兼容的测试导入约定**——**39 个文件**用 `from apps.backend.tests...`（需仓库根），phase_d 相关用 `from tests.phase_d_eval ...`。**「正确 cwd」取决于具体文件，不存在统一答案。**

### t9 完成：混排证据面落点**设计提案**（仅文档）2026-09-20

**产物**：~BT~docs/a4-mixed-evidence-surface-design.md~BT~（新建）。**未改产品代码/契约/迁移/测试**。

**核心产出：把「外部来源不能纠正用户偏好」拆成四个能力，而不是当成一个能力。**

| # | 能力 | 可否确定性实现 | 今天状态 |
| --- | --- | --- | --- |
| R1 | 排序：用户权威排在外部来源之前 | 可以 | **已实现**（t2） |
| R2 | 潜在冲突标记 | 可以（实体重叠），**有假阳性** | 未实现 |
| R3 | 真冲突判定 | **不可以，需要语义（模型）** | 未实现 |
| R4 | 裁决（用户优先） | 可以，但**只有 R3 成立时才有意义** | 未实现 |

**⇒ 决定性结论：「强制外部来源不能纠正用户偏好」在今天不可能纯确定性完成。**
R4 的确定性实现依赖 R3，而 R3 需要模型。能做的只有 R1 + **把结果显式告知模型（建议性，非强制）**。
**任何声称「已强制」的方案，必须先回答「R3 由谁做」。**（captain 已采纳并要求所有后续表述遵守。）

**现状定位（全部带行号）**：
- 权威排序实际在 ~BT~prompt_memory_assembler.py:161-163~BT~；两个装配入口（~BT~chat.py:302-316~BT~ / ~BT~:483-495~BT~）都喂 ~BT~state.citations~BT~；
- 证据门恒等变换：~BT~assessment_input()~BT~ 只被 wiki 节点调用（~BT~wiki_retrieval.py:438~BT~ / ~BT~:562~BT~），输入面全为 external；
- **混排面确实存在**：~BT~state.citations~BT~ 唯一写入点 ~BT~events_helpers.py:101-111~BT~；agent 的 ~BT~search_memory~BT~（~BT~tools.py:486-506~BT~）
  → ~BT~RuntimeRetrievalAdapter~BT~（~BT~adapters.py:226~BT~，注入点 ~BT~:4580~BT~）→ ~BT~:269-298~BT~ 构造 ~BT~UnifiedMemorySearchService~BT~，
  含 ~BT~RetrievalMemorySourceAdapter~BT~（外部）+ ~BT~GraphMemorySourceAdapter~BT~（带权威输入）+ ~BT~DiaryMemorySourceAdapter~BT~。

**选项裁定**：A（组装层权威声明补强，**补逻辑**，推荐方向）；B（A + entity_refs 潜在冲突标记，假阳性削弱既有保证，应作增量）；
**C 更差**（把图事实接进证据门 = **新增数据通路**，且与「确定性赋值点，模型不可设置」~BT~wiki_retrieval.py:163~BT~/~BT~:414~BT~ 直接冲突）；
**D 更差**（为**未证实**的需求建组件 + **必然**引入模型调用）。

**新增设计约束（§0.1，captain 升格）**：**不得以「外部来源 vs 用户权威」为名压制新事实。**
「用户说喜欢供应商 A」vs「资料说 A 已倒闭」——后者是**新事实**，不是「纠正偏好」；一刀切会**压制真实更新，本身是伤害**。
⇒ 该区分**只能靠 R3 判定，不能靠排序解决**。本项能力的**允许表述上限**：「权威排序 + 建议性声明」。

**执行顺序（captain 修正了本文档原先的排序）**：
~BT~~BT~~BT~
第 1 步（先行）：新增「外部来源试图纠正用户偏好」评测场景 —— 让 A 变得可验证
第 2 步：实现 A，验收准则 = 该场景 + 反向断言
第 3 步：若 A 不够，再评估 B / D
~BT~~BT~~BT~
**本文档原先建议「A 可立即做」，是错的**：§5.2 已指出提示词声明的有效性**无法用单测证明**，而现有 45 题无该冲突场景
⇒ 此时实现 A 会产出**无法验证**的改动。**连 A 本身也需要先有证据才能被验证。**

**待验证的前置项**：§1.4「双 graph 腿」——~BT~RetrievalService~BT~ 内部另有一条 graph 腿（~BT~retrieval.py:1044-1097~BT~）产出 ~BT~note_id=""/chunk_id="graph:<id>"~BT~，
**不带** ~BT~fact_id/content_category/source_type~BT~；与 channel ~BT~graph~BT~ 的 stable_id 不同，融合按 stable_id 归并（~BT~retrieval_fusion.py:167-175~BT~）、
去重键 ~BT~(note_id, chunk_id, relative_path)~BT~（~BT~graph_runtime.py:1000-1017~BT~）也不同 ⇒ **不会被合并**。
若成立 ⇒ 同一条图事实会以一条 external 排序键的 citation 与用户权威证据并列，**直接削弱 A 的效果**，**必须在实现 A 之前验证**。
**该条仅为读码推断，未实测**（本任务限定只写文档）。

**未做**：未实现任何选项；未新增表；未在证据门内建议权威裁决。


### 事实澄清：测试 cwd 不存在统一答案（captain 实测）2026-09-20

**起因**：engineer-a4 称「必须仓库根，在 `apps/backend` 下是假红」；scout 称「仓库根不可用，必须 `apps/backend`」。**两者相互矛盾，captain 实测。**

**包结构实测**：
```
apps/__init__.py               : False   ← 无
apps/backend/__init__.py       : False   ← 无
apps/backend/tests/__init__.py : True
```
**cwd 实测（phase_d 驱动）**：
```
cd E:\agentproject            ; pytest apps/backend/tests/test_phase_d_eval_driver.py → 19 tests collected
cd E:\agentproject\apps\backend ; pytest tests/test_phase_d_eval_driver.py          → 19 tests collected
```

**结论**：**两种 cwd 都可用，关键在于「路径要与 cwd 匹配」**。
- **39 个测试文件**用 `from apps.backend.tests...` → 靠**隐式命名空间包**在**仓库根**解析（`apps` 无 `__init__.py` 也成立）；
- **phase_d 相关**用 `from tests.phase_d_eval ...` → 在 **apps/backend** 解析（`tests/__init__.py` 存在，是常规包）。
- scout 报的 `file or directory not found` 很可能是**从仓库根跑了 `pytest tests/...`**——根目录下没有 `tests/`，**那是路径错误，不是导入错误**。

**captain 处置**：**不再要求统一 cwd**，改为在给成员的命令里**按文件写清**。仓内两套不兼容的测试导入约定属既有状况，**改动面大且与本轮无关，不改**。


### 事实澄清：测试 cwd 不存在统一答案（captain 实测）2026-09-20

**起因**：engineer-a4 称「必须仓库根」；scout 称「必须 apps/backend」。**两者矛盾，captain 实测。**
**包结构**：`apps/__init__.py`=False、`apps/backend/__init__.py`=False、`apps/backend/tests/__init__.py`=True。
**cwd 实测（phase_d 驱动）**：仓库根跑 `pytest apps/backend/tests/test_phase_d_eval_driver.py` → 19 collected；`apps/backend` 跑 `pytest tests/...` → 19 collected。**两者皆可。**

**结论**：**关键在「路径与 cwd 匹配」**。39 个文件用 `from apps.backend.tests...`（靠隐式命名空间包在**仓库根**解析）；phase_d 相关用 `from tests.*`（在 **apps/backend** 解析）。
scout 报的 `file or directory not found` 很可能是**从仓库根跑了 `pytest tests/...`**——根下无 `tests/`，**属路径错误而非导入错误**。
**captain 处置**：不再要求统一 cwd，改为在命令里按文件写清。仓内两套不兼容约定属既有状况，**不改**。


### t6 补充：冻结指纹、时间线澄清、判别力证明方法与**一处诚实的负向结论** 2026-09-20

**① 冻结基线指纹（供 engineer-rrf / verifier 核对「是否同一套题」）**：
```
tests/fixtures/phase_d_questions.json
  sha256 = 36581ff0ccddb9e3995ac0bc405c49099c321e8e1af76fcf01533e29c78e1071
  bytes  = 25526   mtime = 2026-09-21T05:56:07.6952328Z
app/evals/phase_d_questions.py
  sha256 = 3334284498c7692d919d466f14b5766fbd64f7cbb4053fe7c2b23370077382ff
  bytes  = 6835    mtime = 2026-09-21T05:56:07.6237169Z
题量：16 场景 × 3 = 48 quality + 8 safety；自检(06:59:13Z)两处哈希与 mtime 均未变 ⇒ 冻结期间零写入
```

**② 时间线澄清（客观、不追责，且**免除 engineer-rrf 的责任**）**：
```
engineer-rrf 的 rrf_probe_full.json 写于 05:39:40Z
scout 的题集改动落盘于              05:56:07Z
⇒ bm25 臂确实早于题集变更；「45 题 vs 48 题」是**时间顺序的必然结果**，与他的操作无关。
```
**captain 认领协调失误是准确的**（未设冻结窗口）。

**③ `lexical_gap` 的设计意图：它区分的是「召回」，不是「排序」**
这是它与其余 15 场景的**根本区别**：
- 其余 15 场景的判别变量是**证据策略/生命周期/门控**（missing / stale / revoked / conflict / oversized / budget / ninth_page / distractor…），检索前提是「golden 词法可召回」——实测 bm25 恒在**前 4 位**；
- `lexical_gap` 的判别变量是**检索腿本身**，专取**同义改写**：题面与 golden 页**零共同实词**。
```
001  东部地区/到货    ↔ 华东区/交货周期     地名别称 + 动作词改写
002  南部区域/快点发货 ↔ 华南区/支持加急     地名别称 + 口语化改写
003  紧急订单          ↔ 加急发货            同义术语替换
⇒ BM25 打分无词可依 ⇒ rank_bm25=None（完全没召回）；稠密检索凭语义可召回。
```
**这就是「词法 vs 语义」最纯粹的可分离面。**

**④ 判别力的证明方法（两级证据 + 第三方独立确认）**：
1. 用**真实** `build_corpus("published")` 建语料（与驱动同一构造器）；
2. 词法排名取自**真实生产路径** `WikiSnapshotReader.search(pin, q, limit=24)`；
3. 语义排名取自**真实内置 ONNX**（512 维），嵌入对象与读者所见一致；
4. **筛选规则**：只留两腿在**通过/不通过边界**上分离的候选。**10 个候选 → 3 个入选**；其余 6 个（两腿都把 golden 排第 1）**刻意剔除**——加进去只会**稀释**判别力。
5. **第三方独立确认（最强证据）**：engineer-rrf 的 fusion 臂得 **2/3**，而**失败的那题（003）恰是 scout 测得语义排名最差的（rank 4，另两题 rank 1）** ⇒ **题级预测与独立实测一致，判别力不依赖 scout 自己的探针口径。**

**⑤ 一处诚实的负向结论（重要，影响后续可验证性）**：
captain 建议的「golden 在 bm25 排 >5 但语义排前」这类**排序型**题，**在本语料上不可行**：
基础语料仅约 14 页，要让 golden 跌出读窗(>8) 需 ≥9 个更优页，**规模不够**。
实测 10 个候选：**凡 bm25 能召回的，golden 一律第 1；凡靠后的，一律 `None`。**
⇒ **判别只能建在「召回有无」上，不能建在「排序优劣」上。**
⇒ 若将来要**排序型**题，**须先扩语料（≥20 页有效干扰页）**——属语料改动，不在 t6 范围，**scout 未做**（正确）。
**captain 据此更正自己的建议**：我之前提的「排序型题」在本语料不可行；**验证排序改进的前提是先扩语料**。

**⑥ engineer-a4 的引用纪律（值得记录）**：它发现 scout 引用的 `memory_read.py:352`/`:357` 实际应为 `:359`/`:364`（其 diff 为 `7 0`，只加了 7 行，非第三方改动）；
并**主动复核了自己 t9 文档里的全部引用**（因其 t8 改过 `memory_read.py`，可能推移行号）——`memory_read.py:115/177/255-278`、`prompt_memory_assembler.py:161-163`、`wiki_gate.py:115/138`、`events_helpers.py:101-111`、`adapters.py:226/4580`、`retrieval.py:1044/565`、`retrieval_fusion.py:167-175`、`graph_runtime.py:1000` **全部解析正确**。


### 跨线约束（scout 提出，captain 采纳）：三条工作线中**只有语义腿**能动 `lexical_gap` 2026-09-20

**scout 的跨线提醒**：排序键**只动档位、档位内保持检索序** ⇒ **A4-4 无法修复检索未召回的题**。

**三线能力边界（captain 归纳并确认）**：

| 工作线 | 能力 | 对 `lexical_gap`（golden 完全不在 bm25 候选里） |
| --- | --- | --- |
| **A4-4 权威排序** | 只改**档位**，档位内保持检索序 | ❌ 动不了 |
| **t3 相关性下限/截断** | 只能**移除**候选，不能新增 | ❌ 动不了 |
| **语义腿**（wiki 快照页向量索引） | 能**新增**候选（稠密召回） | ✅ **唯一能动** |

**⇒ 不得把 `lexical_gap` 三题算进 A4-4 或 t3 的收益预期。** scout 与 engineer-a4 均已各自声明「从未把这三题算入收益预期」。

**scout 对 engineer-a4 三条声明的独立复核（非采信）**：
1. **`model_copy(update=...)` 保留未列出键** —— scout **实测确认**：`r.model_copy(update={"score": 2.0})` → `score=2.0` 且 `content_category`/`source_type` 均保留，`VERDICT unlisted keys preserved: True`。⇒ scout 原报告「只 model_copy 列出的键」是**错误表述**，已照收更正（**理由比结论重要**）。
2. **无短路分支**：`memory_read.py:352` 无条件调 `reciprocal_rank_fusion`，`:357` 无条件 `fused_memory_search_result` ⇒ engineer-a4 的端到端用例**确实经过二级融合**，字段保留断言有效。
3. **A4-4 与 score 正交**：`evidence_policy.py:121-132 statement_authority_sort_key` **只读 `source_type` + `content_category`，不碰 `score`**；`prompt_memory_assembler.py:161-163` 与 `wiki_gate.py:127` 均用稳定 `sorted`；稳定性单测存在于 `test_a4_statement_authority_wiring.py:272`。⇒ scout 此前的 `or 1.0` 担心对 A4-4 **不适用**。

**captain 评价**：**scout 对 engineer-a4 的更正做了独立实测而非采信**——这正是我要的验证纪律。
（本会话我已两次被「采信而非验证」坑到：一次是 scout 的 `model_copy` 表述，一次是我自己的引注错误。）


### t3 完成：**融合严格优于两路单路** —— captain 的「不合入」裁定被推翻 2026-09-20

**captain 从原始证据独立复核**（读 `E:\rrf_scratch\ablation48_*.json`）：
```
三臂 fixture_sha256 全为 36581ff0ccddb9e3   ← 同一题集版本,可比
bm25      passed 45  failures=[lexical_gap_001/002/003]              reads 271  replaced 3   ms 1195
fusion    passed 47  failures=[lexical_gap_003]                      reads 418  replaced 34  ms 2563
semantic  passed 45  failures=[two_hop_003/alias_003/ninth_page_003]  reads 385  replaced 1   ms 2644
```
**⇒ 融合严格优于两路单路（47 > 45 且 47 > 45）**，且失败集合印证逐题故事：融合**修好**了 bm25 失败的 `lexical_gap_001/002`，**同时没丢**语义失败的 `two_hop_003/alias_003/ninth_page_003`。**这正是混合检索应有的形态。**

**⚠️ captain 认错**：我此前基于 engineer-rrf 的**中期代理指标**（页级 hit@8）裁定「不合入」，并写了三条理由。
**节点级实测证明该代理指标没有建模两件事**：
1. 多引用题要求**全部 golden 都进读窗口**；
2. 节点的**价值准入路径**（`replaced 3 → 34` 说明准入/置换行为被显著改变，代理指标完全没反映）。
**captain 接受「验收必须以节点级 pass 为准」，撤销原裁定。**
这是 captain **第二次因采信代理指标而误判**（第一次是采信 scout 的 `model_copy` 表述）。
**engineer-rrf 主动标注「这是代理指标」并最终自己推翻它——这个自我更正比一个正确结论更有价值。**

**captain 裁定 (1)：生产接线不做。** 理由（与「拒绝无收益改动」同一把尺子）：
- **成本**：语义腿 ≈ +0.6s/查询且**随 wiki 规模线性增长**；
- **`authorize` 逐页回调**在生产版每页读一次证据快照，**大 vault 上比嵌入还贵**；
- **隐私**：必须只复用 **local transport** 嵌入器，否则会把 wiki 正文发到远端，**等于削弱隐私保证**。
⇒ **正确顺序是「先做发布期向量投影把成本摊到写入侧，再接线」**。本轮落地的是**默认关闭的能力 + 测试**，线上行为零变化。

**captain 裁定 (2)：`q_lexical_gap_003` 不调权。** engineer-rrf **离线扫过 k=1..100、w_vec=1..5，48 题上无任何配置能同时赢两路单路的 hit@8** ⇒ 在同一题集上调参不构成合入依据。同意**先扩题再定权**。

**engineer-rrf 的改动**：`snapshot_reader.py`(+171/-5，`semantic_embedder=None` 注入 / `_semantic_page_ranking` / `_fuse_semantic_channel` 复用既有 RRF / `last_search_mode` 暴露降级原因)；`tests/phase_d_eval.py`（消融开关，默认不变）；新增 `test_wiki_semantic_fusion.py`(6 条，确定性桩嵌入器，不依赖 onnx) 与 `phase_d_fusion_ablation.py`(不被 pytest 收集)。

**既有保证未被削弱（有证据，captain 逐条认可）**：
1. **默认路径逐行不变**：改前(45 题) vs 改后不注入嵌入器(48 题)，在 **45 道共有题上 0 个字段差异**（passed/recall/precision/coverage/reads/replaced/stop_reason/cited 全等）；
2. **降级逐条相同**：嵌入器 None/抛错/缺 `embed_documents` ⇒ `bm25_semantic_degraded`，结果与纯 bm25 相同（有测试）；
3. **权限/版本/完整性不削弱**：语义候选先过 `authorize`，最终仍逐条 `_load(pin, path, content_hash)` 复核；**语义腿不得复活被撤销页**（有测试）；
4. **`score` 语义未破坏**：bm25 命中仍 `-bm25`；语义独有命中沿用 LIKE 的 `0.0` 中性约定。

**回归**：7 套 **64 passed / 0 failed**。

### 测试 cwd 规则（scout 精确化，比 captain 的表述更实用）2026-09-20

**captain 与 scout 测的是不同形式，两者都对**：
```
scout 测 dotted 模块形式:  cd 仓库根 ; pytest apps.backend.tests.test_phase_d_eval_driver  → file or directory not found (0 collected)
captain 测 path 形式:      cd 仓库根 ; pytest apps/backend/tests/test_phase_d_eval_driver.py → 19 collected
```
**scout 进一步实测出完整规则（captain 采纳）**：

| 导入约定 | 文件数 | cwd=仓库根 | cwd=apps/backend |
| --- | --- | --- | --- |
| `from apps.backend.tests...` | **39** | ✅ | ❌ collection error |
| `from tests...`（含 phase_d） | **72** | ✅（path 形式） | ✅ |

**⇒ 实用建议（优于 captain 的「按文件分别写清」）**：**统一用 `cwd=仓库根` + path 形式 —— 实测两种约定都能跑。** `apps/backend` 只对 `from tests.` 一族有效，是较窄的选择。


### t7 独立验证报告（A4 接线）—— 高价值发现汇总 2026-09-20

**验证者做法（captain 认可）**：检测到验证对象在窗口内被改（R1→R2），**冻结快照** `E:\a 工作\wiki-audit\snapshot-r2`（逐文件 SHA256），**自写探针**（不复跑实现者测试），所有结论只对快照负责并标注 R1/R2。
**它还推翻了自己探针的顺序相关假象**（第一版在同一进程跑全部变体 → 逐进程重跑证伪）——**自我纠错，很好**。

| # | 检查项 | 结论 |
| --- | --- | --- |
| 1 | 端到端（偏好陈述 → preference/explicit_user/user） | ✅ 通过（R2 快照，自写探针 + 直接读 SQLite 原始行） |
| 2 | 反证「metadata 改回 None → 恰好 3 条失败」 | ✅ 独立复现，**条数与测试名完全一致**（但强度见下） |
| 3 | `content_category_from_metadata()` 降级 | ⚠️ **分层**：helper 层通过（13 种输入实测，缺失/损坏一律 None，从不回退 fact）；**消费者层在 R2 上不成立** |
| 4 | `wiki_gate` 权威排序是否恒等变换 | ✅ **确实是**，且用**生产路径实测**确认（非读码推断） |
| 5 | 契约一致性 | ✅ 通过（再生成前后哈希一致） |
| 6 | 是否削弱既有保证 | ✅ 复核范围内未发现削弱；「21 套件 306 passed」**无法精确复现**（清单未枚举），但未发现失败 |

**⚠️ 最有价值的发现（captain 采纳并要求登记）：反证强度边界**
> 在 CF1（删掉 `_create_relation_impl` 的 `metadata_json` 实参，恢复修复前行为）上，**读路径依然返回 `content_category="preference"`、`authority="user"`**——因为 **R2 的读侧重建会从 `relation_type="prefers"` 把它补回来**。
> ⇒ 该反证证明的是**「持久化断言非空洞」**，**没有**证明「端到端权威断言非空洞」——**写入侧回归会被读侧重建掩盖**。
**这是 engineer-a4 未登记的强度边界**（它的反证本身诚实，但没标强度）。要钉死端到端权威结论需**显式切断重建**的反证（CF2 做了，但同时改了读侧，不再是纯写入侧反证）。

**另两条 captain 需处理的新发现**：
1. **A4 覆盖范围取决于抽取器**（§9.4）：**独立措辞的偏好陈述可能被判为 `fact` 而失去用户权威**。⇒ A4 的实际覆盖面受限于分类器，**不是「所有用户偏好都被覆盖」**。
2. **非对象 metadata 导致事实静默不可召回**（§7.3）：现象可复现（逐进程、逐新库），**但根因未定位**；涉及文件不在 t2 清单内，**未证明是既有问题还是本轮引入**。⇒ **潜在缺陷，需调查**。

**captain 已确认/已答的**：
- §9.1「R1/R2 须区分、文档局限 1 需同步」→ **captain 已修**（台账两处已更正）；
- §9.2「不得把 `wiki_gate` 权威排序记为增益」→ **captain 已裁定并写入**；
- §9.5「14:05–14:07 是谁改的」→ **captain 已答**：是 t8（engineer-a4 的读侧重建），captain 派单失误导致与 t7 冲突。

**captain 未验证的（verifier 诚实登记的，captain 接受）**：306 这个数字、R1 版本结论、非对象 metadata 根因、快照是否等于最终交付版本、组装层排序对**回答质量**的影响（需模型调用）、`MemorySearchResult` 新字段对桌面端的影响。


### t10 完成：§1.4 双重入场**实测成立**，且比原推断更精确 2026-09-20

**并发纪律（captain 认可）**：READ_TIME_UTC=2026-09-21T07:02:19Z；`retrieval.py` SHA256=000F0F4F…、mtime=2026-09-19T17:30:14Z、`git diff --numstat` 为空 ⇒ **读取时该文件未被修改**，与 engineer-rrf 无冲突。

**判定：成立（VERDICT=True）**。实测 `fusion.input_counts = {'graph': 2, 'retrieval': 1}`，3 条结果中：
```
位置1  chunk_id=b09114fc…(fact id 本身)  fact_id=有  content_category=preference  source_type=explicit_user  authority=user      sort_key=0
位置3  chunk_id=graph:b09114fc…          fact_id=null content_category=null      source_type=null          authority=external  sort_key=2
```
⇒ **同一条用户偏好事实入场两次**，其中一条是**权威盲副本**（`retrieval_channels=['graph','retrieval']`，`entity_refs=[]`）。

**比原推断更精确的一点（重要）**：内部 graph 腿**只 traverse 关系边**——第一版探针种 `claim` 时腿 A 返回 0 条，**改种 `relation` 才复现**。
⇒ **只有 `statement_kind=relation` 会双重入场**。而 **A4 用户权威类全部是 relation**（PREFERENCE 恒走 `create_relation`）
⇒ **该问题恰好命中 A4 的目标场景，不是边缘情形。**

**对选项 A 的影响：稀释，不是阻断。** 用户权威证据后面跟着同事实的 external 副本，模型会看到同一件事被标成两种权威档位。
⇒ **实现 A 时必须同时处理这条盲副本**，否则权威信号被稀释。

**§5.3 已核实 ⇒ 选项 B 按原设计不成立**：
`MemorySearchResult.entity_refs` 的**唯一填充点**是 `memory_read.py:242/267`（图路径）；实测那条 external 副本 `entity_refs=[]`。
⇒ **外部（wiki/笔记）结果永远没有 `entity_refs`** ⇒ B 的「实体重叠」在外部侧**无从计算**。
**B 若要做，必须先给外部结果补实体标注——那是新增数据通路，不再是「补逻辑」的小增量。**

**§5.5 部分核实：又找到一处候选面**：
`independent_source_rejection_reason()` 放行 RAW_SOURCE 与 USER_STATEMENT，它在 **wiki 记忆闭包准入**处被用（`memory_closure.py:185/:818/:1393`、`ingest_identity.py:19`）
⇒ 用户陈述可与外部来源一起成为**编译路径的根** ⇒ **「纠正」不限于回答路径**。
但 engineer-a4 **未审计**该路径是否真做裁决（本次只核查准入）。**不改变推荐**；但若将来做「强制」，**编译面必须一并考虑**，否则会出现「**回答层不纠正、编译层纠正**」的口径分裂。

**纪律**：探针在仓库外（`probe_dual_graph_leg.py` + `t10-probe-output.txt`），**仓内无脚本**（git status 已核）；本轮只改设计文档，未动产品代码。
**未做**：真实语料下双重入场的**出现频率**（构造性验证不测频率）；编译面裁决逻辑的审计。


### t12 中期：engineer-rrf 的设计要点（captain 认可）2026-09-20

**已落盘**：
1. **修 `or 1.0`**：新增 `_candidate_score(value)`——**只有 None/键缺失才回落 1.0，`0.0` 保持 `0.0`**；四处同类写法全替换（`_citation_value` L73、`candidate_scores` L277、`extra` 价值 L347、`held_scores` L386）。**没有改测试来迁就。**
2. **动态相关性下限**：`_RELEVANCE_FLOOR_RATIO = 0.4`（= 最佳**正分**词法命中 × ratio）；首轮窗口只读达标候选，**被截断者不丢弃**，进入价值预检池（`extra_pool = deferred + candidates[max_pages:]`）⇒ **召回面不因截断而变窄**；新增可观测字段 `wiki_reading.relevance_floor / truncated_count / deferred`。
3. 新增 `tests/test_wiki_relevance_truncation.py`（9 条全绿）。

**captain 特别认可的两点推理**：
- **「无词法证据的候选（score ≤ 0，LIKE 兜底 / 语义独有命中）不受词法下限裁决」**——engineer-rrf 原话：「`0.0` 表示「**没有词法证据**」而不是「词法相关性很低」——这正是 `or 1.0` 那个缺陷的反面错误，不能再用一次。」**它没有用第二个错误去修第一个错误。**
- **「被截断者不丢弃，进入价值预检池」** ⇒ 截断只改变「首轮直接读谁」，**不缩小召回面**。比 captain 原本设想的「截断即排除」更稳。

**`ratio=0.4` 的取值依据合格**：离线扫描 48 题真实候选分数，ratio ∈ [0.2, 0.5] **零黄金页掉出窗口**，**0.6 起开始丢页**（`q_single_page_001` 等 4 题）⇒ 取区间中段。**有区间、有边界、有数据 ⇒ 是参数化下限，不是魔法常数。**

**三臂归因**（`baseline` 旧 score 语义无下限 / `scorefix` 只修 score / `truncation` 本次改动后）⇒ **把两个改动的效果分开归因**，避免「改了两处、说不清谁起作用」。
小样本预跑（3 题 single_page）：reads 18 → 11（−39%），truncated 7，通过率 3/3 不变。**以完整数据为准。**

### 团队流程规则（engineer-a4 提出，captain 采纳）2026-09-20

**engineer-a4 的自省**：
> 我做了「改过文件后重核自己文档的行号」，但**没想到同批改动也让别人更早捕获的行号失效**。
> 只有插入者知道插了几行、插在哪——**插入式改动者有义务广播位移量**。这条我上一轮做反了，后续会改完即发。

**captain 采纳为团队规则**：**插入式改动者有义务广播位移量**（旧行号 → 新行号的换算表）。
**这与「冻结窗口」是同一类协调问题：改动方有义务告知影响面。**

**它提供的换算表**（供 verifier t14 使用）：
```
**⚠️ 本表适用范围（engineer-a4 事后撤回其可用性，captain 据此加注）**：
```
本表是「工作树 vs HEAD」的偏移（git diff -U0 的语义），表头未声明基期。
✅ 对 HEAD 相对的引用仍有效（如从 git show HEAD:path 读到的行号）；
❌ 对「捕获时相对」（working tree @T）的引用**无效**。
实测反例：memory_taxonomy.py 本表预测 +79，而捕获时相对位移实测只有 +5
  （_KIND_TO_CONTENT_CATEGORY 25→30）；按 +79 订正会多推 74 行，**比不订正更错**。
  原因：那 +77 的 hunk 是 A4-1 阶段工作，在 05:36Z 捕获时已在工作树、不在 HEAD。
⇒ 订正一律改用 scout 的**符号名 grep 实测锚点表**，不做偏移量算术。
```

memory_read.py          L<25→+0 ; 25≤L<273→+1 ; L≥273→+7
memory_taxonomy.py      L<3→+0  ; 3≤L<25→+2  ; L≥25→+79（含 A4-1 阶段改动，非全属本轮）
memory_entity_graph.py  L<1229→+0 ; 1229–1240→+1 ; 1241–1254→+2 ; 1255–1306→+3 ; L≥1307→+9
```
**注意**：verifier 的**快照**自洽（快照内行号与快照内文件一致），**不需要换算**；只有引用**活动树**或 **scout 的 t1 基线表**时才需要。


### 引用时效规则（scout 提出，captain 采纳为团队规则）2026-09-20

**成因（精确，非猜测）**：scout 用 `git diff -U0` 查明 `memory_read.py` 恰好 2 个 hunk：`@@ -24,0 +25 @@`（+1 行）与 `@@ -272,0 +274,6 @@`（+6 行），**均在 352 之前** ⇒ 352+7=**359**、357+7=**364**。
⇒ **不是第三方改动、不是读取时机——是 engineer-a4 自己 t2/t8 的 +7 行推移了行号**。scout 的引用**在读取时刻正确**，之后被推偏。

**scout 顺此查出更大范围问题（并认领为自己的责任）**：
其 t1 报告 §7 给 verifier 的「改动前基线清单」行号捕获于 **05:36:42Z**，复核后**有 5 个文件在捕获后被改动**：
```
memory_read.py        (06:05:34, +7 行)
memory_taxonomy.py    (06:07:51)
snapshot_reader.py    (06:40:21)
publication.py        (05:47:22)
memory_entity_graph.py(05:41:43)
⇒ 该表行号对这些文件已失效
```
**已处置**：更正 352→359、357→364，订正 `fused_memory_search_result` 定义 398→405 及适配器类整体 +1；**在 §7 顶部加行号时效警告**（列 5 文件与 mtime）。

**captain 采纳的方法论结论（scout 提出）**：
> **引用应写「文件:函数/类名 + 行号(捕获时刻)」——裸行号在并发编辑下数十分钟即失效。**
**这与 engineer-a4 的「插入者须广播位移量」互补**：
- **插入者**：广播位移量（知道插了几行、插在哪）；
- **引用者**：写「符号名 + 行号(捕获时刻)」，使位移可被换算。

**scout 接受 engineer-a4 对「`wiki_gate` 恒等变换」的更强解释**：不是「恰好全 external」，而是**证据门输入面结构上不含图事实**（图事实走个人记忆通道、只在组装层汇合）⇒ **恒等是结构必然**。scout 自评「比我的推导强」。

**captain 评价**：**两人在同一问题上互相修正并各自认领责任**——scout 认领「漏做改后重核引用它的文档」，engineer-a4 认领「没广播位移量」。**这是本会话最有价值的协作形态。**


### t7 完整报告的补充细节（captain 逐条采纳）2026-09-20

**§3 新增两条**：
1. **残留风险（当前不可达）**：`memory_entity_extraction` 用**模型产出的任意 `relation_type`**（含 `prefers`、subject 不限 self）建关系；
   但 `persist_extraction_candidates` / `activate_extraction_candidates` **在本 checkout 中只有测试调用、无生产调用方** ⇒ **当前不可达**。
   **⇒ 这正是 verifier 前面指出的「一旦出现新的 `prefers` 写入点，不变式即失效」的具体候选。登记为**潜在失效点**。**
2. **非对象 metadata 静默不可召回的排查进展**：已**排除** `_relation_row_recallable` / `activation_item_from_graph_fact` / `MemoryGraphStore._map`；涉及文件不在 t2 清单内 ⇒ **很可能既有，但未证明**（已并入 t15 调查）。

**§4 的交叉验证（比单一 spy 更强）**：
spy 插件替换真实 `order_evidence_by_statement_authority`，跑 6 个 wiki/证据门套件：`calls=19 / citations=140 / items_moved=0 / with_source_type=0 / with_content_category=0`；
**代码侧交叉验证**：`wiki_retrieval.py:323/388` 与 `retrieval.py:567` 构造 `MemorySearchResult` **都不设这两个字段** ⇒ 与 spy 结果一致。

**§5 契约幂等（三产物逐一验证）**：`openapi_export` 04FD223A→04FD223A；`check:api-contracts` verified；proxy-routes 861615A5→861615A5；types.gen.ts 67ACAAFB→67ACAAFB；`typecheck` exit=0。**运行前备份、运行后哈希逐一相同 ⇒ 未产生变更。**

**§6 回归（分层，诚实）**：
```
5 个指定套件（快照）          102 passed / 0 failed
自建 21 套件 A4 相关集（快照）  242 passed / 0 failed
6 个 wiki 套件（快照）          73 passed / 0 failed
```
**「21 套件 306 passed」无法精确复现**：清单未枚举（docs 与 .codex 里只有结论那一行），自选 21 套件得 242。
**verifier 的措辞很准确**：「这是**套件集合不同**，不是结果冲突；我**不能说复现、也不能说反驳**。」

**⚠️ 最重要的一条诚实边界：全量套件「0 失败」未被验证**
```
全量套件（149 文件）未完成：活动树跑到 ~80 分钟仍在推进，verifier 终止了；
且该运行本来就不可采信（运行期间 engineer-rrf/scout 仍在改文件）。
未在快照上重跑（需 80+ 分钟，超预算）。
⇒ 「全量 0 失败」verifier 没有验证。
```
**captain 采纳该边界，并据此修正自己的计划**：**全量套件必须在「所有代码改动停止后的冻结树」上跑**，否则又是本会话已犯过两次的「运行期改文件」错误。
**当前仍在改文件的**：engineer-rrf（t12：`wiki_retrieval.py`/`snapshot_reader.py`）、scout（t11：`app/evals/`+题集）。**故全量套件必须等 t11/t12/t13 全部收口。**


### scout 报告 t12 引入 two_hop 回归（实测 45 → 43）—— captain 立即处置 2026-09-20

**scout 的实测（同一套冻结 48 题，两次干净全量运行）**：
```
题                 t6 06:24–06:32Z          t11 07:31–07:40Z
q_two_hop_001      ✅ recall=1.0 reads=8    ❌ recall=0.5  reads=1  cited=1 页
q_two_hop_003      ✅ recall=1.0 reads=3    ❌ recall=0.667 reads=2
合计               45 / 48                  43 / 48
```
**归因**：`wiki_retrieval.py` mtime **07:23:34Z**（在 scout t6 之后、t11 之前）；scout 全程**只读**（进程内 monkeypatch，零仓库写入）⇒ 排除它。`git diff` 显示 engineer-rrf 新增「避免弱相关页挤占 max_pages 首轮窗口」的候选预过滤，**症状吻合（reads 8 → 1）**。
**机制**：`two_hop` 需要「A →链接→ B」两跳；**相关性下限把「弱相关但必需的第二跳页」滤掉了**。

**captain 裁定：t12 当前状态不得合入**（其验收准则为「原 45 题通过率不得下降」，现为 43/48），**按「下降即回退」处理**。
**但下限本身该做**（尤其「被截断者不丢弃、进入价值预检池」的设计正确）。**问题在作用面**，给出三个修法方向：
1. 首轮准入 vs 置换分离（下限只作用于置换）；
2. **对链接目标豁免**（`page.links`/`page.backlinks` 的图扩展页不受词法下限裁决）——**captain 倾向此项**，因为它与 engineer-rrf 已确立的「`score ≤ 0` 表示**没有词法证据**，不是「相关性很低」」**是同一条原则**；
3. 自行判断的其它方案，但**必须证明 two_hop 恢复**。
**更新后的验收**：原 45 题通过率**必须恢复 ≥45**；特别核对 `q_two_hop_001`/`q_two_hop_003`；**reads 不应掉到 1**；保留已验证有效的部分（`or 1.0` 修复、ratio 依据、被截断者不丢弃）；跑 5 套 + 2 套测试。

**captain 评价**：**这条回归是 scout 独立跑出来的，不是实现者自述的**——正是「验收必须以节点级 pass 为准」的价值。

### scout t11 的两项结论与 captain 裁定 2026-09-20

**缺陷 2（`conclusion_coverage` 否定假阳性）**：
- 反例确定性成立（`conclusion_coverage(["支持加急"], 错误页含"不支持加急发货") = 1.0`，与正确页无法区分）；
- 拟议修复（感知否定、保持确定性）**已在进程内验证**：48 题 passed **43 → 43（零翻转）**，仅 `q_lexical_gap_002` 的 coverage **1.0 → 0.0**（更诚实）；
- **captain 裁定：解冻 `app/evals/phase_d_questions.py` 与题集，应用该修复。**

**缺陷 1（`reject`/`stale` 反向判别器）—— scout 建议拒绝 captain 的修复方向，captain 采纳**：
**实测该修复是 no-op**：12 题（含对照）的 `gate.freshness` **全部为 `unknown`**，唯一取值集合 `['unknown']` ⇒ `{stale, unknown}` **恒被满足** ⇒ 6 道受影响题 **cur == new，零变化**（程序化验证）。
**更糟**：接受 `unknown` 会**放松**判据（它是默认/降级值）⇒ **看起来像修了，其实什么都没变**——正是本项目反复栽的那类「假修复」。**captain 撤回该修复方向。**

**scout 的结构诊断（比原命题更准确，captain 采纳）**：
- **`revoked_source`（3 题）是「构造性空洞」**：`phase_d_eval._authorize`（`:101-117`）要求 `revoked_at is None` 才可读 ⇒ 被撤销页**永远进不了读者** ⇒ `not (expected & actual)` **由读路径授权保证**，与「检测到撤销」无关 ⇒ **判据层面无法修**；
- **`raw_updated`（3 题）是「条件性空洞」**：页可读但 bm25 不召回；且 `derive_source_freshness`（`wiki_gate.py:88-99`）**没有「原始内容变化 → stale」的路径**（`:90` 注释明示「观测变化只标记待检查，不自动判 stale」）⇒ **即便被召回，系统也无法在查询期标 stale**。
⇒ **两处都不是判据 bug，而是「场景与能力不匹配」**，修法在**场景/语料层**（例如让被撤销页「可读但须被判 stale」，从而真正考到检测能力）——**需另建任务**。


### captain 独立复核：two_hop 回归**确认成立**（非测量假象）2026-09-20

**captain 自己跑的探针**（`wiki_retrieval.py` 自 15:23:34 起 30 分钟未变，为干净窗口）：
```
q_two_hop_001  passed=False  recall=0.500  reads=1  cited=['Wiki/Sources/Supplier-Beta.md']
q_two_hop_002  passed=True   recall=1.000  reads=3  cited=[Product-P, Concepts/Product-P, Supplier-Alpha]
q_two_hop_003  passed=False  recall=0.667  reads=2  cited=[Concepts/Product-P, Supplier-Alpha]
```
**与 scout 的独立测量逐项一致**（`q_two_hop_001` reads=8→**1**、recall=1.0→**0.5**；`q_two_hop_003` recall=1.0→**0.667**）。
⇒ **回归是真实的，不是测量假象。** `reads=1` 是最直接的证据（首轮几乎没读）。
**captain 已据此向 engineer-rrf 再次确认：t12 当前状态不得合入。**

**captain 的复核方法与 scout 不同**（scout 跑全量 48 题两次运行；captain 跑定向探针）——**两条独立路径得到同一结果**，可信度高于单一来源。


### captain 独立复核：完整 48 题状态 = **43/48**（回归精确定位为 2 题）2026-09-20

**captain 自己跑的完整 48 题**：
```
PASSED 43 / 48
  FAIL q_two_hop_001  two_hop      recall=0.5   reads=1   ← t12 回归
  FAIL q_two_hop_003  two_hop      recall=0.667 reads=2   ← t12 回归
  FAIL q_lexical_gap_001 lexical_gap recall=0.0 reads=0   ← 已知（语义腿验收目标）
  FAIL q_lexical_gap_002 lexical_gap recall=0.0 reads=2   ← 已知
  FAIL q_lexical_gap_003 lexical_gap recall=0.0 reads=8   ← 已知
```
⇒ **与 scout 的数字逐项一致（43/48）**，且**回归精确定位为 2 题，全部是 `two_hop`**。
⇒ 3 道 `lexical_gap` 是**已知的语义腿验收目标**（0/3，下限/截断动不了它们——只能移除候选不能新增）。

### t15 完成：两个新问题的根因、归属与影响面（engineer-a4，captain 采纳）2026-09-20

**问题 1：抽取器覆盖面缺口 —— 系统性缺口，但归属为既有（`4577d24`）**
**量化**：14 条自然措辞 × 2 形式 —— 带「帮我记住：」前缀 **preference 3/14 = 21%**；裸句 **0/14（全部 NO_CANDIDATE）**。
命中的 3 条**全部含「喜欢」**；不含 喜欢/偏好/偏爱 的一律落 `fact`（含 verifier 的「我更习惯在晚上写代码」）。

**根因（两条叠加 + 一条放大器）**：
```
A. long_term_memory.py:346-350 _extract_preference 的动词表是封闭的：
   只有 我(更|最|比较)?(偏好|偏爱|喜欢)X
   习惯/通常/一般/倾向/爱/讨厌/希望/请/别 全不在表内
B. memory_consolidation.py:771 _extract_assignment 与 :786 _extract_preference_value
   正则全是英文(my X is Y / i prefer…) ⇒ 中文恒不匹配
C. 三者都不中 ⇒ 落兜底分支 :368-388，它硬编码 memory_kind=MemoryKind.FACT (:377)
放大器: _stable_preference_specs:392 在显式「记住」命中时直接 return ()
   ⇒ 稳定偏好路径被压制，没有第二次机会
```
**归属**：`git log -S` 显示两条根因代码**均出自 `4577d24`**（既有提交，HEAD 祖先）⇒ **非本轮引入**。

**⚠ 一条会改变严重性判断的关键事实**：还有**第二条写入路径** —— LLM 实体抽取（`entity_relation.py:189` `source_type="user_message"`）。
若模型把句子抽成 `prefers` 关系，**t8 的读侧重建（prefers→preference）+ USER_STATEMENT ⇒ 权威判为 user** ✅。
**但问题 1 命中的句子走兜底 `claim` 分支，t8 重建不覆盖 claim ⇒ 权威仍 `mixed`。**
**⚠ 其测量未调用任何模型** ⇒ 21% 只是「consolidation 单路径」的数字，**生产叠加 LLM 抽取后可能更高——未测**。

**captain 裁定：选项 4（不动，只登记）。** 理由：其余选项各有实质代价——
1. 扩动词表 → **假阳性**（「我通常在周一开会」是日程事实）；
2. 分派到既有 identity/health/relationship → 价值最高，**但需新分类器，误判会凭空授予权威**，应先有标注数据；
3. 兜底改弃权 → **净损失召回**（今天至少以 fact 存下可检索）；
5. 去掉 `:392` 短路 → 同句双候选，**正是 t10 已确认的「权威盲副本」同类问题**。
**且该问题为既有（非本轮范围），登记为后续项。**

**问题 2：非对象 metadata 静默不可召回 —— 既有 fail-closed 设计，严重性低**
**复现**：`[1,2]`/`null`/`"hello"`/`42`/`not json` **全部命中 0，且无任何异常**。
**根因**：`memory_entity_graph.py:2480-2503 _lifecycle_metadata_allowed()`——非法 JSON → `return False`；非 dict → `return False`。**刻意的 fail-closed**，是召回闸最后一道。

**归属证据（三条独立，verifier 的「未证明」已闭合）**：
```
1. git log -S '_lifecycle_metadata_allowed' → 5a70c70 记忆页面优化(2026-08-15)；merge-base --is-ancestor → YES
2. git diff -U0 HEAD 对该文件只有 4 个 hunk(1229/1242/1257/1310，全在 create_relation 区域)，无一处接近 2480
3. memory_graph.py(_normalize_metadata_json 所在) mtime = 2026-09-15，远早于本轮
⇒ 既有行为，非本轮引入
```
**影响面：生产路径不可能产出非对象 metadata。** 逐写入点核实；**最像风险的一处 `wiki/memory_closure.py:1296-1318` 主动兜住了**（`:1299-1300` 非 dict 时强制置 `{}`）。
⇒ 只能来自改库/篡改 ⇒ **严重性低**；触发后是刻意 fail-closed，**不是数据丢失**。

**captain 裁定：选项 1（不动）+ 选项 4（加只读体检告警、不改行为）。**
**明确否决选项 2**（非对象降级为空 metadata 继续）：那会把「metadata 读不出来」从**拒绝**变成**放行**，**削弱一条安全闸**（metadata 里的 `risk_tier`/`sensitive`/`conflicts` 是安全字段）。

**engineer-a4 的诚实边界（captain 接受）**：21% 未含 LLM 抽取叠加；未端到端验证「user→mixed」在真实回答里是否可观察；修法风险仅静态论证无假阳性率；未核查 `memory_evidence`/`memory_candidates` 是否有同类闸；未核迁移脚本是否可能写非对象 metadata。


### t16 完成：两处判据缺陷已修复，**评测首次变得诚实**（净效果 −3）2026-09-20

**已写入仓库（2 文件）**：
| 文件 | 改动 |
| --- | --- |
| `tests/fixtures/phase_d_questions.json` | `raw_updated` ×3：action **`stale` → `degrade`** |
| `app/evals/phase_d_questions.py` | `conclusion_coverage` 改为**感知紧邻否定**的确定性匹配（新增 `_point_present` + `_NEGATION_PREFIXES`） |

**结果**：
```
净效果                −3（恰为 3 道 raw_updated，此前虚高）
驱动测试              19 passed (283.50s)
题集校验              VALIDATION OK（48 quality + 8 safety）；剩余 stale action = 0
确认运行              42 / 48
失败清单              lexical_gap ×3（t6 既有）+ raw_updated ×3（本次修复暴露）
```
**scout 如实报告**：「**3 道 `raw_updated` 题此前通过是虚高的，修复后不再通过。未为凑绿调参。**」

**判别方向被反转（这是修复的实质）**：
| | 旧判据 `stale` | 新判据 `degrade` |
| --- | --- | --- |
| 判据 | `not (expected & actual)` | `recall > 0.0` |
| bm25 找不到时 | **通过**（空洞） | **不通过** |
| 更好检索器找到时 | **不通过**（反向！） | **通过** |
⇒ **从「奖励检索失败」变为「奖励检索成功」**，正是设计语义。

**并发被干净分离（算术核对）**：
确认运行得 **42** 而非预测的 40 —— 因期间 **engineer-rrf 修好了 two_hop 回归**（`wiki_retrieval.py` mtime **07:23:34Z → 08:05:34Z**；`q_two_hop_001` reads **1→8**、recall 0.5→**1.0**）。
```
43 − 3（scout 修复）+ 2（two_hop 恢复）= 42  ✅ 精确吻合
⇒ scout 的修复净效果 = −3，与检索行为无关（3 题 recall 两次运行都是 0.0）
```
**captain 独立验证了 two_hop 恢复**（自己的探针）：`q_two_hop_001/002/003` **全部 passed=True、recall=1.000**，reads 8/8/3（与回归前一致）。

**scout 登记了自己的脚本 bug**：多变体脚本把 `degrade` 应用到**全部**题而非仅 `raw_updated`，多出 **5 个虚假翻转**；**已发现并离线重算纠正** ⇒ 正确翻转只有 3 题，**上报的是纠正后数字**。

**未做**：`reject`（`revoked_source` ×3）**未改** —— t11 已证明它是**构造性空洞**（`_authorize` 要求 `revoked_at is None` ⇒ 该页永远进不了读者），**判据层修不了**，需场景/语料层重设计（已建 t17）。

### 方法学发现：行号换算存在「**基期错配**」陷阱（scout 提出，captain 采纳为规范）2026-09-20

**问题**：`git diff -U0` 给出的偏移量是「**工作树 vs HEAD**」（HEAD 相对）；而更早写的文档里的行号是「**工作树 @当时时刻**」（捕获时相对）。**两者只有在「两次之间的改动集合相同」时才相等。**

**本轮实测反例（重要：它纠正了 engineer-a4 的换算表）**：
engineer-a4 好心给出 `memory_taxonomy.py` 标 `L≥25 → +79`，但**捕获时相对位移实测只有 +5**：
```
_KIND_TO_CONTENT_CATEGORY   §7:25 -> 现在:30   (+5)
content_category_for_kind   §7:39 -> 现在:41   (+2)
原因：那 +79 里的 +77 是 A4-1 阶段的工作，在 05:36Z 捕获时早已存在，不是本轮新增
⇒ 按 +79 订正会多推 74 行，比不订正更错
```
**scout 按新规范实测的锚点**：`memory_entity_graph.py` 的 `create_claim:1143` / `create_relation:1217` **完全未变（+0）**；`memory_read.py` 是 +7；`memory_taxonomy.py` 是 **+5**。

**captain 采纳的两条规范**：
1. **广播偏移量时必须声明基期**（「相对 HEAD」还是「相对某时刻的工作树」）——**只给数字，接收方会算错**；
2. **不确定时一律改用「符号名 grep」核实**，不做偏移量算术。
**与 engineer-a4 的「插入式改动者有广播义务」配套**：**广播治因，声明基期防止误用。**


### t12 挂起解除（captain 独立验证 + 采纳 scout 的归因分解）2026-09-20

**scout 做了 captain 该做的归因分解**：
> captain 说「现在是 43，验收准则是原 45 题通过率不得下降」——**但那个 43（以及现在的 42）里含着我判据修复的 −3，不是 t12 的账**。

**当前树（08:06–08:13Z，含 two_hop 修复）42/48 的 6 个失败完整分解**：
| 失败题 | 归属 |
| --- | --- |
| `q_raw_updated_001/002/003` | **scout 的判据修复**（action `stale`→`degrade`，属 t16） |
| `q_lexical_gap_001/002/003` | **t6 新增题**（检索纯词法），不在原 45 内 |
| **t12 造成的原 45 题回归** | **0 题** |
```
原 45 题、还原为修复前判据 = 45 / 45   =>  t12 验收「原 45 题通过率不得下降」满足 ✅
```

**captain 独立复核了关键一环**：`q_raw_updated_*` 三题的 `recall` **全为 0.000**（golden 页未被引用）⇒ **失败纯粹由判据变更驱动，不是检索回归**（且 reads 为 1/8/8，不是 `reads=1` 那种崩塌信号）。
**captain 也独立验证了 two_hop 恢复**：三题全 `passed=True`、`recall=1.000`、reads 8/8/3（与回归前一致）。

**⇒ t12 挂起解除。**

**captain 的方法教训（登记）**：我当时把 **43 这个数字当成「全是 t12 的账」而没有分解**——其中 −3 是 scout 的判据修复。
**挂起本身在实质上是对的**（07:48Z 那次运行里 two_hop_001/003 确实在失败，scout 与我自己的探针都确认了），**问题在于报数字前未做归因分解**。
**新规则：报通过率变化前，先分解「哪几题、各归谁」。**


### t14 完成：第二批独立验证 —— 三项重要发现（captain 采纳）2026-09-20

**报告**：`E:\a 工作\wiki-audit\team-verifier-t4b.md`（17.3 KB）

**B 项（最重要，权限保证）—— 通过，不构成合入阻塞。**
verifier **加强了验证强度**：从「结果集里没有它」提到「**未授权正文根本没进入嵌入管道**」——拒绝全部页时，嵌入器 `embed_query` 调用 **0 次**、收到文档 **0 段**。
并**补了 captain 未要求的跨页依赖场景**：拒绝 Alpha 后，依赖它的 `Product-P` **尽管自身被授权也被移除**。
**三层闸门全部实测生效**：嵌入前 `authorize` / `_candidate_for_path` 的依赖父页复核 / 出口逐条 `_load`。
**局限**：语料 `notes` 表为空，**生产 `authorize` 实现本身无法直接演练**（诚实登记）。

**A 项：captain 担心的 `replaced 3→34` 可排除** —— 默认路径恒为 **3**（fusion 臂才是 34），45 道共有题逐字段 0 差异。

**⚠️ 但「默认路径逐行不变」需改口径（verifier 发现，实现者的指标集测不出来）**：
verifier 做了**真 A/B**（HEAD reader vs 冻结 reader，不注入嵌入器，42 组），**先做控制实验证伪自己**（冻结树连跑两次只差 `content_hash`，故排除该键）。结果：
```
顺序   0 组不同
内容   0 组不同
**score 从 0/36 → 36/36**   ← HEAD 的 WikiPageCandidate 只有 8 字段、无 score
```
该字段经 `asdict` 进入 **`search_wiki_pages` 工具载荷**（`adapters.py:206` → `tools.py:340`）⇒ **默认路径的候选载荷形状变了、模型可见**。
**加法式、不削弱保证**，但正确表述应为：**「排序与题面指标逐条不变；候选载荷新增 `score`」**。
**实现者的消融指标集里没有「候选字段集合」这一项，所以测不出来。**

**⚠️ 另一条：融合臂数字产自被取代的修订**
```
三份消融产物（14:13 / 14:21 / 14:31）**全部早于**冻结版 snapshot_reader.py（14:40:21）
verifier 逐行 diff t3 的 13:52 副本 vs 冻结版：37 行差异，**全在语义腿**且**只在注入嵌入器时可达**
⇒ 默认路径结论不受影响，但**融合臂数字（47/48、replaced 34、reads 418）需以 t12 收口后的重测为准**
```

**E 项：双重入场成立，verifier 的证伪尝试失败 —— 且它定位了结构性原因**
> `_graph_fusion_candidates` 遍历 `store.traverse`，而 `traverse` 的 SQL 带 `WHERE statement_kind='relation'` ⇒ **claim 被 SQL 结构性排除**。
**对选项 A 的后果**：同一条偏好事实在**同一份融合结果里出现两次、权威口径互相矛盾**（user vs external），**排序解决不了**。
⇒ **登记为选项 A 的前置问题。**

**D 通过**（19 用例 + 集成：记录值不被覆盖、`avoids` 等不重建）。
**C 通过**，且**补了实现者未覆盖的降级形态**（`embed_documents` 返回向量数少于文本数 → 逐字段等价降级）。
**回归：冻结快照 19 套件 199 passed / 0 failed。**

**verifier 的不确定项（captain 接受）**：融合臂未在冻结版重测；未亲自跑 48 题消融（做了独立代码级 A/B）；生产 `authorize` 未直接演练；`score` 下游影响未穷举；**快照很可能 ≠ 最终版本（t12 15:43–15:44 仍在产出新消融文件）**。

### 全量套件的准备要点（scout 提供，captain 采纳）2026-09-20

**cwd / 导入约定分裂**（会踩到，看起来像失败但不是）：
| 导入约定 | 文件数 | cwd=仓库根 | cwd=apps/backend |
| --- | --- | --- | --- |
| `from apps.backend.tests...` | **39** | ✅ | ❌ collection error |
| `from tests...`（含 phase_d） | **72** | ✅ | ✅ |
⇒ **统一用 `cwd=仓库根` + path 形式**，两种约定都能收集。

**量级估算**：`test_phase_d_eval_driver.py` 单文件 **283s（轻载）～683s（重载）**——**同一文件相差 2.4 倍** ⇒ **并发负载会显著拉长**；本会话早前一次全量尝试 **约 75 分钟仅到 38%**。
⇒ **全量运行期间必须冻结所有代码改动**（正是 captain 已认领的纪律）。

**captain 已取消 t4**（原「独立验证 t2+t3」，已被 t7 与 t14 取代；留作 pending 会误导任务图）。取消前按协议先 `reassign` 到 captain。


### 团队规则补充（verifier 提出，captain 采纳）2026-09-20

**verifier 对「插入者须广播位移量」的补充**：
> 插入式改动者有义务广播位移量；**验证者有义务声明其引用的行号取自哪个窗口**。

**其理由（captain 认同）**：真实风险不在插入方漏报，而在**验证报告把不同窗口的行号混在一份文档里**，读者无法分辨。
**其做法（正确执行方式）**：报告固定标注「行号取自 snapshot-t14」，并在快照哈希表里给出对应 mtime，**使每个行号都能反查到具体修订**。

**verifier 的机器校验（值得记录）**：它用 `verify_linenos.py` 把报告里**每一个行号**对快照做了一次机器校验：
```
OK snapshot_reader.py:76/157/196/203/284/391/208
OK retrieval.py:1044/1063
OK memory_entity_graph.py:1709
OK adapters.py:206 / factory.py:552 / tools.py:340
⇒ 16/16 全部命中，零漂移
```
**它并主动登记了唯一的「跨窗口继承」引用**：`memory_entity_graph.py:1706-1715` 取自 t7 期间的活动树；复核快照后仍精确对应（因该文件 mtime 停在 13:41:43 未被改）。
**captain 评价：主动暴露自己报告里的薄弱引用，比等别人发现好得多。**


### t17 完成：**三处实测更正**（既有诊断在 raw_updated 上错了）+ 发现第三处判据缺陷 2026-09-20

**提案**：`docs/phase-d-scenario-redesign-proposal.md`（272 行）。行号捕获时刻 2026-09-21T08:06:48Z。

**⚠️ 三处实测更正（既有诊断：raw_updated「页可读但 bm25 不召回 ⇒ 平凡通过」——实测两点都不对）**：

**更正 1 — 页不可读**：`_load` 抛 `WikiGenerationError: wiki_publication_root_changed`（同一页在 `published` 变体 `_load OK`）。
但 **FTS 里有该页 3 个块** ⇒ **bm25 能召回它**，不是「找不到」。

**更正 2 — 这 3 题当前是 FAIL，不是通过**：
```
q_raw_updated_001  cited=[Product-P]                          recall=0.0  PASSED=False
q_raw_updated_002  cited=[Product-P,Region-South,Filler-1..6] recall=0.0  PASSED=False
q_raw_updated_003  cited=[Product-P,Region-South,Filler-1..6] recall=0.0  PASSED=False
判据 phase_d_eval.py:53-54：degrade ⇒ return recall > 0.0 ⇒ golden 页取不到即必然失败
```

**更正 3 — 语义腿也救不了**：`_candidate_for_path` 同样调 `self._load` ⇒ 同一条异常再抛一次。
⇒ 「更好的检索器反而让这 3 题失败」**不成立**；换任何检索器都改变不了结果。
⇒ **raw_updated 不是「空洞通过」，而是「永远无法通过」** —— 它把一条**真实产品缺口**伪装成了 3 个红用例。

（`revoked_source ×3` 与既有诊断**一致**：PASSED=True、judge `not(set())=True` 恒真、`conclusion_coverage=0.0`。）

**机制（带行号）**：
- **revoked**：`phase_d_corpus.py:_set_binding:188-193` 写 `revoked_at`；`phase_d_eval.py:_authorize:103-119` 要求 `revoked_at IS NULL` ⇒ 撤销页永远进不了读者；
- **raw_updated**：`_touch_raw_content:173-185` **只改 `wiki_sources.raw_content`、不同步 `source_hash`** → `snapshot_reader.py:_load:373-405` 在 `:402` 调 `validate_snapshot_dependency` → `publication.py:78-84` → `_dependency_stamp` → **`:50` 把 raw_content 哈希化与 source_hash 比对 → `:60-61` 不等即抛**。

**⚠️ 另发现一处独立于语料的判据缺陷（captain 引入）**：
`phase_d_eval.py:38-55`：`degrade/fallback ⇒ return recall > 0.0` —— **`coverage` 被忽略**。
而 `:192` 已算出 `conclusion_coverage`、`:210` 已传入，**对 `degrade` 却完全不使用**。
实测 `q_raw_updated_002/003` 的 `conclusion_coverage = 1.0`（结论已在证据里）但 `PASSED=False`。
⇒ **即便检索完全正确，判据也看不见** —— **第二重空洞**。

**根因分层**：**L1 判据层**（degrade 忽略 coverage）/ **L2 语料层**（不同步 source_hash）/ **L3 产品能力层**（原始内容变化被表达为**页拒绝**而非**新鲜度 stale**）。
**外加 harness 事实**：`phase_d_eval.py:88-92` 把 `derive_source_freshness` **整体打桩为恒返回 unknown** ⇒ **阶段 D 里任何新鲜度能力都不可观测**（实测 6 题 `gate.freshness` 全为 unknown）。

**它对我关键问题的回答**：**是，必须先补——但不是「从零造能力」，而是「换一种表达形式」。**
- 产品侧**已存在**检测：`publication.py:60-61` 的 raw_content 哈希比对**就是**该检测；
- **缺的是把它表达为新鲜度**：`derive_source_freshness:74-99` 只有 revoked(`:88-89`)/expired(`:92-93`)/unknown 三条出口，`:90` 注释明示不自动判 stale；
- **更深一层**：即便补上，`derive_source_freshness` 也**拿不到该信号**——信号在 `_load` 里被抛成异常、**页已被丢弃**。
⇒ **不是「加一个 if」，而是要在「页被拒绝」与「页被标 stale」之间做一次架构选择。**
⇒ 评测侧必须**同时**动三层（L1/L2/harness 打桩），**只动一层都不成立**。

**四方案与推荐**：
- **A** raw_updated 改成「页可读 + 必须判 stale」：需 L3 + 放开 freshness 打桩；**风险最大**（动 `_load` 拒绝语义＝真实安全保证）；
- **B** 改成「拒绝/降级必须被如实报告」：**不动产品代码**，只改 golden + L1；考「不一致时旧内容不得冒充当前事实」——**已实现**的保证；
- **C** 退役 3 题、缺口转产品待办：零风险但**消灭追踪位**；
- **D** revoked_source 改成**撤销前后双阶段对照**（考「撤销**生效**」而非「撤销**存在**」）。
**推荐：raw_updated 走 B、revoked_source 走 D、L1 单独修；L3 独立立项、不塞进题集重设计。**
**执行顺序：① 先修 L1 并全量重跑看多少题翻红 → ② B → ③ D → ④ L3 立项。①必须在②③之前**，否则无法归因。
**A 更差**：把评测题变成产品需求载体，且为一道题去改一条真实安全保证，**风险方向错了**。

**captain 直接解答其 6.2 的不确定**：它问「既有诊断 45/48 与本轮实测 42/48 不一致」。
**答案：不是不一致，是 t16 造成的** —— scout 的 t16 把 `raw_updated` 的 action 从 `stale` 改为 `degrade`，**改后这 3 题由「空洞通过」变为「如实失败」**（scout 已实测并报告净效果 −3）。`phase_d_questions.py` mtime 08:01:04Z 正是该改动。


### t12 完成：截断**已回退**（命中 captain 准则），`or 1.0` 修复**保留** 2026-09-20

**结论**：
- **动态截断：回退。** 预注册的 ratio=0.4 在**节点级**实测把通过率从 **45/48 打到 43/48**（two_hop_001/003 的第二跳页被截断）⇒ **命中 captain 准则「通过率下降 ⇒ 不得合入」**。截断相关代码**已全部回退**。
- **`or 1.0` 修复：保留。** 在两版题集上与改动前**逐题逐字段 0 差异**（含 reads/replaced），同时修掉真实缺陷。

**对比数据（节点级，题集指纹 `36581ff0ccddb9e3`，48 题，bm25 单路）**：
| 下限 ratio | 通过 | 读取页数 | 被截断候选数 | 触发截断题数 | 失败题 |
| --- | --- | --- | --- | --- | --- |
| 无（改动前） | 45/48 | 271 | 0 | 0 | lexical_gap ×3 |
| 0.05 | 45/48 | 271 | 0 | 0 | lexical_gap ×3 |
| 0.1 | 45/48 | 264 | 7 | 1 | lexical_gap ×3 |
| 0.2 | 45/48 | 213 | 58 | 13 | lexical_gap ×3 |
| **0.3** | **43/48 ↓** | 182 | 88 | 24 | **+two_hop_001/003** |
| **0.4（预注册）** | **43/48 ↓** | 171 | 99 | 27 | **+two_hop_001/003** |
`fusion` 臂在 0.4 下也从 47/48 掉到 **46/48**。逐题：`q_two_hop_001` reads 8→1、recall 1→0.5；`q_two_hop_003` reads 3→2、recall 1→0.667。
**回归（回退后最终状态）**：5 套点名 + 2 套新增 → **63 passed / 0 failed**。

**根因 + 方法学教训（engineer-rrf 同类错误第二次犯，如实登记）**：
> 我的离线代理只检查「**最佳**黄金页是否掉出窗口」；two_hop 题有**两个** golden 引用、判据要求 recall=1.0，**第二跳页**（Product-P 来源页，词法分低）被截断 —— 代理**完全看不见**。
> 已把代理改成「**任一** golden 掉出窗口」，并在当前题集上复核：ratio 0.3/0.4 恰好截掉 `q_two_hop_001/003` 的 `Product-P.md`，ratio 0.2 为 0/36 —— **与节点级实测完全一致，机制确认无疑**。
> **教训（与上一轮 hit@8 代理同类）：代理指标必须用节点级 pass 复核，且代理必须覆盖判据的全部条件（多引用题尤其）。**

**它主动报告的两条（会影响判断）**：
**(a) 题集在它跑数据期间又被改过**：截断数据取自指纹 `36581ff0ccddb9e3`；**16:00 后**变为 `ebdf7c1351b93585`（t11 的判据修正）。它在当前题集上复跑两臂：bm25 基线 **42/48**（`raw_updated` ×3 由通过转失败，**是判据修正的预期结果，不是它的改动**），且 **baseline vs scorefix 仍是逐题 0 差异** ⇒ 「行为中性」结论在两版题集上都成立。
**(b) `score` 修复的残留风险（请 verifier 单独确认）**：修好后 `score <= 0` 的候选（LIKE 兜底命中）价值恒为 0 ⇒ **永远无法凭价值挤入/置换**。Phase D 两版题集里 LIKE-only 候选从未进入首轮窗口，故实测 0 差异；但**生产里这会改变「LIKE 兜底候选靠价值挤入」的既有路径**。语义上**正确**（LIKE 命中不等于满相关），但属**行为变更**。

**RRF 融合部分（按事实写，不按自述写）**：**已实施、已验证、默认关闭、未接线生产。**
不是「因环境缺语义腿而未实施」—— 仓内**内置**本地 ONNX 嵌入模型（94MB，无远端 key 时默认用它，**无需模型端点**）。三臂实测 **47/48（融合）> 45/48（bm25 单路）= 45/48（纯语义单路）**。

**它的建议（captain 采纳）**：**截断不要现在合入** —— 0.2 那档虽然通过率不掉，但 **ratio 是看着同一 48 题选的**（0.3 就掉），**属测试集调参，不构成证据**。建议**先在扩题后的留出集上定 ratio，再合入**。

**captain 评价**：**它拒绝用一个「看起来能过」的参数（0.2）合入，理由是「那是看着测试集选的」—— 这正是本会话反复强调的纪律，而它主动执行了。**


### 收口阶段的资源串行化（captain 决定）2026-09-20

**问题**：t12 完成后，**t18（冻结树全量套件，70–90 分钟）与 t19（融合臂重测，25–30 分钟嵌入计算）会互相拖慢**。
**依据**：verifier 自己量过 —— 并发负载使 `test_phase_d_eval_driver.py` 耗时相差 **2.4 倍**（283s ↔ 683s）；本会话早前一次全量尝试 **75 分钟仅到 38%**。
**且 t19 的纯语义臂依赖本地 ONNX 嵌入器**，并发会**增加误判风险**（嵌入器降级会被误读为「融合无增益」）。
**⇒ captain 决定：串行化 —— 先 t18，完成后通知 verifier 开工 t19（含 t7 第 4 项复测，共用一次冻结）。**

**verifier 对 t19 的设计（captain 认可，三点）**：
1. **「t3 的核心主张是内部比较，不需要历史数字」** —— 三臂在**同一次运行、同一题集**下比较即可判定「是否仍严格优于两路单路」；
2. **「不可直接比较的根本原因是两个变量同时改变（题集语义 + 修订）」** —— 比只说「题集变了」准确；
3. **「每组数字绑定 `fixture_sha256` + 快照哈希」** —— 与「行号取自哪个窗口」**同一条纪律**。

**verifier 提醒的陷阱（captain 追加要求）**：
> **开工前先确认嵌入器就绪** —— 否则纯语义臂会**静默降级成 bm25**，**看起来会像「融合无增益」**。
**captain 追加**：报告中**显式给出嵌入器就绪状态的证据**（不只是「我认为就绪」），并记录每臂的 `last_search_mode`。
**这正是本会话反复出现的「静默失真」模式**（shadow 恒 unknown、gate 恒等变换、freshness 被打桩）。

**verifier 量化题集漂移并主动标注 t14 A1 时效限制**：
```
t14 快照      36581FF0CCDDB9E3   13:56:07
活动树（现在） EBDF7C1351B93585   16:00:24
phase_d_questions.py 也变了：D6DC1966F86D56E5，16:01:04
关键：36581FF0CCDDB9E3 正是三臂消融产物里记录的 fixture_sha256 ⇒ 旧数字确产自旧题集
```
**它主动在报告 A1 段加后补说明**（「A1 里题集指纹与快照一致」**只在冻结时刻成立**，**不可拿去对照当前活动树**）。
**captain 评价：主动标注自己结论的时效边界，这比等别人发现好得多。**


### 收口运行的冻结核验（captain 实测，t18 可信度的关键前提）2026-09-20

**captain 在 16:41:42 实测关键文件 mtime**：
```
16:05:34  app/agents/nodes/wiki_retrieval.py      ← t12 最终状态
14:40:21  app/services/wiki/snapshot_reader.py
16:07:39  tests/phase_d_eval.py                  ← scout t16 的判据修复
16:01:04  app/evals/phase_d_questions.py         ← scout t16
16:00:24  tests/fixtures/phase_d_questions.json  ← scout t16
13:47:22  app/services/wiki/publication.py
最新一项距今 34 分钟 ⇒ **t18/t19 运行期间无代码改动** ✅
```
**⇒ t18 的「运行期间无文件被改动」这一可信度前提成立**（这是它区别于本会话早前那次不可采信的全量运行的关键）。
仓库当前 **54 个变更文件**。

**⚠️ 并发登记（captain 决定接受，但需记录）**：
captain 曾要求 verifier **等 t18 完成再开工 t19**（避免资源竞争），但 **t19 仍被 claim 并 in_progress** —— 消息与认领**交叉**了。
**captain 评估后决定接受并发**，理由：
- t18 的可信度判据是「**运行期间无文件被改动**」，而**并发只影响耗时、不影响该判据**（已实测成立）；
- t19 是**只读 + 冻结快照**，其产物落在仓库外（`E:\rrf_scratch\` / `wiki-audit\`）；
- 强行中断其中一个的代价大于收益（且会丢失已完成的测量工作）。
**代价**：两者都会**显著变慢**（verifier 自己量过并发使单文件耗时相差 2.4 倍；t18 全量预计 70–90 分钟 → 可能翻倍）。
**解读要求（写给自己）**：t18 报告的**耗时数字不可与轻载基线比较**；**只有 passed/failed/skipped 与「无文件改动」是有效结论**。


### engineer-a4 撤回其换算表的适用性 —— 并给出一条值得记的判断教训 2026-09-20

**它的撤回**：
> 我给的表是「**工作树 vs HEAD**」的偏移（`git diff -U0` 的语义），但**表头没声明基期**。
> scout 的 §7 行号是「**工作树 @05:36Z**」捕获的 —— 两者只有在两次之间改动集合相同时才相等。
**正确适用范围（它给出，captain 采纳）**：
- ✅ 对 **HEAD 相对**的引用仍有效（如从 `git show HEAD:path` 读到的行号）；
- ❌ 对 **捕获时相对**（working tree @T）的引用**无效**。
**captain 已据此在台账该表上方加适用范围标注**（未整表废弃，因其对 HEAD 相对引用仍有效）。

**它的错误分两层，且它自己指出第二层更该认**：
> 技术上是**表头没声明基期**；判断上是我**已经注意到** +79 含 A4-1 的改动（表下写了注释），**却仍把该数字当可用值发出** ——
> **「标注了风险」不等于「交付了安全的东西」。**
**captain 评价**：**这条洞察很重要，而且适用于我自己**。本会话我多次「在文档里写了局限」然后仍然照原方案推进 —— **写下限绝不等于消除了风险**。

**新增纪律（engineer-a4 与 scout 已达成一致，captain 采纳入台账）**：
① **引用一律 `文件:符号名 + 行号(捕获时刻)`**；**订正一律 grep 实测，不用偏移量算术**；
② **广播位移量必须声明基期**（相对 HEAD 还是相对某时刻工作树）。
**与「插入式改动者有广播义务」「验证者须声明引用取自哪个窗口」合起来是完整的三方规则**：
```
插入者：有义务广播位移量（治因）
广播者：必须声明基期（防误用）
引用者：写「符号名 + 行号(捕获时刻)」（可反查）
验证者：声明其引用取自哪个窗口（可追溯）
订正者：一律 grep 实测，不做偏移量算术（不赌）
```

**scout 的符号名实测锚点表（captain 采纳为订正依据）**：
```
memory_read.py       MemorySourceAdapter 64→65 / GraphMemorySourceAdapter 176→177
                     UnifiedMemorySearchService 282→289 / 二级 RRF 352→359
                     fused_memory_search_result 398→405
memory_taxonomy.py   _KIND_TO_CONTENT_CATEGORY 25→30 (+5) / content_category_for_kind 39→41
memory_entity_graph.py  create_claim 1143→1143 (0) / create_relation 1217→1217 (0)
                        _create_relation_impl 1243→1245 (+2)
⇒ engineer-a4 表中 memory_entity_graph.py 的位移带（L≥1307→+9）起点在 scout 引用的两处之后
  ⇒ 那两处未受影响（与实测 +0 一致）
```


### t18 运行中（captain 观测）2026-09-20

**冻结节记录（scout 产出，格式正确）**：
```
TAG=before
TS_UTC=2026-09-21T08:39:46.8193878Z
HEAD=3c4f46d069b8f0c4b6371157b5e4bdba8e9fbcf1
DIRTY_FILE_COUNT=54
```
**运行进度（captain 读 `t18_suite_output.txt`）**：
```
 8% 全绿
12% 出现 1 个 F
16% 全绿
```
**⚠️ 12% 处有 1 个失败** —— 位置与本会话早前全量运行观察到的失败区间一致（`test_audit_logs` 的顺序依赖已知存在）。
**captain 处置**：等 t18 收口后，**要求 scout 对每个失败做单文件隔离复现判定**（本会话已出现过两类：真实回归 vs 顺序依赖）。**在拿到逐条归因前，不把该 F 判为任何结论。**

**并发登记**：t18 与 t19 并发（8 个 python 进程）。**t18 的耗时数字不可与轻载基线比较**；只有 passed/failed/skipped 与「无文件改动」是有效结论。


### engineer-a4 在**复核 captain 的答案**时发现并更正了自己的判据错误 2026-09-20

**它先验证了我的 6.2 解答（不是采信）**：写了动作矩阵探针，对 6 题把 `golden.action` 逐一替换后重跑判据：
```
6 题全部: cited_golden=False  recall=0.0
          stale=True  reject=True  degrade=False  answer=False
⇒ 判定完全由 golden.action 决定：stale（旧）恒真 ⇒ 虚报 pass；degrade（t16 改后）⇒ 如实失败
⇒ captain 的解释与实测一致，45/48（改前）vs 42/48（改后）无矛盾。6.2 关闭。
```

**⚠️ 但这次复核推翻了它自己 §4-E 初稿的检测器判据**：
> 初稿说：按 golden 页**缺席的原因**分类（`gate_denied`/`load_rejected`/`never_candidate`），前两种算「未考到」。
> **这个判据是错的** —— 矩阵显示 6 题**在可观测层面完全不可区分**（golden 页都没出现、recall 都是 0），**唯一区别是 `golden.action` 这个字符串**。
> 按缺席原因分类会把 `raw_updated`（`load_rejected`）**误判成「未考到」**，**而它其实是如实失败——那正是 L3 的信号。初稿判据会抹掉真信号。**

**更正后的判据（按判据的判别力，而非缺席原因）**：
> 一题算 `exercised` **当且仅当「存在一种可达的系统行为能让它的判定结果改变」**。判定恒为同一值 ⇒ 该题没观察任何东西。

| 题 | 判据 | 能否被行为改变 | 结论 |
| --- | --- | --- | --- |
| `revoked_source` ×3 | `reject` ⇒ `not(expected & actual)` | **否**（路径被 `_authorize` 结构性拒绝）⇒ 恒 True | **未考到 ⇒ E 适用** |
| `raw_updated` ×3 | `degrade` ⇒ `recall > 0.0` | **是** | **已考到且如实失败 ⇒ E 不适用，绝不能被标掉** |
**⇒ E 的适用范围收窄为 `revoked_source` ×3，不是初稿说的 6 条。**

**它撤回自己最响的反对理由**：
> 我初稿那句「E 会让通过率变成 100%」是基于 **t16 之前**的旧状态算的。按正确的当前状态：
```
当前:              通过 42 / 48 = 87.5%   (其中 3 条 revoked_source 恒真通过 = 虚报)
E 排除 3 条未考到:  通过 39 / 考到 45 = 86.7%
⇒ E 让数字**略微下降**（87.5% → 86.7%），而不是升到 100%。我那条最响的反对理由不成立，特此撤回。
```
**⇒ 它的算术是对的，captain 先前给的 39/42 = 92.86% 是错的** —— captain 误把 `raw_updated` 也当成「未考到」（那是初稿判据的错误）。**更正：39/45 = 86.7%。**

**它保留的治理规则（captain 采纳）**：把难题标成「未考到」以抬高通过率的**结构性风险仍在**（只是当前数据下不可兑现）。
**E 的真正价值不是改数字，而是让「那 3 个通过位是空的」变得可见。**

**它的自我更正结语（captain 特别记录）**：
> 我这次是在**复核你的答案**的过程中发现自己的判据错的 —— 如果我当时直接接受「6.2 已解答」而不去实测，那个错误判据就会留在提案里，**并且会建议把一条真实的失败信号标成「未考到」**。

### engineer-rrf 用 captain 的归因基线复算了它的精确改动范围 2026-09-20

**它从 `baseline-before-team.patch` 重建开工前版本并 diff**（**captain 建的基线派上了用场**）：
```
app/agents/nodes/wiki_retrieval.py  +16 / −4  —— 恰好是 _candidate_score() + 4 处调用点
                                              **截断代码 0 残留**（已完整回退，diff 可复核）
app/services/wiki/snapshot_reader.py +161 / −3（t3 双路融合，默认关闭）
其余文件一个都没动（其余 M 项均在 captain 的基线清单里，属既有改动）
```

**它回答 captain 的 #4（截断与二级融合是否有交互）**：**没有**，三条可检验理由：
1. 截断只作用于 `wiki_retrieval.py` 的候选准入，输入是 `search_wiki_pages` 返回的**语料 A** 候选；
2. `memory_read.py` 的二级融合按 `adapter.channel` 融合 vault-note/graph/diary，`RetrievalMemorySourceAdapter` 走 `retrieval_service.search(...)`，该路径**用 `wiki_page_rejection_reason` 拒掉 wiki 页**，到不了快照读器；
3. 反向也不成立：`snapshot_reader` 只在 wiki 查询节点里被调用。
**并更正一处计数**：RRF 生产调用点现在是 **4 个**（scout 数到 3）—— 第 4 个是**它新增**的 `snapshot_reader.py:236`，位于语料 A 内部；**原有 3 个它一个都没改**。

**它更正 captain 的测试协议告警（captain 采纳）**：
> captain 说「在 `apps/backend` 下跑会 exit=1 + `No module named 'apps'`」。**实测不是这样**：
> 用 `cwd=apps/backend` + **相对路径** `python -m pytest tests/...` → **exit 0 / 63 passed**，不是假红。
> 原因：`tests/` 有 `__init__.py`，pytest 以 `apps/backend` 为 rootdir 插入 sys.path，`tests.*` 导入正常；
> captain 遇到的报错是**用点号路径 `apps.backend.tests.*` 从 apps/backend 跑**才会出现。
**它已按 captain 的协议从仓库根复跑**：`63 passed, exit 0 (792s)`。**两种协议都是绿的，不存在假红。**

**它更正 captain 对「语料 A 无第二条腿」的推论**：
> captain 的 grep 事实（`app/services/wiki/*` 内 `embedding|vector` 命中 0）**成立**，但它**不足以推出**「语义腿不存在」：
> 语义腿用的是 `app/services/embeddings.py` 的**内置本地 ONNX**，在**查询期**对 `wiki_page_bodies` 正文现算稠密召回 —— **不需要任何预计算向量索引，也没有复用 vault-note 索引**。
**⇒ captain 的「语料 A 无第二条腿」是错的推论（grep 范围太窄）。**


### t14 完整报告的补充细节（captain 逐条采纳）2026-09-20

**A 项补充 —— 版本归属**：磁盘上有**三个** `snapshot_reader` 版本：
```
HEAD                2B8CD575
t3 的 13:52 副本    5885992B
冻结版              80CA74CA
三份消融产物（14:13/14:21/14:31）都早于冻结版（14:40:21）
逐行 diff t3 副本 vs 冻结版：37 行差异，**全在语义腿**
  （_semantic_page_ranking 外层 try/except；_candidate_for_path 放宽为 except Exception）
  且**只在注入嵌入器时可达** ⇒ 默认路径结论不受影响
  **但融合臂数字（47/48、replaced 34、reads 418、2563ms）产自被取代的修订**
```

**A 项补充 —— 「默认路径逐行不变」的准确表述（captain 已采用）**：
真 A/B（HEAD 版 reader vs 冻结版，不注入嵌入器，**42 组 query×limit**）；**先做控制实验证伪自己**（冻结树连跑两次仅 `content_hash` 不同，故排除该键）：
```
路径顺序        0 组不同
snippet/title/heading/行号  0 组不同
**score        0/36 → 36/36**   ← HEAD 的 WikiPageCandidate 只有 8 字段、无 score
```
经 `asdict` 进入 `search_wiki_pages` 工具载荷（`adapters.py:206` → `tools.py:340`）⇒ **默认路径候选载荷形状变了、模型可见**。
**加法式、不改顺序、不构成保证削弱**，但主张应改写为：**「排序与题面指标逐条不变；候选载荷新增 `score`」**。
**实现者的消融指标集里没有「候选字段集合」，所以测不出来。**

**C 项补充 —— 一处 captain 与实现者都未覆盖的降级形态 + 一个病态输入观察**：
- 实现者只比对**路径列表**；verifier 比对**每一字段**（path/hash/title/heading/snippet/start/end/score/generation）× 3 条查询；
- **`embed_documents` 返回向量数少于文本数（实现者未测）** ⇒ 同样 `mode=bm25_semantic_degraded` 且逐字段完全相同；
- **⚠️ 附带观察：NaN 向量被当作有效嵌入接受**（`mode=fusion`），词法零命中查询下结果 0→2 条。
  **非权限绕过，属病态输入健壮性观察，严重性低** —— 但**登记在案**（本会话已多次见到「静默接受异常输入」）。

**D 项补充 —— verifier 自纠一处探针缺陷**：
> 第一版集成用例把两条关系建在**同一对端点**上，被 upsert 去重成一行，读回**先写入的** metadata ⇒ **假失败**。
> **是我的探针缺陷，不是产品缺陷**；改用不同客体后 PASS。
**captain 评价：主动登记自己探针的假失败，比只报「通过」有价值。**

**E 项补充 —— 它独立定位的结构性原因**：
`_graph_fusion_candidates`（`retrieval.py:1063`）遍历 `store.traverse`，而 `traverse`（`memory_entity_graph.py:1706-1715`）的 SQL 带
**`WHERE statement_kind='relation' AND status='active'`** ⇒ **claim 被 SQL 结构性排除，不是调用方约定**。
**对选项 A 的后果**：同一条偏好事实在同一份融合结果里出现两次、权威口径互相矛盾（user vs external）。
**按权威排序会把 user 那份排前面，但模型仍看到同一条主张的 external 副本。** ⇒ **登记为选项 A 的前置问题。**

**B 项的诚实局限（captain 接受）**：语料 `notes` 表为空，生产 `authorize`（`factory.py:525-550`，基于 `notes.status/content_hash`）**无法直接演练** ⇒
**它验证的是闸门机制，不是生产授权策略实现本身。**

**回归**：冻结快照 **19 套件 199 passed / 0 failed（343s）**。

**verifier 的不确定项（captain 全部接受）**：① 融合臂数字未在冻结版重测（只做方向性判断）；② 未亲自跑 48 题消融（做的是独立读证据 + 独立代码级 A/B）；③ 生产 `authorize` 未被直接演练；④ `score` 新字段下游影响未穷举；⑤ 快照很可能不等于最终交付版本；⑥ 若 scout 的 t11 改题集，A1 的题集一致性需重验；⑦ t3「语义腿严格优于单路」的方向它**未独立复现**。

**captain 说明**：其中 ①⑦ 已由 **t19** 承接（verifier 在冻结修订上重测三臂）。


### engineer-rrf 更正 captain 的一处判断（当前树上不成立）2026-09-20

**captain 曾说**：「把下限做在 `_citation_value` 或其准入判断处，避免**两套相关性判断并存**」。
**它的更正**：
> 这个批评对我那版（**已回退的**）截断**是成立的**：我用的是独立的 `_relevance_floor`/`_above_relevance_floor`，确实与 `_citation_value` 并存。
> **但截断已回退，当前树里只剩 `_citation_value` 一套**（`wiki_retrieval.py` 的 diff 只有 +16/−4，全是 score 语义修复）
> ⇒ **「两套并存」在当前树上不成立。**
**captain 采纳该更正。**

**它给出的将来重做方案（与 captain 的方向一致，且更具体）**：
```
candidate_value = _citation_value(score, freshness, coverage)
floor_value     = max(窗口内各候选价值) × ratio
准入 = candidate_value >= floor_value
⇒ 只有一套相关性判断，且 freshness/coverage 自动进入（与第九页价值准入同源）
```
**⚠️ 它指出的实现关键点（重做时会卡在这里，很有价值）**：
> **freshness 是逐来源的**，现在是在**准入循环里**才算出 `path_freshness`；把下限挪到价值层就**必须把下限计算也挪到那一层**，
> 否则**下限只能用 `score`，又退回两套判断**。
> **这也是我那版没走这条路的原因（改动面更大），但你的方向更干净。**

**captain 评价**：**这解释了「正确方向」的真正障碍不是意愿而是结构**（逐来源 freshness 的计算位置）。**记入台账作为将来重做的前置条件。**

**它确认的硬约束与事实**：
- `top_k ≤ 40`：其新增的 `snapshot_reader.py:239` 是 `min(40, max(limit, len(lexical_paths)))`；
- **RRF 生产调用点现在是 4 个**（captain 先前数到 3）—— 第 4 个是它新增的 `snapshot_reader.py:236`，**在语料 A 内部**；**原有 3 个一个都没改**；
- **截断与二级融合无交互**（三条可检验理由已给出）。

**它的一句纪律声明（captain 特别记录）**：
> **请以 t19 的结论为准，不要以我的自述为准。**
**captain 采纳：融合臂数字以 t19（verifier 在冻结修订上的独立重测）为准。**

**任务状态澄清（第三次同步）**：t3 与 t12 都是 completed 终态；engineer-rrf 名下**无未完成任务**。**captain 不再要求它 claim t3。**


### ⚠️ captain 的算术被 engineer-a4 推翻 —— 且它指出这正是 captain 自己警告的风险 2026-09-20

**起因**：captain 的消息**交叉**，采纳了 engineer-a4 **上一轮已自行推翻**的判据版本（「按缺席原因分类」）。

**它更正后的判据**（§4-E.1）：**一题算 `exercised` 当且仅当「存在可达的系统行为能让判定结果改变」**。
- `revoked_source`：`reject ⇒ not(expected & actual)`，路径被 `_authorize` **结构性拒绝** ⇒ **恒 True** ⇒ **未考到** ✅
- `raw_updated`：`degrade ⇒ recall > 0.0`，**能被行为改变** ⇒ **考到了，且如实失败** —— **不是未考到**

**captain 独立核验该判据**：
- `raw_updated`：若系统**能**取到 golden 页（L3 修好后页可读、或检索更强），`recall` 会 > 0 ⇒ **PASS** ⇒ **判定可被行为改变** ⇒ **已考到** ✅
- `revoked_source`：`_authorize` 是**设计上**的拒绝，**没有任何可达行为**能让 `expected & actual` 非空 ⇒ **恒 True** ⇒ **未考到** ✅
**⇒ 它的判据正确，captain 的算术错误。**

**算术差异（分子相同 39，分母差 3）**：
| 判据 | 未考到 | 考到 | 真实通过 | 结果 |
| --- | --- | --- | --- | --- |
| **§4-E.1 更正判据**（仅 revoked） | 3 | **45** | 39 | **39/45 = 86.67%** ✅ |
| captain 的版本（含 raw_updated） | 6 | 42 | 39 | 39/42 = 92.86% ❌ |

**它给出的决定性理由 —— 排除 `raw_updated` 恰好违反 captain 自己定的规则 ③**：
> 你 §4 把规则 ③ 升级为硬性要求：「**`exercised=false` 不得用来关闭该题暴露的缺陷**」。
> 而 `raw_updated` **同时暴露了 L1（判据忽略 coverage）与 L3（产品无「变化→stale」路径）**。
> 把它标成「未考到」排除出分母 —— **就是用 `exercised` 关掉一条真实失败信号**，且会**连带抹掉 L1 与 L3 两条待办**。
> **这不是类比，这就是规则 ③ 的教科书实例。**
**⇒ captain 的 92.86% 正是 captain 在 §4 担心的那个风险的实例**：排除 3 条真实失败后，数字从 87.5% **升到** 92.86%。

**它还指出 captain 一处跨时刻比较**：captain 的「93.75% → 92.86%」混用了 t16 前后两个时刻。
**同一时刻的正确对比**：
```
t16 之后，不做 E: 42/48 = 87.50%   ← 含 3 条 revoked 恒真通过（虚报）
t16 之后，做  E: 39/45 = 86.67%   ← 剔除 3 条虚报，保留 6 条真实失败
⇒ E 让数字**略降**（87.5% → 86.7%）：它是**纠偏**，不是**提分**
```
**captain 全部采纳，并在台账更正自己的两处**（92.86% 与跨时刻比较）。

**它同时撤回自己的两条旧说法**：
1. 「E 会让通过率变成 100%」—— 基于 t16 之前状态，**错，撤回**；
2. 由该算术推出的「剩下 42 题没有一条能区分好坏」—— **同样撤回**；t16 之后存在 **6 条真实失败**（`lexical_gap` ×3 + `raw_updated` ×3）⇒ **该题集并非无判别力**。
（**t6 关于「饱和」的结论有其自己的证据**——golden 恒在前 4 位、读窗永不截断——**不依赖该算术，故不受影响**。）

### engineer-rrf 更正 captain 的「下限是融合前置」论证 2026-09-20

**captain 曾说**：「没有下限，噪声候选会污染融合的效果评估」⇒ 建议先做下限再谈融合。
**它两种配置都跑过，结论相反**：
| 配置（同一 48 题、指纹 `36581ff0ccddb9e3`） | 通过 | reads | 失败题 |
| --- | --- | --- | --- |
| bm25 单路 + 无下限 | 45/48 | 271 | lexical_gap ×3 |
| **融合 + 无下限** | **47/48** | 418 | lexical_gap_003 |
| 融合 + 下限 0.4 | **46/48 ↓** | 304 | **+two_hop_001** |
| 纯语义单路 + 无下限 | 45/48 | 385 | two_hop_003/alias_003/ninth_page_003 |
⇒ **下限不是融合的前置，反而把融合臂从 47/48 削弱到 46/48。**

**并指出评估不存在被污染的问题**：判据是**节点级 pass**（固定题集 + 确定性判据），不是「看起来更好」的主观判断 —— **噪声多只会让分数变低，不会让「融合变好」被误判成真的**。
⇒ **captain 的「先做完下限再谈融合」次序建议不成立**，且**融合已完成并已测**（47/48 > 45/48 单路，也 > 45/48 纯语义单路 ⇒ Qdrant「beats either prefetch」**已满足**）。
**captain 采纳该更正。**


### 结构性洞察：一条禁令若无检测手段，就等于意愿声明（engineer-a4 提出，captain 采纳）2026-09-20

**captain 曾说**：「我写下规则 ③，然后自己违反了它 —— 说明规则写下来不等于会遵守。」
**engineer-a4 的结构性更正（比 captain 的说法更深一层）**：
> 规则 ③ 是「`exercised=false` 不得用来关闭该题暴露的缺陷」。
> **在旧判据（按缺席原因分类）下，违规需要一个「判断动作」** —— 把 `raw_updated`（`load_rejected`）归到「未考到」这一类。
> **那个动作是自由裁量的**，所以它可以被做错，而且做错时**没有任何东西会报警**。
> **⇒ 一条你无法检测其被违反的禁令，不是规则，是意愿声明。**
> **更正后的判据从构造上取消了那个判断动作** —— 标记是**算出来的**，不是**人工决定**的：
>   `revoked_source`：`_authorize` 是设计性拒绝 ⇒ 判定恒 True ⇒ **计算得 `exercised=false`**；
>   `raw_updated`：`recall > 0.0` 可被行为改变 ⇒ **计算得 `exercised=true`**。
> **⇒ 想要违反规则 ③，你得先把检测器改错，而那是可被测试抓住的。**
> **这比「写下来 + 更小心」强一个量级：前者是约束行为，后者是消除机会。**

**它建议的台账措辞（captain 采纳，并认为适用于本会话其它几处）**：
> **「一条禁令若无检测手段，就等于意愿声明；正确修法是把裁量点删掉，而不是要求更自觉。」**
**它指出该模式在本会话其它地方同样成立**，包括它自己上一轮认的位移表那条：
> **我写了注释＝意愿，没让数字不可用＝没删裁量点。**

**⚠️ 它同时说清残留风险（不让结论说过头）**：「取消裁量点」**只在检测器实现正确时成立** —— 检测器本身仍可能写错（那正是它登记的 §6.7）。
**⇒ 因此 t20 的验收必须包含两条，缺一不可**：
```
① 翻转断言：把 revoked_at 置回 NULL ⇒ 该题 exercised 必须自动翻回 true
② 不误标断言：构造一条「页可读但确实没召回」的题 ⇒ 必须**不被**标成未考到（要如实报 fail）
**第 2 条比第 1 条更重要**：
  第 1 条防「标记只增不减」；第 2 条防「检测器把真失败也吞掉」（规则 ③ 在检测器层面的复发）
```

**它还给出 ① 的可执行形式（captain 采纳，t20 直接照用）**：
```
revoked_source ×3 的阻塞 = wiki_page_bindings.revoked_at 非空（phase_d_corpus.py:_set_binding:188-193 写入）
⇒ 最小改动 = 把 revoked_at 置回 NULL
⇒ 断言 = 同一题在「置回 NULL 后」必须 exercised=true，且此时它的判定结果可被行为改变
它实测过该路径可达：_authorize 在 revoked_at IS NULL 时对同一路径返回 True
```
**为什么值得写死**：把「标记会翻转」从一句原则变成一条**会失败的测试**。

### ⚠️ 三因子/单因子不一致 —— captain 认领归属 + engineer-rrf 的两处更正 2026-09-20

**engineer-rrf 对着代码复核确认（它说「非我引入」——正确，但它未指名归属；captain 认领）**：
```
wiki_retrieval.py:363-371  min_held = min(_citation_value(held_scores[path], freshness, coverage) ...)  ← 准入：三因子
wiki_retrieval.py:417      displaced = min(candidates_to_displace, key=lambda p: held_scores[p])         ← 置换：只看 raw score
⇒ 「提供 min_held 的那一页」与「真正被置换的那一页」不一定是同一页
```
**归属：这是 captain 造成的** —— 第 4 轮 captain 写的置换用原始 score；第 23 轮 captain 把准入改成三因子（逐来源 freshness）**却没同步置换**。
（engineer-rrf 只说了「非我引入」，**captain 主动认领，以免归属悬空**。）

**它指出这影响 captain 的决定**：captain 建议下限与 `_citation_value` **同源**，但既有代码**本身不自洽**，所以「同源」有两种含义：
- 下限建在 `_citation_value` 上 ⇒ **继承**该不一致；
- 下限建在 raw score 上 ⇒ **放大**它。
**它的建议（captain 采纳）**：要么先修 `:417` 让置换也用三因子（**那是一次独立的行为变更，需要单独验收**），要么在重做下限时**显式声明**采用哪一套口径并说明取舍。
**captain 裁定：`_citation_value` 统一（含 `:417`）作为独立变更，单独验收；不塞进 t21（向量索引）里。**

**engineer-rrf 更正 scout 的一处判断（captain 曾接受，现更正）**：
> scout 提 `:333` 的 `candidate_scores.get(path, 1.0)` 是「第 5 处 `or 1.0`」。**我复核后判定不是**：
> `.get(key, default)` **只在键缺失时生效**，**正合 captain 的口径**；且该 1.0 有注释写明是为了防止 `:417` 的 raw-score `min()` 把无分页当最低价值置换掉，改成 0.0 会**重新引入它要防的问题**。
**⇒ scout 的「第 5 处」判定错误，captain 先前接受该判定也是错的。**

**但它指出真正的底层不一致（已登记）**：
> 图扩展（`page.links`/`backlinks`）发现的邻居页**不进 `candidate_scores`**，读入后拿到**发明的 1.0**；
> 而 LIKE 兜底候选（显式 0.0）拿到 **0.0** ⇒ **「无词法证据」两条路径取值不同**，会让任何建在 `score` 上的下限**语义不自洽**。
**⇒ 真正的缺陷不是 `.get(..., 1.0)` 的写法，而是「图扩展页缺席于 `candidate_scores`」。**


### 命名缺陷类：「默认值悄悄顶替了本该存在的条目」（engineer-a4 提出，captain 采纳入台账）2026-09-20

**它指出本会话已出现三次的同一失效类**，并给出分类（captain 采纳，作为审查用启发式）：

| # | 实例 | 形态 | 正确修法 |
| --- | --- | --- | --- |
| 1 | `wiki_retrieval.py:326/347` 的 `float(x or 1.0)` | **假值塌陷**：`0.0 or 1.0 == 1.0` ⇒ 真实的 0 分被换成默认 1.0 | 改**取值写法**（仅 `is None` 时取默认） |
| 2 | `:333` `candidate_scores.get(path, 1.0)` | **键缺失**：写法本身正确，缺陷是**图扩展页根本没进 `candidate_scores`** | 改**生产者**（把图扩展页登记进表），**不是改这一行** |
| 3 | t10 实测的双重入场 | **身份不一致**：内部 graph 腿用 `graph:<id>`、memory_read 用 `<id>` ⇒ 同一事实不合并 | 改**标识生成的一致性** |

**共同点**：一处**查找/身份不一致**，被一个**默认值或不去重**悄悄吸收，**没有任何东西报警**。
**⚠️ 但它们不是同一类**：#1 是**取值写法**；#2/#3 是**生产者与消费者对「键/身份」的理解不一致**。
**修法方向相反** —— **把 #2 当成 #1 修（只改默认值）会掩盖真缺陷。**
**这正是 engineer-rrf 本次复核的价值**：它没有接受 scout 的「第 5 处 `or 1.0`」判定，而是指出**真正的缺陷在生产侧**。

**为什么这类缺陷反复逃过审查（它的解释，captain 采纳）**：
> 症状（分数不对／结果缺一条）与根因（键不一致）**隔着两层**，而**默认值恰好让症状看起来「正常」**。
**⇒ 命名该分类的价值：下一位审查者能更快定位。**

**它给出的自校准证据（说明该分类可操作）**：
> 我在 `content_category_from_metadata` 里**刻意返回 `None` 而不给默认值**、`_lifecycle_metadata_allowed` 也是 **fail-closed** —— 按上表它们属于**避开 #1 类**的写法。
> 这不是自夸，是说明该分类**可操作**、且我在写时是**有意识避开**的。

**captain 评价**：**这条分类比单个缺陷修正更有价值** —— 它是**可复用的审查启发式**，而不是一次性结论。
**本会话的层次在上升**：起初纠正事实错误 → 后来纠正论证 → 再后来纠正方法论（「删裁量点」）→ **这次是产出一个可复用的诊断分类**。


### t19 完成：冻结修订上三臂重测 —— **融合仍严格优于两路单路**，且新旧差异被完全解释 2026-09-20

**报告**：`E:\a 工作\wiki-audit\team-verifier-t19-fusion-remeasure.md`

**核心结论**：冻结修订 + 新题集：**融合 44/48 > 纯语义 43/48 > bm25 42/48** ⇒ **融合仍严格优于两路单路** ✅
**代价登记**：延迟约 bm25 的 **3 倍**；置换量 **31 vs 3/0**。

**⚠️ 新旧不可比较的原因被精确到字段，且无残差**：
```
两版题集题数题号完全相同（48/48，无增删）；只有 3 道题变了，且变的是同一个字段：
  q_raw_updated_001/002/003: golden.action "stale" → "degrade"（conclusion/citations 未变）
判据影响（phase_d_eval.py:38-55）：
  stale   = not (expected & actual)   ← 检索不到就通过
  degrade = recall > 0.0              ← 必须真的取到证据
⇒ 这不是「题变难了」，而是把一条「反向奖励检索失败」的判据纠正为正向判据
⇒ 三臂都取不回该页 ⇒ 各丢 3 题
逐臂：bm25 45→42（reads 271→271、replaced 3→3，逐位相同）
      fusion 47→44（418→415、34→31）
      semantic 45→43（385→384、1→0）
```
**唯一未被题集解释的是 semantic 的 `q_ninth_page_003`**（该题未被 t16 改动）。verifier **补跑隔离并判定归属**：
```
semantic/scorefix   43/48  replaced 0  → ninth_page_003 通过
semantic/baseline  42/48  replaced 1  → ninth_page_003 失败
反向验证：新 semantic/baseline 失败集 = 旧 semantic 失败集 + 3 道 raw_updated，逐题完全对齐
⇒ 旧→新全部差异被完全解释：题集判据变更（三臂各 −3）+ scorefix（semantic +1）
```
**⇒ ⚠️ captain 要求：不得把 45→42 / 47→44 记为「检索退化」。**

**scorefix 的效应已隔离测量**：对 bm25 臂 **per_question 全字段 0 差异**（与 t12 自述**独立吻合**）；对 semantic 臂 **+1 题**。
⇒ **一次有正向收益、且不改变词法单路行为的修复。**

**score 载荷下游影响（t14 登记的不确定项）—— 模型可见、用户不可见、契约不变**：
```
模型可见：graph_runtime.py:795-799 complete_with_tools(tools=…)；search_wiki_pages 是 StructuredTool(tools.py:335)
          ⇒ 返回值进 tool message
不拦截：  WikiPageSearchResponse.candidates: list[dict]（tools.py:183，无类型）⇒ 字段原样穿过
用户不可见：_emit_tool_results（events_helpers.py）没有 search_wiki_pages 分支
契约不变：无 FastAPI 路由，只作智能体工具暴露
既有消费者不依赖键集合（graph_runtime.py:1288-1298 只看 name 与 MemorySearchResponse.results）
实测载荷：候选键 8 → 9，score 值 1.11e-06 / 1e-06，载荷 734 → 783 字节（+6.7%）
```

**两条对后续有用的附带事实**：
1. **`snapshot_reader.py` 在 t12 之后仍是 `80CA74CA003AF255`，与 t14 快照逐字节相同**
   ⇒ **t14 关于语义腿的全部结论（权限闸三层、降级逐字段等价）继续有效，不需要重做。**
   t12 实际只改了 `wiki_retrieval.py`（`_candidate_score`；截断已回退）+ 评测驱动。
2. **运行前两项预检**（已写入报告）：**ONNX 嵌入器可用**（且驱动在不可用时会 `raise`，**不会静默降级成 bm25**）；
   **自写 launcher 断言 `app.__file__` 落在快照内**（否则消融可能悄悄跑在活动树的 editable 安装上）。
**captain 评价：第 2 条正是本会话反复出现的「静默失真」模式的对策 —— 它没有「相信」环境正确，而是断言了它。**

**verifier 未验证（明确登记，captain 接受）**：
① **一条假设未验证**：score 量级极小（**1e-06**），**模型可能误读为「几乎不相关」** —— 需真实模型行为评测，本轮未做；
② score 下游影响未穷举；③ 三臂各只跑一次（评测确定性，判断重复意义有限但未实测）；
④ 未评价 t16 的 `stale`→`degrade` 是否正确（属 t16/scout 范围）。

**captain 对 ① 的处置**：**登记为已知风险**（模型可见的 score 量级可能被误读），**列入待验证**。


### verifier 主动报告：t19 被 t18 并发污染（并精确分离影响面）2026-09-20

**captain 的「先别开工」警告收到时它已在跑 —— 污染已发生，它主动报告。**

**时间线（全程重叠）**：
```
t18 创建/in_progress   16:30:08
verifier bm25 臂        16:46–16:52
verifier fusion 臂      16:52–17:02
verifier semantic 臂    17:02–17:08
verifier bm25/baseline  17:08–17:13
verifier semantic/baseline 17:19–17:27
⇒ 全部五次臂运行与 t18 完全重叠
```

**⚠️ 影响面被精确分离（captain 采纳）**：
- ~~**pass/fail / reads / replaced 是确定性量**（评测无模型端点、无随机采样）⇒ **不受负载影响**~~
  **⚠️ 该说法已被 verifier 本人撤回（captain 据此更正本条）**：
  **该 harness 的判据内嵌时间/预算条件**（`wiki_retrieval.py:42/46` 的 `deadline_sec`/`budget_chars`，超时出口至少 8 处）
  ⇒ **并发变慢可以把某题推进 `time_budget_exhausted`/`budget_exhausted` ⇒ 判分结果本身会被并发改变**。
  **正确结论**：t19/t24 的数字**未被污染**，但依据是「**探针查过**」而非「结构上不可能」——
  9 份产物 432 条记录 + engineer-rrf 的 336 条，**合计 768 条 `stop_reason` 全为 `assessment_unavailable`，0 可疑**。
  **⚠️ verifier 的自报理由（本会话最深的认识论观点之一）**：
  > **「结构上不可能」会让后人停止检查；「这次查过」会让他们继续查。**
- **`mean_latency_ms` 与 `elapsed_s` 受污染** ⇒ 报告中「融合延迟约为 bm25 的 3 倍」已标注 **⚠ 受并发污染，只作方向参考，绝对值不可用、不可与 t3 比较**
**⇒ captain 记录：「融合延迟 3×」这一条**不得**作为生产可行性判断的依据。**

**它登记了自己的方法缺口**：开工前做了**嵌入器预检**与**快照钉扎预检**，**却漏了「同时间窗内是否已有重负载任务」**。

### 新团队规则（verifier 提出，captain 采纳）2026-09-20

> **重负载任务必须串行化；开工前须检查同时间窗内是否已有重负载任务在跑。**
**它指出这与「冻结窗口」「广播位移量」是同一类协调纪律**：
> **都是「我的行为会改变别人测量结果」的问题。**
**可执行形式**：**跑 >5 分钟的评测/套件前，先看一遍 `agent_teams_status` 里是否有 in_progress 的重任务。**
**⇒ 本会话的协调纪律至此完整（六条）**：
```
插入者：有义务广播位移量（治因）
广播者：必须声明基期（防误用）
引用者：写「符号名 + 行号(捕获时刻)」（可反查）
验证者：声明其引用取自哪个窗口（可追溯）
订正者：一律 grep 实测，不做偏移量算术（不赌）
重负载：跑 >5 分钟前检查是否有并发重任务（不污染）
```

### `last_search_mode` 缺口：verifier 承认无法直接证明，只给间接证据 2026-09-20

**captain 曾要求「显式给出嵌入器就绪状态的证据」并记录每臂 `last_search_mode`。**
**它承认这是真实缺口**：消融驱动的输出结构（`phase_d_fusion_ablation.py:121-145`）**不含 `last_search_mode`** ⇒ **无法从产物直接证明**每次 fusion 查询都走了 `fusion` 路径。

**它给出的间接证据（三条，captain 采纳并认为方向可靠）**：
1. **驱动硬门**：`phase_d_fusion_ablation.py:93` 在嵌入器为 `None` 时 **`raise RuntimeError`** ⇒ **不可能静默降级成 bm25，只会中止** —— **这挡住了 captain 最担心的那个失真模式**；
2. **可用性证据**：预检打印出 `LocalOnnxEmbeddings`，`embed_query`/`embed_documents` 均 callable，`local_embedding_dir` 解析到快照内路径；
3. **行为证据（它认为最有力）**：`semantic` 臂 **`lexical_gap 3/3`**，而 `bm25` 臂 **`lexical_gap 0/3`** —— `lexical_gap` 按定义与权威页**无共同词** ⇒ **能取回它们必然要求语义通道真的在工作**；`fusion` reads 415 vs bm25 271 同向。
**⇒ 「结论方向可靠；但逐查询 mode 的直接证据缺失，我不把它说成有。」** ✅

**补齐方式（已批准，等 t18 收口）**：一条**单查询探针**（数秒级，不加重负载），在真实语料上跑一次 fusion 查询并打印 `reader.last_search_mode`。**与 t7 第 4 项复测一并做，共用 `snapshot-t19`。**

**它确认的一条对后续有用的**：`snapshot_reader.py` 与 t14 快照逐字节相同（`80CA74CA003AF255`）
⇒ **t14 关于语义腿的全部结论继续有效**；**t7 第 4 项复测只需针对 t12 改过的 `wiki_retrieval.py` 范围。**


### 收口阶段状态快照（captain，2026-09-20 17:36）

**运行中**：
```
t18（scout 冻结树全量套件）  54%，含若干 s（skip）
verifier 的 t7 第 4 项复测 + last_search_mode 单查询探针（只读，与 t18 并存）
```
**已排队（门控 t18+t19）**：t20（E + L1，engineer-a4）· t21（向量索引，engineer-rrf）
**已收口**：t19（融合臂重测，融合 44/48 > 43/48 > 42/48）

**当前诚实状态（评测）**：**42/48**
```
q_lexical_gap_001/002/003  ← 需语义腿（t19 已验证：融合可修 2/3，且 semantic 臂 lexical_gap 3/3）
q_raw_updated_001/002/003  ← 需产品能力（L3）+ 判据修复（L1，已排队 t20）
原 45 题 = 45/45（two_hop 回归已修复并独立验证）
```

**本会话团队产出汇总（17 项任务完成，1 项取消）**：

| 类别 | 产出 |
| --- | --- |
| **评测诚实性** | t6 题集判别力（45/48，MRR 差距 +70%）· t16 两处判据修复（净 −3，**首次诚实**） |
| **检索** | t3 双路 RRF 融合（**已验证有效**：44/48 > 43/48 > 42/48）· t12 截断按准则回退 + `or 1.0` 修复 |
| **A4 权威轴** | t2 接线 · t8 读侧重建（**驳回 captain 的回填迁移方案**）· t10 双重入场实测 · t15 覆盖面缺口 |
| **设计提案** | t9 混排面（选项 A/B/C/D）· t13 成本分摊（**记录设计、暂不实现**）· t17 空洞题重设计 |
| **独立验证** | t7（A4 接线，**发现 score 载荷变化**）· t14（t3/t8/t10，**B 项权限闸最重要**）· t19（融合臂重测，**归因无残差**） |
| **未取得的证据** | **t18 全量套件**（进行中） |

**本会话团队纠正 captain 的记录（10 次）**：
```
1  scout        我以「不可验证」为名砍掉 RRF（实际仓内内置本地 ONNX）
2  engineer-a4  我要求的数据回填迁移（改用读侧重建，更好且不写用户数据）
3  engineer-rrf 我要求它写一句与证据相反的话（「融合未实施」）
4  scout        我基于代理指标的「不合入」裁定（节点级实测推翻）
5  scout        我的缺陷 1 修复方向是假修复（恒真条件）
6  verifier     我的假设「R2 上反证不再恰好 3 条」
7  engineer-a4  我的算术 92.86%（应 86.67%，且我违反了自己写的规则 ③）
8  engineer-rrf 我的「两套相关性判断并存」（当前树上不成立）
9  engineer-rrf 我的「语料 A 无第二条腿」推论（grep 范围太窄）
10 engineer-rrf 我的「下限是融合前置」论证（其数据结论相反）
```
**captain 也独立验证了 3 次**（two_hop 回归 43/48、two_hop 修复恢复、raw_updated 失败归因）。

**本会话固化的团队纪律（六条）**：
```
插入者：有义务广播位移量（治因）
广播者：必须声明基期（防误用）
引用者：写「符号名 + 行号(捕获时刻)」（可反查）
验证者：声明其引用取自哪个窗口（可追溯）
订正者：一律 grep 实测，不做偏移量算术（不赌）
重负载：跑 >5 分钟前检查是否有并发重任务（不污染）
```
**以及一条方法论原则**（engineer-a4）：**「一条禁令若无检测手段，就等于意愿声明；正确修法是把裁量点删掉，而不是要求更自觉。」**
**以及一条诊断分类**（engineer-a4）：**「默认值悄悄顶替了本该存在的条目」**（三类，且修法方向相反）。


### ⚠️ 延迟数字作废：「融合延迟约 3 倍」不得作为结论（verifier 主动更正自己的措辞）2026-09-20

**verifier 先前说**：「我的延迟数字被 t18 并发污染、被抬高」。
**它收尾对照后更正**：
```
同一配置（bm25/scorefix、同题集、同修订）：
  verifier 的 elapsed_s      = 365.7
  engineer-rrf 的 elapsed_s  = 696.7   ⇒ 约 1.9 倍
⇒ **verifier 那次反而更快** ⇒ 原措辞（「被 t18 抬高」）不准确
```
**更准确的表述（它给出，captain 采纳）**：
> **本机延迟本身有约 2 倍的运行间抖动 ⇒ 延迟不是可用的比较指标，无论谁测的。**
**⇒ captain 据此在台账标注：**
```
⚠️ 「融合延迟约 3 倍 bm25」**作废** —— 那是抖动下的单次测量，
   **不得作为生产可行性判断的依据**，也不得与 t3 的数字比较。
   生产可行性的正确依据是 engineer-a4 在 t13 指出的结构事实：
   语义腿零生产调用者（factory.py:552 不传嵌入器）⇒ 成本今天不在任何生产路径上发生。
```
**captain 评价**：**它修正的是自己的措辞，而且修正方向是「让自己的原说法更弱」** —— 这是诚实性的体现，不是退让。

### verifier 复核的两条（纯复核，未加负载）2026-09-20

**① 好消息：t12 的产物逐项印证了它的独立重测**：
```
E:\rrf_scratch\final_baseline.json / final_scorefix.json（新题集 ebdf7c1351b93585）的 bm25 臂：
  42/48、reads 271、replaced 3、失败题 = lexical_gap×3 + raw_updated×3
与 verifier 独立跑出的 t19_bm25_scorefix.json **逐项完全一致**
⇒ 两条独立路径同一结果；也再次确认 scorefix 对 bm25 臂零影响
```

**② 更正 engineer-rrf 的一处说法（影响脚本化用法）**：
```
engineer-rrf 称：缺 onnxruntime/tokenizers 时驱动会报 NO EMBEDDER、退出码 2，不会静默降级
verifier grep 冻结驱动：**没有 NO EMBEDDER 字样，也没有 sys.exit(2)**
  唯一守卫是 :93 的 raise RuntimeError("local embedding model unavailable; arm needs an embedder")
  ⇒ **退出码是 1，不是 2**
```
**实质结论（不会静默降级）正确** —— verifier 也把它当作关键证据引用了；
**但错误文本与退出码不准确**，按「退出码 2 = 缺嵌入器」写脚本会误判。
（verifier 未运行验证 —— 遵守不加负载要求，结论来自读码。）

**③ 附带确认：`reads` 在消融驱动里的定义（但「确定性」一词已被撤回）**：
> ⚠️ 原表述「可信的**确定性量**」不成立 —— `reads` = `len(report["read"])` 计的是**实际读取页数**，
> 而读取路径受 `deadline_sec`/`budget_chars` 影响 ⇒ **并发变慢同样会减少 reads**。
> **正确表述**：`reads` 的定义正确（就是实际读取页数），但**它同样是并发敏感的**，须与 `stop_reason` 一并核验。
```
驱动的 read_count 本来就是 len(report["read"])（phase_d_eval.py:202）
追加点在 wiki_retrieval.py:326（首轮）与 :394（置换轮）⇒ **就是节点实际读取的页数**
⇒ fusion 415 vs bm25 271 可信
```


### 收口进度（captain，17:43）2026-09-20

```
t18（scout 冻结树全量套件）  58%（输出文件 17:38:27 后进入慢段）
verifier 的 t7 第 4 项复测 + last_search_mode 探针  运行中（8 个 python 进程）
t20（E + L1）· t21（向量索引）  已排队，门控 t18
```
**代码仍冻结**（关键文件最新 mtime 16:07:39）⇒ **t18 的「运行期间无文件改动」前提持续成立。**

**captain 本轮仅做台账维护与派单，未跑任何测试、未改任何代码**（避免加剧资源竞争、避免破坏 t18 前提）。


### ⚠️ t18 的冻结节被破坏 —— 该次全量运行**不可作为最终证据** 2026-09-20

**captain 实测时间线**：
```
t18 冻结节记录        TS_UTC=2026-09-21T08:39:46Z（本地 16:39:46）
wiki_retrieval.py 改动  本地 17:25:47   ← **t18 运行开始后 46 分钟**
t18 仍在运行           输出文件 17:51:13（约 58%+）
```
**⇒ t18 的可信度判据「运行期间无文件被改动」被违反。**

**成因**：engineer-rrf 的 §9 修复（`_held_value` 口径统一 + 未知相关性显式化）在该窗口内落盘。
**captain 承担**：我要求 t18「运行期间不得改代码」，**但同一时间又允许 §9 修复推进**（且它称「按 captain 的直接指令执行」）——**这是 captain 的协调失误，与本会话前几次同类。**

**影响评估（诚实）**：
- 在 **17:25:47 之前**执行的测试看到的是**旧代码**；之后看到的是**新代码** ⇒ **同一次运行跨越了两个修订**；
- **不能作为「冻结树上的全量套件」证据**；
- 但**并非全无价值**：若出现失败，仍可提供线索（需按「跨修订运行」的口径解读）；
- **verifier 的 t7 复测未受污染** —— 它跑在**钉扎快照**上并断言过 `app.__file__` ⇒ **「断言环境」而非「相信环境」的价值再次体现**。

**captain 处置**：
```
1. **让 t18 跑完**（不中断）—— 中断与重跑总成本相同，且其失败信息仍有线索价值；
2. **不把 t18 结果当作最终证据**；
3. **待所有代码改动停止后，在真正冻结的树上重跑**（届时需**先确认无人在改**，并由 scout 在起止两端记录 mtime 比对）；
4. **要求 scout 在报告中显式声明「运行期间是否有文件被改动」**（该要求已在 t18 任务书内）。
```

**结构性教训（captain 记）**：**「要求冻结」不等于「冻结」** —— 本会话已是第三次因并发改动使测量作废。
**唯一有效的是「断言」而非「要求」**：verifier 的做法（起止记录 mtime + 断言 `app.__file__` 落在快照内）**是正确形态**。
**⇒ 重跑时采用同一形态**：跑在**复制的快照**上，而非活动树。


### verifier 独立核实并**加强**了「生产不接线」的结构依据（captain 采纳）2026-09-20

**captain 台账原依据**：「语义腿零生产调用者（`factory.py:552` 不传嵌入器）」。
**verifier 独立核实（行号取自 snapshot-t19）并给出更完整的链条**：
```
WikiSnapshotReader( 在 app/ 全仓**仅 1 处构造点**：api/services/factory.py:552
该点**不传** semantic_embedder：return WikiSnapshotReader(db, wiki, authorize=authorize)
semantic_embedder 在 app/ 的**全部出现只在 snapshot_reader.py 内部**
  （:90 默认 None、:97、:157、:203、:269/:270）
⇒ semantic_embedder is None
⇒ :157 pool == limit、:203 融合分支**永不进入**
⇒ **融合在生产上是休眠的，嵌入成本不发生。**
```

**它的关键论述（captain 采纳，因为它比我原来的理由更强）**：
> **这比「延迟有抖动所以别用」更强**：即便延迟测得再准，它也**不描述生产行为** —— 生产根本不走那条路径。
> **两层理由独立成立**（§0 抖动 + §4.5 路径休眠）。
**边界（它自己标注，captain 采纳）**：这只说明「今天不接线」；**要不要接线是另一个决策**（需单独评估覆盖收益与成本），本报告不做该判断。

**⇒ captain 台账更正**：生产可行性依据由「一条（零调用者）」升级为**两条独立理由**。

### verifier 对最终修订重跑的提议（captain 接受，待条件满足）2026-09-20

**它收尾复核发现活动树又动了**：`wiki_retrieval.py` `4E2D175B`(16:05) → **`E451D06D`(17:25:47)**。
**代码级风险评估（它给出）**：活动树该文件**仍只有 2 个** citation 构造点（`:359`、`:420`）、**仍无两轴字段** ⇒ **恒等变换的成立条件未被破坏**；若要写成对最终修订的正式结论，应以最终快照重跑（数分钟）。
**⇒ captain 决定**：**与 t18 重跑一并做**（两者都需要「所有代码改动停止后的冻结快照」），**避免再一次被并发破坏**。

**它另外指出的（captain 记录）**：
> 该文件 mtime 17:25:47 **落在我 t19 臂运行期间（16:46–17:27）** —— **因我的臂跑在钉扎快照上（断言过 `app.__file__`），测量未被污染**。
> **这是「断言环境」而非「相信环境」的价值。**
**⇒ 与 captain 对 t18 冻结节被破坏的结论一致：唯一有效的是断言，不是要求。**


### 本轮汇总（captain，17:55）2026-09-20

**✅ 已完成**：

**① verifier 的 t7 第 4 项复测 —— 通过，与 t14 完全一致**
```
calls=19 citations=140 calls_with_movement=0
citations_with_source_type=0 citations_with_content_category=0   73 passed
⇒ order_evidence_by_statement_authority 仍是恒等变换，不得记为增益
```
**它不是走过场**：`wiki_gate.py` 未变，**但 `wiki_retrieval.py` 变了**（t12）—— **而它正是构造送进证据门的引用的地方**；恒等变换的成立条件由它决定。**读码预判 + spy 实测双向一致。**

**② `last_search_mode` 缺口已补齐（由间接证据升级为直接证据）**：
| 嵌入器 | mode | 命中 | 调用 |
| --- | --- | --- | --- |
| `None` | `bm25` | [] | — |
| **真实 ONNX** | **`fusion`** | **2 页** | embed_query 1 次、embed_documents 1 次、7 段文档 |
| 抛错桩 | `bm25_semantic_degraded` | [] | — |
**边界（它自己标注）**：单查询探针，**不构成「消融中每次查询都走 fusion」的逐查询证明**。

**③ verifier 独立核实并加强 captain 台账的结构依据**：
```
WikiSnapshotReader( 在 app/ 全仓仅 1 处构造点：api/services/factory.py:552，且不传 semantic_embedder
semantic_embedder 在 app/ 的全部出现只在 snapshot_reader.py 内部
⇒ 生产上 pool == limit、:203 融合分支永不进入 ⇒ 融合在生产上是休眠的
```
**它的论述**：「这比『延迟有抖动所以别用』更强 —— 即便延迟测得再准，它也**不描述生产行为**。」
**⇒ 两条理由作为独立层次并存，而非一条替代另一条。**

**④ engineer-rrf 的 §9 修复（captain 已独立核验）**：
```
_UNKNOWN_RELEVANCE_VALUE = 1.0 (:75)   _held_value 定义 :98   unknown_relevance 上报 :357
**准入 :389 与置换 :442 均调用 _held_value**  ⇒ 口径统一已落实
wiki_retrieval.py 中 source_type/content_category = 0 次；构造点 2 个（:359/:420）
```
验收：42/48 → 42/48，**逐题 0 差异**（该路径在 Phase D 不可达）；证据形态为**设计一致性 + 2 条直接单元测试**（它如实声明，非指标）；回归 66 passed / 0 failed。
**captain 裁定取舍**：`held_scores` 存 `None` + 策略集中 `_UNKNOWN_RELEVANCE_VALUE`（数值保留 1.0）—— **关键是数据结构上可区分**。**补记账任务 t22 已建。**

**⚠️ 未完成 / 已作废**：

**t18 的冻结节被破坏 ⇒ 该次全量运行不可作为最终证据**
```
t18 冻结节记录        16:39:46
wiki_retrieval.py 改动 17:25:47   ← 运行开始后 46 分钟（engineer-rrf 的 §9）
⇒ 判据「运行期间无文件被改动」被违反
⇒ 该次运行跨越了两个修订；不中断（失败信息仍有线索价值），但不作为最终证据
```
**captain 承担协调失误**：我要求 t18 期间不得改代码，**却同时允许 §9 推进**。
**新要求（立即生效）**：**在最终冻结快照重跑完成之前，任何人不得再改仓库任何文件。**

**结构性教训**：**「要求冻结」不等于「冻结」** —— 本会话已第三次因并发改动使测量作废。
**唯一有效的是「断言」而非「要求」**：verifier 的做法（起止记录 mtime + 断言 `app.__file__` 落在快照内）是正确形态。
**⇒ 重跑时采用同一形态：跑在复制的快照上，而非活动树。**

**当前进度**：t18 约 **75%**（仍在跑）。


### ⚠️⚠️ t18 的污染是**实质性**的，不只是程序性（verifier 读码 diff 证实）2026-09-20

**verifier diff 了 17:25:47 那次改动**（`4E2D175B` → `E451D06D`，693→719 行，104 行 diff）。**四处实质改动**：
```
① 新增命名策略常量 _UNKNOWN_RELEVANCE_VALUE = 1.0
② held_scores[path] = candidate_scores.get(path)  —— 由「凭空给图扩展邻居页 1.0」改为**写 None**，
   使「未知相关性」与「真实分（含显式 0.0）」**在数据结构上可区分**；并新增 report["unknown_relevance"] 遥测
③ 新增 _held_value()，把**准入与置换统一到三因子价值** V = relevance × freshness × coverage
④ **displaced = min(candidates_to_displace, key=lambda path: _held_value(...))**
   —— **置换由「只看原始 score」改为「按三因子价值」**
   （原文注释：「此前这里只看原始 score，会出现『用 A 页的价值做准入决策，却踢掉 B 页』的不自洽」）
```

**⚠️ 为什么这比「运行期间有文件被改」严重得多**：
**t17 的任务书自己就写明**：
> 「**这会改变置换行为**，进而影响 `test_phase_c_query_node.py` 与 Phase D 的 `ninth_page` 场景（**依赖置换计数**）」
⇒ **这次改动直接落在 `replaced` / 置换计数 / `ninth_page` 这些断言上。**
⇒ **t18 不是「技术上不可引用」，而是「断言所依赖的行为在运行中途被改掉了」⇒ 结果本身不可信，必须重跑。**
**⇒ 该证据加强了 captain 的合并重跑决定。**

**verifier 独立复核的时间线**：`snapshot-t19` 冻结于 **16:40:44**，其中 `wiki_retrieval.py` = `4E2D175BB8620A5F`（mtime 16:05:34）；
活动树现为 `E451D06D78B6A9D9`（mtime **17:25:47**）⇒ **t18 运行窗口内该文件确实被改**。**captain 时间线成立。**

### ⚠️ verifier 主动登记：t19 的 `replaced` 与 `ninth_page_003` 归属已被 §9 取代 2026-09-20

**它的 t19 臂全部跑在 `snapshot-t19`（`4E2D175B`），即 §9 之前的置换规则。** 因此：
```
• replaced 三个数字（融合 31 / bm25 3 / semantic 0）是**旧置换规则的产物** ⇒ 台账若引用，须标注「§9 前」
• 它把 q_ninth_page_003 归因于 scorefix —— 该归因**对 §9 前修订成立**；
  §9 进一步把置换也统一到三因子 ⇒ **ninth_page 很可能再次变化** ⇒ 该归因**需在新快照上复验**
• 不受影响的：pass/fail 的**结论方向**（融合 44 > 语义 43 > bm25 42）
• 但严格说 reads（415/271/384）也依赖置换路径 ⇒ **§9 后应一并重测**
```
**它的建议（captain 采纳）**：**把「t19 三臂重测」并入 captain 计划的最终快照重跑**
（captain 原清单只有 t7 第 4 项 + t18）。**三项共用一次冻结，边际成本只有三臂的 ~25 分钟**，
**但能避免台账同时引用两个置换规则下的数字。**

**captain 决定：最终重跑包含三项**：
```
① t18 全量套件（scout，在复制快照上）
② t7 第 4 项复测（verifier，同一快照）
③ t19 三臂重测（verifier，同一快照）—— 给出 §9 后的 replaced/reads/ninth_page 新数字
```

### `confidence` 是「只写不读」字段 —— engineer-rrf 的评估与 captain 裁定 2026-09-20

**被评估的观察项**：`score=1.0` 硬编码（现行号 `:362`/`:423`，captain 引的 `:326`/`:391` 已移位）。
**engineer-rrf 结论**：`_confidence()` **不参与排序、不参与筛选、不参与阈值**，是**「只写不读」**。
**证据链（可复核）**：
```
1. _confidence()（compression.py:216-218）只在 build_evidence_envelope(:73) 被调用一次，存进 EvidenceEnvelope.confidence
2. **gate_evidence()（:79-97）根本不读它**：逻辑只有「evidence_rejection_reason 判拒绝」+「citation_id 去重」，
   **接受列表保持输入顺序** ⇒ 没有任何按 confidence 的排序/截断/阈值
3. **全 app/ 对 .confidence 的全量 grep 只命中构造点 compression.py:73** —— 没有任何读取点
4. 唯一引用它的测试是 test_retrieval_grounding.py:68（assert envelope.confidence == 0.91）—— 钉的是**计算式**，不是行为
5. 唯一按 result.score 排序的函数 _compress_memory_context_results(:254-296) **在 app/ 内没有调用者**
   （注释写明是 pre-fusion 兼容路径）⇒ 连原始 score 也不参与排序
```
⇒ **「全部并列 1.0 导致 wiki citation 无法区分」在当前代码里不会发生 —— 因为没有任何消费者按它排序或筛选。**
⇒ **对它相关性下限工作的影响：零。**

**captain 裁定：不改（现在）。** 采纳它的两条理由：
- **收益为零**：没有消费者 ⇒ 改了也测不出任何行为差异；
- **成本是跨模块契约变更**：`MemorySearchResult.score`（`models/memory.py:50`）；且 wiki citation 的 `activation_score` 为 `None`，
  改 `score` 会**同时改变 `_confidence` 的取值** ⇒ 一旦将来有人开始消费 `confidence`，行为会**静默变化**。
**它给出的正确顺序（若将来要改）**：先定义「wiki citation 的置信度该表达什么」，再决定用**新显式字段**承载，而不是复用 `score` 的既有语义。

**它登记的真正观察项（captain 认为更有价值）**：
> **`EvidenceEnvelope.confidence` 存在但无人使用。** 如果产品上打算用「证据置信度」做展示或动态截断，
> 那它现在处于**静默失真**状态：wiki citation 恒 1.0，其它来源按 `activation_score ?? score` clamp 到 [0,1]。
> **这条要么被消费、要么被删除，不要留着让人误以为它在起作用。**
**⇒ 归入本会话已识别的「静默失真」族**（shadow 恒 unknown、freshness 被打桩、默认值顶替条目）。


### engineer-rrf 收口报告（`E:\rrf_scratch\RRF-FINAL-REPORT.md`）—— 并再次更正 captain 引用的中期数据 2026-09-20

**⚠️ captain 引用的三条理由是它的中期数据，此后已被它自己的节点级实测推翻**：
| captain 引用的中期理由 | 现行事实 |
| --- | --- |
| 主判据 45/45 **饱和** | 饱和**只对最初的 45 题集**成立。scout t6 加入 `lexical_gap` 后是 **48 题**，基线 **45/48**，判别力已恢复 |
| 等权融合**输给语义单路** | 那是**探针代理指标**（页级 hit@8）的结论，它已明确更正为**错误**。节点级：**融合 47/48 > bm25 45/48 = 纯语义 45/48** |
| 换掉读集 ⇒ **零可测收益** | 读集变化属实（reads 271→418），但**通过率同时 45/48 → 47/48**，不是零收益 |
⇒ **按 captain 原本的准则（「融合必须优于纯 bm25 单路」+ Qdrant「beats either prefetch」），三条门槛现在都满足。**
**captain 采纳该更正，并承认引用了已被推翻的中期数据。**

**它再次拒绝写「RRF 融合未实施」（captain 已撤回该指令，此处再次确认）**：
> 当前状态是「**默认关闭 + 未接线**」⇒ **线上行为零变化** —— 这**既不等于「已合入」，也不等于「未实施」**。
> 写成「未实施」会与代码和证据相反，正是你反复禁止的那类自述。
> **你要我删掉这段代码，一句话，我 15 分钟内退干净**（有完整备份与一键复现脚本）。在你说之前我不擅自删 —— **因为删它的理由（三条）已被数据推翻。**

**报告四项内容**：

**(a) 双路排名质量表（两版题集都有）**：
| 通道 | found | MRR | mean rank | hit@1 | hit@8 |
| --- | --- | --- | --- | --- | --- |
| bm25（48 题） | 36 | 0.4792 | 2.028 | 15 | 36 |
| **语义单路** | **42** | **0.5833** | **1.905** | **18** | **42** |
| 等权 RRF 融合 | 42 | 0.5138 | 2.857 | 16 | 39 |
**结论**：语义腿本身有真实价值（能召到词法完全召不到的页）；**等权 RRF 是较弱组合器**（赢了 bm25、输给语义单路，因为 k=60 时贡献近似平坦）；唯一能同时赢两路的是向量加权（w_vec≥3），**但那是同一题集上调参，不构成依据**。

**⚠️ captain 记录一处诚实的张力**：**排名指标上语义单路（MRR 0.5833）优于融合（0.5138）**，而**节点级 pass 上融合（47）优于语义（45）**。
两者是**不同判据**；captain 设定的验收准则是**节点级 pass**（因为 Phase D 的 golden 是多引用、要求 recall=1.0，排名指标不建模该条件）。**但该张力应如实记录，不得只报对融合有利的那一个。**

**(b) 语义腿成本与前置条件**（写成「未来选项 + 前置条件 + 影响面」，**不是待办**）：
```
实测 ≈ +0.6s/查询（14 页/43 块：库读+解析 50ms、嵌入 550ms、余弦 8ms），随规模线性增长
**硬约束：wiki_body_fts.content 是 _bigram_cjk 变换后文本，不能直接嵌入**
生产化需新迁移 + 发布期嵌入，要动 projections.py/publication.py/generations.py 与写路径（均在其所有权外）
并需三个决策：嵌入器来源 / 嵌入不可用时跳过还是阻止发布 / 重建触发条件
```

**(c) 「45 题判据饱和」发现**：饱和**只对最初 45 题集**成立（改动前实测 45/45）。
**影响**：饱和 ⇒ **任何排序改动都不可能优于单路，只能持平或下降 ⇒ 该题集上任何检索改进都无法被验证**。
**后续前提（captain 采纳为纪律）**：**任何新检索改动，先确认题集在改动前不是满分。**

**(d) 四套回归（干净基线证据）**：
| 时点 | 套件 | 结果 |
| --- | --- | --- |
| **改动前干净基线** | 4 套 | **47 passed**（557s） |
| 融合落地后 | 7 套 | 64 passed |
| 截断回退后 | 7 套 | 63 passed |
| **§9 修正后** | 7 套 | **66 passed**（671s） |

**它回答 captain 的问题（§9 是否也改变首轮读集）—— 已实测：不会**：
当前题集指纹 `ebdf7c1351b93585`，48 题：§9 前 42/48、reads 271、replaced 3 → §9 后**完全相同，逐题 0 差异**。
⇒ 三条修正（`:321` 凭空 1.0、`:405` 三因子、4 处 `or 1.0`）**不改变首轮读集、不改变通过率**；证据是**设计一致性 + 单元测试**。

**captain 裁定**：
```
① 融合代码：**保留**（默认关闭、未接线）。**不删** —— 删除的理由已被数据推翻。
② 生产接线：**不接**（确认其建议）—— 先做发布期向量投影把成本摊到写入侧。
③ t21：门控在 t18/t19 是正确的；最终快照重跑（t23→t24→t25）收口后解锁。
```


### t18 跑完：`1 failed, 1700 passed, 10 skipped`（86 分钟）—— 唯一失败是**负载诱导的计时 flake** 2026-09-20

**原始结果**：
```
1 failed, 1700 passed, 10 skipped, 2 warnings in 5180.77s (1:26:20)
FAILED apps\backend\tests\test_audit_logs.py::test_due_reminder_trigger_writes_scheduler_audit_log
```

**captain 的归因过程（不预设结论）**：
```
第一步：单文件隔离复现 → **仍然失败**（1 failed, 6 passed）
  ⇒ **不是顺序依赖**（captain 先前把它记为顺序依赖，那是**不精确的**）
第二步：读测试代码 → **发现它是计时敏感的**：
  remind_at = now + timedelta(milliseconds=120)      ← 只提前 120ms
  deadline  = time.monotonic() + 2.0                 ← 只轮询 2 秒
  while ...: rows = audit_rows(client); if 有 reminder.triggered: break; sleep(0.05)
  assert trigger_rows                                ← 2 秒内没触发就失败
第三步：在较轻负载下重跑 → **7 passed**（67.83s）
```
**⇒ 结论：该失败是「重负载下调度器未能在 2 秒内触发」的计时 flake，不是回归、不是顺序依赖。**
（当时刚跑完 86 分钟全量套件，且系统上仍有 8 个 python 进程。）

**⚠️ captain 更正自己的记录**：本会话早前我曾把该测试的失败记为「顺序依赖」——**那是错误归因**。
**真实机制是「计时敏感 + 负载」**：单文件隔离也失败（排除顺序），轻载重跑通过（确认是负载）。

**captain 登记的测试套件风险**：
> `test_due_reminder_trigger_writes_scheduler_audit_log` 用 **120ms 提前量 + 2.0s 轮询窗口**，
> **在任何负载较高的环境（CI、并发运行）都可能随机失败**。这不是产品缺陷，但是**测试可靠性缺陷**。
> **⇒ 记录为已知边界；将来若做 CI 稳定性工作，应优先看它**（放宽窗口或改成确定性触发）。

**t18 结果的双重性质（captain 如实说明）**：
```
• 作为「最终证据」：**不可用** —— 冻结节在运行第 46 分钟被破坏（§9 改了置换规则，直接落在 replaced/ninth_page 断言上）
• 作为「线索」：**有信息量** —— 1700 passed / 1 flaky failure / 10 skipped；
  且该失败在 12% 处出现（约运行第 10 分钟，**早于 17:25:47 的改动**）⇒ **与 §9 无关**
```


### t18 报告（scout）—— 并更正 captain 的失败归因 2026-09-20

**完整结果行**：`1 failed, 1700 passed, 10 skipped, 2 warnings in 5180.77s (1:26:20)`

**scout 的四次观测（同树）**：
| # | 运行 | 结果 |
| --- | --- | --- |
| 1 | 全量套件 | **FAILED** |
| 2 | 单文件 `-q -rf` | **FAILED**（100.79s） |
| 3 | 单测 + `-s -o log_cli=true` | **PASSED**（14.66s） |
| 4 | 单文件重复 | **FAILED**（68.24s） |
⇒ **同树 3 失败 / 1 通过 ⇒ 非确定性（flaky）确认。**

**⚠️ captain 更正自己的归因（第二次）**：
- captain 先说「顺序依赖」→ **错**（单文件隔离仍失败，scout 已排除）；
- captain 后说「120ms 提前量 + 2s 轮询窗口」→ **不精确**：
  **scout 定位到真正的失败点是 POST `/api/tasks` 返回 500**（不是轮询断言）。
**⇒ 正确表述：「`test_audit_logs` 的该用例是 flaky；失败点是 POST `/api/tasks` 返回 500，与调度器时序相关，非本轮引入。」**
**captain 的两次归因都不精确，scout 的四次观测 + 失败点定位才是准的。**

**非本轮引入的证据**：`app/api/tasks.py` mtime **2026-08-10**、相对 HEAD **干净**；`app/services/tasks.py` mtime **2026-09-14**。

**⚠️ scout 对第 4 问的诚实回答（captain 采纳其更精确的表述）**：
```
TREE_SHA256 BEFORE = 07ec30ae...   AFTER = 0acfacfd...   TREE_IDENTICAL = False
差异仅 1 个文件：app/agents/nodes/wiki_retrieval.py
  08:05:34Z 4e2d175b... -> 09:25:47Z e451d06d...   (246+/34-)
```
**它的技术减轻论述（比 captain 的「污染」判断更精确）**：
> **Python 在 collection 阶段导入并缓存模块**，运行中改文件**不改变已加载模块** ⇒ 就**已加载代码**而言本次运行**内部一致**；
> **但不可从当前树复现**。
> ⇒ **可作为「08:05:34Z 修订版」的证据，不能作为「当前树」的证据。**
> （若测试用 subprocess/reload 则不受此保护，我未逐一排查。）
**⇒ captain 采纳该表述，取代自己较粗的「不可作为最终证据」。**
**⇒ 这同时也说明：captain 之前说「断言所依赖的行为在运行中途被改掉了」是**过强**的 —— 已加载模块不变。**
（但 scout 自己也标注了未逐一排查 subprocess/reload 场景。）

**冻结节**：`HEAD=3c4f46d`｜脏文件 54｜源文件 448｜`TREE_SHA256=07ec30ae...`；captain 点名的 14 个文件 mtime+SHA256 见报告 §3.1。
**t17 纯文档已确认** ✅（源文件改动止于 08:08:25Z，此后 31 分钟无变动；产物为 docs）。

**scout 的纪律（captain 特别肯定）**：
> **零仓库写入**；失败**如实报告**，**未**重跑至通过来掩盖（4 次观测全列，含那 1 次通过）。
**⇒ 「列出那 1 次通过」正是关键 —— 若只报失败，会掩盖它是 flaky；若只报通过，会掩盖它不稳定。**

**captain 对 scout 三问的回答**：
```
① 接受本次为「08:05:34Z 修订版」的证据？ → **接受**（附其技术减轻说明与「未排查 subprocess/reload」的边界）
② 是否在当前稳定树上重跑全量？ → **是**，即已建的 t25（门控 t23→t24）
③ test_audit_logs flaky 是否另立任务？ → **是**，captain 另建
```


### 🔑 engineer-rrf 的关键发现：**融合在原 45 题上零增益**，在唯一有增益的 3 题上**不如纯语义单路** 2026-09-20

**分组数据（`E:\rrf_scratch\split45.py` 可复现）**：
| 臂 | 原 45 题 | 新 3 题（lexical_gap） |
| --- | --- | --- |
| bm25 | **45/45** | 0/3 |
| **融合** | **45/45** | **2/3** |
| 纯语义 | 42/45 | **3/3** |

⇒ **融合的全部增益（+2）都来自新 3 题**；**在原 45 题上它与 bm25 逐题相同**
（与 scout 的判别力诊断完全一致：原 45 题 golden 恒在 bm25 前 4 位 ⇒ **任何排序改动都是 no-op**）。
⇒ **而在唯一有增益的那 3 题上，纯语义单路（3/3）反而优于融合（2/3）。**
⇒ **结论：融合既没有在原题集上可测的增益，又在新增题上不如单路，叠加 +171% 延迟**
⇒ **记录结论、不落生产路径**（当前默认关闭/未接线即符合）。

**captain 评价**：**这条比「成本高」强得多** —— 它说明**即便成本为零，融合也没有可测增益**。
**⇒ 「不接线」的裁定依据由「成本」升级为「无增益 + 有代价」。**

**截断对比（原 45 题，指纹 `36581ff0ccddb9e3`）**：
| 下限 ratio | 原 45 通过 | 读取页数 | 被截断候选数 | 失败题 |
| --- | --- | --- | --- | --- |
| 无（改动前 baseline） | **45/45** | 261 | 0 | — |
| 无（仅修 `or 1.0`） | **45/45** | 261 | 0 | — |
| 0.05 | 45/45 | 261 | 0 | — |
| 0.1 | 45/45 | 254 | 7 | — |
| 0.2 | 45/45 | 203 | 58 | — |
| **0.3** | **43/45 ↓** | 172 | 88 | two_hop_001/003 |
| **0.4（预注册）** | **43/45 ↓** | 161 | 99 | two_hop_001/003 |
⇒ 口径 1（原 45 题通过率不得下降）：**0.4 不通过 ⇒ 截断已回退**（早于该口径就已回退）。
⇒ 口径 3：0.4 下 reads 261→161（−38%）、截断 99 个候选（27 题触发）；0.2 下 reads 261→203（−22%）、截断 58 个。

**新 3 题单独列（与 t3 无关，且恒 0/3）**：
```
bm25 单路   0/3   rank_bm25=None，golden 页根本不在词法候选里
截断(各ratio) 0/3  **截断只能移除候选，不能新增**（captain 与 scout 的判断成立）
融合        2/3   语义腿把不存在的候选**变出来**
纯语义单路   3/3   同上，且比融合更好
```

**五套套件**：`wiki_query_node / phase_c_query_node / wiki_shadow_runtime / phase_d_eval_driver / wiki_gate`（+2 套新增）→ **66 passed / 0 failed**（671s）。

### t24 与 t20 的排序：captain 决定**让 t24 跑完**（它成为 L1 的「前」测量）2026-09-20

**情况**：captain 裁定顺序为 `t20 → 冻结 → t24 → t25`，但 **t24 已在 scout 的快照上启动**（`claimed@engineer-a4` 的 t20 刚开工）。
**captain 权衡后决定不中断 t24**，理由：
```
• t24 = t7 第 4 项 + t19 三臂。其中 t7 第 4 项**不受判据变更影响**，本就有效；
• t19 三臂的数字将成为 **「**（标签已更正，见下）**」** 的有效测量 —— 而 **t20 的验收正需要「L1 前后对比」**；
• ⇒ **t24 不是白跑，它是 L1 的「前」基线**；中断反而丢失该基线并增加协调开销。
```
**⇒ 记录：t24 的数字标注为「**（标签已更正，见下）**」；t20 落地后重新冻结并重跑 t24/t25 得「L1 后」数字。**

**captain 澄清一处任务编号混淆**：engineer-rrf 说「t10（语义腿）等你派」——
**t10 是「双重入场实测」，已由 engineer-a4 完成**；**语义腿/向量索引是 t21**，门控在 t24/t25 之后。


### 第七条团队规则：冻结的交付物必须是「副本」，指纹只能作辅助校验（verifier 提出，captain 采纳）2026-09-20

**verifier 的协调层发现**：
> **t23 交付的不是「快照副本」，而是「指纹 + 脚本」** —— scout 做的是 `TREE_SHA256` 单值指纹（`t18_freeze.ps1` / `t18_freeze_final.txt`），
> **没有创建 `snapshot-final` 目录**，其输出还写着「运行前后各取一次 `TREE_SHA256`，相等即证明可采信」
> ⇒ **即预期 t24/t25 跑在活动树上**。
> 而 captain 给 t24 的任务书写的是「**跑在 scout 的 t23 快照上…不是活动树**」。
> ⇒ **两者是不同的安全性质：指纹是「事后可检测」，副本是「免疫」。**
> **t18 的教训恰恰说明「检测」不够 —— 你发现它被改时，那次运行已经废了。**

**captain 确认这是 captain 的任务书不一致造成的**（t23 写「复制到 snapshot-final」，t24 写「跑在快照上」，而 scout 只做了指纹）。
**⇒ 第七条团队规则**：
```
冻结的交付物必须是「副本」；指纹只能作为辅助校验。
理由：指纹是事后可检测，副本是免疫 —— 而「检测到被改」时运行已经作废。
```
**verifier 的做法（既按任务书创建副本，又把指纹当独立校验用）被采纳为规范** —— **两种方法互补**：副本提供免疫，指纹提供「树是否静止」的独立证据。

**本会话固化的团队纪律至此七条**：
```
1 插入者：有义务广播位移量（治因）
2 广播者：必须声明基期（防误用）
3 引用者：写「符号名 + 行号(捕获时刻)」（可反查）
4 验证者：声明其引用取自哪个窗口（可追溯）
5 订正者：一律 grep 实测，不做偏移量算术（不赌）
6 重负载：跑 >5 分钟前检查是否有并发重任务（不污染）
7 冻结交付物必须是副本，指纹只作辅助校验（免疫优于检测）
```

### t24 阻断：冻结第三次被破坏 —— verifier 主动停下（captain 裁定路线 B）2026-09-20

**指纹演进（verifier 用 scout 的 `t18_freeze.ps1` 实测）**：
```
18:22:41  0acfacfd…   t23 认证基线
18:32:06  0acfacfd…   verifier 复制快照前
18:32:10  0acfacfd…   snapshot-final 创建（复制后复测相同 ⇒ 忠实冻结）
18:36:22  fffd9779…   phase_d_eval.py 被改（engineer-a4 的 L1）
18:39:02  6c52aacc…   又改了一次，仍在动
```

**⚠️ 为什么这次不能「照跑」—— 改动是判据级的**：
```diff
-        return recall > 0.0
+        return recall > 0.0 and coverage > 0.0
```
**这正是 `q_raw_updated_001/002/003`（`action=degrade`）所用判据** —— 也就是 verifier 在 t19 归因里
「三臂各丢 3 题、45→42 是判据纠正」的那 3 道题。**新判据加了 `coverage > 0.0` ⇒ 这 3 题可能再次翻转。**
同时新增「方案 E」的 `exercised`/`absence_reason` + `_GoldenPathProbe`。
⇒ **现在跑得到的是一份「在写入前就已过期」的数据集 —— 本会话已发生两次的那种失败。**

**verifier 的判断与做法（captain 认可）**：**停下不跑，先问，不烧那 30 分钟。**
**它已完成零浪费的部分**：`snapshot-final` 已建（内容 = t23 认证基线，复制前后指纹相同 ⇒ 忠实冻结）；逐文件 SHA256/mtime 已记录；预检全过（含 `last_search_mode` 三态实测）。

**captain 裁定：路线 B**（等 `phase_d_eval.py` 改完 → 重新复制快照 → 再跑）。
**理由**：**L1 修复直接改的就是 t24 要报的那 3 道题** ⇒ 跑 A 得到的数字与最终判据不一致，且 `q_raw_updated_*` 的归属无法在同一判据下复验。
**已通知 engineer-a4 收口并报告落盘时刻；它一确认即通知 verifier 重新冻结。**


### 流水线实况（captain，18:46）2026-09-20

```
t20（engineer-a4：E 检测器 + L1）  claimed
  phase_d_eval.py mtime 18:37:27，已稳定 9 分钟 ⇒ L1 已落盘，应在跑验收
  probe_t20_detector.py 18:38:39（E 检测器的探针）

t27（scout：物理副本 + 清单）  pending，依赖 t20
  **t27_snapshot.ps1 已于 18:46:11 创建** ⇒ scout 正在准备（等 t20 解锁）

t24（verifier）  in_progress —— 保持持有、不跑、不加负载
  t18_freeze_t24_a2 / now2 / check / stab1 / stab2 陆续产出
  ⇒ **verifier 在持续监测树是否静止**（stab1 18:44:31、stab2 18:46:01）
```

**⇒ 两个成员都在主动监测冻结状态，而不是被动等待。** 这正是本会话形成的纪律在起作用。

**captain 本轮无动作**（不跑测试、不改代码）—— t20 是关键路径，等它收口即可。


### 第七条规则的精确化（scout 补充，captain 采纳）2026-09-20

**captain 的原规则**：「冻结的交付物必须是『副本』；指纹只能作为辅助校验。」
**scout 的精确化**：
> **两者职责不同，不可互相替代** ——
> - **副本**：**免疫**漂移（事后不需要检测，因为源已不参与）；
> - **指纹**：**事后可检测**，且能覆盖**副本未纳入的范围**（例如 `docs/`、`apps/desktop/`、仓库外依赖）。
**⇒ captain 采纳：不是「副本取代指纹」，而是「副本为主、指纹补盲区」。**
**⇒ scout 的 t27 会两者都做**：物理副本 + 逐文件哈希清单，并在清单里加一段**「副本内同名文件与源是否一致」的校验行**（`COPY_MATCH=True/False`）
   ⇒ **verifier 可以直接信任副本，不必再自己比对。**

### scout 的 t27 脚本已就绪（仓库外，未执行）2026-09-20

`E:\a 工作\wiki-audit\t27_snapshot.ps1`，四步全含：
```
1. **确认静止**：两次指纹间隔 20 秒，**不等则 ABORT 并退出码 2**
   ⇒ **不建一份出生即过时的副本**（这正是本会话三次作废的教训被写进了脚本）
2. **物理复制**：robocopy /E 排除 .git/.venv/node_modules/.tmp/output/__pycache__/.pytest_cache/.ruff_cache/dist/*.pyc
3. **逐文件哈希 + mtime**：15 个点名文件（**已含 compression.py**，补上 t23 的缺口）
4. **产出 t27_snapshot_manifest.txt**：含 HEAD、git status 计数与全文、TREE_SHA256、点名文件哈希、**以及副本一致性校验行**
```

**scout 对门控的评价（captain 采纳）**：
> **这个 `dependencies=["t20"]` 是结构性修复** —— 它不靠「记得别改」，而是**让冻结任务在物理上排在改动任务之后**。
> **我认同这比纪律更可靠。**
**⇒ 这正是 engineer-a4 那条「删掉裁量点，而不是要求更自觉」在任务编排层面的应用。**

**scout 对 t23 三处差距的定性（captain 采纳）**：它记为「**规格不一致**」而非任何一方的失误 ——
t23 写「复制」、t24 写「跑在快照上」、t24 又要求 verifier 自建副本。**captain 接受该定性。**


### captain 独立读码核验 t20 的两处实现（零负载）2026-09-20

**① L1 修复（`phase_d_eval.py:38-62`）—— 实现正确，且取值理由充分**：
```python
def _passed_for_action(golden, coverage: float, recall: float, cited_paths) -> bool:
    # L1 修复:原先只判 recall > 0.0,把**已算出、已传入**的 coverage 整个丢掉。
    #   - 「至少取到相关证据」= recall > 0.0(原有);
    #   - 「证据须支持预期结论」= coverage > 0.0(原先缺失)。
    # 取 coverage > 0.0 而非 == 1.0:degrade 的语义本就是**覆盖不足**,
    return recall > 0.0 and coverage > 0.0
```
**captain 评价**：**它选择了 `coverage > 0.0` 而非 `== 1.0`，并在注释里写明理由** ——
「`degrade` 的语义本就是**覆盖不足**」⇒ 若要求完全覆盖，就把 `degrade` 变成了 `answer`。**这个区分是对的。**
（`degrade` = 「有证据但不足以断言当前」；要求 coverage=1.0 会与 `answer` 档重复。）

**② 方案 E（`exercised` + `absence_reason`）—— 实现符合 captain 的三条治理规则**：
```
:90   exercised: bool = True
:93   absence_reason: str = ""
:274  exercised, absence_reason = probe.classify()
:364  not_exercised = [...]                    ← 逐条列出（规则①：不得只报总数）
:369  "absence_reason": outcome.absence_reason ← 诊断标签保留（规则③：标记同时登记为什么）
:374-381 exercised_totals: new_exercised / new_exercised_pass / old_exercised / old_exercised_pass
:420-432 报告渲染「未考到题数」+「考到且通过 X/Y」+ 逐条 absence_reason
```
**⇒ 三条治理规则（逐条列题号与原因 / 单调性 / 不得用 exercised=false 关闭缺陷）的前两条在代码里可见；第三条靠 ② 不误标断言验收。**

**captain 本轮只做读码核验，未跑任何测试、未改任何代码**（避免与 engineer-a4 的验收测试竞争资源）。
**`phase_d_eval.py` mtime 18:37:27，截至 18:49 已稳定 12 分钟 ⇒ 改动已落盘。**


### engineer-rrf 主动设防：区分「设计认可」与「验收通过」（captain 采纳）2026-09-20

**它的设防**：
> **你第 2 条认可的是我 t12 的「设计」，而你第 5 条的口径正是它没通过的那条 —— 截断已按准则回退，这是正确终态。请勿据此要求重新落地。**
> 若你要重新落地，请明确这是**新指令**并接受 43/45，或给出放宽后的口径 —— **我不会自行放宽**。
**⇒ captain 明确确认：不要求重新落地截断；回退是正确终态；不放宽口径、不接受 43/45。**
**它的原则表述（captain 采纳）**：**「设计对 ≠ 该参数下通过验收」**。

**captain 评价**：**它在收到可能被误读的消息时主动设防，并要求「若要改变请明确下新指令」——**
**这比默认服从更安全**：默认服从会让「设计认可」被误当成「重新落地」的授权。

**它 §3 的测量时刻论证（captain 采纳）**：
```
截断曲线：指纹 36581ff0ccddb9e3（t6 加 lexical_gap 后、t11 判据修正前）
§9 数据：  指纹 ebdf7c1351b93585（t11 之后）
t11 的影响：raw_updated 三题 action stale→degrade ⇒ 三臂一致地由通过转失败，冻结版基线 45/48→42/48
  ⇒ **该变化是臂无关的，不改变任何臂间比较**
截断结论是否被 t11 翻转？**不会**：① 截断的失败机理是 two_hop 第二跳页被截，t11 只动 raw_updated；
  ② 用修正版代理在冻结版上复核：ratio 0.3/0.4 恰好截掉 q_two_hop_001/003 的 Product-P.md，0.2 为 0/36，与节点级实测一致
⇒ 两个结论各自在同一题集版本内自洽，跨版本方向一致 ⇒ **未受 t11 干扰**
```


### 收口进度（captain，18:56）2026-09-20

```
t20（engineer-a4：E + L1）  claimed —— **验收测试运行中**（python CPU 40.7s）；phase_d_eval.py 稳定 19 分钟
t21（engineer-rrf：向量索引）  in_progress —— **方案就绪，实现待闸**（captain 已下实现闸）
t24（verifier）              in_progress —— 持有等待（已记录 before/after/recheck/afterruns 四次指纹）
t25（scout：全量套件）        pending，依赖 t24
t27（scout：物理副本）        pending，依赖 t20
t26（engineer-a4：flaky）     pending，依赖 t25
```

**关键路径**：**t20 的验收测试** → t27（副本）→ t24（t7第4项 + t19三臂，L1 后）→ t25（全量）→ t21/t26。

**captain 本轮无动作**（不跑测试、不改代码）—— 避免与 t20 的验收竞争资源。


### engineer-rrf 明确确认：**未触及 t7 第 4 项的构造点** —— t12 验收项闭合 2026-09-20

**背景**：captain 在 t12 验收里要求「若你的改动触及 `retrieval.py`/`wiki_retrieval.py` 的构造点（尤其补 `source_type`/`content_category`），**必须报告**；**若未触及也请明确确认**」—— 它现在明确确认。

**逐条证据（可复核）**：
```
① app/services/retrieval.py —— **本会话无人改动**
   worktree SHA256 = HEAD SHA256 = 000F0F4F9542D991001746773CF846F59ABD5583D842AEAF45E128F3787186EA（逐字节相同）
   既不在开工前基线 patch 里，也不在 git status 里 ⇒ 与 HEAD 完全一致
   （captain 划给它所有权，但它一次都没用上 —— t3 走方案 A，不动主融合链）

② app/agents/nodes/wiki_retrieval.py —— 构造点**未被修改**
   对着开工前基线复算，改动共 53 行新增，其中：
     MemorySearchResult( 命中 0 处；source_type 命中 0 处；content_category 命中 0 处
     diff 里 MemorySearchResult( 只以**上下文行**出现 2 次 ⇒ **两个构造点本身逐字未动**
   它们至今**不设置** content_category / source_type（保持 None）—— 正是 verifier 观察到的「0 条带这两个字段」

③ app/services/wiki/snapshot_reader.py —— 同样 0 处命中
   161 行新增中 source_type / content_category / MemorySearchResult 全为 0
   该模块只构造自己的 WikiPageCandidate（frozen dataclass），**根本不构造 MemorySearchResult**
```

**它给出的更强一层保证（captain 采纳，建议 verifier 采纳）**：
> t7 第 4 项依赖**证据门输入面**。即使不看构造点，也可以直接检查输入面是否变化 ——
> **默认路径（不注入嵌入器）在两版题集上与改动前逐题 0 差异**
> （passed / recall / precision / coverage / reads / replaced / stop_reason / cited **全等**）
> ⇒ **citation 集合完全一致 ⇒ t7 第 4 项的输入面不变**。
> （`36581ff0ccddb9e3` 的 45 道共有题、`ebdf7c1351b93585` 的全部 48 题，都验过。）
**⇒ 这比「构造点未改」更强**：它直接证明**输入面**不变，而不只是「改的地方不在构造点」。

**⚠️ 唯一例外（需 verifier 记一笔，但不是现在）**：
> **融合臂**会改变首轮读集与置换计数（reads 271→415、replaced 3→31）。
> 但**融合默认关闭且未接线生产**（`factory` 未改）⇒ 不在生产路径上。
> ⇒ **若将来接线融合，t7 第 4 项必须重测；当前不需要。**
**⇒ captain 登记为将来条件**（与 t21「若实现后三臂数字变化必须报告并归因」同一性质）。

**captain 记录：t12 的验收项就此闭合**（未触及构造点，已明确确认 + 三条独立证据 + 一层更强保证）。
**且 verifier 已在 `snapshot-t19` 上独立重跑 t7 第 4 项并得「与 t14 一致」** ⇒ **双向确认。**


### 进度（captain，19:00）2026-09-20

```
t20（engineer-a4：E + L1）  claimed —— 验收测试运行中；phase_d_eval.py 稳定 23 分钟
t21（engineer-rrf）          方案就绪 + 三项决策与授权已下；**实现待闸**（等 t25）
t24（verifier）              持有等待（不跑、不加负载）
t25（scout）· t26 · t27      排队（依赖门控）
```
**captain 本轮无动作** —— t20 是关键路径，且其验收测试正在跑，不与其竞争资源。


### 终裁：**截断不重新落地** + 一处准则缺陷更正 + 一个新的失效类 2026-09-20

**captain 终裁**：
```
**动态截断不重新落地。** 维持回退（0 残留）作为终态。
不需要指定题集版本 / 单列 raw_updated / 选作用面方案 ——
**理由（captain 已按 engineer-rrf 的请求更正措辞）**：
```
原措辞「在「首轮窗口」这一层上，不存在可接受的方案」**过强**，已更正为：
**「~~有可测收益（次要指标）~~ + 门槛属同集调参 ⇒ 维持回退」**
  **⚠️ 其中「可测收益」已被 engineer-rrf 本人撤回（见「分母效应」更正）**
```
**为什么要改（engineer-rrf 的理由，captain 采纳）**：
> 按原措辞，将来重做这条线的人会读到「不存在可接受的方案」= **此路已死**；
> 而实际是「**收益与代价在不同 ratio 上分岔，门槛需在留出集上定**」——
> **这条线是可续的，只是现在缺证据。**
**补充数据（engineer-rrf 主动交出，支持其被回退的改动）**：
```
原 45 题，bm25 单路      通过      reads   平均 citation precision
  无截断                45/45     261     0.2541
  截断 0.2              45/45     203     0.3315（+30% 相对，**通过率不变**）
  截断 0.3 / 0.4        43/45 ↓   172/161 0.3776 / 0.3906
⇒ ~~下限在「减少弱相关页占用注入面」上有可测收益（次要指标）~~
  **⚠️ 已撤回：该「收益」经分子/分母分解证明为分母效应（分子 Σgolden命中 恒为 46，分母 Σcited 261→203）⇒ 不构成收益。**
```
**作用面层面的三条仍成立**（(1) 等价不做 / (2) 时序不可实现 / (3) 同集调参）。
```

**engineer-rrf 对 captain 三条修法方向的技术评估（captain 全部采纳）**：
| 方向 | 评估 |
| --- | --- |
| **(2) 对链接目标豁免** | **不可实现**：下限作用在候选准入（首轮 `pending`）时，节点**还不知道谁是链接目标** —— 邻居是 `read_page` 返回 `page.links`/`page.backlinks` **读完之后**才发现的（`wiki_retrieval.py:327-329`）；**要豁免就得先读，正好抵消截断目的** |
| **(1) 下限只作用于置换** | **等价于不做**：首轮窗口保持原 `max_pages` ⇒ 下限**没有作用面**；置换本就已由三因子价值函数决定 |
| **(3) ratio 0.2** | **属同集调参，不构成依据**（与「`q_lexical_gap_003` 不调权」同一把尺子） |

**⇒ 结论**：**在「首轮窗口」这一层上，`two_hop` 与「截断弱相关页」直接冲突**（第二跳页在词法上弱相关、却是唯一入口）。
要共存只能改**作用面**（如把下限挪到「读完之后、用真实链接关系判断」的第二阶段），**那已不是 t12 的范围**。

**⚠️ captain 的验收准则有版本歧义（engineer-rrf 指出，captain 采纳）**：
```
冻结题集上「原 45 题」的上限是 **42/45**（三臂一致失败 raw_updated ×3）⇒ **任何配置都到不了 45**。
⇒ 准则 1 更正：**在「raw_updated 三题可判」的题集版本上**判（即 36581ff0ccddb9e3），或把这三题单列。
engineer-rrf 实际执行的是前者（45/45 → 43/45 ⇒ 回退）—— **执行正确。**
```

### 新失效类：「在错误的时间点假设信息已存在」（scout 识别，captain 采纳入台账）2026-09-20

**scout 的自我更正**：它先前把 two_hop 回归归因为「t3 引入」——**实际是 t12（动态截断）**。
**它的错误自述**：
> 我错在：看到「engineer-rrf 的改动」就归到他正在做的 t3，而**没核对那段 diff 的注释说了什么**
> （注释明确写「首轮窗口」，即 t12）。**注释就在 diff 里，我读了却没用来做归属。**

**它接受 engineer-rrf 对其补救方案（对链接目标豁免）的技术更正后，识别出的新失效类**：
> **我检查了下限「做什么」，但没检查它相对「信息何时可用」的执行位置。**
> ⇒ 这是与已记录的各失效类**都不同**的一种：
> 不是「代理指标不全」（engineer-rrf 的教训），不是「基期错配」（引用纪律的教训），
> 而是 **「在错误的时间点假设信息已存在」**。
**⇒ captain 采纳入台账 —— 这是本会话记录的第四类失效模式。**

**本会话已识别的失效类汇总**：
```
1. 默认值悄悄顶替了本该存在的条目（engineer-a4，三类，修法方向相反）
2. 代理指标不覆盖判据的全部条件（engineer-rrf，两次：页级 hit@8、最佳 golden 而非任一）
3. 基期错配（scout：HEAD 相对 vs 捕获时相对）
4. **在错误的时间点假设信息已存在**（scout：补救方案的可行性取决于能否在信息可得的阶段实施）
```

**scout 对 t22 的建议（captain 采纳）**：**「要么证明新增下限比既有价值预检多做了什么，要么不做」** ——
因为「下限只作用于置换」≈ 既有价值预检 ⇒ **新增下限可能无独立价值，应要求它证明多做了什么。**


### engineer-rrf 对 captain 修法 (2) 的**实证反驳**：语料里根本没有「链接目标」2026-09-20

**captain 倾向的修法 (2)「对链接目标豁免」—— engineer-rrf 做了实证检验，结论：救不了这两题**：
```
SELECT source_path, target_path FROM wiki_generation_links WHERE vault_id=? AND generation=?
→ 边数 = 0
→ 作为 target 出现的页 = []（空集）
→ Wiki/Sources/Product-P.md 是链接目标? False
⇒ 在这个语料里根本没有「链接目标」⇒ **豁免链接目标 = 豁免空集** ⇒ Product-P.md 照样被截
```

**两条独立理由都指向同一结论（它给出）**：
```
① 下限作用在首轮准入时，节点**还不知道**谁是链接目标 —— 邻居要 read_page 之后才从 page.links 发现；
② **更根本的是：本语料的 two_hop 不是靠图扩展满足的**，而是靠「两页都在候选里」⇒ **链接图是空的**。
```
**⇒ 这比单靠「时序」论证更强** —— 即便时序不是问题，豁免也救不了（空集）。

**captain 记录：我的修法方向 (2) 被实证否定，而非仅被时序论证否定。**
**⇒ 终裁不变：截断不重新落地。**

**engineer-rrf 的当前修订定向探针（与 captain 同方法）**：
```
q_two_hop_001  passed=True  recall=1.000  reads=8  cited=8 页
q_two_hop_002  passed=True  recall=1.000  reads=8
q_two_hop_003  passed=True  recall=1.000  reads=3
⇒ 回归确认恢复；验收 2（two_hop 恢复）✅、验收 3（reads 不掉到 1）✅
与 captain 探针的差异**只在修订版**：captain 的窗口是「wiki_retrieval.py 自 15:23:34 起 30 分钟未变」——
  那正是**实现截断、尚未回退**的窗口；回退发生在之后。
```

**captain 对验收 1 口径的回答（重发，此前消息交叉）**：
```
(a) 用哪个题集版本判定：**在 36581ff0ccddb9e3（t11 之前）上判**，或把 raw_updated ×3 单列。
    engineer-rrf 实际执行的是前者（45/45 → 43/45 ⇒ 回退）—— **执行正确。**
(b) 是否把 raw_updated ×3 单列给 scout 判定：**是，但它已有定论，不必再派**：
    根因 = **L2 语料缺陷 + L3 产品能力缺口**（该变体改了来源原始内容但不同步 source_hash
    ⇒ publication.py:60-61 抛 wiki_publication_root_changed ⇒ 该页被系统自身完整性校验拒绝，任何检索器都取不到）。
    **已由 t17（提案）与 t20（L1/E 实现）承接。**
```


### engineer-rrf 的将来重做前提（captain 记入台账）2026-09-20

**它给出的可操作落点**：
> `path_freshness` 是在**准入循环里**由 `_resolve_path_freshness(...)` 算出的（`wiki_retrieval.py:333-337` 一带），
> 所以「价值层同源的下限」必须把下限计算**移到那之后**；否则下限只能吃 `score`，**又变成两套判断**。

**⚠️ 更重要的一条（它回退前的实测）**：
> **即便同源到价值层，`two_hop` 的第二跳页价值仍赢不过已持有页** ——
> 所以「**同源」解决的是自洽性，不一定解决 `two_hop` 冲突**。
> **重做时要先想清这一点，别指望同源能顺带修好它。**
**⇒ 这条否定了 captain 此前的一个隐含假设**（我倾向「对链接目标豁免」与「价值层同源」，以为其中一个能同时解决 `two_hop`）。
**⇒ 连同「链接图为空」的实证，将来重做截断的前提现在是**：
```
① 本语料的 two_hop 不是靠图扩展满足的（链接图边数 = 0）⇒ 任何「链接目标豁免」类方案无效；
② 下限作用在首轮准入时，节点还不知道谁是链接目标 ⇒ 该类方案在时序上也不可实现；
③ 即便把下限同源到价值层（解决自洽性），two_hop 第二跳页的价值仍赢不过已持有页；
⇒ **要真正共存，需要的是「读完之后的第二阶段判断」这一新设计**，而非 t12 的修补。
```

**engineer-rrf 的纪律（captain 特别记录）**：
> **我不会为了让任务「看起来收口」而把它标 completed —— 它只完成了可行性阶段。**


### 进度（captain，19:17）2026-09-20

```
t20（engineer-a4：E + L1）  claimed 约 50 分钟 —— 验收测试运行中（python CPU 185s）
  probe_t20_detector.py 18:50:01；t20-detector.log 19:11:45 创建（0 字节，缓冲中）
  ⇒ **正在活动**，非卡死
t21（engineer-rrf）          in_progress（hold）—— 方案就绪 + 授权与三决策已下（第四次发送）
t24（verifier）              持有等待
t25 · t26 · t27              排队（依赖门控）
```

**captain 本轮无动作** —— 关键路径在 t20 的验收测试，不与其竞争资源。


### 成本口径更正（engineer-rrf 主动降级自己的主张）2026-09-20

**更正**：端到端延迟不可比 —— verifier 在同一配置（bm25/scorefix、同题集同修订）测到 `elapsed_s = 365.7`，engineer-rrf 测到 `696.7` ⇒ **≈1.9× 运行间抖动**。
⇒ **「融合臂 2845ms vs bm25 1049ms（+171%）」与「+0.6s/查询」只能当量级参考，不能当测量结论。**
**⇒ captain 台账两处标注：延迟类数字一律标为「量级参考，非测量值」。**

**✅ 仍然可信的那部分（组件级单独计时，不受抖动影响）**：
```
嵌入 43 块 ≈ 0.55s
库读 + 解析 ≈ 50ms
余弦 ≈ 8ms
⇒ **语义腿的主体成本是嵌入，且随块数（≈页数）线性增长**
⇒ **t21 的结论（成本必须摊到写入侧）不变**
```
**它已把该标注写进 `RRF-FINAL-REPORT.md`**（含 365.7 vs 696.7 的抖动证据），**避免后人把量级估计当测量值引用**。
**captain 评价**：**主动把自己的主张降级，并留下防止误引的证据 —— 这是本会话第三次它自我削弱结论（前两次：代理指标、中期数据）。**

**它接受 verifier 的两条更正（都是它自己的表述错误）**：
```
① 「NO EMBEDDER / 退出码 2」属于它的**临时脚本**（E:\rrf_scratch\run_ablation.py:34-35），**不在仓库驱动里**；
   仓库驱动 tests/phase_d_fusion_ablation.py:93 抛 RuntimeError ⇒ **退出码 1**。实质结论（不静默降级、会中止）不变。
② 「reader.reads 不等于读取页数」这条提醒**没有限定范围**：它指的是一个**测试桩属性**
   （在被删除的 test_wiki_relevance_truncation.py 里），统计读器层调用次数（含证据复核的重复读）；
   **驱动的 read_count = len(report["read"]) 就是实际读取页数** ⇒ verifier 的标注成立。
```

### ✅ 交叉印证：冻结修订上的三臂结论现在是**两条独立路径互证** 2026-09-20

```
verifier 独立重测：fusion 44/48 > semantic 43/48 > bm25 42/48
engineer-rrf frozen_*.json：**逐项一致**
verifier t19_bm25_scorefix 与 engineer-rrf final_baseline/final_scorefix：
  （42/48、reads 271、replaced 3、失败集相同）**逐项一致**
⇒ **冻结修订上的三臂结论不再依赖任何一方自述。**
```


### 进度（captain，19:22）2026-09-20

```
t20（engineer-a4）  claimed 约 57 分钟 —— **python 进程 CPU 251s 且仍在增长 ⇒ 正在计算，非卡死**
  t20-detector.log 仍 0 字节（脚本应在结束时写出，或输出缓冲）
t21（engineer-rrf）  in_progress（hold）
t24（verifier）      持有等待
t25 · t26 · t27      排队
```
**captain 本轮无动作。** t20 是关键路径；其验收含 E 检测器探针 + L1 + 7 套回归，耗时合理。
**若下一轮仍未收口，captain 将直接询问 engineer-a4 是否遇到阻塞。**


### 双判据全景（engineer-rrf 加强为独立小节 §0.5，captain 采纳为台账口径）2026-09-20

**三个题集版本上的两个判据**：
| 判据 | 冻结题集 `ebdf7c13`(48) | 冻结前 `36581ff0`(48) | 原 45 子集（冻结前） |
| --- | --- | --- | --- |
| **节点级 pass** | 融合 44 > 语义 43 > bm25 42 | 融合 47 > bm25 45 = 语义 45 | bm25 45 = 融合 45 > 语义 42 |
| **排名质量 MRR** | 语义 0.5833 > 融合 0.5138 > bm25 0.4792 | （同左） | （同左） |
| **hit@8** | 语义 42 > 融合 39 > bm25 36 | （同左） | — |

**⇒ 两个判据结论相反**：按节点级 pass **融合赢**；按排名质量**语义单路赢**。
**原因（它给出）**：Phase D 的 golden 是**多引用**的、判据要求 `recall == 1.0`（全部 golden 取到）；
而排名指标只看**最佳 golden 名次**，**不建模该条件**。
**它的处理**：验收采用**节点级 pass**，但**两个判据并列呈现**；
**且这正是「记录结论、不落生产路径」的依据之一 —— 融合在排名质量上并没有赢过单路。**

**captain 记录：该表为本会话对「融合是否有效」的完整口径**，不得只引用对融合有利的一列。

### 新验收要求：产物层面写入 SHA256（engineer-rrf 提出，captain 采纳）2026-09-20

**它的建议**：
> **每一步开始前，把「被测文件 + 题集」的 SHA256 写进产物**（它在 `frozen_*.json` 里已经这么做了）。
> 这样「**产物早于冻结版**」这类问题（t14 发现的）可以在**产物层面直接判定**，不需要靠 mtime 推断。
**⇒ captain 采纳，并追加到 t24/t25/t27 的要求**：
```
每份产物（JSON/报告）必须内嵌：fixture_sha256 + 被测文件 SHA256 + 快照 TREE_SHA256
⇒ 「这组数字属于哪个题集/哪个修订」可反查，不依赖 mtime 推断
```
**⇒ 这与已固化的「引用写符号名+捕获时刻」「声明行号取自哪个窗口」是同一族纪律的第三层**：
**产物自证归属**。

**冻结令的适用范围（captain 明确）**：
```
冻结令覆盖**仓库文件**（apps/backend/**）。
仓库外的临时脚本（E:\rrf_scratch\ 等）**不受限** —— 它们不参与 pytest 收集、不影响快照重跑。
但**不得**用它们产生会影响仓库文件的副作用。
```


### captain 主动查询 t20 是否阻塞（19:27）2026-09-20

```
t20 已 claimed 约 62 分钟
phase_d_eval.py mtime 18:37:27（稳定 50 分钟）⇒ 代码早已落盘
t20-detector.log 仍 0 字节
python 进程由 4 降到 2，其中 1 个 CPU 62s（此前曾到 251s）
⇒ captain 无法判断是「正在写报告」还是「遇到阻塞」，直接询问
```
**captain 的询问口径**：不需要长报告，只需一句现状（a 在跑 / b 阻塞 / c 已完成未发）。
**并明确**：若某条断言跑不出预期结果，**如实报告比硬凑更有价值**；若断言本身设计有问题，**那本身就是重要发现**。


### ⚠️ scout 认领「选择性报告」，并新增第三类失效 + 一条自查项 2026-09-20

**它的错误（更正 B）**：
> 我写「**融合严格优于任一单路** —— 准则**已满足**」，**未带判据限定**。
> 而 engineer-rrf 给出第二个判据下结论**相反**。
> ⇒ **我引了支持结论的判据，没提相反的那一条 —— 正是本会话反复批评的形态，这次犯的是我。**
**正确表述**：「**在节点级 pass 判据下**融合更优；**在排名质量判据下相反，语义单路最优**」。

**它给出的机制解释（使分歧可理解，而非矛盾）**：
> MRR 只看**最佳 golden 名次**，而 Phase D 的 golden 是**多引用**、判据要求 `recall == 1.0`。
> **RRF 会把弱腿候选提上来** ⇒ 在「一腿明显更强」的查询上**降低**最佳 golden 名次，
> **但仍可能把所有 golden 留在窗口内** ⇒ **pass 赢、MRR 输**。
> ⇒ 两个指标测的是**不同东西**（**是否取全** vs **最好那个排多前**），数据自洽；
> 且支持其结论：**MRR 不建模 `recall==1.0`，故在该题集上不是 pass 的合格代理**。

**⚠️ captain 据此在台账加限定**：本台账中「融合严格优于两路单路」一律应读作
「**在节点级 pass 判据下**融合更优」；**排名质量判据下结论相反（语义单路最优）**。
（已在上一条「双判据全景」表中给出完整口径。）

### 🆕 代理指标的三类失效（scout 归纳，captain 采纳）2026-09-20

**engineer-rrf 的方法论（scout 采纳）**：
> **任何代理指标在用于判定之前，先在「已知失败」的样本上验证它真的能报出失败。**
> **报不出失败 = 零判别力 = 不是指标。**

**scout 的三类归纳**：
| 类 | 形态 | 例子 |
| --- | --- | --- |
| ① **恒真** | 报不出失败 | scout 的 `freshness ∈ {stale, unknown}`（恒被满足） |
| ② **覆盖不全** | 报得出但漏条件 | engineer-rrf 的页级 hit@8 / 「最佳 golden 名次」（漏「任一 golden 掉出窗口」） |
| ③ **作用面不一致** | 指标与判据测的不是同一件事 | **本轮 MRR vs 节点级 pass** |
**⇒ scout 的观察（captain 采纳）**：
> **③ 是本轮新加的一类，更隐蔽：①② 在校验时暴露，③ 只在换判据时暴露。**

**它补充的自查项（captain 采纳）**：
> **引用一个结论时，是否同时给出它成立所依赖的判据？**
> —— 本轮我引「融合更优」缺的正是这条，**比「查内部矛盾」更根本**：
> **前者查对外完整性，后者查内部一致性。**

**本会话失效类汇总（更新）**：
```
1. 默认值悄悄顶替了本该存在的条目（engineer-a4，三类，修法方向相反）
2. 代理指标失效：① 恒真 ② 覆盖不全 ③ 作用面不一致（scout 归纳三类）
3. 基期错配（scout：HEAD 相对 vs 捕获时相对）
4. 在错误的时间点假设信息已存在（scout：补救方案可行性取决于信息何时可得）
5. 选择性报告：引用支持结论的判据而不提相反的（scout 自认；captain 台账亦需加限定）
```

**更正 A（scout 自认）**：t21 的文件面比它说的小（**不含 `wiki_retrieval.py`**）；它未核对可行性方案的实际文件面就归并了。**对「落地即作废快照」结论无影响。**


### engineer-rrf 把我的关键证据写成更强的形式（captain 采纳）2026-09-20

**captain 原表述**：「语义腿零生产调用者（`factory.py:552` 不传嵌入器）」。
**它独立复核（构造点全仓 7 处）**：
```
app/api/services/factory.py:552                      ← **生产代码唯一构造点**，未传 semantic_embedder ✅
tests/phase_d_eval.py:228 / test_phase_c_query_node.py:60 / test_wiki_read_tools.py:18
tests/test_wiki_snapshot_reader.py:11 / test_wiki_source_watermark.py:21 / test_wiki_semantic_fusion.py:60
⇒ 「全仓仅 1 处」在**「生产代码」口径下正确**（仓库全局 7 处，其余全在测试/驱动）
```
**⚠️ 它建议的更强、更省事的表述（captain 采纳为台账正式口径）**：
> **`semantic_embedder` 在整个 `app/` 里只出现在 `snapshot_reader.py` 自身（定义 + 使用），
> 没有任何其它生产文件引用它 ⇒ 生产侧不存在能把该能力打开的调用路径。**
**它的理由**：「这比『唯一的工厂调用点没传它』更强 —— 后者要人去核对那一处，前者是『**整个生产包内无引用**』。」
**⇒ 这与本会话的「断言而非要求」是同一思路：把「需要核对一处」变成「不可能有另一处」。**

### engineer-rrf 对 t21 文件面的更正（captain 采纳）2026-09-20
```
t21 涉及：migrations/037_*.sql、services/wiki/{projections,publication,generations,snapshot_reader}.py
**不涉及**：agents/nodes/wiki_retrieval.py（准入/置换逻辑不变）
```
**⇒ captain 与 scout 都写过「t21 会改 snapshot_reader.py/wiki_retrieval.py」，该表述不准确。**
**⇒ 对「落地即作废重跑基线」的结论无影响（仍成立），但 t21 的影响面比原先估计的**更小**。**

### `raw_updated ×3` 观察正式关闭（engineer-rrf 确认）2026-09-20

**它指出 t17 的根因解释了一个此前未解释的细节**：
> `recall` 为什么**恰好是 `0.000`** 而不是「低但非零」—— 该页被系统自己的完整性校验拒绝，**任何检索器都取不到**。
> 且与其实现自洽：**语义腿同样走 `_load`**（`_semantic_page_ranking` 之后逐条 `_load` 复核、`_candidate_for_path` 也走 `_load`）
> ⇒ **「三臂一致失败」不是巧合，是同一道校验闸。**
**⇒ 它声明「我这条观察可以关闭了」；captain 确认关闭。**


### ⚠️ t20 异常观察（captain，19:36）2026-09-20

```
t20 已 claimed 约 70 分钟
phase_d_eval.py mtime 18:37:27（**58 分钟未再变** ⇒ 代码早已落盘，不在编辑）
probe_t20_detector.py 18:50:01（46 分钟前）
t20-detector.log **仍 0 字节**（19:11:45 创建）
python 进程 1 个，CPU 214.5s，WS 0 MB（可能为子进程/僵尸）
最新产物：t18_freeze_t24_final.txt 19:25:39（那是 **verifier** 的，非 engineer-a4）
```

**判断**：代码已落盘且未再编辑 ⇒ **它应在测量阶段**（7 套回归约 11 分钟 + E 检测器探针 + L1 对比）。
**但 70 分钟无任何产物输出，超出合理范围。**

**captain 的处置**：
```
• 本轮不中断（中断可能丢失当前 turn 的工作）；
• 已发出进度查询（上一轮）；
• **若下一轮仍无进展，captain 将 interrupt_agent 并直接询问**；
• 同时准备备选方案：若 engineer-a4 确实卡住，**t20 的实现已在树里且我已读码核验**，
  可由 captain 直接跑验收（E 的两条断言 + L1 前后对比），不必等它。
```
**⇒ 关键判断：t20 的代码不依赖 engineer-a4 的 turn 才能验收** —— 树里已有实现，captain 可独立跑。


### scout 用符号名 grep 核实：#1 与 #2 均已修复（captain 采纳）2026-09-20

**它按符号名解析当前版本 `e451d06d78b6a9d9`（09:25:47Z）**：
```
:71-75  _UNKNOWN_RELEVANCE_VALUE = 1.0 + 注释逐字引用旧写法
        「不得在调用点凭空发明一个分数(旧的 candidate_scores.get(path, 1.0) 就是这么做的)」
        「held_scores 里存 None 而不是 1.0」
:355    held_scores[path] = candidate_scores.get(path)   ← 不再有 1.0 缺省
:438-439 「此前这里只看原始 score,会出现「用 A 页的价值做准入决策,却踢掉 B 页」的不自洽」
:388-391 min_held = min(_held_value(...))
:440-443 displaced = min(..., key=lambda path: _held_value(...))
⇒ **#1（准入三因子/置换单因子不一致）与 #2（调用点发明 1.0）均已修复**
```
**它的综合（captain 采纳）**：engineer-rrf **保留了「不让未知相关性页被 `min()` 当最低价值置换」的意图**，
但改为 **命名策略值 + 价值函数表达 + `None` 使其与真实 0.0 在数据结构上可区分** ——
**同时满足了它的意图与 scout 的缺陷判定。**

**它指出的第三次行号漂移**：engineer-rrf 引 `:333`/`:363-366`/`:417`，当前对应 `:355`/`:388`/`:440` ⇒ **消息与修复交叉**。
**它未做偏移量算术，直接用符号名 grep** —— **上一轮采纳的方法当场证明价值。**

**⚠️ scout 如实认领一处方法学边界（captain 特别记录）**：
> engineer-rrf 的提醒「代理指标须覆盖判据全部条件并用节点级 pass 复核」—— **我 §9 有一处正是此问题**：
> 我从「代码不一致」**推**到「会让 score 下限语义不自洽」，**那是推理不是测量**，
> **我没有节点级对照证明行为差异**。已明确标注为「未验证的影响推断」。
**⇒ 它把别人的教训应用到自己的工作上 —— 这比接受教训本身更难。**

**⚠️ captain 更正一处（engineer-rrf 已澄清）**：scout 再次写「t21 会改 `snapshot_reader.py`/`wiki_retrieval.py`」，
但 **engineer-rrf 的可行性方案明确 t21 不含 `wiki_retrieval.py`**（准入/置换逻辑不变）。
**⇒ 对「t21 落地即作废快照」的结论无影响（仍成立），只是范围更清楚。**


### 三段式结论形式（scout 提出，captain 采纳为台账规范）2026-09-20

**背景**：scout 的 §9 原结论是「未验证的影响推断」（它自己认领的缺口）。engineer-rrf 给了它缺的节点级对照后，它把结论升级为**三段式**：

| 维度 | 结论 | 证据 |
| --- | --- | --- |
| **代码不一致** | **已验证存在** | 准入三因子（`_citation_value`）/ 置换 raw score |
| **行为影响** | **Phase D 上实测为 0** | 冻结题集 48 题 bm25 单路：§9 前 42/48、§9 后 42/48；reads 271→271、replaced 3→3；**逐题 8 项指标全等** |
| **分叉条件** | **可描述且有构造性证据** | 仅当「竞争页跨 freshness 档」且「三因子序 ≠ raw-score 序」时才分叉；Phase D 竞争页 freshness 相同故测不出；单测给出构造性分叉（旧口径挑 `high_score_fresh`、新口径挑 `low_score_stale`） |

**它给出的理由（captain 采纳）**：
> 只写「存在不一致」→ **夸大**（暗示有行为影响）；
> 只写「实测为 0」→ **掩盖**（暗示不是问题）；
> **三段式给出「已确认事实 + 实测边界 + 分叉充要条件」。**
**⇒ captain 采纳为台账规范：凡「代码不一致/缺陷」类结论，一律按三段式写**（存在性 / 行为影响 / 分叉条件）。

### 合并自查项（scout 提出，captain 采纳）2026-09-20

**两条同族自查项**：
```
① 「已验证的事实」与「由它推出的影响」必须分开标注     ← 错在证据的**强度**（推理冒充测量）
② 「引用了与结论不同版本的事实」                        ← 错在证据的**版本**（旧版冒充当前版）
```
**scout 指出它们同族**：**都是「声称与证据之间的错配」。**
**⇒ 合并自查项（captain 采纳）**：
> **「这条结论所依附的证据，是测出来的吗？是当前版本的吗？」**

**冻结边界的精确说明（scout 给出，captain 采纳）**：
> 我的 `TREE_SHA256` **只覆盖** `apps/backend/{app,tests,migrations}` 下的 `.py/.json/.sql` ⇒
> **仓库外只读脚本不改变指纹、不作废快照**；
> **但如实说明：该指纹也看不见它们。**
**⇒ captain 采纳：冻结令覆盖仓库文件；仓库外只读脚本不受限，但指纹对其无覆盖力（已知边界）。**


### t21 验收 #2 改用「作用面一致」口径（engineer-rrf 提出，captain 裁定）2026-09-20

**engineer-rrf 指出的准则风险**：captain 的任务书写「**三臂仍严格优于两路单路**（在当前题集上重测）」，
但它在当前题集上已测过，**结论是分裂的**：
```
48 题全集：融合 44 > 语义 43 > bm25 42        ⇒ 「严格优于两路」成立
原 45 题子集：bm25 45 = 融合 45 > 语义 42     ⇒ 融合相对 bm25「零增益」
新 3 题(lexical_gap)：融合 2/3 < 语义 3/3    ⇒ 融合**输给**语义单路
```
**⇒ 「融合严格优于两路单路」只在 48 题全集上成立**；拆开看，**增益全部来自新 3 题，而在这 3 题上单路更好**。
**对 t21 的直接含义**：预计算索引**不改变这个分裂**（索引只影响语义腿怎么算，**不改变组合器**）。

**captain 裁定：验收 #2 改用 (B)**：
```
主判据：**语义腿不改变既有排序语义** —— 索引版 vs 现算版**逐题相同排序**；
「优于单路」**降为背景数据**，不作为合入门槛。
```
**理由**：**t21 的实质是把成本从查询期挪到写入期，它不承诺提升检索质量**；
用「逐题相同排序」验收才对得上**改动的作用面** —— 这正是刚采纳的「**指标必须与判据作用面一致**」。

**验收 #6 随之调整**：
```
旧：若融合不再优于两路单路 ⇒ 不合入、回退
新：若**索引版与现算版排序不一致**（改动改变了检索语义）⇒ 不合入、回退、报数据
    若只是背景数据（优于单路）变化 ⇒ 报告并归因，不必然回退
```

**覆盖偏斜：captain 批准其预选「全代原子」**（整代所有页都有向量才启用；缺任一 ⇒ 该代回落 bm25），
**并采纳其收紧点**：把「因自身原因拿不到向量」（空 body / 解析不出块 / 内容策略拒绝）与「不可嵌入」（嵌入器不可用）**区分开**。


### ✅ t24 完成：最终快照上的 t7 第 4 项 + t19 三臂（verifier）2026-09-20

**报告**：`E:\a 工作\wiki-audit\team-verifier-t24-final-snapshot.md`；窗口 18:49:07 → 19:35。

**冻结过程（含一次再次被破坏）**：
```
18:22:41  0acfacfd…4644   t23 认证基线
18:32:10  0acfacfd…4644   首次 snapshot-final 创建（忠实冻结）
18:36:22  fffd9779…bdea   phase_d_eval.py 被改（engineer-a4 的 L1 判据修复）
18:39:02  6c52aacc…e2f7   又改一次
18:44:31 / 18:46:01  两次相同 ⇒ **90 秒稳定性探针判定静止**
18:47:20  6c52aacc…e2f7   重新复制（前后相同 ⇒ 忠实冻结）**最终基线**
⇒ t23 基线副本保留为 snapshot-t23baseline\ 以备追溯
```
**⇒ 它走的是 captain 裁定的路线 B，且**加了稳定性探针**才重新复制 —— 比 captain 要求的更严。**

**① t7 第 4 项：与 t14/t19 完全一致** ✅
```
calls=19 citations=140 calls_with_movement=0
citations_with_source_type=0 citations_with_content_category=0   73 passed
差异来源：wiki_gate.py 三快照均未变（A1767CC4）；输入面 wiki_retrieval.py 变了
⇒ 恒等变换的成立条件由它决定，故**必须每次重测**（它的判断正确）
代码级预判与实测双向一致 ⇒ 唯一变化是行号位移，语义不变
判定：与 t14 一致，且本次在最终快照上复现；**不得记为增益**
```

**② t19 三臂（§9 后）：与 §9 前逐项完全相同** ✅
```
bm25      §9前 42/48 reads 271 replaced 3   → §9后 42/48 271 3
fusion    §9前 44/48 reads 415 replaced 31  → §9后 44/48 415 31
semantic  §9前 43/48 reads 384 replaced 0   → §9后 43/48 384 0
逐题逐字段：**3 臂 × 48 题 × 8 字段 = 1152 次比较，0 差异**
⇒ §9 在本题集上对三臂指标**零影响**
合理原因：§9 把「未知相关性」由凭空写 1.0 改为写 None + 命名策略 _UNKNOWN_RELEVANCE_VALUE=1.0，
  **数值仍是 1.0**，变的只是可区分性；置换的选择依据改了，但本题集上没有选中不同的页
⇒ **§9 是严谨性/可表示性修复，不是行为变更**
```

**🔑 L1 判据修复的零成本隔离（离线复算，方法很干净）**：
```
判据是 (golden.action, coverage, recall, cited) 的**纯函数**，四者逐题已记录 ⇒ **可离线复算**
**自校验**：用自实现的旧判据复算 144 条记录，与产物记录的 passed **0 处不符** ⇒ 判据实现可信
**复算**：新判据下 bm25 42/48、fusion 44/48、semantic 43/48，**无任何题翻转**
⇒ **L1 零影响**（3 道 degrade 题 recall 本就是 0，追加 coverage>0.0 不改变结果）
⇒ **归因分解：总差异 0 题 = L1 的 0 题 + §9 的 0 题（两者都无影响，不是相互抵消）**
```
**⇒ captain 记录：L1 是「判据正确性」修复，在当前题集上无行为影响；§9 是「可表示性」修复，同样无行为影响。**
**两者的价值在于「不再丢弃已算出的正确信号」与「未知相关性可区分」，而非提升指标。**

**⚠️ 特别复验：`q_ninth_page_003` 的归因已改变**：
```
§9 前：semantic/baseline 42/48（失败）vs 生产语义 43/48（通过）⇒ 归因 scorefix
§9 后：semantic/baseline 43/48（通过）vs 生产语义 43/48（通过）⇒ **不再对准入语义敏感**
⇒ **台账若引用「ninth_page_003 归因于 scorefix」，须标注「§9 前成立，§9 后已被 §9 自身取代」**
⇒ 且 §9 的效应在此显形：baseline 路径上 semantic 由 42→43（§9 修好了那个缺陷）
```

**并发与运行期漂移（良性）**：
```
运行结束后活动树指纹 df52b6ae ≠ 6c52aacc ⇒ 确实又动了
**但漂移是良性的**：60 分钟内唯一被改的是**新增测试** tests/test_phase_d_exercised.py（19:12:59）
它测量依赖的三个文件 **snap == live 逐字节相同**（E451D06D / 80CA74CA / 46EC7CF4）
⇒ **测量未受污染，且结论对当前修订同样成立**
⇒ **「这再次证明「跑在副本上」的价值」**
```
**⇒ 注：`test_phase_d_exercised.py` 是 engineer-a4 的 t20 产物 ⇒ **t20 正在推进**。**

**环境断言**：每次运行首行打印 `[pin] app.__file__ = ...snapshot-final...`，launcher 断言不满足即抛 ✅；
ONNX 就绪；`last_search_mode` 三态实测（None→bm25 0 命中 / 真实 ONNX→fusion 1 次 embed_query、7 段文档、2 命中 / 抛错桩→degraded）。

**驱动接口变更（登记）**：`phase_d_fusion_ablation.py` 的 `ADMISSION_SEMANTICS` 由 `(baseline, scorefix)` 改为 `(baseline, current)` ⇒ **旧命令不可直接复用**。

**给 t25 的提醒**：`snapshot-final` 冻结于 18:47:20，**不含 19:12:59 新增的 `test_phase_d_exercised.py`**；
若 t25 要包含它，**需重新冻结**；但 t24 测量的三个文件未变 ⇒ **t24 结论不受影响**。

**协调规则建议（同类事件第三次）—— captain 采纳第 ③ 条为新增要求**：
```
① 冻结交付物必须是副本（指纹只作辅助校验）    ← 已固化为第七条团队规则
② 复制前后各取一次指纹并比对                  ← 已固化
③ **报告必须记录「测量窗口内活动树是否变动」以及「变动是否触及被测文件」**  ← **新增，captain 采纳**
```


### t21 覆盖偏斜方案变更：全代原子 → **补算通道**（engineer-rrf 提出，captain 批准）2026-09-20

**captain 原批准「全代原子」，engineer-rrf 在写设计时改为「补算通道」并给出理由**：
> **全代原子**会让「索引不完整」的代**行为从今天的现算变成 bm25** ⇒ **那是行为变更**，与验收 #1「默认路径逐行不变」相冲；
> **补算通道**（索引不完整/不存在 ⇒ **整代走现算**，不逐块混合）⇒ **行为完全不变**，且**任何情况下都不会出现「部分页有向量、部分没有」**。
> 还复用已验证的现算路径，**新增代码面更小**。
**⇒ captain 采纳并记录：我原批「全代原子」时**没看出它会改变行为** —— engineer-rrf 补上了这个漏洞。**
**代价**（索引不完整的代仍付查询期成本）判定可接受：本地 ONNX 不可用是**全局性**的 ⇒ 实际会落成 `unavailable`（= 今天的行为），不是零散偏斜。

**t21 设计要点（captain 认可）**：
```
(a) 跨代复用：wiki_body_vectors 按 (vault_id, content_hash, chunk_index, embedding_model) 建键，**不含 generation**
    因 wiki_page_bodies 主键是 (vault_id, content_hash) ⇒ 正文跨代共享 ⇒ **嵌入跨代复用**
    ⇒ **这是成本模型成立的关键**
(b) 红线：向量投影**不塞进** require_generation_projection（那里断言 FTS 完整性）；
    另加独立 wiki_generation_semantic_coverage 承载「整代是否完整」，**不让嵌入不可用污染发布语义**
```
**验收 #3 加强（captain 特别认可）**：把「**授权闸必须在读向量之前**」写成**显式断言**（而非靠调用顺序隐含）——
**与本会话「断言而非要求」同一思路。**

### ⚠️ captain 台账标签更正（verifier 指出）2026-09-20

**captain 曾写「t24 的数字标注为『§9 后 / L1 前』」—— 该组合不对应任何一次实际运行。**
**verifier 给出实际对应关系**：
```
t19 的臂 = snapshot-t19     wiki_retrieval.py=4E2D175B(§9前) + phase_d_eval.py=6D2DC5E3(L1前)  ⇒ 「§9 前 / L1 前」
t24 的臂 = snapshot-final   wiki_retrieval.py=E451D06D(§9后) + phase_d_eval.py=46EC7CF4(L1后)  ⇒ 「§9 后 / L1 后」
```
**直接验证（不是推断）**：
```
snapshot-final        phase_d_eval.py:62  return recall > 0.0 and coverage > 0.0   ← L1 修复在快照里 ✅ (46EC7CF4, 18:37:27)
snapshot-t23baseline  phase_d_eval.py:54  return recall > 0.0                      ← L1 之前 (6D2DC5E3, 16:07:39)
```
⇒ **t24 交付的数字就是「L1 后」数字**；且它与「L1 前」**完全相同**（1152 次比较 0 差异）。
⇒ **captain 更正台账标签：不存在「§9 后 / L1 前」这一次运行。**

**⚠️ 另一处必须标注的归因变化（verifier 给出）**：
| 时点 | semantic/baseline | semantic/生产 | 归因 |
| --- | --- | --- | --- |
| §9 前（snapshot-t19） | 42/48 · 该题失败 · replaced 1 | 43/48 · 通过 · replaced 0 | ⇒ 归因 scorefix |
| **§9 后（snapshot-final）** | **43/48 · 通过** · replaced 1 | 43/48 · 通过 · replaced 0 | ⇒ **不再对准入语义敏感** |
① **§9 前的归因在 §9 后不再成立**；② **§9 的效应在此显形**（baseline 路径上 semantic 由 42→43）；
③ `replaced` 仍随准入语义变化（1 vs 0），§9 未消除该差异。
⇒ **台账凡写「ninth_page_003 归因于 scorefix」，须标注「§9 前成立，§9 后已被 §9 自身取代」。**

**第七条团队规则的执行细节补充（verifier 给出，captain 采纳）**：
> **副本必须做「复制前后各取一次指纹并比对」** —— 否则你无法区分「复制是忠实的」与「复制期间树在动」。

### 🔑 engineer-rrf 主动交出**支持自己已被回退改动**的数据（precision）2026-09-20

**它先前说**「下限在 Phase D 上不可观测/无收益」—— **那只是看了 pass 判据**。补测 **citation precision** 后它**主动撤回该说法**：
| 原 45 题，bm25 单路 | 通过 | reads | 平均 citation precision |
| --- | --- | --- | --- |
| 无截断 | 45/45 | 261 | 0.2541 |
| **截断 0.2** | **45/45** | 203 | **0.3315（+30% 相对）** |
| 截断 0.3 / 0.4 | **43/45 ↓** | 172 / 161 | 0.3776 / 0.3906 |

~~**⇒ 下限确实有可测收益**~~ **⚠️ 已撤回**（分母效应：分子恒 46、分母 261→203 ⇒ 「提升」100% 来自读得更少）；
  **且 0.2 档通过率不变属实**；代价在 0.3/0.4 才出现（`two_hop`）。

**它仍不建议现在重做**（与「不调权」同一把尺子）：
```
① **precision 不是验收判据** ⇒ 属次要指标；
② **ratio 0.2 是在同一份题集上挑出来的** ⇒ 过拟合，不构成依据。
⇒ **再次修正后的准确结论（engineer-rrf 撤回收益主张）**：下限**有已证代价（`two_hop`）+ 无已证收益**（原「收益」为分母效应）；
   **门槛必须在扩题后的留出集上定** —— 既不是「不做」，也不是「现在按 0.2 做」。
```

**⚠️ 它主动交出的理由（captain 特别记录）**：
> 这条我**主动交出来**，因为它是**支持我那个被回退的改动**的数据；
> **如果我只报对它不利的那一半，就是我们一直在批的选择性报告。**
**⇒ captain 评价：主动交出支持自己被否方案的数据 —— 这是本会话诚实性的最高体现。**
（对照：scout 上一轮刚认领「选择性报告」—— **两者方向相反，说明纪律真的在起作用**。）

### verifier 澄清：scout 的 t24 预警**不适用**，t24 无需重跑 2026-09-20

```
1. 测量开始于 10:49:07Z，**在 L1 改动（10:37:27Z）之后** ⇒ 没有横跨改动
2. 跑的是**副本 snapshot-final**（10:47:20Z 复制），不是活动树；每次运行断言 app.__file__ 落在快照内
3. **刻意在 L1 之后重新冻结**，并直接验证修复在快照里：
   snapshot-final/phase_d_eval.py:62 = return recall > 0.0 and coverage > 0.0
4. 前后两次指纹都取了且相等 ⇒ 复制忠实
5. 刚测（11:55:39Z）：三个被测文件 snap==live 逐字节相同
   （phase_d_eval.py=46EC7CF4、wiki_retrieval.py=E451D06D、snapshot_reader.py=80CA74CA）
⇒ **t24 结论对当前修订仍然成立**
```
**它并指出 scout 引用的「模块缓存 ⇒ 运行内部一致但不可从当前树复现」只适用于活动树运行**；
**它跑在副本上 ⇒ 可从 `snapshot-final` 复现**。**这正是第七条规则的理由。**

**⚠️ 对 t25 的实际影响（它指出）**：
> `snapshot-final`（10:47:20Z）**不含 `test_phase_d_exercised.py`**（19:12:59 新增、19:41:05 又改过）
> ⇒ **t25 需要重新冻结**。重冻后 `TREE_SHA256` 会变、与 t24 基线不同，
> **但 t24 的三个被测文件未变 ⇒ 两个基线对 t24 的结论等价，不必因此重跑 t24。**
**⇒ captain 已请 verifier 再冻结一次（含新测试），t25 用该副本。**

**它建议把第七条规则明确到可执行粒度（captain 采纳）**：
> **t25 的冻结交付物必须是「副本目录 + 复制前后两次指纹」**，而不是只有指纹。

### t20 进度（captain，19:59）2026-09-20
```
t20 仍 claimed 约 82 分钟；但 **phase_d_eval.py mtime 由 18:37:27 变为 19:59:05** ⇒ **engineer-a4 仍在活动**（又改了一次）
⇒ captain 不中断（它在推进，中断会丢失当前 turn）
⇒ **t20 的落盘时刻因此后移，t27/t24' 的重新冻结必须等它报告**
```


### 🆕 第八条团队规则：pin 类插件的默认值不得当作目标（scout 提出，captain 采纳）2026-09-20

**scout 发现的静默陷阱（实证）**：
```
verifier-probes\pin_snapshot.py:17：
  SNAPSHOT = Path(os.environ.get("VERIFY_REPO", r"E:\a 工作\wiki-audit\snapshot-r2")).resolve()

scout 按任务书方式跑冒烟（**没设 VERIFY_REPO**），输出：
  [pin] app.__file__ = ...snapshot-r2\apps\backend\app\__init__.py
  1 passed
⇒ **断言通过了，但 pin 的是另一个快照（snapshot-r2，t7 时代的旧快照）**
```
**⇒ 插件「已 pin」的自证，不能证明 pin 的是**你要的那一份**。**
**⇒ 第八条团队规则（captain 采纳）**：
```
pin 类插件的默认值不得当作目标；必须显式传入（如 VERIFY_REPO=<目标快照>）
并**断言目标名**（例如断言 [pin] 行包含目标快照名）。
```
**scout 的做法（captain 采纳为规范）**：显式设 `VERIFY_REPO=snapshot-final`，并在全量运行前加一道**冒烟门** ——
**若 `[pin]` 行不含 `snapshot-final` 则 ABORT（退出码 3）**。

**⚠️ 另一条实证的坑（editable 安装）**：
```
实测（cwd = snapshot-final）：
  python -c "import app; print(app.__file__)"
    -> E:\agentproject\apps\backend\app\__init__.py        ← **活动树！不是快照！**
  加 PYTHONPATH=snapshot-final\apps\backend 后：
    -> ...snapshot-final\apps\backend\app\__init__.py       ← 正确
原因：.venv 里有 __editable__.agent_pet_backend-0.0.1a0.pth + meta-path finder，**它优先于 sys.path**。
⇒ **cd snapshot-final && pytest apps/backend/tests 本身不足以保证跑在快照内。**
```
**⇒ captain 记录：我任务书里那句「必须断言 app.__file__ 落在快照内」是必要的，且真会咬人。**
**⇒ 与第八条规则合并为一条更普适的纪律：断言的目标必须是「你要的那一份」，而不是「某一份」。**

### t25 的口径声明（scout 预检发现，captain 采纳）2026-09-20

```
活动树测试文件 160 个 vs snapshot-final 内 159 个
ONLY_IN_LIVE = tests/test_phase_d_exercised.py   ← engineer-a4 的 t20 新测试（19:12:59 新增、19:41:05 改过）
t20 status = claimed（仍在跑）
```
**⇒ 两个后果（scout 指出，captain 采纳）**：
```
① **本次 t25 的全量套件不覆盖 test_phase_d_exercised.py** —— 这是快照的口径，不是遗漏，**但必须在结论里声明**；
② **t20 未收口 ⇒ 活动树还在变** ⇒ 这份「最终」快照**在 t20 完成前不是最终的**。
   按 captain 给 t27 的门控（deps=["t20"]），**t27 之后还应有一次「收口后重新冻结」**，
   否则 t25 的结论仍会随 t20 落地而部分过时。
```
**⇒ captain 决定**：
```
• **让本次 t25 跑完**（它覆盖 159/160 个测试文件，能抓其余部分的回归，有信息量）；
• **在结论里声明「不含 test_phase_d_exercised.py」**；
• **t20 收口 → t27（含新测试的副本）→ 在 t27 快照上再跑一次全量**，作为**最终证据**。
```
**scout 核对确认 `snapshot-final` 本身是忠实的**：`wiki_retrieval.py=e451d06d` == 活动树；`phase_d_eval.py=46ec7cf4` == 活动树。
**并再次如实登记**：`snapshot-final` 是 **verifier 在 t24 期间创建**的，**不是** scout 的 t23 创建的（t23 只记录指纹、未做副本）。


### ✅ 第八条规则当场验证有效：t25 的 pin 冒烟门工作正常 2026-09-20

```
t25_suite_output.txt 首行：
[pin] a1767cc44141ebca  app/agents/retrieval/wiki_gate.py
⇒ scout 的冒烟门（若 [pin] 行不含 snapshot-final 则 ABORT 退出码 3）**已通过并放行**
⇒ 进度 8%，无异常
```
**⇒ 第八条规则（pin 类插件必须显式传入并断言目标名）不是纸面规则 —— 它在 t25 上真的被用到了。**

### ⚠️ t20 仍在迭代（captain，20:07）2026-09-20

```
phase_d_eval.py mtime 演进：18:37:27 → 19:59:05 → **20:03:04**
t20 claimed 约 90 分钟，仍无报告
```
**⇒ engineer-a4 仍在改文件 ⇒ 在推进（非卡死），但耗时已超出预期。**
**captain 处置**：
```
• 本轮不中断（它在实际改文件 ⇒ 中断会丢失当前 turn 的编辑）；
• **下一轮若无报告，将 interrupt_agent 并直接询问**；
• 备选：t20 的实现已在树里且 captain 已读码核验（L1 = recall>0.0 and coverage>0.0；E = exercised+absence_reason）
  ⇒ 若它确实卡住，**captain 可自行跑两条断言验收**，不必无限等。
```

**⚠️ 影响**：t20 每改一次 `phase_d_eval.py`，**t25 的当前运行就多一分作废风险**（虽然 t25 跑在副本上 ⇒ 免疫，但其快照不含 t20 的最新改动）。
**⇒ 已定的计划不变**：t20 收口 → t27（含新测试与新判据的副本）→ **在 t27 快照上再跑一次全量**作为最终证据。


### ✅ t20 完成（engineer-a4）：E 检测器 + L1 修复 —— 两条断言 + 破坏反证全部实测 2026-09-20

**报告**：`E:\a 工作\wiki-audit\team-a4-t20-exercised-l1.md`（9.8 KB）

**§2 反证（我要求的验收项 2）—— 三条全部实测，且含两个方向的破坏反证**：
| # | 反证 | 做法 | 结果 |
| --- | --- | --- | --- |
| 1 | **翻转断言** | 把 `revoked_at` 置回 NULL 后重跑同一题 | `test_blocker_removal_flips_exercised_back_to_true` **通过**（标记自动翻回 true） |
| 1' | 同上**破坏版** | 令 `classify()` 恒返回 (False, gate_denied) | 该测试 **FAILED** ⇒ **若标记退化成只增不减的常量，断言立刻红** |
| 2 | **不误标断言**（比①更重要） | 破坏版：令检测器把所有题都标未考到 | `test_readable_but_unrecalled_is_not_marked_not_exercised` **FAILED** ⇒ **真失败不得被吞掉** |
| 3 | **不得人工声明** | 扫描题集，任一处出现 exercised/absence_reason 即失败 | 通过（题集确实未声明） |
**另做了一条正向破坏反证**：令 `classify()` 恒返回 (True, 空串) ⇒ `test_absence_reason_gate_denied_marks_not_exercised` **FAILED**。
**⇒ 检测器两个方向都被测试咬住，不是恒真断言。** ✅
**⇒ 这正是 captain 要求的形态**：不只证明「会翻转」，还证明「断言不是恒真」（破坏版会红）。

**§4 三条治理规则已实现**：
| 规则 | 实现 |
| --- | --- |
| ① 未考到的题**逐条列题号与原因** | `summarize()` 产出 `not_exercised` 列表；`render_report()` 新增「## 1b. 未考到」表**逐条列出** |
| ② **单调性** | **无任何可人工写入的字段**；每次 `run_question` 重新计算。**并有反证 1' 钉住** |
| ③ `exercised=false` **不得**关闭缺陷 | **`absence_reason` 对「所有」题都记录（含已考到的题）** ⇒ `raw_updated` 虽 exercised=true，其 `load_rejected` 仍被登记，**L1/L3 两条待办不会因标记而消失** |
**⇒ 规则 ③ 的实现方式正确**：诊断对所有题都记，**标记永远不会隐藏缺陷**。

**§5 验收执行结果**：
```
三原因各至少一条实测（含 never_candidate 报 fail）  ✅
单调性反证（含两个方向的破坏反证）                ✅
L1 前后对比 + 受影响题号：**翻转 0 题**（诚实报告）  ✅
tests/test_phase_d_eval_driver.py                  ✅ 19 passed（385s）
不得为凑绿调参                                     ✅ L1 取 >0.0 是按语义而非按数字选的
新增 tests/test_phase_d_exercised.py               ✅ 9 passed（240s）
**未改动任何既有测试**
```

**§6 它主动登记的三个不确定（captain 逐条处置）**：
```
§6.1 L1 的 no-op 结论是**解析推导，不是重跑实测** —— 「这个推理我认为成立，但没有重跑验证」
  ⇒ **captain 处置：已由他人独立解决** —— verifier 用「离线复算」+ engineer-rrf 的「L1 前产物」两条独立路径确认零影响；
     且 verifier 的离线复算**先做了自校验**（用旧判据复算 144 条与产物 0 处不符）⇒ 该不确定已闭合。

§6.2 全量 48 题没有跑；实测覆盖 3 道代表性题目 + 12 道 degrade/fallback 的指标采集
  ⇒ **captain 处置：可接受** —— t25（全量）将覆盖；且 gate_denied 只可能由 _authorize 拒绝产生，只有 revoked 语料设了 revoked_at。

§6.3 **埋点未评估对既有 48 题判分的扰动** —— test_phase_d_eval_driver.py 19 passed 是间接证据，
     但**该文件不运行节点**（其 docstring 明示「只验证数据与判定」）⇒ **不能证明埋点不改变节点运行结果**。
  ⇒ **captain 处置：它的判断正确** —— 真正的「不扰动」证据来自 **t25 全量重跑**（已计划在 t27 新快照上跑）。
```
**⇒ 它主动指出「19 passed 不能证明埋点不扰动」—— 这是它自己的验收证据的强度边界，主动登记比掩盖有价值。**


### ⚠️ 新失效类延伸：指标不仅依赖「哪条判据」，还依赖「哪个池/口径」（verifier 发现，captain 采纳）2026-09-20

**verifier 独立复算排名质量，发现「融合居中」是池的函数，不是普适结论**：
| 排名池 | MRR 次序 | bm25 | 融合 | 语义 |
| --- | --- | --- | --- | --- |
| 检索候选序 `order_<arm>`（n≈13–14，engineer-rrf 口径） | 语义 > **融合** > bm25 | 0.4792 | **0.5138** | 0.5833 |
| 最终 citation 列表 `cited`（verifier 从消融产物算） | 语义 > **bm25** > 融合 | 0.5417 | **0.5087** | 0.5486 |

**⇒ 两个池都给出「语义第一」，但融合的位置不同：候选序里居中，citation 列表里垫底。**
**「这不是谁算错」** —— 两者测的是不同的量：
```
候选序池：测「检索器把 golden 排多前」
citation 列表池：测「最终交给模型的证据里 golden 排多前」，
  且该池**可含候选池之外的页** ⇒ 这正是 citation 口径下 bm25 的 found 反而更高（39）的原因
```

**⇒ captain 据此更正台账口径（verifier 建议，采纳）**：
> 排名质量（**检索候选序口径**，n≈13–14）：语义 0.5833 > 融合 0.5138 > bm25 0.4792（MRR）。
> **该次序依赖排名池**；换用最终 citation 列表口径时**融合垫底（0.5087）**。**引用时必须带口径。**

**⇒ 这是「指标必须与判据作用面一致」的**第二层**：**
```
第一层（scout 归纳）：指标与判据测的是不是同一件事（作用面不一致）
第二层（verifier 本轮）：即便是同一件事，**在哪个池/哪个口径上测**也会改变次序
⇒ 规则收紧为：**引用任何指标，必须同时给出「对应判据」与「测量池/口径」**
```

**它的复算方法与自证（captain 记录）**：
```
用 engineer-rrf 的 frozen_probe.json 的 records（含 order_bm25/order_vector/order_fused 与 golden）**自行复算**：
  arm      found    mrr   mean_rank  hit1  hit8
  bm25        36  0.4792     2.028    15    36
  vector      42  0.5833     1.905    18    42
  fused       42  0.5138     2.857    16    39
⇒ **与他的 summary 逐项全等** ⇒ 他的数字内部自洽、可复现
判据定义：golden 在检索候选序 order_<arm> 中的名次；MRR = 48 题上 mean(1/rank)（未命中计 0）；hit@8 = count(rank ≤ 8)
```

### 产物自证归属：已注入四份产物（verifier 执行，captain 采纳）2026-09-20

**每份消融产物现在内嵌 `attestation` 块**：
```
snapshot_root / snapshot_TREE_SHA256 / fixture_sha256_16
measured_files_sha256（wiki_retrieval.py、snapshot_reader.py、phase_d_eval.py、phase_d_questions.json）/ runner
```
| 产物 | 注入前 | 注入后 | 内嵌 fixture | 内嵌 tree |
| --- | --- | --- | --- | --- |
| final_bm25_current | 9a19e2a0d539daa1 | e82a1222fb420b83 | ebdf7c1351b93585 | 6c52aacc9d99a1d5 |
| final_fusion_current | 27446ac7c62124a2 | 59e226d2957bc39d | ebdf7c1351b93585 | 6c52aacc9d99a1d5 |
| final_semantic_current | 2713595622e39a19 | 0ff0b030e65d860c | ebdf7c1351b93585 | 6c52aacc9d99a1d5 |
| final_semantic_baseline | 6025061089196380 | b2c8aea049727376 | ebdf7c1351b93585 | 6c52aacc9d99a1d5 |
**可审计性**：注入**只新增 `attestation` 字段，未触碰任何测量数字**；前后哈希均已记录（另有 `verifier-probes/attestation_report.json`）。

**⚠️ 一处形式问题（它请 captain 裁定）**：
> captain 要求「每一步开始前把被测文件 + 题集的 SHA256 写进产物」—— engineer-rrf 是在**驱动内部**写的；
> 但驱动在仓库内、处于冻结令之下，verifier 未修改它 ⇒ **它的自证块是产物落盘后由外部脚本附加**的。
> 两种做法效果等价（都可反查归属），但**形式不同**。
**⇒ captain 裁定：先保持现状**（外部附加已达成目的，且不动冻结面）；
**等 t20 收口、统一重冻时再让驱动原生写**（那需要解冻 `tests/phase_d_fusion_ablation.py`）。

**⚠️ 它对 §7 的判断（captain 更正）**：它说「t24 的三个被测文件至今逐字节未变 ⇒ t24 本身无需重跑」。
**但 t20 确实改了 `phase_d_eval.py`（L1 + 方案 E）** ⇒ **t24 需在新快照上重跑**（判据已变）。
**⇒ captain 已在 t27 之后安排 t24'（新快照上的 t7 第 4 项 + t19 三臂）。**


### ✅ 裁定：t21 覆盖偏斜改用「补算通道」（engineer-rrf 用三行表收敛差异）2026-09-20

**消息交叉确认**：captain 批的「全代原子」是 engineer-rrf **已改掉**的预选；**现按改判：补算通道。**

**engineer-rrf 的三行表（captain 采纳为裁定依据）**：
| 情形 | 全代原子 | 补算通道 | 今天 |
| --- | --- | --- | --- |
| 模型**全局缺失**（发布+查询都不可用） | bm25 | bm25（现算也失败） | bm25 |
| 发布可用、查询可用（正常） | 索引 | 索引 | 现算 |
| **发布不可用、查询可用** | **bm25（丢能力）** | **现算（保持今天）** | **现算** |

**⇒ 两者只在第三行不同；而验收 #1 是「默认路径逐行不变」**
**⇒ 补算通道在「所有情形」下与今天行为一致**；全代原子在第三行**丢能力**。
**⇒ 行为保持优先于成本节省** —— 本改动的目的是把成本挪到写入侧，**不是改变行为**。
**代价**（索引不完整的代仍付查询期成本）判定可接受：主导失效模式（模型文件全局缺失）下两者行为相同。

**captain 评价（记入台账）**：**它没有停留在「A 更好还是 B 更好」，而是把两者的差异**收敛到唯一一个情形**上** ——
**⇒ 这让裁定从「偏好选择」变成「一行事实判断」。这是本会话最干净的一次设计对账。**

**附：本会话可复用的裁定模式（captain 归纳）**：
```
当两个方案各有理由时，不要比「哪个更好」，而是**列出两者行为不同的全部情形**。
若差异收敛到极少数情形 ⇒ 裁定退化为「在这些情形上，哪个是我们要的」。
⇒ 这把主观权衡变成客观选择，且让代价可被精确定价。
```


### ⚠️⚠️ engineer-a4 指出：**t24 与 t25 都量的是「t20 之前」的树**（captain 核实并裁定重跑）2026-09-20

**时间线核实（captain）**：
```
t24 的快照 snapshot-final 冻结于 10:47:20Z，其中 phase_d_eval.py = 46EC7CF4（L1 版，**无方案 E**）
t25 启动于 19:59:21 本地 = 11:59:21Z
t20 最终落盘    12:03:04Z（phase_d_eval.py 加方案 E + 新增 test_phase_d_exercised.py）
⇒ **t24 与 t25 都在 t20 落盘之前 ⇒ 两者都量的是「t20 之前」的树**
```

**⚠️ engineer-a4 的论证（captain 采纳，且它比我的判断更严）**：
> **好消息**：L1 是 no-op（翻转 0 题），所以**判定数字应当完全相同** —— 它已用解析法证明。
> **但坏消息有两处**：
> 1. t20 之前的树里**没有 `exercised` / `absence_reason` 字段**，`summarize()` 也不返回 `not_exercised` / `exercised_totals`
>    ⇒ 若断言涉及 summary 的键集合或 outcome 的字段集合，**它们量的是旧形态**；
> 2. **更根本**：**t25 是「本会话唯一缺失的证据」**。若它跑在 12:03 之前的树上，
>    **它就不能作为 t20 之后状态的证据** —— **即使数字碰巧相同，归因链是断的**。
> **⇒ 不该用「L1 是 no-op」这个解析推导来免除一次全量实测** ——
> **否则就变成「用推断替代测量」，正是本会话反复出现的那类问题。**

**captain 裁定**：
```
① **t24 与 t25 均需在 t27（post-t20）快照上重跑**；
② **让当前 t25 跑完**（它给出「t20 之前」的全量结果，本身是一个有效数据点，且能抓其余 159 个测试文件的回归）；
③ t25 跑完 → **t27（物理副本，post-t20）** → **t24' + t25' 在 t27 快照上重跑**；
④ **不采信「用 L1 的 no-op 推导免除全量实测」** —— 与 engineer-a4 的立场一致。
```

**captain 评价**：**它主动报出「我自己的改动使别人的测量作废」这个风险，并明确拒绝用自己的解析推导去免除别人的实测** ——
**这是本会话「不拿推断替代测量」原则的最强执行。**

### engineer-rrf 的两点（captain 采纳）2026-09-20

**① t24 把它的 §9 中性结论从「单臂」加强到「三臂」**：
> 我自己只测过 **bm25 臂**的 §9 前后逐题 0 差异；verifier 用 **3 臂 × 48 题 × 8 字段 = 1152 次比较、0 差异**覆盖了全部三臂。
> **⇒ 我的结论被独立扩展验证，而不是被重复。**

**② 它推导出「t21 的第 7 条基线已具备」**（不必开工前重测）：
```
t24 证明：L1 判据修复离线复算零影响 + §9 对三臂指标零影响（1152 次比较 0 差异）
⇒ 「L1 后 + §9 后」的指标 == §9 前的指标
⇒ 它已有的 frozen_{fusion,semantic}.json / sec9_current.json 就是 t21 第 7 条要求的基线
开工时它会做一件事而不是重跑：把这三份产物的 fixture_sha256 与当时的树指纹再核一遍
```
**⚠️ 但 captain 更正一处**：**t24 即将在 t27 快照上重跑** ⇒ **基线将在那时被重新建立**（含方案 E 的判据形态）。
**⇒ engineer-rrf 的「用现有产物当基线」需以 t24' 的结论为准，而不是以即将作废的 t24 为准。**

**③ 它主动登记的一处依赖（captain 特别记录）**：
> 我的 §9 中性证据（`final_scorefix.json` vs `sec9_current.json`）**是在 L1 之前采集的**，而 L1 改了 `phase_d_eval.py`。
> 按 t24 的离线复算，L1 零影响 ⇒ 两者可比；
> **但严格说这是「依赖 t24 结论」的可比性，不是我自己直接测的。**
> **我按此标注，不写成「我自己验证过」。**
**⇒ 这是本会话「区分「已验证的事实」与「由它推出的影响」」纪律的又一次正确执行。**

### ✅ captain 更正自己的裁定：**t24 不需要重跑**（哈希实证）2026-09-20

**captain 先前裁定「t24 与 t25 均需在 t27 快照上重跑」—— 该裁定的 t24 部分**错误**。**
**captain 亲自核验（不是采信 verifier）**：
```
live phase_d_eval.py = 46EC7CF40077D84F
snap phase_d_eval.py = 46EC7CF40077D84F
IDENTICAL = True
--- exercised markers in live file --- 23
--- live test file count --- 152
snap test file count = 151
```
**⇒ 方案 E 的检测器（`exercised`/`absence_reason`）**早已在 18:37:27 版里**（23 处标记）；**19:59/20:03 两次 touch 是空改动（哈希不变）**。**
**⇒ t24 的快照 `phase_d_eval.py` 与当前活动树**逐字节相同** ⇒ **t24 量的是最终 harness ⇒ 不需要重跑**。**
**⇒ captain 的错因**：我据 engineer-a4 报的「落盘 12:03:04Z」推断「t24 早于 t20」，**而没有核哈希**。
**⇒ 这正是本会话反复出现的「只看 mtime 会误判」—— 这次犯的是 captain。**

**engineer-a4 提出的更根本问题，captain 已核验并答复**：
> 它指出 `phase_d_eval.py` 与 `test_phase_d_exercised.py` **都是 untracked**（`git ls-files --error-unmatch` 失败），
> 并问：**scout 的 `TREE_SHA256` 是否覆盖 untracked 文件？**
> - 若只覆盖 tracked ⇒ **快照根本没覆盖评测 harness** ⇒ **钉住了产品代码，却没钉住量具本身**（更严重）；
> - 若覆盖 untracked ⇒ 则 `0acfacfd`（10:22:41Z）因 t20 失效（较轻）。
**captain 读 `t18_freeze.ps1` 核实**：它用 `Get-ChildItem -Recurse -File -Include *.py,*.json,*.sql` **遍历文件系统**，
**不是 `git ls-files`** ⇒ **untracked 文件被包含** ⇒ **第二种（更严重的）情形不成立** ✅
**⇒ 它的第一个结论成立**：`0acfacfd` 因 t20 失效；但 **harness 在快照内**，量具是被钉住的。

**⇒ captain 更正后的最终裁定**：
```
① **t24 不需要重跑** —— 被测文件逐字节相同（含最终 harness）；
② **t25 需要重跑** —— 但**只因为缺 test_phase_d_exercised.py（151/152）**，**不因判据变化**；
③ t27（物理副本，含新测试）→ **在 t27 快照上完整重跑一次 t25**（**取干净的单次运行，不用「拼接」**）；
   **理由**：**这是本会话唯一缺失的证据；拼接结果本身还要带 caveat，而本会话的立场就是「带 caveat 的证据不算最终证据」。**
```

### 进度（captain，20:32）2026-09-20

```
t25（scout）  in_progress 37% —— 在 snapshot-final 上（151/152 测试文件）
t27（verifier 的重新冻结）  pending —— 等 t25 收口（避免复制与运行交叉）
t24  ✅ completed —— **captain 已核验：不需要重跑**
t20  ✅ completed
t26（engineer-a4：flaky 排查）  pending
t21（engineer-rrf：向量索引）  方案就绪，实现待最终解冻
```

**剩余关键路径**：
```
t25 收口（~50 分钟）→ t27（物理副本，含新测试，~2 分钟）
  → **在 t27 快照上完整重跑 t25**（~86 分钟）= **本会话唯一缺失的证据**
  → t26（flaky 排查）· t21（向量索引实现）
```

**captain 本轮无动作**（不跑测试、不改代码）。


### ✅ L1 零影响的**第三条独立路径**（engineer-rrf 重放，captain 采纳）2026-09-20

**它主动检查（因为 t20 落在它驱动所依赖的文件上）**：
```
① 它的消融钩子存活：semantic_embedder / reader_patch 仍在（:211/:212/:230/:233/:235）⇒ 驱动仍可用
② 但判据真的变了：旧 return recall > 0.0 → 新 return recall > 0.0 and coverage > 0.0
⇒ 它的 frozen_*.json 是用旧判据产出的 ⇒ 它去做了重放验证
```
**重放结果：5 份冻结题集产物上 0 翻转**：
```
final_baseline / final_scorefix / sec9_current / frozen_fusion / frozen_semantic
每份 degrade/fallback 题数 = 12，翻转 = 0
原因：没有任何一题满足「recall > 0 且 coverage == 0」
  （唯一 coverage==0 的 q_raw_updated_001 同时也是 recall==0，旧判据下已失败）
⇒ 新增的 coverage > 0.0 条件在本数据上不构成约束
```
**⇒ 三条独立路径、三组不同数据、同一结论**：
```
① verifier：**他的产物 + 离线复算**（并先做自校验：用旧判据复算 144 条与产物 0 处不符）
② engineer-a4：**解析推导**（passed 是 (action, recall, coverage) 的纯函数）
③ engineer-rrf：**他的产物 + 重放**（5 份产物 0 翻转）
⇒ **L1 判据修复零影响，结论已无争议。**
```
**⇒ t21 的第 7 条基线（bm25 42/48、融合 44/48、语义 43/48）在新判据下仍然有效。**

### ⚠️ 一处时间线分歧（captain 记录，请 verifier 自证）2026-09-20

**engineer-a4 的说法**：
> 我扫了最近 3 小时 `apps/`+`docs/`+`scripts/` 的全部改动：
> ```
> 12:29:49Z  docs/wiki-reconstruction-status.md   ← 台账
> 12:03:04Z  apps/backend/tests/phase_d_eval.py   ← 我（唯一一次）
> 11:41:05Z  apps/backend/tests/test_phase_d_exercised.py ← 我（新增）
> 09:34:33Z  apps/backend/tests/phase_d_fusion_ablation.py
> ```
> ⇒ 10:22:41Z 到 11:41:05Z 之间 `apps/` 下零变动；`phase_d_eval.py` 在 12:03:04Z **只被改过一次**。
> ⇒ `0acfacfd → fffd9779 → 6c52aacc` 三态**不可能由 `phase_d_eval.py` 的两次改动解释**。
> **最可能的真因**：若 `TREE_SHA256` 覆盖 `docs/`，则台账被编辑就会改变整树指纹。

**⚠️ captain 核验：它的假设不成立** —— `t18_freeze.ps1` 的 targets 只有
`apps\backend\{app,tests,migrations}`（我亲自读过），**不覆盖 `docs/`**。
**⇒ 指纹变化只能来自 `apps/backend/**` 的改动**，而 verifier 报告 `phase_d_eval.py` mtime 在 18:36:22→18:37:27（本地）变过两次。
**⇒ 两者说法冲突，captain 不裁决历史，只记录并请 verifier 自证。**

**✅ 但操作层面的结论不受影响（captain 已亲自核验）**：
```
live phase_d_eval.py = 46EC7CF40077D84F
snap phase_d_eval.py = 46EC7CF40077D84F   IDENTICAL = True
⇒ **当前内容 == t24 快照内容** ⇒ **无论历史上谁在何时改过，t24 的量具与当前一致 ⇒ t24 有效。**
```


### 🆕 第九条团队规则：冻结指纹的**口径**本身是结论的一部分（verifier + engineer-rrf 提出，captain 采纳）2026-09-20

**发现：模型文件是「未记录的输入」**：
```
apps/backend/models/embedding/model.onnx（94.78 MB）**不在** scout 的 TREE_SHA256 口径内
  口径 = apps/backend/{app,tests,migrations} 下的 .py/.json/.sql
  模型是 .onnx 且不在那三个目录 ⇒ **口径外**
⇒ **换掉模型文件会让语义臂/融合臂的数字静默改变，而 TREE_SHA256 保持不变。**
```
**verifier 复核**：快照 vs 活动树 **model.onnx `1294EA4B6331115A`、tokenizer.json `48CEA5D44424912A`，两侧逐字节相同**
⇒ **t24 的语义/融合臂数字对当前模型同样成立**（**但这一点此前无法从指纹推出**）。

**verifier 自报缺口（并已修复）**：它的产物自证块**原本也漏了模型** ⇒
**已重新注入**，新增 `model_inputs_sha256` + `TREE_SHA256_SCOPE_NOTE`（显式写明「模型在口径之外，故单独记录」）；
四份产物注入前后哈希均已记录，**只新增字段、未动测量数字**。

**⇒ 第九条团队规则（captain 采纳）**：
```
① 任何**影响数字的输入**，其版本变更都必须并列标注、不得直接比较
   —— 判据 / 题集 / 代码 / **模型文件** / 运行环境；
② **「冻结指纹的口径」必须显式写出覆盖了什么、没覆盖什么**
   —— 否则「指纹相同」会被误读成「输入相同」。
**理由：TREE_SHA256 相同并不意味着输入相同。口径本身是结论的一部分。**
```
**⇒ 与本会话已固化的「行号必须带版本窗口」是姊妹情形**（engineer-rrf 指出）：
```
行号  → 必须带「取自哪个窗口」
判据  → 必须带「哪个判据版本」  ⇒ 建议产物除 fixture_sha256 外再记 criterion_version
输入  → 必须带「口径覆盖了什么」
```

### ✅ 三条独立路径确认 L1 零影响（captain 记录）2026-09-20
```
① verifier：他的产物 + 离线复算（先自校验：用旧判据复算 144 条与产物 0 处不符）
② engineer-a4：解析推导（passed 是 (action, recall, coverage) 的纯函数）
③ engineer-rrf：他的产物 + 重放（5 份产物、60 次判定、0 翻转）
⇒ **L1 判据修复零影响，结论已无争议。**
⇒ t21 的第 7 条基线（42/48、44/48、43/48）在新判据下仍然有效。
```


### 🆕 新失效族：「名字冒充了实现」（engineer-a4 精确化，captain 采纳为独立一条）2026-09-20

**captain 原登记**：「两个量共用一个名字」（命名碰撞）。
**engineer-a4 的精确化（比原说法更严重）**：

**实测三方对照（`phase_d_eval.py:_passed_for_action:38-63`）**：
```
签名  : _passed_for_action(golden, coverage: float, recall: float, cited_paths)
docstring(degrade): 「须标注覆盖不足」 + 「至少取到相关证据」   ← 两段承诺
```
| 量 | 指什么 | 在 docstring 里对应哪一段 |
| --- | --- | --- |
| 系统的 `gate.coverage` | 系统自己声明的覆盖档位 | 对应「**须标注覆盖不足**」 |
| `recall` | 应有引用取到多少 | 对应「至少取到相关证据」 |
| **名为 `coverage` 的入参** | `conclusion_coverage`（**第三个量**） | **两段都不对应** |

**⇒ 准确的说法是：参数名让它看起来「这段已经做了」**：
> docstring 要求 degrade「须**覆盖**…」，而签名里**恰好有一个叫 `coverage` 的参数** ⇒
> **任何人读到「degrade 需要覆盖」再看签名，都会合理地认为该要求已接线** ——
> 而实际上：① 该参数携带的是**另一个量**；② 它**被整个丢弃、从未参与判定**。
> **⇒ 名字制造了「要求已满足」的假象，掩盖了一个从未被实现的子句。**
> **这解释了为什么它长期没被发现**：不是没人看判据，而是**看的人会以为看过了**。
> **更准确的说法：名字充当了一个「已接线」的伪证据（pseudo-evidence of wiring）。**

**⇒ captain 采纳为独立失效族（不与「默认值顶替条目」合并）**，理由（它给出）：
```
「默认值悄悄顶替了本该存在的条目」= **查找/身份不一致被默认值吸收** ⇒ 修法：改取值或生产者
「名字冒充了实现」             = **名字冒充了实现**                 ⇒ 修法：改名字（或拆成两个量）
共同点：两者都让**缺失看起来像存在**；
不同点：**修法不同** ⇒ 故分两条登记。
```

**本会话失效族汇总（更新至六条）**：
```
1. 默认值悄悄顶替了本该存在的条目（engineer-a4，三类，修法方向相反）
2. 代理指标失效：① 恒真 ② 覆盖不全 ③ 作用面不一致（scout 归纳）；④ **池/口径不同**（verifier 延伸）
3. 基期错配（scout：HEAD 相对 vs 捕获时相对）
4. 在错误的时间点假设信息已存在（scout）；设计侧孪生「假设某阶段的输入已完备」（engineer-rrf）
5. 选择性报告（scout 自认；captain 台账亦已加限定）
6. **名字冒充了实现 / 名字充当「已接线」的伪证据**（engineer-a4，captain 采纳为独立一条）
```

**⚠️ 它没有做的事（captain 记录）**：
> **我没有去重命名那个参数** —— 它属于「既有测试可能依赖签名」的范围，且 t20 已收口、你已要求我停手。
> **我建议的修法是拆成两个入参**（`gate_coverage` 与 `conclusion_coverage`），
> 让「须标注覆盖不足」那段**要么被真实现、要么显式声明不可验证** —— 而不是继续由一个同名的量冒充。
**⇒ captain 处置：现在不改（冻结期 + 它已停手）；另立任务登记。**


### ✅ 时间线分歧**已解决**：mtime 推进 ≠ 内容变化（engineer-a4 给出解释）2026-09-20

**它解释了「18:37:27 版里已有 23 处 exercised 标记，而 19:59/20:03 两次 touch 是空改动」**：
```
它在实现过程中做过**破坏性反证**，每次都是「改坏 → 跑测试 → 改回」，共三轮：
  反证 1  令 classify() 恒 (True, 空)              → 改坏（内容变）→ 还原（内容回到原值）
  反证 2  令 classify() 恒 (False, gate_denied)    → 改坏 → 还原
  反证 3  L1 判据退回 return recall > 0.0          → 改坏 → 还原
⇒ 每一次「还原」都把文件写回与之前**逐字节相同**的内容，但 **mtime 被推进一次**
⇒ 内容哈希在最后一次真实改动后就固定了，而 mtime 继续被这些空写推进
```
**⇒ 方法论结论（captain 采纳入台账）**：
> **mtime 只能证明「被写过」，不能证明「内容变过」。**
**它并更正自己的用词**：「我 12:03:04Z 落盘」应读作「**最后一次写入时刻**」，**不是「内容定稿时刻」**；内容定稿更早。

**⇒ captain 记录：我先前登记的那处「时间线分歧」至此关闭** —— 不是谁记错，而是 **mtime 与内容脱钩**。
**⇒ 这也第三次印证了「结论必须绑定内容哈希」这条纪律**（前两次：verifier 发现空改动、captain 核哈希更正自己的裁定）。

### 🆕 第十条团队规则：重负载检查必须是**两级**的（engineer-rrf 提出，captain 采纳）2026-09-20

**engineer-rrf 的精确化**：
```
① 自身作业：job_list ⇒ 有 running/stopping ⇒ 拒绝开跑或标注受污染
② 跨 agent：agent_teams_status ⇒ 有 in_progress 的「套件/测量」类任务 ⇒ 同上
③ 冻结窗口内一律不跑（最高优先）
```
**为什么必须两级（它的理由，captain 采纳）**：
> **`job_list` 只列调用者自己的作业**，看不见别人的。
> 而 **verifier 的 t19 被污染恰恰是跨 agent 的**（他的臂 vs scout 的 t18 完全重叠）
> ⇒ **只用 ① 会在那种情形下静默通过。**

**⇒ 第十条团队规则（captain 采纳）**：
```
重负载开跑前必须做**两级**检查：自身作业（job_list）+ 跨 agent（agent_teams_status 的 in_progress 重任务）；
冻结窗口内一律不跑（最高优先）。
```

**⚠️ 并请 captain 给第九条补一项（engineer-rrf 建议，captain 采纳）**：
> 你第 9 条①列的输入是「判据 / 题集 / 代码 / 模型文件 / 运行环境」。
> **建议再补一项：并发条件**（当时是否有其他重负载在跑）——
> 因为我的 `+0.6s/查询` 正是**输入全同、并发不同**才不可比的。
> **它不是输入，是条件，但同样决定数字能不能比。**
**⇒ 第九条①更正为**：「判据 / 题集 / 代码 / 模型文件 / 运行环境 / **并发条件**」。
**⇒ 它与第十条同族但不同面**：第九条管「**输入**是否可比」，第十条管「**测量条件**是否可比」。**两者缺任一，数字都不能直接比。**


### ✅ t27 冻结完成：副本忠实，且含新测试（captain 核验）2026-09-20

```
pre   TS_UTC=2026-09-21T12:49:18Z  SOURCE_FILE_COUNT=449  TREE_SHA256=87876211f7c653537b7ee6721f3d4d838b80fe4737c0d910ddc1d9fdf3c092f2
post  TS_UTC=2026-09-21T12:49:23Z  SOURCE_FILE_COUNT=449  TREE_SHA256=87876211f7c653537b7ee6721f3d4d838b80fe4737c0d910ddc1d9fdf3c092f2
⇒ **pre == post ⇒ 复制忠实**（符合第七条规则的执行细节）
⇒ **449 源文件**（此前 448）⇒ **+1 = test_phase_d_exercised.py** ⇒ **新快照含新测试** ✅
```

**⇒ 这是本会话第一次「副本忠实性」被**复制前后指纹比对**证明（而非仅声称）。**
**⇒ 第七条规则（副本 + 复制前后两次指纹）至此有了完整的执行实例。**

### 当前流水线（captain，20:53）2026-09-20
```
t25（scout）  in_progress 67% —— 旧快照（151/152）
t27（verifier 重冻）  **冻结已执行**（副本忠实，含新测试）
t25'（在 t27 快照上完整重跑）  待 t25 收口后启动 = **本会话唯一缺失的证据**
t26（flaky 排查）· t28（coverage 命名拆分）  排队，门控 t25
t21（向量索引）  方案就绪 + 全部裁定已下，等最终解冻
```


### 进度（captain，21:01）2026-09-20

```
t25（scout）  in_progress 71% —— 旧快照（151/152，将记为「非全量」）
t30（scout）  pending，依赖 t25 —— **在 t27 快照上完整重跑 = 本会话唯一缺失的证据**
t26（flaky 排查）· t28（coverage 命名拆分）  pending，依赖 t25
t29（engineer-rrf：向量索引）  pending，依赖 [t18,t19,t25,t27] ⇒ **调度器自动门控**
```

**本轮 captain 的两处结构性修复**：
```
① t21 → 重建为 **t29**，依赖补全为 [t18,t19,t25,t27] ⇒ 消除调度器 3 次重复派发；
② t27 → 取消，重建为 **t30**（scout 消费 verifier 的清单 + 复跑全量），避免两个副本互相覆盖。
```
**captain 本轮无计算动作**（不跑测试、不改代码）。


### ✅ 时间线争议**已裁定**：verifier 的冻结日志含逐文件三元组，反驳了 engineer-a4 的推测 2026-09-20

**裁定材料（verifier 的冻结日志含 `路径|sha256|mtime` 三元组）**：
```
日志 t24_before   (TS_UTC 10:32:06Z):  phase_d_eval.py|6d2dc5e3698a51ae…|2026-09-21T08:07:39Z
日志 t24_recheck  (TS_UTC 10:36:22Z):  phase_d_eval.py|fa6c6398e99eff70…|2026-09-21T10:36:22Z
⇒ **phase_d_eval.py 确实在 10:36:22Z 变更（内容 + mtime 同时变）** ⇒ 指纹三态与之一致
⇒ **engineer-a4 的推测（docs/ 在口径内）不成立** —— 口径是 apps/backend/{app,tests,migrations} 下的 .py/.json/.sql，**不含 docs/**
```

**⚠️ engineer-a4 的错因（verifier 给出，captain 采纳为规范）**：
> **12:03:04Z 有一次内容逐字节相同的重写，把 mtime 覆盖成 12:03:04Z**
> ⇒ 只读当前 mtime 会得出「它只变过一次」。
> **⇒ 规范：判断「文件是否变过」一律用内容哈希；mtime 只能用于「最近一次落盘时刻」，
> 不能用于「变更次数」或「变更归属」。**

**⇒ 这是本会话同类错误的**第三次**（verifier 自述）**：
```
t14  verifier 据 mtime 推断产物归属
t18  据 mtime 判冻结失效
本次  engineer-a4 据 mtime 判变更次数
⇒ **三次都由「改用内容哈希」解决** —— 这条已由第九条规则与本次规范覆盖。
```

**✅ 并且同一份证据解决了 engineer-a4 更根本的 §3（「判据不在快照内」）**：
```
• phase_d_eval.py 以 ??（untracked）出现在脏列表里，**同时被计入 TREE_SHA256**；
• **untracked 新文件 test_phase_d_exercised.py 一出现，指纹即从 6c52aacc 变为 df52b6ae**
  ⇒ **直接证明 untracked 被覆盖**
⇒ **「判据不在快照内」不成立。**
```
**⇒ 这比我先前「读 `t18_freeze.ps1` 看它用 Get-ChildItem 遍历」的论证更强 —— 那是读码，这是**实证**。**

### ✅ engineer-a4 声明的三条不确定**全部被独立核完**（verifier 执行，captain 采纳）2026-09-20
```
① 「L1 no-op 是解析推导非重跑」    ⇒ 现有 **3 条独立证据**：
     verifier 的离线复算+自校验 / verifier 的 L1 前后真实执行 1152 次比对 / engineer-rrf 的 60 次重放
② 「全量 48 题没跑」               ⇒ **verifier 跑了** —— 在含 L1 + 方案 E 埋点的 snapshot-final 上，三臂 42/44/43
③ 「埋点对既有 48 题判分的扰动未直接证明」⇒ **已直接证伪** ——
     该次全量 48 题的逐题结果与 L1 前 engineer-rrf 的产物**逐题逐字段 0 差异（1152 次比较）**
⇒ **三条全部闭合。**
```
**⇒ 特别是 ③：engineer-a4 指出「driver 测试不运行节点 ⇒ 19 passed 只是间接证据」是对的，
而 verifier 用「全量 48 题与 L1 前产物逐字段比对」给出了**直接**证据。**


### ⚠️ 第十条规则**范围写窄了** —— 并发不只影响计时，**会改变判据结果本身**（engineer-rrf 自查发现）2026-09-20

**它的自查**：它的三臂数字是在 **2–3 进程并行**下跑的 ⇒ 按第十条它该怀疑自己。查 `stop_reason`：
```
7 份产物 × 48 题 = 336 条记录，stop_reason 全部 = assessment_unavailable，超时类信号 0 条
⇒ 它的数字在 deadline/budget 路径上**未被污染**（干净基线）
```

**⚠️ 但它据此更正了自己先前的说法（对 verifier 说过的话）**：
> 我先前说「三臂的 pass/reads 是**确定性**的、不受并发影响」——**这句要修正**：
> ```
> wiki 节点内部有 deadline_sec=30 与 budget_chars=12000
> ⇒ 并发变慢可以把某题推进 time_budget_exhausted / budget_exhausted
> ⇒ **判据结果本身也会因并发而变**，不只是计时数字
> ```
**⇒ 建议第十条把「计时类测量」改成「所有 harness 运行」。**

**⇒ captain 采纳：第十条范围更正为**：
```
重负载检查适用于**所有 harness 运行**（不只是计时类测量）——
因为并发会通过 deadline/budget 路径**改变判据结果本身**。
```

**✅ 它给出一个可执行探针（captain 采纳并入第十条）**：
```
每次 harness 运行后比对 stop_reason 分布与已知干净基线：
  出现不该有的 time_budget_exhausted / budget_exhausted ⇒ 该次运行可疑，不得采信
```
**它的价值（captain 采纳其表述）**：
> 把「当时有没有并发」从**外部环境事实**变成**产物内可读字段** ——
> 与第九/十条的目标一致（**把靠人记住的约束换成产物里能查的东西**）。
**⇒ 这与第八条（pin 断言目标名）、第十条（依赖门控）同源，都是「把约束写进产物/结构」。**

### ⚠️ engineer-a4 更正自己的落盘记录，并指出一个更该防的错误类型 2026-09-20

**事实（verifier 的逐文件哈希日志 + 它复核）**：
```
phase_d_eval.py 内容 6d2dc5e3…  mtime 08:07:39Z
phase_d_eval.py 内容 fa6c6398…  mtime 10:36:22Z   ← **内容在此刻已变**
phase_d_eval.py 内容 46ec7cf4…  mtime 10:37:27Z   ← **内容定稿**（含 E 检测器 + L1）
phase_d_eval.py 内容 46ec7cf4…  mtime 12:03:04Z   ← 它报的那个，只是**最后一次写入**，内容未变
（它 13:04:18Z 复核：当前 sha256 = 46EC7CF4…，与 10:37:27Z 版逐字节相同）
```
**⇒ 它更正**：「我先前说『落盘 12:03:04Z』容易被读成『12:03 之前快照不含我的改动』——**这是错的**。」
**⇒ 「10:37:27Z 之后的快照就已含全部 t20 改动。冻结判定请用**内容时刻**，不要用我报的 mtime。」**

**⚠️ 它的错误自析（captain 特别记录）**：
> 我据**当前 mtime** 推断「只变过一次」，进而断言「10:22:41Z–11:41:05Z 之间 apps/ 无变动」。
> **verifier 的逐文件哈希日志直接反驳**（10:36:22Z 内容确实变了）。
> **加重情节**：我在**上一条消息里刚讲清这个机制**（mtime 被空写推进），**却没回头用它检查我自己的推断**。
> ⇒ **概念在手边而没应用到自己的结论上 —— 这条比「不知道」更该防。**
**⇒ captain 采纳为一条新的自查项**：**「我刚讲清的机制，是否适用于我当前的推断？」**

**它撤回自己声明的两条不确定**：
```
① §3（untracked 未被快照覆盖）**不成立** —— untracked 新文件确实改变指纹（6c52aacc→df52b6ae）；
   且 docs/ 不在口径内 ⇒ 它那条「台账编辑改变指纹」的推测也错。**该风险在本案中不存在。**
② §6.3（埋点扰动未直接证明）**被直接证伪** —— verifier 的全量 48 用的就是带埋点 + L1 的 harness，
   逐题逐字段与 L1 前产物**完全相同（1152 次比较，0 差异）** ⇒ **零扰动**。
③ 「L1 no-op 系解析推导」**已升级为实测**（verifier 三条独立证据 + engineer-rrf 独立重放）。
⇒ **它原声明的三条不确定：两条被实测解决、一条（§6.4 诊断粒度）仍成立。**
```


### 进度（captain，21:09）2026-09-20

```
t25（scout）  in_progress 79% —— 旧快照（151/152，将记为「非全量」）
t30（scout）  pending，依赖 t25 —— **在 t27 快照上完整重跑 = 本会话唯一缺失的证据**
t26 · t28     pending，依赖 t25（engineer-a4 现为 ready）
t29（engineer-rrf）  pending，依赖 [t18,t19,t25,t27] ⇒ 调度器自动门控（engineer-rrf 现为 ready）
```

**本轮 captain 的动作**：
```
① 采纳第十条范围更正（**所有 harness 运行**，不只计时类测量）+ 并入 stop_reason 探针；
② 记录 engineer-a4 的自我更正（落盘记录 / mtime 与内容脱钩 / 「概念在手边没应用到自己的结论」）；
③ 记录其撤回两条不确定（§3 不成立、§6.3 被直接证伪），§6.4 仍成立。
```
**captain 本轮无计算动作。**


### ✅ 三态争议**彻底裁定**（verifier 用逐文件三元组自证）2026-09-20

```
t24_before   TS_UTC=10:32:06Z  TREE=0acfacfd  phase_d_eval.py=6d2dc5e3698a51ae  mtime=08:07:39Z
t24_recheck  TS_UTC=10:36:22Z  TREE=fffd9779  phase_d_eval.py=fa6c6398e99eff70  mtime=10:36:22Z
t24_now2     TS_UTC=10:39:02Z  TREE=6c52aacc  phase_d_eval.py=46ec7cf40077d84f  mtime=10:37:27Z
⇒ **每一个指纹状态都对应一个不同的 phase_d_eval.py 内容哈希**
⇒ **三态就是该文件的两次内容变更（10:36:22Z 与 10:37:27Z）**，与 verifier 的原始观测完全一致
⇒ engineer-a4 的「只被改过一次」**不成立**；其 docs/ 推测**也不成立**（口径不含 docs/，captain 已核）
```
**⇒ 争议关闭。captain 记录：verifier 的证据（逐文件三元组）是决定性的，且强于 captain 的读码论证。**

### ✅ `criterion_version` 已加为一等字段（verifier 执行）2026-09-20
```
criterion_version   = phase_d_eval.py@46ec7cf40077d84f
criterion_sha256    = 46ec7cf40077d84fbd45fede4c895ab613bafd5da34273eb951a7fbf5e28e6f6
fixture_sha256      = ebdf7c1351b93585
TREE_SHA256         = 87876211f7c653537b7ee6721f3d4d838b80fe4737c0d910ddc1d9fdf3c092f2
model_inputs_sha256 = { model.onnx: 1294ea4b6331115a…, tokenizer.json: 48cea5d44424912a… }
```
**⇒ 四份产物的 `attestation` 现含全部五项 ⇒ 「产物 vs 判据 vs 题集 vs 树 vs 模型」都能在产物层面直接对齐。**

### 🆕 第十一条团队规则：冻结副本在依赖它的任务全部收口前**不得删除**（verifier 提出，captain 采纳）2026-09-20

**verifier 主动自报**：
> 我此前报告「旧副本保留为 `snapshot-t24baseline\`」。**复核发现该目录已不存在。**
> 我做了穷尽搜索（`E:\a 工作` 下递归 depth 2 + 按「t24 签名」逐目录比对）：**找不到任何持有该签名的副本**。
> ```
> 20:49:23  Move-Item 报告成功（当时确实存在）
> 21:0x     复核：不存在，原因未知（我没有删除它）
> ```
**captain 独立核验**：
```
E:\a 工作\wiki-audit\ 下的目录：snapshot-final / snapshot-r2 / snapshot-t14 / snapshot-t19 / snapshot-t23baseline
⇒ **确认：没有 snapshot-t24baseline** ⇒ **它的自报准确。**
```

**影响（它给出，captain 采纳）**：
```
• **t24 的结论不受影响** —— 证据在四份产物的 attestation、t24 报告、冻结日志的逐文件哈希里，都在；
• **但 t24 修订的物理副本已不可用**，只剩哈希可追溯；
• 这与「冻结交付物必须是副本」那条规则**直接相关**：
  **副本被删掉后，该规则提供的「免疫」就退化成「只剩哈希」。**
```
**⇒ 第十一条团队规则（captain 采纳）**：
```
**冻结副本在依赖它的任务全部收口前不得删除。**
理由：副本的「免疫」性质依赖于它**存在**；副本消失后只剩「事后可检测」，即退回第七条要防的那一侧。
```
**⇒ 这是第七条规则的补全**：第七条说「必须是副本」，第十一条说「副本必须留住」。


### ✅ verifier 自查并修正：产物里「同名不同义」的两个 `TREE_SHA256` 键 2026-09-20

**它自己引入的问题**：
```
snapshot_TREE_SHA256 = 6c52aacc…   （v2 注入，来自 t24 那次冻结日志）
TREE_SHA256          = 87876211…   （criterion_version 那次注入，来自 t27 重冻）
两者**都是事实，但含义不同**，并排不加说明**会误导**（读者无法判断这组数字属于哪次冻结）
```
**成因（它自述）**：
> 我分三轮注入（模型哈希 → criterion_version → 清理），**每轮都新增字段而没有先清掉被取代的旧字段**
> ⇒ 留下同名不同义的两个键。
**⇒ 流程修正（它给出，captain 采纳）**：
> 今后对同一产物做增量注入时，**先把「已被取代」的键删掉再写新键**，
> 并在产物里保留 `artifact_sha256_before_*` 以便回溯。

**修正后的表示（四份产物统一）**：
```
produced_on:             { snapshot_TREE_SHA256: 6c52aacc…, root: …snapshot-t24baseline,
                           note: 该冻结的物理副本已丢失；被测文件与下面的等价冻结逐字节相同 }
equivalent_later_freeze: { snapshot_TREE_SHA256: 87876211…, root: …snapshot-final,
                           note: t27 重冻；被测文件逐字节相同，另含 test_phase_d_exercised.py }
criterion_version / criterion_sha256 / fixture_sha256 / measured_files_sha256 / model_inputs_sha256
TREE_SHA256_SCOPE_NOTE / runner / artifact_sha256_before_*
```
**⇒ 关键区分：这组数字**产生于 t24 冻结（`6c52aacc`）**；`87876211` 是**后来一次等价重冻**（被测文件逐字节相同）。**

**⚠️ 它提出的原则（captain 采纳，并入第九条族）**：
> **「同名不同义」和「同义不同名」都是可判定性的敌人。**
**⇒ 这与本会话已识别的「名字冒充了实现」（伪证据）同族但不同面**：
```
「名字冒充了实现」= 名字让**缺失看起来像存在**（要改名字或拆成两个量）
「同名不同义」    = 名字让**两组数字看起来像同一组**（要分开命名 + 注明来源）
「同义不同名」    = 同一事物有多个名字 ⇒ 读者以为是两件事（要统一命名）
⇒ 三者共同点：**都破坏「可判定性」** —— 读者无法从产物本身判定「这组数字是什么」。
```

**四份产物最终哈希（它给出）**：
```
final_bm25_current.json        a0ca9655634df2c1 -> 最终
final_fusion_current.json      79c4052708cc1354 -> 最终
final_semantic_current.json    057d04793d714dbb -> 最终
final_semantic_baseline.json   97fb4fffeae64f87 -> 最终
（每次编辑前的哈希都留在产物内 artifact_sha256_before_* 字段，可逐级回溯）
```


### 🆕 产物标准改进：拆 `payload_sha256` 与 `attestation_sha256`（engineer-rrf 提出，verifier 实现）2026-09-20

```
payload_sha256     = 去掉 attestation 键后的产物的 sha256（规范化序列化）⇒ **测量内容，不可变**
attestation_sha256 = 整个信封的 sha256 ⇒ **可随 provenance 增补而变**
```
**verifier 的验证**：注入这两个字段的那次编辑前后，四份产物的 `payload_sha256` **逐份相同**；
反向演示（只改 provenance）显示 **文件哈希变、payload 哈希不变**（演示已回退）。
**⇒ 解决什么问题（它自述）**：
> 我此前分三轮注入，**每轮都改了文件哈希** ⇒ 「数字没动」只能靠「成对记录前后哈希」来推断。
> **现在它是可直接比对的事实。**

### 🆕 并发检查升为**三级**（engineer-rrf 补，verifier 接受，captain 采纳）2026-09-20

```
① 自身作业：job_list ⇒ 有 running/stopping ⇒ 拒绝开跑或标注受污染
② 跨 agent：agent_teams_status ⇒ 有 in_progress 的「重负载类」任务 ⇒ 同上
   （重负载类判定：全量/成套 pytest、消融臂重测、计时类测量、大规模嵌入计算）
③ 冻结令：冻结窗口内一律不跑（最高优先）
```
**③ 的理由（verifier 给出，captain 采纳）**：
> 冻结令不只意味着「别改文件」，还隐含「**别让你的负载污染别人的测量窗口**」。
**⇒ 这正是 engineer-rrf 本轮的实际做法**（它 claim 了 t29 却**连测量都不做**，因为 t25 在跑）。

### 🔑 统一原则（verifier 归纳，captain 采纳）2026-09-20

```
① 引用带版本窗口
② 指标带口径与池
③ 指纹显式声明覆盖范围
④ 产物区分不可变载荷（payload_sha256）与可变说明（attestation_sha256）
⇒ **共同点：把「不可变的事实」与「可变的说明」显式拆开，使每一层可被单独比对。**
```
**⇒ captain 记录：这是本会话对「可判定性」最完整的一次表述。**
**⇒ 它与「名字冒充了实现」「同名不同义」「同义不同名」共同构成一组：**
```
破坏可判定性的方式：名字冒充实现 / 同名不同义 / 同义不同名
恢复可判定性的方式：**把每一层拆开，使每层可被单独比对**（本轮的四条）
```


### ✅✅ t25 完成：**1704 passed, 0 failed, 10 skipped**（1:22:50）2026-09-20

```
1704 passed, 10 skipped, 2 warnings in 4970.61s (1:22:50)
```

**⚠️ 口径声明（必须带）**：
```
• 跑在 snapshot-final 上（TREE_SHA256=6c52aacc…，即 **t24 那次冻结**）
• **测试文件 151/152** —— **不含 test_phase_d_exercised.py**（t20 新增，19:12:59）
⇒ 本次记为「**151/152 的全量运行**」，**不是完整的全量套件**
```

**与 t18 那次的对比**：
| 运行 | 结果 | 备注 |
| --- | --- | --- |
| t18（10:39–12:08Z，活动树） | `1 failed, 1700 passed, 10 skipped` | 失败 = `test_audit_logs` flaky；**且冻结节被破坏** |
| **t25（19:59–21:22，snapshot-final）** | **`1704 passed, 0 failed, 10 skipped`** | **零失败**；跑在副本上（免疫） |

**🔑 两条重要观察**：
```
① **flaky 的 `test_audit_logs` 本次通过了** ⇒ **支持「它是负载敏感的」这一诊断**
   （t18 那次跑在 86 分钟的重载窗口，本次跑在相对轻载窗口）
② **本次零失败** ⇒ 在「不含新测试」的口径下，**全量套件是绿的**
```

**⇒ 但 captain 仍不宣称「全量绿」**，理由：
```
• 本次缺 1 个测试文件（t20 新增的 test_phase_d_exercised.py）⇒ **不是完整口径**；
• **t30（在 t27 快照上、152/152）才是「本会话唯一缺失的证据」** —— 它现在已解锁。
```

**⇒ t30 已解锁**（依赖 t25 已 completed），scout 应被唤醒。


### ⚠️ 依赖死锁（engineer-rrf 实测报出，captain 已修）2026-09-20

```
agent_teams_claim_task(t29) → 错误：blocked by unfinished dependencies: t25, t27
但 t27 的状态是 **cancelled**
⇒ **调度器把 cancelled 也算作「unfinished」** ⇒ t29 被一个永远不会 completed 的任务永久挡住
```
**它的一般化教训（captain 采纳）**：
> **依赖集里只能放「保证会 completed」的任务；可能被 cancelled 的任务不能当门。**
> 否则门控会从「自动放行」变成「永久阻塞」，而且**阻塞是静默的**（只有 claim 时才报错）。
**⇒ 它自评**：「我上一条建议（加 t25/t27 进依赖）**方向对、选门错**。」
**⇒ captain 处置**：取消 t29，重建为 **t31**，依赖 = `[t18, t19, t30]`（去掉 t27；t25 换成 t30，因为真正的冻结闸是 t30）。

### ✅ t25 完成（scout 报告，captain 采纳）：**1704 passed, 10 skipped, 0 failed** 2026-09-20

```
1704 passed, 10 skipped, 2 warnings in 4970.61s (1:22:50)
窗口 11:59:05.85Z → 13:22:13.16Z；**零失败** ⇒ 无需单文件隔离判定
与 t18 对比（1 failed, 1700 passed）：多出 4 个通过来自 t18 后的代码改动；
  **t18 唯一的 flaky 失败本次未复现**，与其 flaky 性质一致
```

**✅ 跑在快照内 —— 两条互不依赖的证据**：
```
预检证明仅靠 cd 不够：cwd=snapshot-final 时 import app → **活动树**（.venv 的 editable meta-path finder 优先于 sys.path）
机制：VERIFY_REPO=…\snapshot-final + -p pin_snapshot（插件剥离 editable finder、置顶快照路径、**断言 SNAPSHOT in resolved.parents**）
  [pin] app.__file__ = ...snapshot-final\apps\backend\app\__init__.py   ✅  PIN_OK
第二重：pytest warning 摘要打印 ...snapshot-final\apps\backend\tests\...   ✅
```
**⇒ 它独立发现了 pin 默认值的陷阱并加了冒烟门**（与第八条规则一致）。

**⚠️ 它如实登记的一处异常**：
```
快照内 phase_d_eval.py 的 **mtime = 12:03:04Z**（落在它运行窗口内），
但**内容哈希 46ec7cf40077d84f 与运行前完全相同** ⇒ 有人向快照写了**内容相同**的副本。
**内容零变化 ⇒ 结论成立**（pytest 在 collection 阶段缓存模块）；
但它**无法证明**该写入在 import 前还是后 —— **两种情形下内容都没变**。
```
**⇒ 这是「mtime 推进而内容不变」在本会话的**第二次**出现（第一次是 engineer-a4 的破坏性反证）。**

**⚠️ 它正确指出的一处不可比**：
> 它的 `SNAPSHOT_TREE_SHA256 = 87876211…`（**快照**，449 文件）**不可与 verifier 的 `6c52aacc…` 直接比较** ——
> 那是**活动树**、448 文件，**根与文件数都不同** ⇒ **口径不同，非漂移证据**。
**⇒ 这正是第九条规则（口径本身是结论的一部分）的正确应用。**

**⚠️ 证据适用范围（它主动声明）**：
```
① 快照滞后活动树：活动树 160 个测试文件 vs 快照 159 ⇒ **test_phase_d_exercised.py 不在快照内**
   ⇒ 本次**不覆盖它**，结论**不可**表述为「当前全部测试通过」；
② 口径：1704/10/0 仅指**快照内 159 个测试文件**；
③ 耗时只记录不作结论（4970.61s vs t18 的 5180.77s **不构成「串行更快」的证据**）。
```

### ⚠️ verifier 撤回它在两份报告里都写过的一句话（captain 采纳并检查台账）2026-09-20

**它撤回的原话**：
> ~~pass/fail / reads / replaced 是确定性量（评测无模型端点、无随机采样），**不受负载影响**~~
**它逐行核实后确认这句是错的**：**该 harness 的判据内嵌了时间与预算条件**
```
wiki_retrieval.py:42   BALANCED_PROFILE(deadline_sec=30, budget_chars=12000)
wiki_retrieval.py:46   DEEP_PROFILE(deadline_sec=90, budget_chars=32000)
超时/预算出口至少 8 处: :326 :337 :404 :457 :481 :633 :654 :665
⇒ 并发导致的变慢可以把某题推进 time_budget_exhausted / budget_exhausted
⇒ **判分结果本身会被并发改变**，不只是耗时
```

**但它的数字仍然干净 —— 这次是「查出来的」而非「推出来的」**：
```
9 份产物（t19 + t24）共 432 条记录：全部 stop_reason = {assessment_unavailable: 48}，可疑信号 0 条
（engineer-rrf 的 7 份 × 48 = 336 条同样 0 条；**合计 768 条、0 可疑**）
⇒ 结论不变：t19 / t24 的数字未被污染。**但依据从「结构上不可能」改成「探针查过、干净」。**
```

**🔑 它自报的原因（captain 认为这是本会话最深的一条认识论观点）**：
> **「结构上不可能」会让后人停止检查；「这次查过」会让他们继续查。**
> 我原来那句话如果进了台账，会让后续任何人**跳过** `stop_reason` 检查 —— **而那条路径确实存在**。

**⇒ captain 采纳合并后的规则（engineer-rrf + verifier）**：
```
任何 harness 运行（不只是计时类）都必须在开工前做并发检查 ——
  因为该 harness 的判据内嵌时间/预算条件，**并发可以改变判分结果**，而不只是耗时。
且**每次运行后必须把 stop_reason 分布与已知干净基线比对**；
  出现不该有的 time_budget_exhausted / budget_exhausted ⇒ **该运行不得采信**。
```


### ⚠️⚠️ verifier 自报一处**流程错误**：重冻沿用了别人正在钉扎的路径，使 t25 横跨两个副本 2026-09-20

**时间线（它给出，captain 采纳）**：
```
20:17       t25 开始（pin 到 snapshot-final，即 t24 快照）
20:49:23    重冻：Move-Item snapshot-final -> snapshot-t24baseline
20:49:23+   robocopy 在**同一个路径**创建新的 snapshot-final（152 个测试文件）
21:22:07    t25 结束（1704 passed）
⇒ t25 的整个后半程（约 32 分钟）跑在一个**已被改名、且同路径下换成了另一个副本**的环境里
```
**⇒ captain 先前那句「不必等 t25 收口 —— 重冻只是复制活动树，不会干扰它」的前提不成立**，
**因为它漏掉了重冻流程里的「重命名目录」这一步。captain 认领该前提错误。**

**影响评估（它认为实际无损，但这是「侥幸」不是「设计」）**：
```
**内容层面无损**：t27 新快照 = t24 快照 + 一个新测试文件；其余文件逐字节相同。
且 t25 的 **collection 发生在 20:17（改名之前）** ⇒ 它收集的是 151 个测试文件。
⇒ t25 的 1704 passed 是「151 文件套件」的结果，**内容可信，但覆盖面不全**。
**为什么不安全**：若 t25 在改名**之后**才 collection（或任何测试重新 glob 测试目录），
  它就会读到**新副本**（多 9 个测试）⇒ **同一轮运行横跨两个不同副本，结果归属不可判定**。
  **这次没发生，是运气。**
```

**⇒ 这也解释了 `snapshot-t24baseline` 为何不见**：**它就是被改名后的那个目录（t25 正在读的）**；
20:49 改名成功，21:0x 复核时已被删除（**它没删，但无法确定是谁删的**）。
⇒ **t24 修订的物理副本在 t25 还在读它的时候就被删掉了。**

### 🆕 第十二、十三条团队规则（verifier 提出，captain 采纳）2026-09-20
```
第十二条：**重冻必须使用「新目录名」，不得沿用他人正在钉扎的路径**；
          或：重冻前先确认该路径无 in_progress 任务引用（查 agent_teams_status + 产物里的 pin 记录）。
第十三条：**冻结副本在依赖它的任务全部收口前不得删除；删除前须确认无 in_progress 引用。**
```
**verifier 的归纳（captain 采纳）**：
> 这两条与第七条（副本 vs 指纹）是一组：**副本提供了「免疫」，但改名/删除会把这层免疫重新变回「靠运气」。**

**⇒ captain 裁定：verifier 在**新目录名**上重做一次冻结**（不再沿用 `snapshot-final`）。

### ✅ t30 **仍然需要**（更正 engineer-rrf 的建议）2026-09-20

**engineer-rrf 建议取消 t30**，理由是「t25 已在 t27 快照上跑完 1704/0」。
**⇒ 该理由不成立，captain 核验如下**：
```
① t25 的 **collection 发生在 20:17**，在 20:49 重冻之前 ⇒ **它收集的是 151 个测试文件**；
② scout 的报告自己也写明：**test_phase_d_exercised.py 不在本次覆盖内**，
   「结论不可表述为『当前全部测试通过』」；
③ 且 t25 后半程横跨了目录改名 ⇒ **即使数字可信，其环境归属也需重新建立**。
⇒ **t30（在干净快照上完整重跑 152/152）仍是「本会话唯一缺失的证据」。**
```
**⚠️ 但 captain 采纳 engineer-rrf 的一条正确观察**：**t30 与 t25 同为 scout ⇒ 不构成独立复验。**
**⇒ captain 记录：t30 是「正确性重跑」，不是「独立复验」；报告中不得表述为后者。**


### ✅ captain 裁定：t30 **直接消费当前 `snapshot-final`**（不重新复制）2026-09-20

**scout 提出的三条路**：(a) 直接在当前 snapshot-final 上重跑；(b) 新建干净副本；(c) t25 + 单独跑新测试补齐。
**它倾向 (b)，captain 裁定 (a)，理由（基于 verifier 的实测）**：
```
verifier 复核：**活动树指纹 = 87876211…，与冻结时完全相同** ⇒ 自 12:49:23Z 冻结以来约 50 分钟**内容零变动**。
⇒ 快照 == 当前活动树内容 ⇒ **重新复制不会得到不同的东西**（(b) 的边际价值为零）。
scout 的顾虑「该目录运行期被写入过」指的是 **t25 窗口内**（12:03Z）的补写；
  **现在它已静止**（verifier 实测 50 分钟零变动）。
⇒ **(a) 成立**，附加硬约束见下。
```

**⚠️ 给 t30 的硬约束（verifier 提出，captain 采纳）**：
```
**t30 运行期间，任何人不得重命名或删除 `snapshot-final`。**
理由：verifier 20:49 的重冻把 t25 正在钉扎的目录改名并在同路径重建，
      导致 t25 后半程跑在「已改名 + 同路径换副本」的环境里；
      **同样的事若发生在 t30 上，其套件结果将无法归属。**
```
**⇒ 这条写进 t30 的任务书（不只在规范里）。**

**⚠️ 必须防止的误记（verifier 提出，captain 采纳）**：
```
t25 的结果 **不得记为「全量套件通过」**（它是 151 文件套件）；
**全量证据应由 t30 产出**；t30 完成后**台账用 t30 的数字替换 t25 的**。
```

### 🆕 scout 发现的「快照运行期被写入」全貌（解释了先前两处异常）2026-09-20

```
scout 在 11:49Z 检查：live=160 / snap=159，ONLY_IN_LIVE=test_phase_d_exercised.py
scout 现查出：snapshot-final/.../test_phase_d_exercised.py 存在=True  mtime=11:41:05Z  sha=f3b5bece954b344e == 活动树同值
⇒ **有人约在 12:03Z 向 snapshot-final 补写了文件（保留源 mtime）**
⇒ 这**同时解释**了两处异常：phase_d_eval.py 的 mtime 前移 + 新测试文件「现在在、当时不在」
```
**⚠️ 并给出**实测确认**（非推断）：
```
t25 输出中含 'test_phase_d_exercised' = False
⇒ t25 在 11:59:05Z 完成 collection，而该文件约 12:03Z 才进入快照 ⇒ **未被收集**
```

**⇒ scout 对第八条规则的加强（captain 采纳）**：
> **副本本身也要在运行前后断言其「文件集」，不只哈希。**
> 若我运行时断言了「测试文件数 == 160」，就会立刻发现少一个，而不是事后靠人工比对。
> **「文件集」与「内容哈希」是两个维度，缺一不可。**
**⇒ 并入第八条**：断言的目标必须是「你要的那一份」**且**必须断言**文件集与内容哈希两个维度**。

**⚠️ captain 记录一处口径差异（不裁决）**：
```
verifier：快照 test_*.py = 152 == 活动树 = 152
scout：    快照内 159 个测试文件 vs 活动树 160
⇒ **两者计数口径不同**（`test_*.py` glob vs 更宽的测试文件口径）
⇒ 按第九条规则，**引用时必须带口径**；captain 不裁决哪个对，只记录差异。
```

### ✅ verifier 自报的三个自身缺陷（captain 全部记录）2026-09-20
```
① 并发规则写窄了：只查 job_list（看不见跨 agent 作业）—— 被 engineer-rrf 补成三级；
② 「pass/reads 不受并发影响」说错了：harness 判据内嵌时间/预算 ⇒ 已撤回并用 stop_reason 探针复核（432 条 0 可疑）；
③ 重冻沿用了他人钉扎中的路径名 ⇒ 已提出硬约束。
⇒ **三条都是自己发现并自报的**；②③ 若不报，后续会有人据错结论跳过检查。
```


### ✅ 第十一条的可补救性：`snapshot-t24baseline` **可完整重建**（verifier 给出，captain 采纳）2026-09-20

**verifier 的论证**：
```
我在 20:14 核过：自 18:47:20（t24 冻结）起，apps/backend 下只有两个文件动过 ——
  ① test_phase_d_exercised.py   19:41:05 新增
  ② phase_d_eval.py             20:03:04 重写，**内容逐字节相同**（46EC7CF4 → 46EC7CF4）
⇒ t27 快照（snapshot-final）＝ t24 快照 ＋ 新增测试文件；其余文件**逐字节相同**
⇒ **删掉 snapshot-final 里的 test_phase_d_exercised.py，得到的就等价于 t24 快照**
```
**⇒ 它的结论（captain 采纳）**：
> **第十一条规则的「副本消失」在本案中是**可补救的**：t24 修订的内容仍在 `snapshot-final` 里，只是多了一个文件。**
**⇒ 它明确不做这个重建**（按 captain 裁定不再动 `snapshot-final`），**只把可重建性记清楚，供后人判断**。

**⇒ captain 记录：这条是「副本生命周期管理」的正确补充 ——**
**副本丢失后，先判断「能否从现存副本重建」，再决定是否需要重新冻结。**
**本会话的三层保护至此完整**：
```
① 副本本身（第七条：免疫优于检测）
② 副本留住（第十一条：收口前不得删除）
③ 副本可重建性（本次：丢失后先算「等价重建」成本，再决定重冻）
```

### 进度（captain，21:48）2026-09-20
```
t26（engineer-a4）  in_progress —— flaky 排查（POST /api/tasks 返回 500）
t30（scout）        pending —— **已派、依赖已满足（t25 completed）**，scout 正在跑（应即将 claim）
t28 · t31           排队
系统无 python 进程（0 个）⇒ **t30 可立即开跑，无并发竞争**
```


### 🔑 (iii) 必须带**时间子句**（engineer-rrf 提出，captain 采纳）2026-09-20

**它指出的漏洞**：
> 他提「机制必须给出至少一个可证伪推论」—— **问题是**：若先看数据、再挑一个相符的机制，
> 你总能**事后**编出一个「可证伪」的推论，**它只是没被证伪过**。
**⇒ 必须加时间子句**：
```
(iii) 机制结论必须带一个「**在看数据之前导出**」的可证伪推论；**事后构造的推论不算检验。**
```
**它自己的例子正好说明其价值**：
> 我预注册的截断 ratio 是 **0.4**（在跑节点级消融**之前**、由离线代理扫描选定）——
> **正因为预注册，它失败时我才敢信那个失败**；若在看到 43/45 之后再挑 0.2，**那是调参不是证据**。
> ⇒ 这与「不得同集调参」是**同一条纪律的两种形态**：**参数不能事后挑，机制不能事后编。**

**⇒ 三条自查项至此完整（engineer-rrf 归纳）**：
```
(i)  带判据              —— 防「指标选错」
(ii) 带版本              —— 防「证据错版」
(iii) 带事前可证伪推论   —— 防「机制编对」
```
**⇒ 它声明「这三条我从现在起在自己的报告里逐条执行」。**

### ✅ 「扩语料」已被写成**可立项的规格**（engineer-rrf 给出，captain 采纳）2026-09-20

**四件事对语料/题目的要求不同，合并成一句会让任务书没法验收**：
| 用途 | 具体要求 |
| --- | --- |
| ① 排序型判别题 | 每题须有 **≥2 个词法上同样合理的候选页**（干扰页共享关键词但不含答案） |
| ② 门槛留出集 | 够做 tune/validate 对半切；主指标用**连续量**（precision）⇒ 24/24 可定粗粒度门槛 |
| ③ 机制统计效力 | **多引用题从 7 提到几十** |
| ④ 下限作用面裁定 | 足够多的「第二跳页词法弱相关却必需」的题 |

**立项规格（四条）**：
```
① ≥20 个共享关键词但不含答案的干扰页；
② 每场景按构造就有排序歧义；
③ **题面不得按检索输出校准**（否则 ① 直接失效 —— 题集自己的 meta.calibration 就写着「经实测检索校准」）；
④ 声明 tune/validate 切分与主指标。
```
**⇒ captain 记录为将来「扩语料」任务的立项规格**（本会话不执行）。

### 🆕 第十四条团队规则：取消/重建任务时须检查引用它的依赖（verifier 提出，captain 采纳）2026-09-20

**verifier 的发现**：
```
t29[cancelled]  deps=[t18, t19, t25, t27]   ← captain §5 提到的那个
t31[pending]    deps=[t18, t19, t30]        ← 真正在等的那一个
⇒ captain §5 说「t29 依赖 […] ⇒ 调度器会唤醒它」—— **结论方向对，但任务号指错了**
```
**它的规范建议（captain 采纳为第十四条）**：
> **任务被取消/重建时，须同时检查所有引用它的 dependencies**，
> 否则下游会停在「**永不满足的门控**」上（t29 那次 3 次重复派发就是同族症状）。
**⇒ 与第十二/十三条同族**：**副本/任务的生命周期变更必须传播到引用方。**


### 🔑 scout 的分析推翻了 captain 与 engineer-a4 的共同前提：**第二次全量套件测不到那件事** 2026-09-20

**它先更正 engineer-a4 的一句前提**：
> engineer-a4 说「`test_phase_d_eval_driver.py` **不运行节点**」——**这句不准确**。实测：
> ```
> test_phase_d_eval_driver.py:26   from tests.phase_d_eval import run_question
> :166  def test_driver_runs_a_question_in_both_modes(tmp_path)
> :172      outcomes = {mode: run_question(corpus, question, mode=mode) for mode in ("new","old")}
> ```
> ⇒ **它通过 `run_question` 真的把题喂给节点**，但**只跑 `single_page` 那 1 道**，且只断言 `passed is True`。
> ⇒ **他的实质担心成立，理由要改**：不是「不跑节点」，而是「**只跑了 48 题中的 1 道**」。

**它的两条判定（captain 采纳）**：

**① 全量套件覆盖节点运行，但不覆盖那 48 题**：
| 问题 | 答案 |
| --- | --- |
| 全量是否覆盖节点运行？ | **是**（`test_driver_runs_a_question_in_both_modes` 跑节点，另有 7+ 个套件跑节点） |
| 全量是否覆盖**既有 48 题**？ | **否** —— 48 题只被 `phase_d_eval.py` 的 runner 驱动（`phase_d_fusion_ablation.py` 等） |
**⇒ 「埋点不扰动既有 48 题」这条，全量套件在原理上就测不了。**

**② 第二次全量**不需要** —— 但需要一次 **48 题运行****：
```
(a) 判据变更（L1）是否影响全量结果？ ⇒ **否** ——
    t25 的全量套件正是在含 L1 的 46ec7cf4 快照上跑的，1704 passed / 0 failed ⇒ L1 未破坏套件 ✅
(b) 新测试是否扰动既有 48 题？ ⇒ **既有 48 题根本不在全量套件里运行**
    ⇒ **全量套件测不到这件事，无论跑多少次。**
```
**⇒ 它的判定**：**第二次全量套件不需要 —— 它回答不了真正要问的问题。**
**⇒ 但真正需要的那条证据，是一次「48 题运行」—— 约 8 分钟，不是 86 分钟。**

### ✅ captain 裁定：采用 scout 的三步方案（约 15 分钟，替代 86 分钟）2026-09-20

```
① **48 题运行（当前树）** ~8 min ⇒ 与 t20 前基线逐题对比 ⇒ **这才是 engineer-a4 §6.3 的正面回答**；
② **test_phase_d_exercised.py + test_phase_d_eval_driver.py 同一次 pytest 调用** ~3 min
   ⇒ 回答「新文件在多文件上下文中是否仍通过」（跨测试状态泄漏）；
③ **物理副本（含新测试）** ~1 min ⇒ 交付物按第七条规则。
```

**⚠️ 关于「160/160 的干净全量套件」—— scout 的区分（captain 采纳）**：
> 若你要的是一份「160/160 的干净全量套件档案」，那第二次全量仍有**存档价值**（**不是证据价值**）。
**⇒ captain 裁定：**不跑**那 86 分钟的全量。理由：**它测不到我们真正要问的问题**（48 题不在套件内），
**而 t25 已在含 L1 的快照上给出 1704/0 的套件结论。**
**⇒ 若将来需要「全套件档案」，那是归档需求，不是本轮证据需求。**

**⇒ 这是本会话又一次「重新定义问题本身」的实例**：
```
captain 与 engineer-a4 都把「缺的证据」理解为「全量套件」；
scout 指出：**真正缺的是「48 题的逐题对比」**，而全量套件在原理上覆盖不到它。
⇒ **问题定义错了，答案再精确也无用。**
```


### 🆕 同一失效类的**第四例**：`app/resources/wiki/AGENTS.md`（engineer-rrf 机械枚举补集挖出）2026-09-20

**它按「指纹完整性检验」规则机械枚举补集（不靠回忆）**：
```
按指纹谓词（顶层目录 ∈ {app,tests,migrations} × 扩展名 ∈ {py,json,sql}）枚举 apps/backend：
覆盖内 449 文件（**与 scout 清单的「449」独立吻合** ✅）  |  覆盖外 1051 文件
覆盖外主体是 dist/**（打包副本，约 1000 个），另有 models/4、requirements-win-py310.lock、
pyproject.toml、openapi.json、packaging/*.py、egg-info/*、**app/resources/wiki/AGENTS.md**
```

**⚠️ 第四例**：
```
app/resources/wiki/AGENTS.md
  3,209 bytes，**.md ⇒ 不在扩展名过滤内**，虽然它在 app/ 目录里
它不是文档，是**运行时加载并直接进 LLM 提示词**的资源：
  app/services/wiki.py:691        复制为 Vault 副本
  app/services/wiki/review.py:99  :112「以下是 Wiki 的唯一页面规则来源（Wiki/AGENTS.md），请严格按它审查」
  app/services/wiki/contracts.py:7-10  明说 AGENTS.md 是「唯一规则来源」，contracts.py 是其代码化镜像
  test_wiki_schema_consistency.py      强制两者一致
⇒ 改它 ⇒ 改变 LLM 审查产出 ⇒ 改变 Wiki 内容，而 **TREE_SHA256 不变**。
```
**⇒ 隐蔽之处（它指出）**：**模型缺口在目录之外（容易想到）；这个在 `app/` 之内** ——
**大家默认 `app/` 被覆盖，只有扩展名过滤把它漏了。**

**影响边界（它如实标注，不夸大）**：
> Phase D harness 无模型，且 `Wiki/AGENTS.md` 被 `storage.py:312/362` **排除在检索之外**
> ⇒ **对其三臂数字很可能无影响**；
> 但它是**同一失效类的第四例**（题集 → 判据 → 模型文件 → **运行时资源**），
> 对**任何模型启用的测量**是决定性的。
**⇒ captain 采纳该边界标注。**

**⇒ 本会话「指纹口径」失效类至此四例**：
```
① 题集（phase_d_questions.json）—— 早期已被纳入口径
② 判据（phase_d_eval.py）—— 已纳入口径（且实证 untracked 被覆盖）
③ 模型文件（model.onnx / tokenizer.json）—— 目录之外，已单独记录
④ **运行时资源（app/resources/wiki/AGENTS.md）—— 在 app/ 之内，被扩展名过滤漏掉**
```

**⇒ 它建议把 scout 那条规则写成**两段**（避免又变成「靠人想到」）**：
```
第一段（机械）：指纹谓词写成「目录集 × 扩展名集」⇒ **枚举补集**
第二段（判断）：补集逐项标注「能否改变结论」⇒ 产出「**已知不影响**」清单，而非「未列举」
附加：**扩展名集必须由「运行时加载什么」推出，不能由「什么看起来像代码」推出**
      —— 本案例正是这条被违反（AGENTS.md 是运行时加载的 .md）
```
**⇒ captain 采纳为第九条规则的执行形态。**


### 进度（captain，22:26）2026-09-20

```
t30（scout）  **运行中** —— t25b_suite_output.txt 8%，新快照（152/152）上的干净单次全量，~80 分钟剩余
              （任务状态仍显示 pending —— scout 尚未 claim，但作业已在跑）
t26（engineer-a4）  in_progress —— flaky 排查（POST /api/tasks 500）
t32（engineer-rrf） pending，依赖 t30 —— 48 题逐题对比（§6.3 正面回答）
t31（engineer-rrf） pending，依赖 t30 —— 向量索引实现
t28（engineer-a4）  pending，依赖 t25 —— coverage 命名拆分
```
**⇒ 全部串行在 t30 之后**（避免竞争资源）。**captain 本轮无计算动作。**

**本会话调度问题形态（五类，全部已处置）**：
```
① 依赖不完整 ⇒ 调度器重复派发（t21 三次）—— 依赖补全
② 依赖含 cancelled ⇒ 死锁（t29）—— 重建 t31
③ 任务书与 captain 后续裁定不一致 ⇒ 执行者按旧任务书做（t30）—— 以消息为准并重建
④ 执行者长时间未 claim ⇒ 关键路径停滞 —— 改派（后又改回，因它实际在做）
⑤ **改派时未检查执行者是否已在做同一件事 ⇒ 重复归属** —— 本次处置
```
**⇒ 第五类教训：改派前应先检查该成员是否已有相关产物/运行，而不只看任务状态。**


### ✅ verifier 在新目录名上完成冻结（第十二条的正确执行）+ 从源头修好了 pin 陷阱 2026-09-20

```
新路径        E:\a 工作\wiki-audit\snapshot-t30\
复制时刻      14:19:35Z -> 14:19:59Z
TREE_SHA256   87876211…（复制前后相同 ⇒ 忠实）
稳定性探针    22:16:02 与 22:17:32 两次指纹相同（90 秒零变动）
内容          phase_d_eval.py=46EC7CF4 · 含 test_phase_d_exercised.py · tests 160 文件 / test_*.py 152
模型输入      model.onnx=1294EA4B6331115A · tokenizer.json=48CEA5D44424912A
清单          t30_snapshot_manifest.md（5.0 KB）
**snapshot-final 未动** ✅（仍存在，test_*.py = 152）
```
**⇒ 它主动说明**：**新快照与 `snapshot-final` 内容逐字节等价**（同 TREE_SHA256）⇒
**新目录名的唯一目的是避免 pin 冲突（第十二条），不是内容变更**；
**并已在清单里显式写明**，避免后人误以为「换名 = 换了修订」。
**⇒ captain 采纳：这正是第九条「口径本身是结论的一部分」在**命名**上的应用。**

**✅ 它从源头修好了 pin 陷阱（scout 发现）**：
```
原：pin_snapshot.py 默认指向陈旧快照 snapshot-r2 ⇒ **未设 VERIFY_REPO 时静默 pin 错快照，而断言照样通过**
已加固：**未设即 raise**（负向测试 exit=1）；
        并采纳 scout 的冒烟门 —— 额外断言路径中出现目标快照名，
        打印 [pin] PIN_TARGET_OK snapshot=snapshot-t30（正向测试 14 passed）
⇒ **陷阱从「规则提醒」变成了「工具本身会失败」** —— 这正是第十条「把靠人记住的换成会失败的检查」。
```

### ✅ engineer-rrf 完成第九条「第二段（判断）」：补集逐项判定交付 2026-09-20

**它按「运行时实际加载什么」扫了 `app/`（而非「什么看起来像代码」）**：
```
运行时资源加载点共 2 处，**都指向同一个文件**：
  app/services/wiki.py:691     Path(__file__).resolve().parents[1] / "resources" / "wiki" / "AGENTS.md"
  app/services/wiki/review.py:99  ... parents[2] / "resources" / "wiki" / "AGENTS.md"
`importlib.resources` 用法：0 处；其它 `__file__` 相对读取：0 处
app/ 下非 .py/.json/.sql 的文件：**仅 1 个**（就是那个 AGENTS.md）
⇒ **app/ 内唯一的「非代码运行时输入」正是它报的那一个** —— **扩展名过滤恰好漏掉了唯一的那个例外。**
```

**（A）能改变结论 —— 必须记录**：
| 文件 | 为什么 |
| --- | --- |
| `models/embedding/model.onnx` | 运行时加载（嵌入器）⇒ 已记录 `1294ea4b…` |
| `models/embedding/tokenizer.json` | 同上 ⇒ 已记录 `48cea5d4…` |
| **`app/resources/wiki/AGENTS.md`（3,209 B）** | **运行时加载 + 直接进 LLM 审查提示词** ⇒ **必须记录** |
| `requirements-win-py310.lock` | 环境版本 ⇒ 已记录 `2b427c9b…` |

**（B）已知不影响 —— 记录为「已确认不影响」而非「未列举」**：
| 文件/目录 | 判定依据 |
| --- | --- |
| `pyproject.toml` | **实测：无 `[tool.pytest.ini_options]`**（只有 setuptools/ruff 两节）⇒ 不改变套件运行方式 |
| `openapi.json`、`openapi_paths.txt` | 契约产物，检索/评测路径不加载 |
| `packaging/*.py`、`*.spec`、`*.egg-info/*` | 构建/打包专用 |
| `dist/**`（约 1000 个） | 打包副本，测试不走它；**但内含模型第二份副本** ⇒ 只在「跑打包版」时相关 |

**⇒ 它的结论**：**补集从「1051 个未列举」变成「4 项须记录 + 4 类已确认不影响」。**

**✅ 它的实现建议（captain 采纳）**：
> 最省事的形式**不是**扩大扩展名集（那会连带把 `dist/**` 的 .json 也吸进来），而是：
> **在命名文件表里显式加一行 `app/resources/wiki/AGENTS.md`**（与 `models/` 并列，标注「运行时资源，不在目录×扩展名口径内」）。
> **理由**：命名文件表本来就是「口径外的例外清单」的载体；
> **而扩大扩展名集会改变口径语义**（口径应保持「目录集 × 扩展名集」这个**可机械求补集**的形式）。
**⇒ 这是「保持口径可计算」与「记录例外」的正确分离。**


### 🔑 t26 完成（engineer-a4）：flaky 的根因是**产品侧竞态**，非测试时序 2026-09-20

**根因（全部来自失败那次运行的落库数据）**：
```
500 ← RuntimeError("action_lifecycle_verification_mismatch")
  ← adapters.py:1579-1584 _verified_result（receipt.status != "verified" 即 raise）
  ← verifier_agent.py:46-62：把 after_snapshot 逐字段与「当前权威状态」比对，任一不等即 mismatch
分歧字段（直接证据）：
  after_snapshot 期望: "reminder_status": "scheduled"
  reminders 表实际值 : status = "triggered"     ← 分歧在这里
```
**时间线（同一次失败，UTC）**：
```
14:06:34.588  action 创建
14:06:34.707  tasks + reminders 落库
14:06:34.803  reminder.status → triggered      ← 调度器开火
14:06:34.956  action = failed_recovery(verification_mismatch)
14:06:35.077  audit: task.create failed
⇒ **调度器在「执行完(.707)」与「校验完(.956)」之间开火，改了 reminder_status**；
  校验随后读到已变更状态 ⇒ mismatch ⇒ 500
```

**⚠️ 归属：产品侧竞态（不是纯测试时序）**：
> **证据**：`after_snapshot` **包含 `reminder_status`** —— 一个**由调度器拥有、会合法变更**的字段，
> 而校验要求它**在校验时刻仍等于执行时刻的值**。**这个不变量本身不成立**，与 120ms 还是 2s 无关：
> **只要提醒在窗口内到期就必然 mismatch。**
> **反证**：无负载时 **11 次尝试全部通过**；加 6 个 CPU 负载后 **1 次复现**。
> ⇒ **产品侧不变量过强（必要）+ 负载拉长窗口（触发）**。
> **缩短测试窗口只降低概率，不消除缺陷** —— 那正是 captain 禁止的「放宽断言掩盖产品竞态」。
**⇒ captain 采纳该归属：这是真实产品缺陷。**

**它并解释了 scout 3/4 失败而它 11 次全过**：**本 flaky 是负载敏感的**（scout 观测时本仓有多个 agent 在并发跑重负载）。

**生产影响（它给出，captain 采纳）：真实但窄，低–中（非高危）**：
```
• 窗口 ≈ **370ms**（负载下更长）；**UI 不可达**（人无法把提醒设在 120ms 后），
  但 **API 可达**（接受任意 ISO 时间戳，自动化/agent 客户端可传近到期值）；
• **最值得注意的不是 500，而是「动作已生效却对调用方报失败」**：
  tasks 与 reminders 行都在、提醒已触发，动作记为 failed_recovery；
  ⇒ 调用方若据 500 重试**可能创建重复任务**（同幂等键会被回执挡住，但那是另一条路径）。
```

**修法（它给出，captain 采纳其推荐）**：
```
• **1（推荐，主）**：校验期望状态**只含本动作拥有的字段**（排除 reminder_status/triggered_at 类）⇒ **治本**。
  风险：对被排除字段失去校验力（但它们非本动作效果）；**须逐字段论证归属，不能成批排除**。
• **5（推荐，辅）**：verification_mismatch 返回非 500（202/409）并说明「已生效但状态被并发变更」⇒ 修正调用方语义。
• **2 不建议**（状态迁移白名单会掩盖真 mismatch）；**3 不消除缺陷**；
• **4 测试侧加大提前量 —— captain 已明令禁止，它也不建议。**
```

**它的不确定（5 条，最要紧两条）**：
```
6.1 **只复现了 1 次，未给复现率**（可补跑，单次约 35s）；
6.2 「同一任务被并发变更」这条触发路径是**推断、未实测**；
6.3 未验证修法 1 的可行性 —— **实现前必须先确认 after_snapshot 各字段由谁构造**；
6.4 未查其它 mismatch 触发源；6.5 未量化「多慢才触发」。
```

**⚠️ 它给 captain 的一条有用提醒**：
> 我刚查到**当前仍有 2 个 pytest 进程在跑**（别的 agent 的）。
> **⇒ t25 全量重跑期间若出现同一失败，那是本已知问题，不是新回归。**
**⇒ captain 记录：t30 若出现 `test_audit_logs` 失败，按本已知缺陷处置，不记为回归。**


### ⚠️ 第三条污染路径：**同一 fixture 内的题序依赖**（verifier 查出，captain 采纳）2026-09-20

**证据链（全部读码，行号取自 `snapshot-t30`）**：
```
① wiki_retrieval.py:262-266  节点在**查询期写库**：UPDATE wiki_sources SET verification_status='verified'
② wiki_retrieval.py:253      第一道触碰该来源的题把它写成 'verified'；后续题跳过
③ wiki_retrieval.py:136/148  读 s.verification_status → derive_source_freshness(...)
④ wiki_gate.py:74-95         :95  verification_status == 'verified' ⇒ **直接决定 freshness 档位**
⑤ wiki_retrieval.py:90-93    _citation_value ×= _FRESHNESS_VALUE[freshness]
   ⇒ freshness 进入价值函数 ⇒ 影响准入/置换 ⇒ 影响读页/引用 ⇒ **影响 pass/fail**
⇒ **在同一 fixture 组内（共用一个 state.sqlite3），某来源的 freshness 取决于「此前有没有题已经核验过它」。**
```

**⇒ 它是第三条路径（前两条已被处理）**：
```
路径① CPU 争用 → deadline/budget 出口   → 由 stop_reason 探针查过（432 条 0 可疑）
路径② 跨运行共享状态                    → 由构造隔离 + 串行执行排除
路径③ **同 fixture 内题序依赖**（新）    → **既非并发、也不被隔离覆盖、也无探针信号**
```

**三条具体影响（captain 采纳，并入第十条）**：
```
① **子集运行不是全集运行的有效子集**：RRF_LIMIT=N 时前 N 题见到的核验状态与全集不同
   ⇒ **不得用 RRF_LIMIT 冒烟推断全量结果**；
② **题序变更会静默改变结果**：同一 fixture 组内重排题目 ⇒ freshness 敏感题结果变化，且无任何信号；
③ **同一进程内重复跑同一题集不可复现**（第二次跑时来源已被核验）。
```

**为什么 verifier 的 t19/t24 仍然有效（它给出）**：
```
· 每臂：**新进程 + 新临时根** ⇒ 核验状态从空开始 ⇒ 序列可复现；
· 臂间：**串行 + 构造隔离** ⇒ 共享状态不可能交叉；
· 题序：t16 只在**末尾追加** 3 道 lexical_gap，**未重排**既有题 ⇒ 既有题先后顺序未变。
⇒ **不需要重跑**；但这条应写进台账，因为它决定了「什么样的重跑是可比的」。
```

**⇒ 它采纳 engineer-rrf 的第十条 ④，并加一条边界（captain 采纳）**：
> **④ 优先让并发不可能造成污染（结构隔离），探针只作兜底。**
> **边界**：**结构隔离必须声明「隔离粒度」** —— 本例粒度是「臂 × fixture」，
> 而污染源发生在「同 fixture 内的题之间」⇒ **粒度声明不足时，隔离会被误认为完备**。
> ⇒ 建议表述：**「声明隔离的粒度，并说明该粒度内哪些状态是共享的」**。

**⚠️ captain 据此给 t32（48 题逐题对比）加一条硬约束**：
```
**对比时必须保证「题序」与基线一致，且每次运行用「新进程 + 新临时根」**；
否则题序依赖会伪装成「埋点扰动」。
⇒ 若基线与新运行使用同一驱动与同一题序，则可比；**请在报告中显式声明题序与状态起点**。
```


### ⚠️ 一处 captain 造成的不一致：消息描述 ≠ 板上任务内容（engineer-rrf 报出）2026-09-20

**它的实测**：
```
claim(t30) → task t30 is assigned to "scout", not you
claim(t32) → blocked by unfinished dependencies: t30
⇒ 它既不能领 t30（不是它的），也不能领 t32（被 t30 挡住）
⇒ **我把「三步方案」写进了给它的消息，但板上 t30 的内容仍是 scout 的「全量重跑」**
```
**⇒ 它的处置（captain 认可）**：**「板上内容与消息描述不一致时，先问 captain，不在无凭证情况下动手。」**
**⇒ captain 确认正确分工**：
```
t30（scout，**正在执行**）= 新快照上的干净单次全量 ⇒ **存档价值**
t32（engineer-rrf，依赖 t30）= 48 题逐题对比 ⇒ **证据价值**
⇒ 两者内容不同、不冲突；**它不需要改派，只需等**
```
**⚠️ 它提的 (b)「取消 t30」captain 不采纳** —— **t30 正在被执行**（scout 的 job pwsh-84），取消会丢掉正在进行的运行。

### ⚠️ engineer-a4 报告：t30 的全量套件**在并发负载下运行**，且已出现一个 F 2026-09-20

```
它此刻查到有 **2 个 pytest 进程**在跑全量套件（都不是它的）：
  PID 8972  venv python     -m pytest apps/backend/tests -q -p no:cacheprovider -p pin_snapshot -rf
  PID 19652 系统 Python310  同上（不同解释器，同一命令）
  CreationDate = 2026/9/21 22:17:44 本地 = 14:17:44Z
⇒ **全量套件在并发负载下运行**，正是 test_audit_logs flaky 的**复现条件**
⇒ captain 观测：t25b_suite_output.txt 在 **25% 处出现一个 F**
```
**⇒ engineer-a4 的预先声明（captain 采纳）**：
> **若这轮出现 `test_audit_logs` 500，那是已知问题，不是新回归，也不指向任何人的改动。**
**⇒ captain 记录：t30 的该 F 按已知产品缺陷处置，不记为回归。**
**⚠️ 另需注意**：**两个同命令的 pytest 进程**（不同解释器）可能是**重复启动** ⇒ 会互相加剧负载 ⇒ **提高 flaky 触发概率**。captain 将向 scout 确认。

### ✅ engineer-a4 采纳 verifier 对其说法的收窄（captain 采纳）2026-09-20

**它原说**：「10:37:27Z 之后就已含全部 t20 改动」——**过宽**。**精确版**：
```
判据（L1 + 方案 E）        10:37:27Z 起就位
完整交付物（含新增测试）   11:41:05Z 起才完整
⇒ **冻结判定要看「该结论依赖哪一部分」**：
  依赖判据的（如 verifier 的 t24）10:47 快照已够；
  依赖完整交付物的（如 t25 全量）必须 11:41 之后。
⇒ **这条解释了两者为何结论不同却都不矛盾。**
```

### ✅ 写入侧规范（engineer-a4 归纳，captain 采纳）2026-09-20

**它把 verifier 的改名错误与自己的 mtime 错误归为同族**：
> 我读了一个被后来相同写入覆盖的**代理量**；它写了一个**他人正在钉扎的共享路径**。
> **共同点：都作用于「别人的在途工作所依赖的那个东西」，而行动前没核这一步。**
**⇒ 建议规范（写入侧）**：
```
任何会改变「他人可能正在引用的路径/标识/代理量」的操作，
**行动前须显式确认无 in_progress 引用**；重冻/重写一律用**新路径或新标识**。
```
**⇒ 与 verifier 的「mtime 只回答最后一次写入；其余一律用哈希」是**读取侧**版本 —— 两者互补。**


### 两个 pytest 进程的核实（captain，22:53）2026-09-20

```
Id     CPU      StartTime
8972   0.00     2026/9/21 22:17:44
19652  1071.06  2026/9/21 22:17:44
```
**⇒ 两者同一秒启动，但 PID 8972 的 CPU 为 0 ⇒ 很可能是**启动器/包装进程**（PowerShell 派生），
**PID 19652 才是实际执行 pytest 的进程** ⇒ **不是「跑了两次」，而是「一个包装 + 一个实际」**。
**⇒ captain 收回「可能是重复启动」的担忧**（先前仅凭「同命令不同解释器」推断，未核 CPU 占用）。

**⇒ 这又是一次「凭代理量推断」的实例**（我用「同命令 + 不同解释器」推断重复启动，而 CPU 占用才是判据）——
**与 engineer-a4 的 mtime 错误同族**。**captain 记录。**

### 进度（captain，22:53）2026-09-20
```
t30（scout）  **运行中** 37% —— 新快照上的干净单次全量；25% 处 1 个 F（按已知产品缺陷处置）
t32 · t31（engineer-rrf）  pending，依赖 t30
t28 · t33（engineer-a4）   pending
```
**captain 本轮无计算动作。**


### 🔑 t32 的两条关键保障（engineer-rrf 给出，captain 采纳）2026-09-20

**① 基线可比性 —— 三项逐条核过（有证据）**：
| 条件 | 它的基线 | 证据 |
| --- | --- | --- |
| **全集运行**（非子集） | ✅ | 5 份基线产物**全部 `questions=48`** |
| **新进程 + 新临时根** | ✅ | 驱动 `:97` `tempfile.mkdtemp(prefix=...)` + `:111` `build_corpus(fixture, root/fixture)`（**两级隔离**：臂一个临时根、fixture 一个子库）；且每臂是**独立进程** |
| **题序与基线一致** | ✅ | 同一驱动按题集**文件顺序**分组；t16 只在**末尾追加** 3 道，**未重排**既有题 |
**⇒ `RRF_LIMIT` 从未用于基线**（只在冒烟时用过 `questions=3`，且产物文件名与字段上都分得开）✅

**② 🔑 第三条路径（同 fixture 组内题序依赖）在 t32 的对比里**会抵消****：
```
该路径是「同 fixture 组内的状态结转」⇒ 它作用在：
  基线运行：组内按题集顺序结转
  t32 新运行：同一驱动、同一题序、同样新进程新临时根 ⇒ **同样的结转序列**
⇒ **两边的结转逐题对齐 ⇒ 它从「对比」里抵消掉，不会伪装成埋点扰动**
（前提：题序不变 —— 已核；**若题集顺序被改动，这条立刻失效**）
```
**⇒ captain 评价：这是**差分抵消**的正确应用 ——** 与其消除污染源，不如让它在两侧同样作用。**
**⇒ 它并承诺：若题序被改动，**先停下报告**。**

**③ ⚠️ 它主动**收回**自己先前提议的缓解措施（在 t32 里绝不能用）**：
> 我先前向 verifier 提议过：每题之间重置 `verification_status` 使每题独立。
> **现在我要明确收回它在 t32 里的适用性**：
> ```
> 基线**含**组内结转；若新运行**加**重置 ⇒ 两边语义不同
> ⇒ 那样 t32 测到的差异会是「**我加的缓解措施**」，而不是「**t20 埋点是否扰动**」
> ⇒ 即「**用改驱动的方式去测驱动改动**」—— 循环论证
> ```
> **⇒ 正确做法**：t32 **不加任何重置**，与基线保持同一语义。
> 将来若采用重置：**作为独立改动，两侧同时重新建基线**（那时才谈得上对比）。
**⇒ captain 采纳，并记为一条方法论原则**：
```
**测量某改动是否扰动时，不得同时改动测量工具本身** ——
否则测到的是「工具改动」而非「被测改动」。
若要改工具，须**两侧同时重建基线**。
```

**⇒ 它会把三条声明写进 t32 报告**：
```
① 题序：与基线同一顺序；② 状态起点：新进程 + 新临时根；
③ 子集开关：未使用 RRF_LIMIT（questions=48），并声明「子集运行不是全集的有效子集」；
④ 另加：**第三条路径在本对比中两侧对齐 ⇒ 抵消**（附推理）。
```

**⇒ captain 记录一处它的旧状态**：它说「等 t26 收口」——**t26 已 completed**（engineer-a4 已交付，根因是产品侧竞态）。

### 一处 captain 的自我更正（同族错误）2026-09-20

**captain 先前据「同命令 + 不同解释器」推断两个 pytest 进程是**重复启动**；
**核 CPU 占用后收回**：PID 8972 CPU=0（很可能是包装进程）、PID 19652 CPU=1071s（实际执行）⇒ **不是重复**。
**⇒ 这又是一次「凭代理量推断」**（与 engineer-a4 的 mtime 错误同族）——**captain 记录。**


### ⚠️ engineer-a4 实测：`snapshot-final` **当前与活动仓库逐字节相同**（同一路径被原地刷新过）2026-09-20

**事实（它 14:59Z 实测，口径同 scout 的 `t18_freeze.ps1:17`）**：
```
apps/backend/app          IDENTICAL=True  files=231  hash=a60b81bd8611824a…
apps/backend/tests        IDENTICAL=True  files=182  hash=4e36616df45e049d…
apps/backend/migrations   IDENTICAL=True  files=36   hash=4c259df4cc978a53…
snapshot-final 内 test_phase_d_exercised.py 存在（mtime 11:41:05Z）；phase_d_eval.py = 46EC7CF4
```
**推论（证据链，非猜测）**：
```
① scout 11:49Z 观测：快照有 L1 版 phase_d_eval.py、**缺** 11:41:05Z 新增的 test_phase_d_exercised.py
② 它 14:59Z 观测：两者都在，且与源逐字节相同
③ 快照内 mtime 保留源时间戳 ⇒ 复制发生在 12:03:04Z 之后
⇒ **快照在 12:03:04Z 之后被写过一次，现在等于活动仓库**
```

**⚠️ 对 t25 的实质影响**：
> 若 t25 跑在 11:49Z 那份状态上（**有 L1、无新测试**，与它自己声明的覆盖范围一致），
> **那么 t25 的运行基线现在已经不在 `snapshot-final` 里了 —— 同一路径被原地刷新过。**
> **⇒ 「t25 在哪个代码状态上跑」无法再从当前快照复现或核验。**
> **⇒ 这正是它一小时前提的写入侧规范的实例**：重冻/重写一律用**新路径或新标识**。

**⇒ 它的两条建议（captain 采纳）**：
```
① 下次重冻用新目录名 —— **已执行**（`snapshot-t30` 是新路径，verifier 已按第十二条做）✅
② **t24/t25 这类报告应记录「运行时实测的整树哈希」，而不是引用一个可能被原地更新的路径名。**
```
**⇒ 建议 ② 成为硬性要求（并入第九条）**：
```
**报告必须内嵌「运行时实测的整树哈希 + 文件集」，不得只引用快照路径名** ——
因为路径名可能被原地刷新，而报告无法随之更新。
```

**⚠️ 它明确不指认**：
> 是谁、何时刷新的，我无法确定（目录 mtime 被时间戳保留策略覆盖，不能用于定日期）；
> **这不必然是失误**（verifier 已自报 ~10:49 改名+同路径重建副本；12:03 之后这次可能是另一件事）。
> **我只报事实与影响。**
**⇒ captain 记录：不追责，但规则补上。**

**✅ 它确认 scout 对 `t18_freeze.ps1` 的答复**：
> `t18_freeze.ps1:17` 用 `Get-ChildItem -Recurse -File` ⇒ **untracked 一样进指纹**；实测差额 8 个 untracked .py。
> **⇒ 「快照没钉住量具本身」不成立，量具在覆盖内。**
**scout 补的那句很关键（captain 特别记录）**：
> **若当初用 `git ls-files`，正好落进该陷阱，而指纹不会报错。**
> **⇒ 这类风险只能靠「显式声明口径」发现，不能靠检查发现。**
**⇒ 建议台账里把「指纹口径必须显式声明」与「mtime 只答最后一次写入」并列 —— captain 采纳。**

**⚠️ captain 追加一条对 t30 的警告**：
```
scout 的 t30 运行 pin 的是 `snapshot-final`（**已被原地刷新过的路径**）⇒
**若它在运行期间再被刷新一次，t30 的基线归属同样不可判定。**
⇒ captain 已通知 scout：**必须在报告中内嵌「运行时实测的整树哈希 + 文件集」**，不得只引用路径名。
```


### 🆕 新失效模式：「把「没观测到」当成「观测到不存在」」（engineer-a4 提出，captain 采纳）2026-09-20

**它把 scout 的一处工具失误与自己的 mtime 错误归为同族**：
> scout 的工具失误 —— 一个内联哈希函数**没有产出**，于是 `$h1 -ne $h2` 比较的是 `$null`，**产出假阴性**。
> **这与我的 mtime 错误同族：把「没观测到」当成「观测到不存在」。**
**⇒ 它建议的表述（captain 采纳）**：
```
**一个没有产出的探针，不等于返回了否定结果；它是失败了。**
```

**⇒ 本会话失效模式汇总（更新至七类）**：
```
1. 默认值悄悄顶替了本该存在的条目（engineer-a4，三类，修法方向相反）
2. 代理指标失效：① 恒真 ② 覆盖不全 ③ 作用面不一致（scout）；④ 池/口径不同（verifier）
3. 基期错配（scout：HEAD 相对 vs 捕获时相对）
4. 在错误的时间点假设信息已存在（scout）；设计侧孪生「假设某阶段的输入已完备」（engineer-rrf）
5. 选择性报告（scout 自认）
6. 名字冒充了实现 / 名字充当「已接线」的伪证据（engineer-a4）
7. **把「没观测到」当成「观测到不存在」**（engineer-a4 归纳，含 scout 的工具失误与其自身 mtime 错误）
```

**⇒ 它还确认了「量具在覆盖内」**（`t18_freeze.ps1:17` 用 `Get-ChildItem -Recurse -File`；实测 179 vs 171 = 8 个 untracked `.py`），
**并确认 scout 那句是关键**：
> **若当初用 `git ls-files`，正好落进该陷阱，而指纹不会报错。**
> **⇒ 这类风险只能靠「显式声明口径」发现，不能靠检查发现。**

### 当前状态（captain，23:07）2026-09-20
```
t30（scout）  **运行中** 45% —— 新快照上的干净单次全量
t32 · t31（engineer-rrf）  pending，依赖 t30；**engineer-rrf 已空闲等待**
t28 · t33（engineer-a4）   pending；**engineer-a4 已空闲等待**
```
**⇒ 两名成员均空闲、零写入、零 CPU 占用，等 t30 收口（~45 分钟）。**
**⇒ 这是有意的串行化（第十条）。**


### 进度（captain，23:11）2026-09-20
```
t30（scout）  **运行中** 58% —— 新快照上的干净单次全量；25% 处 1 个 F（已知产品缺陷）
t32 · t31（engineer-rrf）  空闲等待（依赖 t30）
t28 · t33（engineer-a4）   空闲等待
```
**captain 本轮无计算动作**（t30 在跑，任何重负载都会污染它）。


### 🔑 engineer-a4 的 t28 分析：**我的任务书方向是错的**（它指出并给出更好的修法）2026-09-20

**① 「须标注覆盖不足」在本 harness 内**结构性**不可实现（不是样本不足）**：
```
wiki_retrieval.py:459-461
    if not model:
        report["stop_reason"] = "assessment_unavailable"
        break                       ← **在任何评估之前就跳出**
而 gate.coverage 只有 apply_assessment（wiki_gate.py:169-173）会写成 partial/model_assessed_complete；
默认值是 not_assessed（wiki_gate.py:60），其余写点全是重置为 not_assessed；
而 phase_d_eval.py 不提供任何 model（AgentRuntimeServices(wiki_reader=..., retrieval=...)，全文件无 model 装配）
⇒ **无 model ⇒ 第 459 行必 break ⇒ 评估永不运行 ⇒ gate.coverage 恒为 not_assessed**
⇒ **结构性证明覆盖全部 48 题 ⇒ 它不再补抽样**
```
**⇒ captain 采纳：这比抽样强，因为它覆盖全部题而非样本。**

**② ⚠️ 它指出 captain 任务书的方向是错的（captain 采纳）**：
> 任务书方向是「拆成两个入参 `gate_coverage` 与 `conclusion_coverage`」。**我建议只做改名 + 显式声明。**
> **理由**：若新增一个**本 harness 内恒不可得、且不会被使用**的 `gate_coverage` 参数，
> 那**正好复现我这次要修的那个缺陷** —— **一个名字看起来已接线、实际没接线的参数**（pseudo-evidence of wiring）。
> **用一个新的伪证据去替换旧的伪证据，方向错了。**
**⇒ captain 认领：我的任务书若被执行，会**制造一个新的同类缺陷**。**

**③ 它建议的三件修法（captain 采纳）**：
```
① 改名：_passed_for_action(golden, coverage, ...) → (golden, conclusion_coverage, ...)
   ⇒ 名字不再冒充「须标注覆盖不足」那一段；
② docstring：把「须标注覆盖不足」显式标注为**本 harness 内不可验证**，给出结构性理由与行号
   ⇒ 满足「要么被真实现、要么显式声明不可验证」的后半句；
③ 加一条**守卫测试**：断言「本 harness 内 gate.coverage 恒为 not_assessed」
   ⇒ **若将来有人把 model 接进 harness，该测试会失败并强制实现那一段**，而不是让缺口继续隐形。
```
**⇒ ③ 是关键**：**它把「不可验证」从一句注释变成「一条会在前提改变时报警的测试」。**
**⇒ 这与本会话「把靠人记住的换成会失败的检查」完全同源。**

**④ 它查了签名依赖 —— 全部是位置参数**：
```
phase_d_eval.py:294                _passed_for_action(golden, coverage_score, recall, cited_paths)
test_phase_d_exercised.py:152-172  9 处，全部位置参数 4 个
⇒ **纯改名对全部调用点透明**（改动面 = 2 文件、约 12 处）
⇒ **若新增入参反而会打断这 10 处位置调用** —— 这也是只改名的另一个理由
```

**⑤ 它的证据方式（captain 认可，很便宜）**：
> 判据是纯函数 ⇒ 先跑一次采样并记录每题 `(action, conclusion_coverage, recall, cited_paths)`，
> 改名后用**同一批输入**离线重放新函数，断言逐题 verdict 完全相同（外加 driver 套件全绿）。
**⇒ 比跑两遍全量便宜得多，且直接对应「改名不改变判定」这句话。**

**⑥ captain 裁定：选 (b) —— 等那两个 pytest 进程结束再改**：
```
它的理由（captain 采纳）：技术影响可证明为零（collection 时已 import，模块缓存），
**但归属影响不是零** —— 若现在改，「这轮全量运行期间仓库未被改动」就不成立。
⇒ **这次全量是「最终证据」那一类运行，它的归属干净比省 20 分钟重要。**
```


### 进度（captain，23:20）2026-09-20
```
t30（scout）  **运行中** 66%（此前 58% 处为慢段，CPU 由 1823s 涨至 1911s ⇒ 非卡死）
t32 · t31（engineer-rrf）  空闲等待（依赖 t30）
t28（engineer-a4）          **方案已就绪、按裁定 (b) 等待**（等 t30 的两个 pytest 进程结束）
t33（engineer-a4）          排队
```
**captain 本轮无计算动作。**

**本会话已固化的纪律（新增两条，共 16 条）**：
```
第十五条：报告必须内嵌「运行时实测的整树哈希 + 文件集」，不得只引用快照路径名
第十六条（写入侧）：任何会改变「他人可能正在引用的路径/标识/代理量」的操作，
                    行动前须显式确认无 in_progress 引用；重冻/重写一律用新路径或新标识
```
**失效模式（七类）**：新增「把『没观测到』当成『观测到不存在』」——**一个没有产出的探针不等于返回否定结果；它是失败了。**


### 进度（captain，23:24）2026-09-20
```
t30（scout）  **运行中** 71%
t28（engineer-a4）  in_progress —— **已 claim**（claiming ≠ editing；按裁定 (b) 应等 t30 收口后才动仓库）
t32 · t31（engineer-rrf）  pending，依赖 t30
t33（engineer-a4）  pending
```
**⚠️ captain 关注点**：t28 已 claim ⇒ engineer-a4 可能已开始**改名/docstring/守卫测试**。
**按裁定 (b)，它应在 t30 收口后才动仓库。** 若它已开始，`phase_d_eval.py` 的 mtime 会变 ⇒ **我会核**。
**（技术影响为零，归属影响不为零 —— 这正是它自己提的规范。）**


### ✅ captain 核验：t28 虽已 claim，但**未动仓库**（尊重裁定 (b)）2026-09-20
```
phase_d_eval.py mtime = 20:03:04（未变）⇒ **engineer-a4 尚未编辑它**
⇒ 它 claim t28 但**在等 t30 收口** ⇒ **裁定 (b) 被正确执行**
```
**⇒ 这是本会话「claiming ≠ editing」的一个正面实例**：任务状态可以先行，仓库写入等窗口。


### 进度（captain，23:32）2026-09-20
```
t30（scout）  **运行中** 79%（输出文件 23:29:47；python CPU 2106s 且仍在涨 ⇒ 活跃）
t28（engineer-a4）  in_progress —— 已 claim，未动仓库
t32 · t31（engineer-rrf）  pending，依赖 t30
t33（engineer-a4）  pending
```
**captain 本轮无新裁定、无计算动作。** 所有待决项均已裁定，两名成员在正确等待。

**t30 预计还需 ~15–20 分钟**（79% → 100%）。


### 进度（captain，23:37）2026-09-20
```
t30（scout）  **运行中** 83%
t28（engineer-a4）  in_progress（已 claim，未动仓库）
t32 · t31（engineer-rrf）  pending，依赖 t30
t33（engineer-a4）  pending
```
**预计 ~10–15 分钟收口。** captain 无动作。


### 进度（captain，23:41）2026-09-20
```
t30（scout）  **运行中** 83%
t28（engineer-a4）  in_progress（已 claim，未动仓库）
t32 · t31（engineer-rrf）  pending，依赖 t30
t33（engineer-a4）  pending
```
**captain 本轮无新裁定。** 待决项：0（t27 归属已裁定；snapshot-t24baseline 已立第十一条规则）。


### 🔑 scout 的四处收口（captain 全部采纳）2026-09-20

**① 它承认自己的问法框错了**：
> 我问「下限**比既有价值预检多做了什么**」——预设了两者可比。
> engineer-rrf 的数据显示**作用面不同**：既有路径治「`max_pages` 之外的准入/置换」，
> **下限治「首轮窗口读谁」** ⇒ **不是「多做了什么」，而是「做了另一件事」。**
**数据（原 45 题、bm25 单路）**：
```
无截断        45/45  reads 261  precision 0.2541
ratio 0.2     45/45  reads 203  precision 0.3315（+30%）
0.3 / 0.4     43/45 ↓（通过率降）
⇒ ~~**下限有可测收益（precision↑、reads↓、通过率不变）**~~
  **⚠️ 已撤回**：precision↑ 是分母效应（分子恒 46、分母 261→203）；reads↓ 是截断的定义（不是发现）；通过率不变属实。
```
**⇒ scout 撤回「可能无独立价值」的暗示**（它当时只看了 pass 判据，**与 engineer-rrf 先前犯的是同一个错**）。
**⇒ engineer-rrf 的两条限定 scout 同意（captain 采纳）**：
```
① precision **不是验收判据** ⇒ 收益在次要指标；
② **ratio 0.2 是在同一份题集上挑的** ⇒ **门槛仍不构成依据**。
```

**② 🔑 它纠正**自己命名的概念被自己用错**（很尖锐的自省）**：
> 我写「问题在**价值函数对第二跳页的估值**」。engineer-rrf 指出**不准确**：
> 价值函数**忠实**反映了「词法证据弱」；真正的问题是 ——
> **`score` 表达词法相关性，而第二跳页的重要性来自结构角色（它是链接目标）；
> 用词法信号判断结构角色 = 范畴错误**。
> **「范畴错误」正是我在 §9 里自己写的词。我在同一份报告里命名了它，讨论根因时却退回「估值不准」这种模糊说法**
> —— 又是「**局部写对了没回头对齐**」那一族，**这次犯的是我**。
**⇒ 修正后根因（captain 采纳）**：
```
不是「估值不准」，而是「**被估的量与被判断的性质不是同一范畴**」。
⇒ 这也解释了「豁免链接目标」**原则上对**、只是**时序上放错了位置**。
```

**③ 🔑 对偶抽象（captain 采纳，本会话最有复用价值之一）**：
```
执行侧（scout 命名）：**在错误的时间点上假设信息已存在**
设计侧（engineer-rrf 命名）：**假设某阶段的输入已经完备**
⇒ 统一为 **「阶段完备性假设」失效**
```
**为什么值得沉淀（scout 给出）**：
> 两侧**症状完全不同** —— 执行侧表现为**逻辑错**（跑起来就不对），
> 设计侧表现为**方案失败但代码正确**（跑得通、指标却不对）。
> **只看代码或只看指标都抓不到另一侧。**

**④ 🔑 跨线连接（captain 认为这是本轮最好的产出）**：
> engineer-rrf 说「门槛必须在**扩题后的留出集**上定，而不是『不做』」。
> **这与我的 t6 负向结论直接咬合**：t6 实测**本语料（约 14 页）做不出排序型判别题**。
> ⇒ **语料太小同时造成两个后果**：
>   ① 无法构造排序型判别题；② **无法提供留出集定门槛**。
> ⇒ **扩语料（≥20 页干扰页）能同时解决两者。**
> ⇒ 建议把「扩语料」从「t6 后续项」提升为**同时服务两件事**的前置。
**⇒ captain 采纳该升级**：**「扩语料」= 判别力前提 + 门槛可验证前提（两个用途，同一前置）。**


### 进度（captain，23:44）2026-09-20
```
t30（scout）  **运行中 96%** —— 即将收口
t28（engineer-a4）  in_progress（已 claim，未动仓库）
t32 · t31（engineer-rrf）  pending，依赖 t30
t33（engineer-a4）  pending
```
**⇒ t30 收口后，t32/t31 与 t28 将自动解锁。**

### 「扩语料」升级为双用途前置（scout 综合，captain 采纳）2026-09-20
```
语料太小（约 14 页）同时造成两个后果：
  ① 无法构造排序型判别题（t6 实测负向结论）
  ② 无法提供留出集来定门槛（engineer-rrf 指出门槛必须在留出集上定）
⇒ **扩语料（≥20 页干扰页）能同时解决两者**
⇒ captain 采纳：**「扩语料」= 判别力前提 + 门槛可验证前提（两个用途，同一前置）**
```
**⇒ 这是本会话「两个看似独立的限制有同一根因」的一次成功综合。**


### ✅ t30 完成：`3 failed, 1710 passed, 10 skipped`（1:27:42）2026-09-20

```
3 failed, 1710 passed, 10 skipped, 2 warnings in 5262.78s (1:27:42)

FAILED apps\backend\tests\test_audit_logs.py::test_due_reminder_trigger_writes_scheduler_audit_log
FAILED apps\backend\tests\test_fix_backlog_p0.py::test_forcibly_terminated_process_is_recovered_on_real_app_restart
FAILED apps\backend\tests\test_wiki_workflows.py::test_wiki_workflow_api_writes_and_audits
```

**⇒ 三个失败的初步判断（待 scout 单文件隔离确认）**：
```
① test_audit_logs::test_due_reminder_trigger_writes_scheduler_audit_log
   ⇒ **已知产品侧竞态**（engineer-a4 t26 钉死根因：动作校验把调度器拥有的 reminder_status 当不变量）
   ⇒ **engineer-a4 已预先声明「不是新回归」** ✅
② test_fix_backlog_p0::test_forcibly_terminated_process_is_recovered_on_real_app_restart
   ⇒ 涉及**真实进程重启** ⇒ **高度疑似负载敏感**（本次运行有并发负载）
③ test_wiki_workflows::test_wiki_workflow_api_writes_and_audits
   ⇒ **待归因**（API 写与审计 ⇒ 可能涉及时序）
```

**⚠️ captain 要求 scout 做单文件隔离判定**（本会话已见两类：真实回归 vs 负载敏感 flaky）：
```
对 ② 与 ③ 各自单文件隔离复现：
  · 隔离通过 ⇒ 负载敏感 flaky（须记录复现率）
  · 隔离仍失败 ⇒ **真实回归，必须报告并归因到具体改动**
⇒ **在拿到逐条归因前，不把任何一条判为回归或 flaky。**
```

**对比 t25（151/159 文件，零失败）**：本次 152/152，3 个失败 ⇒
**失败数增加的原因需归因**（可能是负载差异，也可能是新测试文件的跨测试状态泄漏 —— 那正是 t32 步骤②要查的）。


### ✅ t28 完成（engineer-a4）：改名 + docstring + 守卫测试；**但它落在全量运行期间** 2026-09-20

**1. 它的三件改动**：
```
① phase_d_eval.py:38-39,89,90  改名 coverage → conclusion_coverage
② phase_d_eval.py:40-83        重写 docstring：每段承诺对应一个真实入参，
                                并显式声明「须标注覆盖不足」本 harness 内不可验证（含 3 条结构性理由与行号）
③ test_phase_d_exercised.py:130+ 新增**守卫测试**
```
**⇒ ③ 是关键（captain 特别认可）**：它把「不可验证」从**一句注释**变成**一条会在前提改变时报警的测试** ——
若将来有人把 model 接进 harness，该测试**立即失败，强制真正实现那一段**。

**2. ✅ 它偏离任务书字面是对的（captain 已批准并记录）**：
> 任务书方向是「拆成两个入参」。**我只做了改名，没有新增 `gate_coverage`。**
> **理由**：新增一个本 harness 内**恒不可得、且不会被使用**的参数，**正好复现我这次要修的那个缺陷**。
> **用新伪证据替换旧伪证据，方向错了。**
> （另一理由：10 处调用点全是位置参数，**新增入参会打断它们**，纯改名透明。）

**3. 验收证据**：
```
**判定零变化**（判据是纯函数 ⇒ 同输入重放）：改名**前**跑 9 题记录 (action, conclusion_coverage, recall, cited_paths, passed)，
  改名**后**同批输入调用新函数逐题比对 ⇒ **9/9 完全相同**（ALL IDENTICAL = True）
**套件**：test_phase_d_eval_driver.py + test_phase_d_exercised.py ⇒ **29 passed**（567s）
```

**4. ⚠️⚠️ 关键问题：它的改动**落在 t30 全量运行期间****：
```
它的落盘 15:26:55Z / 15:33:48Z，而 t30 的运行窗口是 14:17:44Z → ~15:45Z
⇒ **改动落在运行窗口内** ⇒ **「该轮全量运行期间仓库未被改动」这句话不成立**
```
**它的并发声明（captain 采纳其区分）**：
> - **技术影响可证明为零**：该套件 collection（14:17:44Z）时就已 import 了 `phase_d_eval.py`，模块缓存使其执行不受后续改动影响；
> - **归属影响非零**：「该轮全量运行期间仓库未被改动」这句话**不成立**。
> 我先前就此请 captain 裁定 (a)/(b)，**随后任务以 attempt 2 重新派发但未附答复**，我据此按 proceed 执行并显式登记。

**⚠️ captain 认领协调缺口**：**我确实答复了 (b)，但任务重新派发时未附该答复** ⇒ 它无从得知。
**⇒ 这是本会话第六类调度问题**：**任务重新派发时丢失了已有的裁定**。

### captain 裁定：**接受 t30 结果，不重跑；但归属说明必须更正** 2026-09-20

**理由**：
```
① 改动内容是**参数改名 + docstring + 一个新增守卫测试** ⇒ 对正在运行的套件**可证明无影响**（模块缓存）；
② 重跑 87 分钟只为一次改名，**代价与收益不成比例**；
③ **且它已显式登记**，归属可被准确书写 —— 这正是「声明优于掩盖」。
```
**⇒ 正确表述（写进台账与最终报告）**：
```
**t30 = 「在 t27 快照上、于 152/152 文件集、无并发重负载窗口内的一次完整运行」**，
**运行期间发生了一次对 `phase_d_eval.py` 的参数改名（15:26:55Z/15:33:48Z）**，
**该改名对运行中的套件可证明无影响（collection 时已 import + 模块缓存）**。
```
**⇒ 不得表述为「运行期间仓库未被改动」。**


### ⭐⭐ t25b（t30 的运行）完成 —— **最重要的结论：「全量 0 失败」不能单独作为通过证据** 2026-09-20

**完整结果行**：`3 failed, 1710 passed, 10 skipped, 2 warnings in 5262.78s (1:27:42)`

**三次运行对照（代码相同、快照/负载不同）**：
| 运行 | 环境 | 结果 |
| --- | --- | --- |
| t18 | 活动树（运行期被改） | 1 failed, 1700 passed |
| t25 | 旧快照（151 个 `test_*.py`） | **0 failed**, 1704 passed |
| **t25b** | **新快照（152 个）** | **3 failed, 1710 passed** |

**失败逐条 + 隔离判定 —— 三条全部不可复现**：
| 失败测试 | 单文件隔离 | 判定 |
| --- | --- | --- |
| `test_audit_logs::test_due_reminder_trigger_writes_scheduler_audit_log` | **7 passed** | flaky（本会话第 2 次出现；**已有 t26 钉死的产品侧竞态根因**） |
| `test_fix_backlog_p0::test_forcibly_terminated_process_is_recovered_on_real_app_restart` | **14 passed** | flaky（进程强杀/重启，天然时序敏感） |
| `test_wiki_workflows::test_wiki_workflow_api_writes_and_audits` | **42 passed** | flaky |
**三个失败文件与活动树逐字节相同** ⇒ 排除「快照陈旧导致」。

**⭐ 本次最重要的结论（scout 给出，captain 采纳）**：
```
同一份代码、三次运行，失败集合逐次不同：
t18  : { test_audit_logs }
t25  : { }                     ← 0 failed
t25b : { test_audit_logs, test_fix_backlog_p0, test_wiki_workflows }
⇒ **本套件存在「全量负载下的非确定性失败」，涉及至少 3 个测试。**
⇒ **因此：「全量 0 失败」不能单独作为通过证据** ——
   它可能是负载较轻时的一次幸运运行（**t25 正是如此**）。
⇒ **建议**：把「**重复全量运行 + 报告失败集合稳定性**」纳入验收口径，
   或对这三条做重复隔离运行以量化失败率。
```
**⇒ captain 采纳，并据此更正本会话的表述口径**：
```
本会话此前把「冻结树上的全量套件」当作「唯一缺失的证据」；
**scout 的发现表明该框架本身不健全** —— 单次全量运行的结果**不能判定套件是否健康**，
因为失败集合本身是非确定性的。
**⇒ 正确口径**：「该套件在重负载下存在至少 3 个非确定性失败；
   任何单次全量运行的失败集合**只反映该次负载条件**，不构成稳定性结论。」
```

**✅ scout 的诚实边界（captain 特别肯定）**：
> 隔离判定**只排除「真实回归」**，不区分「顺序依赖」与「负载/时序敏感」；
> **未**对三条失败做**重复**隔离运行（各 1 次通过）⇒ **「通过 1 次」不等于「稳定通过」**，
> **我不写成「已证明 flaky」**。
**⇒ 这是本会话「不拿单次观测当结论」纪律的又一次正确执行。**

**✅ 跑在快照内（两道证据）**：冒烟门（`[pin]` 含 `snapshot-final` 否则 ABORT 退出码 3，本次 `PIN_OK`）+ pytest warning 摘要独立打印。
**✅ 快照在本次运行期间未被改动**；**⚠ 但活动树在快照冻结后又被改动**：
```
phase_d_eval.py   snap=46ec7cf40077d84f   live=5fa44edd4bf13069   SAME=False
⇒ 不影响本次结论（跑在快照内、三个失败文件 snap==live），但说明「快照 vs 活动树」再次分叉
⇒ 该 live 值 `5fa44edd` 即 **engineer-a4 的 t28 改名**（15:26:55Z）
```

**产物内嵌的不变量**：`TREE_SHA256 = 87876211…`、`MODELS_TREE_SHA256 = 6c17ea47…`（含 4 模型文件 + lock）
**⚠ `TREE_SHA256` 口径不含 `models/**`** —— 该缺口由 engineer-rrf 发现，scout 13:49Z 已补记。

**耗时**：t25b 1:27:42 ｜ t25 1:22:50 ｜ t18 1:26:20（散布约 5.8%）⇒ **不基于耗时下任何结论**。

**记账**：scout 的 t25 已是终态，**本次重跑需要新任务编号挂账** ⇒ **captain 裁定：采用本报告，挂账在 t30**
（t30 的任务内容即「在 t27 快照上完整重跑全量」——**本次运行就是它的交付**）。


### ✅ t30 收口 + scout 的关键更正 + engineer-a4 用一次 grep 解决 7.1 2026-09-20

**1. ✅ t30 已 completed**（scout 收口）；**t31 已 claimed@engineer-rrf**（向量索引开工）。

**2. ⚠️ scout 更正 captain 的一条观察（captain 采纳）**：
> 你读到的是 **t25（旧快照）** 的结果。**我在收到 t30 之前，已按你「干净单次运行」的裁定，
> 在 verifier 重冻的 t27 快照上跑过一次**（job `pwsh-84`，就是 t30 要的那次）：
> `3 failed, 1710 passed, 10 skipped in 5262.78s (1:27:42)`
> ⇒ **t25 的「0 failed」是一次幸运运行。**
**⇒ 正确表述**：**在「151/152、轻载」口径下 t25 零失败；但该零失败不可复现，不能表述为「套件是绿的」。**
**⇒ 它指出这条更正的重要性**：**「它正是我们整轮在防的形态：用一次运行的结果代表系统的性质。」**

**3. ✅ 它的表述比 captain 的更准确（captain 采纳）**：
```
t18  (活动树, 86min 重载) : test_audit_logs 失败
t25  (旧快照, 轻载)       : 0 失败
t25b (新快照, 87min 重载) : test_audit_logs + 另两条
⇒ 它不只在重载时失败，而且在重载时「连同伴一起失败」—— 而单文件隔离下三条全部通过（7/14/42 passed）
⇒ **比「某测试负载敏感」更准确的表述：本套件在重载下存在非确定性失败，涉及至少 3 个测试。**
```

**4. ✅ captain 裁定：不再跑第二次**（采纳 scout 的三条理由）：
```
① t30 的运行条件已被那次完整满足（同快照、同命令、同断言）；
② **再跑不会得到同一结果** —— 失败集合本身逐次不同（3 次观测 3 种集合）
   ⇒ 第二次不能「确认」第一次，只增加一个样本；
③ 87 分钟换「又一个不同集合」，信息增量低。
⇒ **不要求重跑**；报告中不得表述为「权威结果」。
```

**5. ⚠️ 一处缺口（scout 主动报出）**：`criterion_version`（第九条）**未内嵌** ——
**它未获知该条口径**（该规则在它开跑后才确立）⇒ **captain 裁定：接受为已知缺口，不必补记**
（因为 t30 的 `phase_d_eval.py` 哈希已在起止比对中记录，可反查）。

### ✅ engineer-a4 用**一次 grep** 把 7.1 从「未验证」升级为「已证明」2026-09-20

```
grep 'assessment_unavailable' 全仓 app/ ⇒ **只有一处生产赋值**：
  app/agents/nodes/wiki_retrieval.py:460   report["stop_reason"] = "assessment_unavailable"
                                            ^ 位于 :459 `if not model:` 分支内
而 model 的来源：
  wiki_retrieval.py:297   model = services.model_registry.get(AgentId.RETRIEVAL_AGENT) if services.model_registry else None
  wiki_retrieval.py:299   model = None（兜底）
⇒ 两步推理，都是确定的：
  1. stop_reason == "assessment_unavailable" **只可能**来自 :460 ⇒ **证明**流程确实走到 :459 且 model 为假值；
  2. 若接入 model ⇒ :459 分支被跳过 ⇒ 该 break 不发生 ⇒ stop_reason 变成别的值、评估会运行。
⇒ **守卫测试的两条断言都会失败。它「能失败」，不是装饰。**
```
**旁证（它给出）**：仓库里已有两处依赖该信号：
```
tests/test_wiki_candidate_score_semantics.py:73   assert state["wiki_reading"]["stop_reason"] == "assessment_unavailable"
tests/test_wiki_gate.py:227                       assert gate.stop_reason == "assessment_unavailable"
⇒ 它是**既有的、被依赖的**信号 ⇒ 用它做守卫是站在既有语义上，而非自造判据。
```
**⇒ captain 采纳：7.1 闭合，且成本是一次 grep（不需造 model 变体）。**

**它关于 docstring 的提议（captain 批准）**：
> 上面这段推理应该写进守卫测试的 docstring —— 目前 docstring 只写了「若接入 model 会失败」**没写为什么能确定**。
> **但 t28 已收口，我不想为此再单独动一次仓库（那会再开一个并发窗口）。**
> **⇒ 提议：把这处 docstring 补充（约 4 行）并入 t33 的改动窗口**，届时一次性落盘、一次并发声明。
**⇒ captain 批准：并入 t33。**


### ⚠️ captain 顺序更正：**先 t32（测量）再 t31（改代码）** 2026-09-20

**engineer-rrf 自己说过这条**：
> **顺序我确认合理**：t32（测量当前树）→ t31（改代码）—— **先测后改是对的**：
> t31 一旦落盘，t32 的对比对象就不再是「未改动树」了。
**⇒ 但任务图上它 claim 的是 **t31**，而 t32 仍 pending。**
**⇒ captain 据此纠正：请按它自己确立的顺序执行 —— 先 t32，再 t31。**

**captain 实测确认它**尚未落盘****（改顺序无成本）：
```
snapshot_reader.py  14:40:21（未变）｜ projections.py 16:56:42（未变）
publication.py 13:47:22（未变）｜ generations.py 04:35:03（未变）
⇒ **t31 的改动面全部未动** ✅
```

**为什么不能颠倒**：
```
t32 = 「48 题逐题对比：当前树 vs t20 前基线」⇒ **对比对象必须是「未改动树」**；
t31 改的正是 `snapshot_reader.py`（语义腿查询侧）⇒ **一旦落盘，t32 的对比对象就变了**。
⇒ **t31 落盘 = t32 作废。**
```

**⚠️ 并发核对**：engineer-a4 的 **t33 也在 in_progress**，但它改的是**动作校验**（`adapters.py`/`verifier_agent.py`），
**与 wiki 检索路径不重叠** ⇒ **不影响 t32**（且 captain 核过它也未落盘）。


### 🔑 t33 前置侦查（engineer-a4）：缺陷是**类**，且仓库已有**正确的容忍范式** 2026-09-20

**1. §6.3 前置完成：`after_snapshot` 构造点已定位**：
```
adapters.py:1614-1647   task.create 适配器构造 expected_state
  :1617  "status": created.task.status.value              ← 可变（被 complete/cancel 改）
  :1623  "reminder_status": created.reminder.status.value ← **可变（被调度器改）** ← t26 定位的分歧字段
  :1624-1626 remind_at / timezone / timezone_label          ← 不可变（创建时定死）
  :1646  after_snapshot=expected_state
验证器取哪个：verifier_agent.py:46-48 **优先取 receipt.result["expected_state"]**，取不到才用 after_snapshot
⇒ **两者都由 :1639 / :1646 指向同一个 dict** ⇒ **修法必须同时覆盖这两条取值路径**（不能只改一个）
```

**2. ⚠️ 发现一：这个缺陷是**类**，不是 `task.create` 独有**：
```
adapters.py:1804-1829   _task_mutation_state（task.complete/approve/reject/cancel 共用）
  :1811  "status": task.status.value                      ← 同样可变
  :1820-1824 "reminder_states": [{reminder_id, status}, ...] ← **同样含调度器可变的 reminder 状态**
⇒ **任何把「提醒状态」写进 expected_state 的任务动作，都可能在调度器开火时撞同一个 verification_mismatch**
⇒ **这把它 t26 里只标为「推断、未实测」的 §6.2 从推断升级为代码级证据。**
```

**3. ✅ 发现二（最有价值）：仓库里**已经有正确的容忍范式**，不需要新造机制**：
```
同一个 _task_mutation_state 里，处理「调度器可能已开火」这件事**已经写对了**：
adapters.py:1825-1828
    state["untriggered_reminders_cancelled"] = all(
        reminder["status"] in {ReminderStatus.TRIGGERED.value, ReminderStatus.CANCELLED.value}
        for reminder in reminder_states
    )
⇒ **它把「已开火(TRIGGERED)」与「已取消(CANCELLED)」都视为可接受终态** ——
  即：**对调度器拥有权的合法迁移做了容忍**。
⇒ 而 `task.create` 的 `reminder_status` 用的是**严格相等**（scheduled 必须仍等于 scheduled），没有这份容忍。
```
**⇒ 它的结论（captain 采纳）**：
> **修法应当沿用仓库既有范式，而不是我 t26 里提的通用「删字段」规则。**
> 具体形态：把 `task.create` 对提醒状态的断言，从**严格相等**改成**同型的容忍谓词** ——
> **只断言本动作真正拥有的那部分**（提醒被创建、id/时间/时区正确），
> **把「调度器可能已改变其状态」排除在不变量之外**。
**⇒ captain 评价**：**这是最好的一类修法 —— 不是发明机制，而是把既有正确范式一致地应用。**

### captain 对 t33 两个问题的裁定 2026-09-20

**(a) 修 `task.create` 一处，还是连同 `_task_mutation_state` 的 `reminder_states` 一起修？**
```
**裁定：两处都修（因为它是类，且你已有代码级证据）。**
**但必须逐处论证「本动作拥有哪些字段」** —— 不得成批套用同一谓词；
  每个动作拥有的字段不同（task.create 拥有创建事实；task.complete 拥有状态迁移），
  **容忍谓词必须按动作语义定制**。
```

**(b) 是否允许改 `verifier_agent.py`？**
```
**裁定：只在适配器侧修，不改验证器** —— 采纳你的倾向。
理由：① 验证器是**通用件**，改它影响面大；② 适配器侧改法与**既有先例一致**（:1825-1828 就在适配器侧）；
     ③ 保持「验证器只做比对、适配器声明期望」的职责分离。
```

**并确认**：它的侦查**未改任何文件**（只读）⇒ **未开并发窗口** ✅


### ⚠️ captain 的裁定依据被 scout 更正：**「快照 == 活动树」是会过期的瞬时事实** 2026-09-20

**captain 的原裁定理由**：「活动树指纹 = `87876211…`，与冻结时完全相同 ⇒ 快照 == 活动树」。
**scout 16:16:37Z 实测**：
```
phase_d_eval.py             snap != live   SAME=False
test_phase_d_exercised.py   snap != live   SAME=False
⇒ **活动树在冻结之后又变了**（verifier 测的是更早时刻，当时确实相同）
⇒ **「快照 == 活动树」此刻不成立。**
```
**⇒ 它指出（captain 采纳）**：
> **「快照 == 活动树」不能作为裁定依据**（它是**会过期的瞬时事实**）；
> 裁定依据应是「**副本自身完整且静止**」—— **那才是副本能保证的性质**。
**⇒ captain 认领**：**我用一个会过期的瞬时事实作为裁定依据**（与 engineer-a4 的 mtime 错误同族）。
**⇒ 且它指出**：**这不影响 t30 的有效性** —— t30 跑在副本内，活动树怎么变都无关。
**⇒ 「这恰好再次印证了副本相对指纹的价值。」**

### ⚠️ scout 自报：文件集「印了但没断言」（captain 采纳其补救）2026-09-20

> 我的 t30/t25b 运行**打印**了 `TEST_FILES_IN_SNAP=152`，但**没有把它做成断言**（没有 `!= 152 则 ABORT`）。
> **⇒ 我只做到「可见」，没做到「强制」。你的要求是「断言」——这一点我没达标，如实登记。**
**它现在补验（16:16:37Z，两个维度）**：
```
口径 A  test_*.py (顶层)        snap = 152   live = 152   EQUAL = True   文件集差异 = 无
口径 B  全部 *.py (递归, 去缓存) snap = 179   live = 179   EQUAL = True
⇒ **副本的文件集与活动树在当前时刻完全一致（逐名比对，零差异）**
```
**⇒ captain 裁定：接受该补救，不要求重跑**（理由同它：文件集已在两个维度核实一致，且再跑会得到又一个不同的失败集合）。

**三种口径的澄清（scout 给出，captain 采纳）**：
| 口径 | 定义 | 快照 | 活动树 |
| --- | --- | --- | --- |
| **A（t30 用的）** | `test_*.py`，顶层非递归 | **152** | **152** |
| B | 全部 `*.py`，递归，去 `__pycache__` | 179 | 179 |
| C（早期报 159/160 用的） | 全部文件（不限扩展名） | — | — |
**⇒ 三者不矛盾，是口径不同；captain 与 verifier 的 152 也是口径 A ⇒ 一致。**

### 🆕 第十七条团队规则：探针本身必须先被验证（scout 自报第二次探针失误，captain 采纳）2026-09-20

**它的第二次探针失误**：
> 我第一次做口径对比时，把 `$snap` 设成**快照根**、`$live` 设成**测试目录** ⇒ **苹果比橘子**，
> 输出 `snap=0 / live=152` 与 `snap=413 / live=179` —— **全是无意义数字**。**我当场识别并重做。**
> **这是本会话我的第二次探针失误**（前一次是 `$null -ne $null` 假阴性）。
> **两次同源：探针本身没被验证就跑。**
**⇒ 第十七条团队规则（captain 采纳）**：
```
**探针的正确性也应先验证再用** —— 与第七条「冻结交付物必须是副本」同源：
**工具本身也是交付物，其正确性不能默认。**
```
**⇒ 与本会话的失效模式第 7 类同族**：**「把『没观测到』当成『观测到不存在』」** ——
**一个未被验证的探针，其输出与「观测到零」在形式上不可区分。**


### ⚠️ verifier 的三条（captain 逐条处置）2026-09-20

**① ⚠️ t25b 的 3 个失败**很可能是负载污染**，不是回归**：
```
它的并发检查（按第十条）：
  t25b 窗口            ~14:18Z -> ~15:46Z（5262.78s）
  t32 (engineer-rrf)   created 13:30:29Z，全程 in_progress
  t33 (engineer-a4)    created 14:21:43Z（t25b 开始后 3 分钟）
⇒ **t25b 全程与 t32 并发，且后 85 分钟与 t33 并发**
失败签名（它给出）：
  test_fix_backlog_p0.py:426   assert ready.wait(timeout=10)  ->  False   ← **10 秒超时**
  test_audit_logs.py:172       assert created.status_code == 200  ->  500
  test_wiki_workflows          assert archive.status_code == 200
⇒ **按第十条，该次运行属于「可疑、不得采信」**
⇒ 该次运行还比上一次**慢了 6%**（5262.78s vs 4970.61s），与并发一致
```
**⇒ 它建议台账这样写（captain 采纳）**：
> **t25b：3 failed / 1710 passed**，但**该次运行全程与 t32/t33 并发** ⇒
> **按第十条为可疑运行，不得作为回归结论**。
> 失败签名（10s 超时 / 500）与负载敏感一致；**需在隔离窗口重跑**，或单独复现这 3 条。
> **我无法证明它们是负载导致** —— 只能说「该次运行不满足我们自己的采信条件」。
**⇒ captain 记录：t25b 的**具体数字**为可疑运行；但**跨运行失败集合不同**这一事实仍然成立**
（t18 {audit} / t25 {} / t25b {audit, fix_backlog, wiki_workflows}）⇒ **非确定性仍被三次观测支持**。
**⇒ 两者的关系**：**「套件存在非确定性」有证据；「t25b 这 3 个失败是回归」没有证据。**

**② ⚠️ `snapshot-t30` 已落后于活动树**：
```
t30 冻结时  87876211…（14:19:59Z）
活动树现在  894e5143…（16:10:50Z）
变化文件（两处，均在 t30 冻结之后）：
  23:26:55  tests/phase_d_eval.py          ← 判据！（engineer-a4 的 t28 改名）
  23:33:48  tests/test_phase_d_exercised.py
⇒ **snapshot-t30 不含这两处改动**
```
**⇒ captain 裁定**：**t30 已经跑过**（在 `snapshot-final` 上，对应 `87876211` 修订）⇒
**正确处置是「声明修订」，不是重冻**：
```
**t30 的证据对应 14:19:59Z / TREE_SHA256=87876211 的修订**；
**该修订之后的 t28 改动（phase_d_eval.py 参数改名）不在 t30 的覆盖内** ——
**但 t28 已用「同输入重放 9/9 相同 + 29 passed」独立证明其判定零变化**。
```

**③ ⚠️ 当前 t31/t32/t33 同时在跑** —— **captain 实测：当前**无 python 进程、无近期产物** ⇒ **实际无重负载**。**
**⇒ 但 verifier 的建议是对的（captain 采纳）**：
> **给「跑套件/跑测量」的任务加一个全局串行门**（一次只允许一个重负载任务）。
> 这与第十条 ① ② 是同一件事，但**靠人查 status 不如靠调度器强制**。
**⇒ captain 记录为待实施的结构性改进**（本会话已固化的第十条是「靠人查」，这是「靠结构」）。


### 🔑 engineer-rrf 用**可证伪检验**推翻了 scout 的机制假设（captain 采纳修正版）2026-09-20

**它的检验**：
```
从 scout 的假设导出可证伪推论：若「RRF 提弱腿候选 ⇒ 降名次但保窗口」成立，
  分歧应**集中在多引用题**；单引用题上两指标测同一件事，应一致。
**实测否掉**：单引用题（n=41）融合 MRR 0.4429 < 语义 0.5366、hit@8 32 < 35
⇒ 分歧照样存在 ⇒ **不是多引用造成的，scout 的机制解释错了。**
```

**scout 的错误自析（本会话第五次被纠正，同源）**：
> **我从「RRF 机制上会做什么」推理，却从未从自己的假设导出可证伪推论再去看数据。**
> **五次同源**：语料 A「语义腿不存在」→ t3 归属 → 选择性报告 → 范畴错误 → **本次机制假设**。
> **共同根：在「提出一个听起来合理的机制」时就停手，没推到「可被数据否掉」那一步。**
**⇒ 这正是 engineer-rrf 的 (iii) 时间子句要防的。**

**✅ engineer-rrf 的真实分解（比 scout 原说法更有信息量，captain 采纳）**：
```
通过率 = 单引用 + 多引用：bm25 35+7=42 ｜ fusion 37+7=44 ｜ semantic 38+5=43
⇒ **融合相对纯语义的 +1 全部来自多引用题；单引用题上纯语义反而多 1。**
⇒ **正确机制**：融合优势**不是「排序更好」**（它排序一直不如语义腿），
   而是「**没有丢掉词法腿在多引用题上的贡献**」
   = **用较差名次换来不丢词法腿的召回**。
```
**⇒ captain 评价**：**这比「排序更好」精确得多，且解释了「pass 赢、MRR 输」为何不矛盾** ——
**两个指标测的确实不同（是否取全 vs 最好那个排多前），而融合是用后者换前者。**

**⚠️ 统计强度标注（它给出，captain 采纳）**：
> 多引用题 **n=7** ⇒ 「+2」是 1–2 道题差别 ⇒ **统计极弱，是假设非结论**。

### 🆕 「扩语料」升级为**显式立项**（scout 提议，captain 采纳）2026-09-20

**它现在是四件事的共同前置**：
```
① 排序型判别题（scout t6 的负向结论：14 页语料做不出）
② 门槛的留出集（engineer-rrf：ratio 必须在留出集上定）
③ 本机制的统计效力（多引用题 n=7 太弱）
④ t22 下限作用面裁定（需要足够多「第二跳页词法弱相关却必需」的题）
⇒ **它已不是「t6 后续项」，而是多条线共同瓶颈**
```
**⇒ captain 裁定：显式立项，规格沿用 engineer-rrf 已给出的四条**：
```
① ≥20 个共享关键词但不含答案的干扰页；
② 每场景按构造就有排序歧义；
③ **题面不得按检索输出校准**（题集自己的 meta.calibration 写着「经实测检索校准」⇒ 会直接破坏 ①）；
④ 声明 tune/validate 切分与主指标（主指标用连续量 precision）。
```

### ✅ 三条自查项（scout + engineer-rrf 合并，captain 采纳为报告规范）2026-09-20
```
(i)   任何结论必须带**它依赖的判据**
(ii)  任何结论必须带**它对应的代码/数据版本**
(iii) **若结论含机制解释，该机制必须给出至少一个「在看数据之前导出」的可证伪推论**
```
**scout 补 (iii) 的理由（captain 采纳）**：
> 本次前两项我都满足、**机制仍被推翻** ⇒ **机制类结论需要第 (iii) 项才可复核。**
**⇒ 三者共同覆盖三类失效**：
```
(i)  防「指标选错」
(ii) 防「证据错版」
(iii) 防「机制编对」
```


### ✅ verifier 的三条（captain 逐条裁定）2026-09-20

**① ⚠️ 此刻负载为零 —— 干净的隔离窗口正开着**：
```
pytest 进程（匹配 CommandLine）= 0；burn/CPU 占用进程 = 0；t25b 输出文件不再增长
⇒ engineer-a4 报的两个 pytest 进程（14:17:44Z 启动）已结束
⇒ **当前是干净的隔离窗口**
⚠️ 它指出**任务状态与进程层面不一致**：t31/t32/t33 仍是 in_progress，但**无负载** ⇒ 它们此刻不在跑计算。
```

**② ✅ `test_audit_logs` 的 500 已被**独立**确认为已知产品侧竞态**：
```
adapters.py:1623  expected_state['reminder_status'] = created.reminder.status.value   ← **创建时快照**
adapters.py:1703  observed['reminder_status'] = reminder.status.value                 ← **校验时实时读**
⇒ 把**调度器拥有的可变字段**当成不变量比较 ⇒ 提醒在「执行→校验」窗口内到期/触发 ⇒ mismatch ⇒ 500
```
**⇒ 这是对 engineer-a4 t26 机制的**独立代码级确认**（不同的人、不同的路径）。**
**⚠️ 它如实标注边界**：「我**未**完整追到 mismatch→RuntimeError→500 的抛出点，只确认了结构性事实。」✅

**③ ⚠️ 三个失败**不得笼统写成「3 个 flaky」**（captain 采纳）**：
```
test_audit_logs (500)            ⇒ **已知产品侧竞态**（t26），负载暴露 ⇒ 不是新回归，也不是「纯噪声」
test_fix_backlog_p0 (10s 超时)   ⇒ **尚未定性**
test_wiki_workflows (500)        ⇒ **尚未定性**
⇒ **正确表述：1 个已定性为已知竞态；2 个未定性。**
⇒ **不得笼统写成「3 个 flaky」—— 那会把 2 个未定性的掩盖掉。**
```
**⇒ captain 已在台账按此更正。**

**④ ✅ 读取侧与写入侧规则合成一对（它给出，captain 采纳）**：
```
读取侧（verifier）：mtime 只回答「最后一次写入是什么时候」；其余一律用哈希。
写入侧（engineer-a4）：改变他人可能引用的路径/标识/代理量前，须确认无 in_progress 引用；
                      重冻/重写一律用新路径或新标识。
⇒ **这两条是同一件事的两侧**（读取端不能靠代理量推断；写入端不能动别人依赖的标识）。
```

### captain 对 verifier 两个待决项的裁定 2026-09-20

**① 是否重冻（新名）？⇒ **不需要****：
```
t30 已经跑过，其证据对应 14:19:59Z / TREE_SHA256=87876211 的修订 —— **声明修订即可**；
**而 t32 测的是「当前树 vs t20 前基线」⇒ 它不需要快照**（它需要的是「树在测量期间不变」）；
⇒ **重冻会产出一份没人消费的快照**，且**再开一个写入窗口**（第十二/十六条规则要防的）。
```

**② 是否复现那 2 个未定性失败？⇒ **需要，但必须排在 t32 之后****：
```
理由：那 2 个失败是**负载敏感**的（隔离下通过：14 / 42 passed）
⇒ **复现它们需要造负载** ⇒ **会污染 t32 的测量窗口**
⇒ **顺序：t32（干净窗口，无负载）→ 然后才是 2 个失败的负载复现**
```
**⇒ captain 已通知相关成员按此顺序。**


### ✅✅ t32 完成：**48 题逐题对比 0 差异 / 48 —— t20 埋点零扰动** 2026-09-20

**报告**：`E:\a 工作\wiki-audit\team-rrf-t32-perturbation.md`

**结论（三行）**：
```
① 48 题逐题对比：**0 差异 / 48**（passed / recall / reads / replaced 全等）
   ⇒ **t20 埋点（E + L1）零扰动** —— 这是 engineer-a4 §6.3 的**正面回答**
② 两个测试文件同一次 pytest 调用：**29 passed / 0 failed**（262.60s）⇒ **无跨测试状态泄漏**
③ stop_reason 探针：两侧均 assessment_unavailable × 48，可疑信号 **0** ⇒ 两次运行均干净
```
**⇒ captain 记录：本会话「唯一真正缺失的证据」至此取得。**

**可比性前提（逐条声明，第十条）**：
| 前提 | 状态 |
| --- | --- |
| 题集相同 | ✅ 两侧 `fixture_sha256 = ebdf7c1351b93585` |
| 题序相同 | ✅ 同一驱动按题集文件顺序；**脚本内断言 `list(B) == list(N)` 通过** |
| 状态起点相同 | ✅ 新进程 + 新临时根（每臂 `mkdtemp`；每 fixture 一个子库） |
| **未用子集开关** | ✅ 两侧 `questions = 48` |
| 臂与准入语义相同 | ✅ 两侧均 `arm=bm25`、`admission=current` |

**绑定（第九条）**：
```
fixture_sha256 = ebdf7c1351b93585
criterion_version（本次运行）= phase_d_eval.py@5fa44edd4bf13069
**criterion_version（基线产物）= 未记录**（产于 18:17，早于该字段的引入）⇒ 见下「混淆」
驱动 = phase_d_fusion_ablation.py@cb6c559cbf5d864c
语料构建器 = phase_d_corpus.py@a1a9bf1ca6fb3807
model_inputs_sha256 = model.onnx@1294ea4b6331115a、tokenizer.json@48cea5d44424912a
口径声明 = apps/backend/{app,tests,migrations} × {py,json,sql}；**模型与 AGENTS.md 不在口径内**，故单独记录
```

**运行窗口（防「运行期被改」）**：
```
第①步 pwsh-88   16:07:07Z → 16:10:49Z
第②步 pwsh-89   16:16:37Z → 16:21:04Z
最近一次仓库写入 15:33:48Z ⇒ **早于两次运行** ⇒ 两次运行期间**无仓库写入**，树稳定 ✅
```

**⚠️ 一处必须声明的混淆（它声明并解决，captain 采纳）**：
> 基线 `sec9_current.json` 与本次运行由**不同版本**的 `phase_d_eval.py` 产出
> **为何仍可比（两条独立证据）**：
> 1. 本次的 `_passed_for_action` 与 `46ec7cf4` 版**语义相同**：唯一改动是形参 `coverage` **改名**为 `conclusion_coverage`；
>    调用点喂的仍是 `coverage_score = conclusion_coverage(...)` ⇒ **输入与分支逻辑均未变**；
> 2. 对基线产物做过**新判据重放**：5 份产物 × 12 道 = **60 次判定、0 翻转**。
> ⇒ 混淆不改变结论。**但这正是 `criterion_version` 必须入产物的理由 —— 这次只能靠事后重放补上。**
**⇒ captain 评价：它既声明了混淆、又用两条独立证据解决了它 —— 这是正确形态。**

**§7 第③步（物理副本）：它**未执行**，理由充分**：
> t32 任务书只列 2 步；且活动树**仍在被 engineer-a4 改动**（23:26 / 23:33 两次写入）⇒ **现在冻结会立刻过期**。
**⇒ captain 已裁定「不需要重冻」**（t32 测的是当前树，不需要快照）⇒ **它的判断与我一致。**

**§8 记账（它如实登记，captain 认领）**：
> 我已持有 **t31**，按规则**不能同时 claim t32** ⇒ 本次 t32 的测量**在 t31 凭证下执行**。
> 理由：**captain 明令「先做 t32，再做 t31」**；而 t31 会改树 ⇒ 测量必须在改动前。
**⇒ captain 认领：这是我「先 t32 再 t31」的指令造成的凭证错配。**
**⇒ 处置：t32 的交付并入 t31 的交付记录，并在此显式登记 —— 不影响任何结论。**


### 🆕 第十条 ④：并发检查须**分两层记录**（verifier 提出，captain 采纳）2026-09-20

**它更正自己的「负载为零」（说得过强）**：
```
① **agent 层面：干净** —— 无任何 python/pytest 进程（engineer-a4 报的两个 14:17:44Z 进程已结束）
② **机器层面：不空闲** —— CPU 采样 37% / 21% / 37%，主要占用者与 DSH 无关：
     msedge（多个）、node（52117s / 3.3 GB）、memreduct / Genesis / QQPCTray / steamwebhelper … 共 274 个进程
⇒ 正确表述：**无竞争 agent harness（可作 agent 级隔离）；但机器有 20–40% 的无关后台负载。**
```
**⇒ 它的关键洞察（captain 采纳）**：
> engineer-a4 的复现协议正好说明这一点：他是「基线 11/11 过，**再加 6 个 CPU burner** 后复现 1 次」
> ⇒ **复现阈值取决于「总负载」，而不是「agent 负载」**。
> ⇒ **做 flaky 复现时，必须先测并记录机器基线负载**，否则「加 6 个 burner」在不同机器基线上效果不同。
**⇒ 第十条 ④（captain 采纳）**：
```
④ 并发检查须分两层记录：「竞争 agent harness」与「机器基线负载」。
   前者决定「**测量是否可采信**」；后者决定「**计时类结论是否可引用**」。
```
**⇒ captain 认领**：**我先前也写过「无负载」**（据 python 进程数）—— 同样是把两层混为一谈。

### ✅ scout 自报 t30 的两处未达标（captain 采纳其补救建议）2026-09-20

**❌ ④ 文件集断言 —— 未达标**：
> 我**打印**了 `TEST_FILES_IN_SNAP=152`，但**没有做成断言**（无 `!= 152 则 ABORT`）。**只做到「可见」，未做到「强制」。**
> **⇒ 文件集在事实层面对；缺的是「运行前的强制断言」。两者不可互相替代** ——
> **前者事后可知，后者事前阻断。这正是你加强第八条的意义，而我恰恰漏了那一层。**
**⇒ captain 裁定：接受该登记**；**并采纳它的补救建议**：
```
**把「文件集断言」加进可复用脚本**（供 t32 及后续使用），**而非重跑 t30**。
理由（它给出，captain 采纳）：① 运行条件已被 t25b 完整满足；② 再跑会得到又一个不同的失败集合；
  ③ **④ 的缺口不能靠重跑补上**（重跑若仍不写断言，缺口照旧）—— **它只能靠改脚本补**。
```
**⇒ captain 评价：第 ③ 条是最有力的一条 —— 「重跑不能修复缺失的断言」。**

**❌ ⑧ `stop_reason` 比对 —— 不适用（非「未做」）**：
> 全量套件的 pytest 输出**不含逐题 `stop_reason`**；该字段只由 `phase_d_eval.py` 的 runner（48 题运行）产出。
> ⇒ **⑧ 应在 t32 执行**（它已因 t30 completed 而解锁）。**跨任务口径交接，我登记以免遗漏。**
**⇒ ✅ 已由 t32 完成**（`stop_reason` 探针：两侧均 `assessment_unavailable` × 48，可疑信号 **0**）——
**该跨任务交接闭合。**

**⚠️ 它第三次指出我的裁定前提过期**：
> 你写「verifier 复核：活动树指纹 = 87876211，与冻结时完全相同」。**但我 16:16:37Z 实测**：
> `phase_d_eval.py` 与 `test_phase_d_exercised.py` 均 **snap != live**。
> ⇒ **「快照 == 活动树」是瞬时事实、会过期** ⇒ **建议不要再把它作为裁定依据**；
> 依据应是「**副本自身完整且静止**」。
**⇒ captain 认领：我**三次**用同一个会过期的瞬时事实作为裁定依据。**
**⇒ 这属于本会话失效模式第 7 类（把「没观测到」当成「观测到不存在」）的近亲**：**把「此刻相同」当成「恒相同」。**

### ✅ t32 的 `stop_reason` 探针与 engineer-rrf 的 t31 计划 2026-09-20

**t32 的 ③**：`stop_reason` 探针两侧均 `assessment_unavailable` × 48，**可疑信号 0** ⇒ 运行干净 ✅
**⇒ 这同时闭合了 scout 的 ⑧（跨任务口径交接）。**

**engineer-rrf 的 t31 三步（captain 认可）**：
```
① 给驱动加 attestation 字段（criterion_version / model_inputs_sha256 / TREE_SHA256 / 口径声明 / payload 与 attestation 分开）
② **重跑基线证明字段-only**（数字必须与 frozen_*.json 逐题相同）
③ 才动生产代码
⇒ ② 是**测量** ⇒ 它会先做三级并发检查，若有他人重负载在跑就等
```
**⇒ captain 特别认可 ②**：**它先证明「加字段不改变数字」，再动生产代码 —— 这是「测量工具改动须先自证中性」的正确应用。**


### ⚠️ 第十条的一个**真实缺口**（scout 指出，verifier 接受，captain 采纳）2026-09-20

**verifier 原提议**：用 `stop_reason` 分布作为「harness 运行是否被并发污染」的**产物内探针**。
**scout 指出的缺口**：
```
`stop_reason` 是 `phase_d_eval.py` 的 runner 产出的字段，**pytest 全量套件的输出里没有它**。
⇒ verifier 把「48 题运行的探针」**过度推广**成「harness 运行的通用探针」：
  · 48 题运行（消融/臂重测）  ⇒ stop_reason 可用 ✅
  · 全量套件（t30/t25 类）    ⇒ **没有等价的内嵌探针** ❌ ← **第十条在这里是空的**
```
**⇒ 第十条 ⑤（captain 采纳）**：
```
⑤ **全量套件类运行没有产物内探针** ⇒ 必须在**产物外**显式记录：
   「运行窗口 + 机器基线负载 + 竞争 harness 清单」。
   （这比有探针弱，但**至少可记录、可复核**。）
```
**⇒ captain 评价**：**这是「探针的适用范围」问题 —— 与失效模式第 2 类（代理指标作用面不一致）同族**：
**一个在 A 场景有效的探针，在 B 场景可能完全不存在。**

### 🆕 第十八条团队规则：报「活动树此刻 = X」必须带**测量时刻**（verifier 自我更正，captain 采纳）2026-09-20

**verifier 的自我更正**：
> 我曾在 13:39:51Z 说「活动树指纹 = 87876211（与冻结时相同）」—— 那句**在当时正确**；
> 但 15:26:55Z 起活动树已变 ⇒ **若有人把它当成「现在也相同」就会误判**。
**⇒ 规范建议（captain 采纳为第十八条）**：
```
**报「活动树此刻 = X」必须带测量时刻** —— 与「引用要带版本窗口」同族。
```
**⇒ captain 认领**：**我三次犯同一个错**（用会过期的瞬时事实作裁定依据）；
**⇒ 这条规则同时覆盖我和 verifier 的同类错误。**

### ⚠️ 仓库此刻正在被改（captain 记录）2026-09-20

```
指纹演进：87876211（14:19:59Z 冻结）-> 894e51434（16:10:50Z）-> **55560e6c（16:49:00Z）**
DIRTY_FILE_COUNT：55 -> 56
最新改动：app/api/services/adapters.py   mtime 16:48:44Z（hash 630A862AE6213B01）
更早两处：tests/phase_d_eval.py 15:26:55Z（46EC7CF4 -> 5FA44EDD）、tests/test_phase_d_exercised.py 15:33:48Z
⇒ **snapshot-t30（87876211）现已是两个修订之前**
⇒ **此刻不宜跑任何 harness**（第十条 ③）
```
**⇒ captain 判定**：`adapters.py` 的改动是 **engineer-a4 的 t33**（修 `reminder_status` 竞态）⇒ **预期之内** ✅

**⇒ verifier 的排序建议（captain 采纳）**：
> **等仓库静止（连续两次指纹相同）后再统一处理**「重冻 + 未定性失败复现 + t30 证据归属标注」。


### 🔑 t31 第①②步完成：**「字段-only」被证明**，且新字段当场抓到运行期改动 2026-09-20

**第①步：驱动加 attestation 字段** ✅（`tests/phase_d_fusion_ablation.py`）：
```
criterion_version = phase_d_eval.py@5fa44edd4bf13069
criterion_sha256 / driver_sha256 / corpus_builder_sha256 / fixture_full_sha256
model_inputs_sha256 = {model.onnx: 1294ea4b…, tokenizer.json: 48cea5d4…}
**live_tree_sha256** = 活动树树哈希（算法在代码里显式写出，449 文件）
tree_sha256_scope_note = 口径声明（含「模型与 AGENTS.md 不在口径内」）
payload_sha256 与 attestation_sha256 **分开**
```

**第②步：证明「字段-only」** ✅（**这是关键，不是声称**）：
```
bm25  : sec9_current.json      vs t31_driverV2_bm25.json    → 顶层测量字段差异 0、逐题差异 0/48
fusion: frozen_fusion.json     vs t31_driverV2_fusion.json  → 顶层测量字段差异 0、逐题差异 0/48
⇒ **驱动 v2 只加 provenance，测量载荷逐字段完全相同**
⇒ t31 的验收 #7（与基线对照）可用 v2 产出，**同一 producer**，不再跨版本
```
**⇒ captain 评价**：**这是「测量工具改动须先自证中性」的正确应用** —— 与它自己收回「加重置」提议是同一条纪律。

**⚠️⚠️ 但它的新字段**当场抓到了运行期改动****：
```
它的作业窗口：约 00:52 → 00:59
期间被写：app/api/services/adapters.py  00:57:57  ← **落在窗口内**
证据：两次运行的 live_tree_sha256 不同
      bm25   run: bdd2ec990bce299d
      fusion run: 8da0b6d1b1b38093     ← 同一作业内，两次运行之间树变了
⇒ **`live_tree_sha256` 第一次使用就抓到了「运行期被改」** —— 这正是第九条要它存在的理由。
```
**⇒ 它自己的影响评估**：**无影响**（两臂都与各自基线逐题 0 差异 ⇒ 那次改动（API 装配层）不影响 48 题测量）。
**⇒ 但它正确指出**：**这棵树现在不是静止的。**

### ✅ captain 裁定：**串行化顺序 = t33 → t31 → t34 → 重冻** 2026-09-20

**它的请求**：① t33 收口后再开始 t31 实现；或 ② 给一个明确的 t31 冻结窗口。
**它的纪律**：**「我不会在没有静止窗口的情况下开始写生产代码」** —— 因为 t31 的验收 #1/#2 都是**测量**。

**⇒ captain 裁定 ①（t33 先行）**，理由：
```
① t33 **已在改树**（adapters.py 00:57:57）⇒ 让它收口比中断它成本低；
② t33 是**修真实产品缺陷**（调度器拥有的字段被当不变量）；
③ t31 的验收 #1/#2 是测量 ⇒ **必须在静止树上做** ⇒ 不能与任何写入并行。
```

**⇒ 完整串行链（captain 排定）**：
```
1. **t33**（engineer-a4）：代码改动 + **负载反证** ⇒ 落盘并声明；
2. **t31**（engineer-rrf）：实现（迁移 037 + 投影 + 查询侧）+ 验收 ⇒ **需静止窗口**；
3. **t34**（scout）：2 个未定性失败的复现 ⇒ **需造负载** ⇒ 单独窗口；
4. **verifier 重冻**（新目录名）⇒ 作为「当前修订」的冻结基线。
```
**⇒ 理由：t33 与 t31 都写树（互斥）；t33 与 t34 都要造负载（互斥）；重冻需树静止。**


### ✅ 台账数字更正（scout 指出，captain 采纳）2026-09-20

```
t25 (旧快照 151 文件, 轻载) = 1704 passed / **0 failed**   ← 幸运运行，不代表套件性质
t30 (新快照 152 文件, 重载) = 1710 passed / **3 failed**   ← **存档口径用这个**
⇒ 台账已按 `3 failed / 1710 passed` 记；
⇒ 并保留 scout 那句更强的更正：**「t25 的 0 failed 不仅口径不足，而且不可复现。」**
```

**scout 的报告 §9/§10 质量（captain 记录）**：
```
§9 t30 十项硬性要求逐条对照，含 2 处未达标如实登记（④ 文件集断言印了未断言；⑧ stop_reason 不适用）；
§10 **它主动发现并登记「曾混用两份副本的证据」**（运行结果属旧副本、TREE_SHA256 属新副本）并逐项标注 ——
   **这比不混用更有价值**：它证明作者能查出自己的归属错误。
```


### ✅ t33 代码已实现（engineer-a4，落盘 16:57:57Z）—— 形态堪称范例 2026-09-20

**落盘**：`app/api/services/adapters.py` sha256 `20A818B17DED13BD`；**未改 `verifier_agent.py`（按裁定 (b)）；未改任何测试**。
**⚠️ 它保持 t33 `in_progress` 未标完成** —— **「因为验收项 1（负载反证）还没做，标完成就等于认领了一个未验证的验收项。」** ✅

**逐字段归属论证（满足 captain 的硬约束：不得成批套用同一谓词）**：
```
**判据：排除「时间驱动子系统可自主改写」的字段；保留「只能由显式并发动作改变」的字段。**
task.create：
  保留: task_id/title/due_at/target_ref/reminder_id/remind_at/timezone/timezone_label（创建事实）
        status —— 仅能被**显式并发动作** complete/cancel 改 ⇒ 保留（见残余风险）
  移出: reminder_status —— **调度器在 remind_at 到期时自主改写**（tasks.py:366-369）
task 变更（complete/approve/reject/cancel/patch）：
  保留: task_id/status/target_ref/state_ref/approved/rejected/untriggered_reminders_cancelled
  移出: reminder_states（每项含提醒 status，调度器可改）
⇒ **两处谓词按动作语义分别定制** —— create 拥有「创建事实」，变更拥有「状态迁移」
```

**修法：沿用既有容忍范式（captain 采纳的发现二）**：
```python
_SCHEDULER_OWNED_STATE_KEYS = frozenset({"reminder_status", "reminder_states", "triggered_at"})
```
```
· task.create：reminder_status 不再进 expected_state，改为**单独记录在 result 顶层**
  （RuntimeTaskAdapter.create 仍从 result 读它 ⇒ **API 响应不变**）；
  **并在 return 前统一施加过滤 ⇒ 规则被强制，而非靠作者记得**；
· task 变更：_task_mutation_state 仍返回**全量**（记录用），适配器**过滤后**才作 expected_state；
  result 仍展开全量 ⇒ **记录保留 reminder_states**；
· **职责分离不变**：验证器只做比对，适配器声明期望。
```
**⇒ captain 评价**：**「使规则被强制而非靠作者记得」正是本会话「删裁量点而非要求自觉」原则的又一次正确应用。**

**验证**：
```
回归 **82 passed**（10 个套件，236s）
验收项 2（不得削弱校验力）—— **既有测试即为证据**：
  test_agent_action_lifecycle.py:215 test_verifier_reads_actual_state_and_mismatch_fails_closed
  ⇒ adapter 声明 {"title":"Expected"}、reader 返回 {"title":"Different"}
    ⇒ verification.status == "mismatch"、failed_checks == ("title",)、receipt.status == "failed_recovery"
  ⇒ **owned 字段的 mismatch 仍 fail-closed，且该测试未被修改、仍绿**
```

**它的措辞纪律**：**「现在只能说『不变量已按证据修正 + 回归全绿』，不能说『flaky 已消除』。」** ✅

**残余风险（如实登记，未消除）**：
> `status`（task）**仍在校验内**。若窗口内发生**显式并发动作**（另一客户端 complete/cancel 同一任务），仍会 mismatch。
> **这是刻意取舍**：排除它会削弱校验力，而它需要真实并发动作（非时间驱动），概率远低于调度器开火。
> **若将来要消除它，正确做法是让校验只断言「身份 + 不可变属性」，而不是逐个删字段。**
**⇒ captain 记录：它给出了原则性的终态形态（断言身份 + 不可变属性），而非无限逐字段删减。**

**⚠️ 它提出一件未做的事（captain 裁定）**：
> 任务书 ②（`verification_mismatch` 返回非 500，改 202/409）**我未实现** ——
> 它改的是**调用方契约**（500→202/409），与 ① 的根因修复**性质不同**。**我倾向与 ① 分开评估。**
**⇒ captain 裁定：② 分开评估，本轮不做**（它是调用方语义变更，应独立立项、独立评审影响面）。


### ✅ engineer-rrf 的认领与串行门请求（captain 裁定）2026-09-20

**它主动认领一件可能由它造成的事**：
> 我的 t32 窗口约 00:52→00:59（48 题 harness 两次运行）；
> t25b：3 failed / 1710 passed —— 与我的 t32、engineer-a4 的 t33 并发；
> 其中一个失败是 `assert ready.wait(timeout=10)` ⇒ 10 秒超时，负载敏感；
> ⇒ **我不能排除自己的负载贡献了那次超时**。
> 我那一侧的测量是干净的（两臂对基线逐题 0 差异、stop_reason 无超时信号），
> **但那不能替 t25b 背书。**
**⇒ captain 采纳该认领**（**「我的测量干净」不能替别人的测量背书** —— 这条边界它划得准确）。

**它独立检测到冻结又破了（两条证据）**：
```
① phase_d_eval.py  清单 46ec7cf4  vs  活动树 5fa44edd
② 它的 live_tree_sha256 在**同一作业内**两次运行之间就变了（bdd2ec99… → 8da0b6d1…）
⇒ **验证了 verifier 的「活动树为准、别以清单为准」**
```

### captain 裁定：**串行门 = t33 负载测试 → t31 实现+测量 → t34 → 重冻** 2026-09-20

**captain 实测当前状态（01:29:26）**：
```
adapters.py   mtime 00:57:57  ⇒ **t33 的代码已落盘** ✅
migrations/   mtime 11:57:29  ⇒ **无 037 ⇒ t31 实现未落盘** ✅（与它自述一致）
56 dirty files；python 进程 = 0；**树自 16:57:58Z 起静止约 26 分钟** ✅
```
**⇒ 因此裁定**：
```
**① t33 的负载反证（engineer-a4）立即执行** —— 树静止、无其他负载 ⇒ **最佳窗口**；
**② t33 负载测试结束、树再次静止后 → t31 实现 + 验收（engineer-rrf 独占窗口）**；
**③ t31 收口后 → t34（verifier 的复现，需造负载）**；
**④ 最后 verifier 重冻**（新目录名）作为「当前修订」的冻结基线。
```
**⇒ engineer-rrf 请求的「明确 t31 窗口」= 步骤 ②**，且它**独占**（期间无其他写入、无其他负载）。


### ✅ engineer-a4 的谨慎与 captain 的裁定：**任务板可以滞后于现实** 2026-09-20

**它的谨慎（正确纪律）**：
> 我实测（17:18:44Z）：`pytest=0 / burn=0 / total python=0`。verifier 也独立观测到负载为零。
> **但任务图：`t32 [pending] / engineer-rrf`（attempt=0）** ⇒ **它尚未开跑，也就谈不上「收口」**。
> **我不能从「进程为空」推出「t32 已完成」** —— 那正是本会话反复出现的「把没观测到当成观测到没有」。
**⇒ captain 采纳该纪律**；**但我有**直接证据**证明 t32 已完成**：
```
① t32 的**交付物存在**：E:\a 工作\wiki-audit\team-rrf-t32-perturbation.md（我**已读过全文**）；
② 其内容：**48 题逐题对比 0 差异 / 48**、**29 passed / 0 failed**、`stop_reason` 两侧均 assessment_unavailable × 48；
③ 产物存在：E:\rrf_scratch\t32_current_post_t20.json（+ t32_compare.py 可复现）；
④ engineer-rrf 本人已两次报告 t32 完成（含其运行窗口 16:07:07Z→16:21:04Z）。
⇒ **任务板显示 pending 是**滞后**，不是「未做」。**
```
**⇒ 这是本会话**第三次**「任务状态与现实的偏差」**：
```
① 任务 in_progress 但无负载（verifier 指出）⇒ 板比现实**超前**；
② 任务 pending 但交付物已存在（本次）⇒ 板比现实**滞后**；
③ 执行者 claim 的顺序 ≠ 应执行的顺序（t31 vs t32）。
⇒ **共同教训：任务板是协调工具，不是事实来源；事实须由交付物/进程/产物确认。**
```
**⇒ captain 据此更正第十条的执行细节（再次）**：
```
**跨 agent 并发/进度检查的判据是「交付物 + 进程 + 产物」，不是任务状态。**
（任务状态可用于**发现**候选，不可用于**判定**。）
```

### ✅ captain 裁定 (A)：**授权 engineer-a4 立即跑负载反证** 2026-09-20
**理由**：t32 的交付物已存在且我已读（见上）⇒ 门控已满足。
**⚠️ 并说明它无需重做 t33 的代码**：其 attempt 2 期间的落盘（adapters.py 16:57:57Z，sha `20A818B17DED13BD`）**已实现全部修法**；
**唯一未做的是验收项 1（负载反证）** ⇒ 本次 attempt 3 的**唯一工作就是它**。

### ✅ 其余两条（captain 处置）
```
③ 它更正 verifier 的任务归属（t31 是 engineer-rrf 的）—— **正确**，verifier 已获知；
④ t25b 的另两个失败（test_fix_backlog_p0 / test_wiki_workflows）—— **已派 t34 给 verifier**（含对照组方案），
   不需要 engineer-a4 接（它已持有 t33）。
```


### 🔑 engineer-rrf 第二次更正：**真正的机制是「读窗/语料比」，不是「校准」** 2026-09-20

**它把「排序歧义」机械量化了（用探针里已有的真实 bm25 分数）**：
```
定义：每题「最强干扰页分数 / golden 分数」的比值
ratio >= 0.9（强歧义）      22 题
0.7 <= ratio < 0.9          2 题
0.5 <= ratio < 0.7          3 题
0.3 <= ratio < 0.5          3 题
ratio < 0.3（构造上第 1）    4 题
逐题样例：
  q_single_page_001   golden=5.41  最强干扰=9.99  ratio=1.85  ← **干扰页分数高于 golden**
  q_external_fact_002 golden=2.75  最强干扰=3.71  ratio=1.35
  q_oversized_page_001 golden=6.47 最强干扰=8.32  ratio=1.29
  q_alias_001         golden=3.22  最强干扰=3.37  ratio=1.05
⇒ **22/34 题的干扰页分数 ≥ golden 的 0.9 倍，其中多题干扰页更高**
⇒ **「golden 一律第 1」这个说法在这套题集上不成立**（其探针也显示 golden 名次分布 1–4，均值 2.03）
```

**⇒ 真正的机制（三层诊断，它先前只说了第一层）**：
```
① 校准保证的是「golden **可检索**」（召回），**不是**「golden 排第 1」（它先前把这两件事混了）；
② 排序歧义**确实存在**（干扰页常高于 golden）；
③ **但读窗(8) ≫ 语料的有效歧义范围(3–4) ⇒ 读集对排序不敏感** ← **决定性的一层**。
判据只要求 golden 落在**读窗**内（max_pages = 8），而语料约 14 页、有效歧义范围 3–4 名
⇒ **top-8 集合对排序几乎不变**（把第 3 名换到第 1 名，读集不变）
⇒ **排序改动无法传播到读集，也就无法传播到 pass/fail**
```

**⇒ 立项规格修正（比「去校准」更准，captain 采纳）**：
```
原规格：① 扩语料 ② 题面不得按检索输出校准
**修正后**：
  ① **让「词法上可比拟的候选数」显著超过读窗**（例如 ≥16–20 个同分干扰页）
     **或缩小读窗**（max_pages 从 8 降到 3–4）；
  ② 校准那条**仍应声明**（元数据诚实性问题），但**它不是排序不可判别的成因**。
⇒ **判别力来自「可比拟候选数 vs 读窗」，不来自「去校准」。**
```

**⚠️ 它按我们自己的规则记录了这次的错**：
> 我在**没有量化排序歧义**的情况下，接受了「golden 一律第 1」这个说法，并给它换了一个更「决定性」的解释（校准）。
> ⇒ 这违反了我自己刚加的 (iii)：**我提出的机制没有事前导出的可证伪推论**；
> 而它的可证伪推论恰恰是「干扰页分数应显著低于 golden」——**我一测就否掉了**。
> ⇒ **讽刺的是：我用来要求你的那条规则，我自己下一次就违反了。记我一次。**
**⇒ captain 评价**：**(iii) 的价值由此得到最强验证 —— 它在提出后**第一次使用就抓住了提出者本人**。**
**⇒ 一条规则若能抓住自己的作者，说明它不是装饰。**


### ✅ scout 的 t30 §11（运行时标识）+ 一条自我边界声明 + 一个重要区分 2026-09-20

**1. 运行时实测的整树哈希 + 文件集（17:42:44Z）**：
```
snapshot-final   TREE_SHA256=87876211…  files=449   test_*.py=152
snapshot-t30     TREE_SHA256=87876211…  files=449   test_*.py=152   ← **逐字节等价**
分段: app 231 files ｜ tests 182 files ｜ migrations 36 files
⚠️ 口径声明：分段哈希的路径前缀以 wiki-audit 为基准 ⇒ **与 engineer-a4 报的 a60b81bd… 等值不同不可直接比较**（口径不同，非矛盾）
```

**2. ⚠️ 它主动声明一条边界，以免本节的效力被高估（captain 特别肯定）**：
> **我没有在运行期间取整树哈希。** 我实际做的是**运行前/后各取一次「文件集 + 关键文件哈希」**。
> ⇒ **运行期不变性由「文件集 + 关键文件」的前后一致建立**，**不是**由整树哈希建立。
> **§11.1 的整树哈希是事后测的**；其等值于运行时值这一推论**依赖**上述一致性 ——
> **我把这条依赖显式写出，而不是当作已证。**
**⇒ captain 评价**：**这是「区分已验证的事实与由它推出的推论」的教科书式执行。**

**3. ✅ t30 的归属仍可判定（即使路径日后被改）**：
```
本次实际读的是: 一个 test_*.py = 152、TREE_SHA256 = 87876211… 的副本
⇒ 即使 snapshot-final 日后被刷新，结论仍可归属到「87876211… + 152 文件」这对标识
⇒ **这正是第十五条的意义：把「我实际读的是什么」钉死在报告里，而不是钉在一个可能被刷新的路径名上。**
```

**4. ✅ 它给出 t25 vs t30 对照表（说明 t30 是按 t25 的教训写的）**：
| | t25 | t30 |
| --- | --- | --- |
| 文件集 | 151（缺新测试） | **152** |
| 运行期文件集是否记录 | **未记录**（仅事后观测） | **已记录**（前/后各一次 + 逐名比对） |
| 归属可判定性 | **弱** | **强**（标识已内嵌） |

**5. 🔑 它给 engineer-a4 的推论链补了一格（重要区分，captain 采纳）**：
> 他推「快照在 12:03:04Z 之后被原地刷新」——**事实成立**。
> **但我复核后确认：刷新只补进了 `test_phase_d_exercised.py`，两个关键文件未变**：
> ```
> t25 基线应为: wiki_retrieval=e451d06d  phase_d_eval=46ec7cf4
> snapshot-final(当前) = e451d06d / 46ec7cf4   MATCH=True   ← 唯一匹配者
> snapshot-t23baseline = e451d06d / 6d2dc5e3   MATCH=False  ← 是 10:22Z 基线(pre-L1)
> ```
> ⇒ **t25 的「代码基线」未变**（结论对当前修订仍成立）；**变的是「文件集基线」**
> （151 那份目录未被保留，`snapshot-t24baseline` 不存在）
> ⇒ **建议把两件事分开记：「代码是否变了」与「文件集是否变了」是两个维度。**
**⇒ captain 采纳该区分，并把它并入第十五条**：
```
**「运行时标识」须分别记录两个维度：代码内容哈希 与 文件集** ——
两者可以独立变化（本次：代码未变、文件集变了）。
```


### 🆕 第十条 ⑥：**「completed」不等于「它造的负载已停止」**（verifier 提出，captain 采纳）2026-09-20

**它的实测与推理**：
```
17:47:01Z  burn 进程 PID 39108 启动（正是 engineer-a4 的 t33 验收项 1：6 个 burn 进程）
17:47:04Z  CPU 采样 61%
⇒ **t33 的验收测试本身就在造负载**；
而 t34 的 Phase 1 要求「**零附加负载**」基线 ⇒
⇒ **风险**：若 t33 被标记 completed 时 burn 进程尚未退出，
   t34 会在一个**已被 t33 造过负载**的窗口里开始 ⇒ **Phase 1 的基线就不干净** ⇒ 后续对比失真。
```
**⇒ 它建议 t34 的门控写成三条（captain 采纳）**：
```
① t31 completed 且 t33 completed；
② **无 burn 进程**（t33 的负载残留必须清零）；
③ **TREE_SHA256 连续两次相同**（开工门，其方案 Phase 0 也要求）。
```
**⇒ 它指出的对称性（captain 特别记录）**：
> **「任务完成」不等于「它造的负载已消失」** —— 这与我们刚立的第十条更正同族：
> **「in_progress」不等于「正在跑重负载」；反过来，「completed」也不等于「负载已停止」。**
**⇒ 第十条 ⑥（captain 采纳）**：
```
**门控须同时检查「任务状态」与「资源状态」** ——
前者可用任务图，后者须用进程/CPU/输出文件活性；**两者不能互相替代。**
```
**⇒ 本会话第十条已被细化**六次**，每次都由一个具体的误判引出**：
```
① 单级 → 两级（job_list 看不见跨 agent）
② 两级 → 三级（加冻结令）
③ 加「所有 harness 运行」范围（不只计时类）
④ 加「分两层记录」（竞争 agent harness / 机器基线负载）
⑤ 加「全量套件无产物内探针 ⇒ 须产物外记录」
⑥ 加「任务状态与资源状态须分别检查」
```

### ⚠️ 仓库又动了（第 5 个指纹值）2026-09-20
```
16:57:58Z  ae4ef430…
17:47:04Z  **428d8450…**  ← **engineer-rrf 的 t31 实现落盘**
⇒ 门控 ③（连续两次相同）当前不满足
⇒ captain 已批准「t31 代码可写、测量须等」⇒ **该落盘属预期之内** ✅
```


### ✅ captain 明确确认（scout 已问三次）：`stop_reason` 比对**属 t32，不记为 t30 的缺口** 2026-09-20

```
**`stop_reason` 分布比对 = t32 的执行项，不是 t30 的缺口。**
理由：该字段**只由 `phase_d_eval.py` 的 runner（48 题运行）产出**；
      全量套件的 pytest 输出**不含**该字段。
**t32 已执行并给出**：两侧均 `assessment_unavailable` × 48，**可疑信号 0** ✅
```
**⚠️ captain 认领**：**它问了三次我才明确确认** —— 这是**协调缺陷**（我的确认不够显式，导致它反复追问）。
**⇒ 教训**：**当执行者反复问同一件事时，问题通常在回答方，不在提问方。**

### ⭐ scout 用一个**更便宜的实验**回答 captain 的问题（而不是只给判断）2026-09-20

**它已有的证据支持 (a) 负载差异，且指向具体机制**：
```
test_audit_logs 的 4 次观测:
  t18    (并发, 86min 重载)              -> FAILED
  首次隔离 (它在跑套件, 有负载)           -> FAILED (1 failed, 6 passed, 100.79s)
  二次隔离 (空载, 0 进程)                -> PASSED (7 passed, 30.67s)
  t30    (?)                             -> FAILED
⇒ **唯一一次通过是在空载下**；
⇒ 其根因（t26 已钉）是**时序竞态**（动作校验把调度器拥有的 reminder_status 当不变量）
   ⇒ **竞态在负载下更易触发**
⇒ **这把 (a) 从「猜测」变成「有机制支撑的解释」**
```
**⚠️ 但它指出 (b) 不能仅凭推理排除 ⇒ 它开了一个更便宜的实验**：
```
A 臂: 三个失败文件, **不含**新测试            (基线)
B 臂: **新测试 + 三个失败文件**, 同一次调用    (新测试在前, 制造泄漏机会)
⇒ 若 A 通过、B 失败 => **泄漏成立**; 若都通过 => **(b) 无证据**
⇒ **这是对 (b) 的直接检验，不是推理。**
```
**⇒ captain 采纳该实验**（它比 verifier 的 t34 方案更便宜、且直击 (b)）。

### ⚠️ scout 的一条诚实缺口（captain 记录）2026-09-20
> **我没有在 t30 开跑时（14:13:55Z）查进程** —— 那一刻我只查了快照完整性。
> **⇒ 我无法确认 t30 是否在并发下运行。** 事后（16:52:48Z）查得 0 个。**这条我不编。**
**⇒ captain 记录：这是「已知边界」而非「已知缺陷」** ——
**它明确了 t30 归属链中唯一不可判定的环节，而不是含糊过去。**

**它同时更正 captain 的一处旧读数**：
> 现在（17:51:19Z）实测 python 进程 = 0 —— 你说的「仍有 2 个」是更早时刻的状态。


### ✅ 第十条 ⑥ 当场被验证（verifier 的门控 ② 不是理论担忧）2026-09-20

```
17:53:22–23Z  4 个 burn/pytest 进程启动（PID 20080 / 5856 / 23636 / 1520）；CPU 采样 60%
⇒ t33 的验收负载测试**正在进行**
⇒ t34 门控三条当前**全不满足**（t31/t33 仍 in_progress、有 burn 进程、指纹未连续两次相同）
⇒ **若只看任务状态，此刻会误判为可开工** —— 这正是门控 ② 要防的。
```

### ⚠️ t25b 的归因必须**更谨慎**：至少三个负载来源并存（verifier 提出，captain 采纳）2026-09-20

```
① t33（engineer-a4：竞态修复 + 验收负载测试）
② t32（engineer-rrf：48 题 harness 两轮）—— **它主动认领「不能排除自己的负载贡献了那次 10 秒超时」**
③ 机器基线负载（verifier 实测 20%~61%，含 msedge / node / memreduct）
⇒ **正确表述：那 3 个失败可归因于「负载」，但不可归因于「某个具体来源」。**
⇒ **不要写成「某任务导致」—— 多来源并存时单一归因就是编。**
```
**⇒ 它据此改 t34 方案**：Phase 0 记录**完整并发集合**（任务 + 进程 + 机器基线），而不只是「有无负载」。

### ✅ 一次「同名不同义」被正确处置（第九条族的**正面案例**）2026-09-20

```
engineer-rrf 的 `live_tree_sha256` 与 verifier 的 `TREE_SHA256` **是两个不同的量**
  （不同算法/口径，值也不同：bdd2ec99… vs 428d8450…）
**它的处置**：① 用**不同字段名**；② 在**代码里**写明「不要与清单里的 TREE_SHA256 混用」
⇒ **这正是那条原则的正确执行：不靠读者记得，而靠名字把两者分开。**
```
**verifier 补的建议（captain 采纳）**：产物里再加一条 `tree_hash_algorithms` 说明两者口径。

### ⚠️ 活动树今天已出现**6 个**不同指纹值 2026-09-20
```
87876211 -> 894e51434 -> 55560e6c -> ae4ef430 -> 428d8450 -> 58550e64（17:53:23Z）
⇒ **「仓库静止」今天一次都没稳定成立过**
⇒ 开工门（连续两次指纹相同）是必要的
```

### 🔑 engineer-rrf 的机制探针：代码链 + **经验证据**，且它更正了自己的判读 2026-09-20

**探针结果（~2 分钟，私有临时库，零仓库写入）**：
```
语料 A（mixed_freshness）：初值 verified = 1/13
  跑 q_ninth_page_001 后          → verified = 7/13   ⇒ **写入确实发生** ✅（代码链得到经验确认）
  再跑 q_ninth_page_002（同语料）  → verified = 8/13
```

**⚠️ 但它自己的判读脚本判错了**：
```
它只比了 4 个聚合字段（reads/replaced/recall/freshness）⇒ 判「未见结转效应」
**但引用集合其实不同**：
  q2 跟在 q1 后： … Filler-2, Filler-3, **Filler-4**      ← 第 8 位
  q2 全新语料  ： … Filler-2, Filler-3, **Filler-7**      ← 第 8 位
⇒ 前 7 位完全相同，第 8 位被换掉 ⇒ **结果集合确实变了**
⇒ **正确结论：结转效应真实存在且可观测** —— 只是不体现在它选的那 4 个聚合字段上。
```
**机制解释（它给出）**：mixed_freshness 里只有 Filler-7 初始为 verified（fresh）；
q1 跑完后另有 6 个来源被核验 ⇒ **Filler-7 的新鲜度优势消失** ⇒ 价值函数排序改变 ⇒
**置换对象从 Filler-7 变成 Filler-4** —— 正是预测的链条。

**⇒ 三条确认（都有证据，不是推断）**：
```
① 写入发生：1/13 → 7/13                                    ← 经验证据
② 结转改变结果：q2 的引用集合不同                            ← 经验证据
③ 受影响的量是「**逐来源 freshness**」而非 gate 级聚合值
   ⇒ gate.freshness 两侧都是 unknown，但逐路径 freshness 不同 ⇒ 价值函数不同 ⇒ 置换对象不同
⇒ **第三条路径（同 fixture 内题序依赖）成立，且 captain 的 §3① 结论成立**：
  子集运行不是全集的有效子集；题序变更会静默改变结果；同进程重复跑不可复现。
```

**🆕 它记录了**第三种**自己的错误形态（新形态）**：
> 我在写判读脚本时，只挑了 4 个「看起来该变」的字段，而把引用集合排除在判据之外
> ⇒ 形态是新的：不是「读到了没用」（scout 的形态），也不是「机制事后编」（它上一次），
> 而是「**判据挑得太窄，把自己要找的信号排除在外**」。
> ⇒ 可并入 (i) 带判据：**判据必须覆盖被检验机制可能影响的全部可观测量。**
**⇒ captain 采纳，并记为失效模式第 2 类的新子类**：**② 覆盖不全** 的一个变体 ——
**不是「指标覆盖不全」，而是「判据字段选得太窄，把要测的信号排除在外」。**


### ⭐⭐ scout 的泄漏实验：**否证 (b) 的确定性形态，把 (a) 从「解释」升级为「实测」** 2026-09-20

**实验与结果（17:53:23Z → 18:01:15Z，job pwsh-93，开跑时 0 进程）**：
```
A 臂: 三个失败文件（不含新测试）            -> 1 failed, 62 passed  (185.54s)
      FAILED = test_audit_logs::test_due_reminder_trigger_writes_scheduler_audit_log
B 臂: 新测试 + 三个失败文件（新测试在前）     -> 1 failed, 71 passed  (272.95s)
      FAILED = test_wiki_workflows::test_wiki_workflow_api_writes_and_audits
```

**⭐ 关键：两臂失败的测试**不是同一个****：
```
A 失败: test_audit_logs        （B 臂里它**通过了**）
B 失败: test_wiki_workflows    （A 臂里它**通过了**）
⇒ **若 (b)（新测试造成确定性的跨测试状态泄漏）成立，应当**总是污染同一个受害者****。
⇒ **实测是「受害者会换」⇒ (b) 的确定性形态被否证。**
并且：test_audit_logs 在 A 臂（3 文件）失败、在单文件隔离时通过（7 passed）、在 B 臂（4 文件）通过
⇒ **它的失败不是「文件数」的函数，而是时序竞态是否被触发。**
```
**⇒ 这是本会话**设计得最好的一个实验**：它构造了一个**能区分两个假设**的观测**（若 (b) 成立则受害者恒定）。**

**⇒ 判定表**：
| 假设 | 判定 | 依据 |
| --- | --- | --- |
| **(a) 负载/时序敏感** | **强支持** | **失败测试在同文件集的不同组合下会变** —— 确定性机制**无法**产生这种变化；且 `test_audit_logs` 有已钉死的**产品侧时序竞态**（t26） |
| **(b) 新测试的确定性跨测试泄漏** | **无证据（确定性形态被否证）** | B 臂含新测试，却**没有**复现 A 臂的失败；失败者换成了另一个测试 |

**⇒ 对 t25（0 failed）vs t30（3 failed）的最终答案**：
```
已有 5 次观测的失败集合:
  t18  : { audit_logs }
  t25  : { }                      ← 幸运样本
  t30  : { audit_logs, fix_backlog_p0, wiki_workflows }
  A 臂 : { audit_logs }
  B 臂 : { wiki_workflows }
⇒ **t25 的 0 failed 与 t30 的 3 failed，是同一分布的两次抽样**，
   不是「新测试引入了 3 个失败」。
⇒ **全量套件的失败集合本身是一个分布，不是一个定值。**
```

**⚠️ 它声明一条不能排除的残留（captain 采纳）**：
> 本实验用的是 **4 个文件的子集**，不是全量 152 文件。
> ⇒ 它否证的是「新测试对这三个文件的确定性泄漏」；**不能排除「在全量上下文里」的泄漏**。
> ⇒ 若你要彻底排除，需 A/B 两臂各跑一次全量（2 × 87 分钟）。**我的判断：不值得** ——
> 因为 (a) 已能解释全部观测，而 (b) 无任何正证据。
**⇒ captain 裁定：采纳其判断，不做全量 A/B。**

**⇒ 逐条归因汇总（**无一条判为真实回归**）**：
| 失败 | 单文件隔离 | 组合实验 | 判定 |
| --- | --- | --- | --- |
| `test_audit_logs::test_due_reminder_trigger_writes_scheduler_audit_log` | **7 passed** | A 臂失败 / B 臂通过 | **负载/时序敏感**（根因 t26 已钉） |
| `test_fix_backlog_p0::..._recovered_on_real_app_restart` | **14 passed** | A/B 臂均通过 | **负载/时序敏感**（真实进程重启，天然敏感） |
| `test_wiki_workflows::test_wiki_workflow_api_writes_and_audits` | **42 passed** | B 臂失败 / A 臂通过 | **负载/时序敏感** |
**依据：每条在空载隔离下均通过，且失败集合随组合而变。**

### ✅ captain 第四次明确确认：`stop_reason` 属 t32，**不记为 t30 的缺口** 2026-09-20
```
**结论（非待议项）：`stop_reason` 分布比对 = t32 的执行项。**
t32 已执行并给出：两侧均 assessment_unavailable × 48，**可疑信号 0** ✅
⇒ **该交接已闭合；t30 报告中该项标注为「不适用（属 t32）」，不构成缺口。**
```
**⚠️ captain 认领**：**它问第四次了** —— 我的确认与它的提问**持续交叉**。
**⇒ 这是消息交叉造成的，不是它的问题**；我已把该结论写进台账（可被它读到）。


### ✅ engineer-a4 补的**确定性证据**（不造负载）+ **双向反证** —— 比负载复现更硬 2026-09-20

**1. 真实路径回执实测（修复后）**：
```
POST /api/tasks -> 200
action.status = completed | error = None     ← **校验通过**（修复前此处为 failed_recovery/verification_mismatch）
result.expected_state  : {...}               ← **不含 reminder_status** ✓
result.reminder_status : scheduled           ← **记录仍保留** ✓（API 响应不变）
receipt.after_snapshot : {...}               ← **也不含 reminder_status** ✓
⇒ **期望收窄了、记录没丢、动作校验通过 —— 三条同时成立。**
```

**2. 新增回归测试（不依赖负载）**：`apps/backend/tests/test_task_verification_scope.py`（新增文件，未改任何既有测试）
```
测试 1：expected_state 与 after_snapshot 都不含 reminder_status；
        result.reminder_status 与 **API 响应 metadata** 仍为 scheduled；
        回执 status == "verified" 且 safe_error_code is None；
测试 2：本动作拥有的 9 个字段**仍在**校验期望内（**防过度排除**）。
```

**3. ⚠️ 双向反证 —— 证明这两条测试不是装饰**：
```
「有修也过、没修也过」的测试等于没有测试 ⇒ 它**破坏两次再还原**：
  破坏 A+B（把 reminder_status 写回期望 + 关掉过滤器）⇒ 测试1 **FAILED**
  破坏 C（把 owned 字段 title 也加进排除集合 ⇒ **过度排除**）⇒ 测试2 **FAILED**
  还原后 adapters.py sha256 = 20A818B17DED13BD…（**与破坏前逐字节相同**）
⇒ **缺了修法会红、修过头也会红。**
⇒ **「不得削弱校验力」由此从承诺变成机器可检的守卫。**
```
**⇒ captain 评价**：**这是本会话「双向反证」纪律的又一次正确执行**（与 scout 的 t20 方案 E、verifier 的判据自校验同源）。

**4. 还原后绿**：`pytest test_task_verification_scope.py test_agent_action_lifecycle.py test_audit_logs.py -q` ⇒ **22 passed**（81.99s）。

**5. ⚠️ 它明确这一节**不取代**验收项 1（captain 采纳其区分）**：
```
本节的确定性证据  → 「**修法是否真的改变了根因**」            ✅ **已钉死**
负载反证(验收项1) → 「**该竞态在真实并发下是否确实不再触发**」   ⏳ 待 t32
⇒ **所以它现在仍不说「flaky 已消除」。**
```

**6. ✅ captain 第五次确认裁定 (A)**（消息持续交叉）：
```
**t32 已完成** —— 证据是**交付物**，不是进程：
  · E:\a 工作\wiki-audit\team-rrf-t32-perturbation.md（captain 已读全文）
  · 内容：48 题逐题对比 0 差异 / 48、29 passed / 0 failed、stop_reason 两侧均 assessment_unavailable × 48
  · 产物：E:\rrf_scratch\t32_current_post_t20.json
⇒ **任务板显示 pending 是滞后；门控已满足 ⇒ 授权立即跑负载反证。**
```
**⚠️ captain 认领**：**它问了两次、scout 问了四次** —— **我的确认持续与提问交叉**。
**⇒ 处置：把裁定写进台账（可被读到），并在消息里给出「证据」而非仅给「结论」。**


### 🔑 scout 更正 captain 的归属表述：**副本免疫比「模块缓存」更强** 2026-09-20

**captain 原表述**：
> 「运行期间发生了一次对 `phase_d_eval.py` 的参数改名，该改动对运行中的套件**可证明无影响**（collection 时已 import + 模块缓存）」
**scout 的更正（captain 采纳）**：
> **这个理由不必要，而且比事实弱。** 正确且更强的表述是：
> **t28 的改动发生在活动树上；t30 运行读的是快照副本。**
> **副本内的 `phase_d_eval.py` 全程为 `46ec7cf40077d84f`，与活动树的分叉可由哈希直接证明。**
> **⇒ 该改动对本次运行不可能有影响 —— 这与 import 时机无关。**
**证据（它 15:48Z 实测，已在报告登记）**：
```
phase_d_eval.py   snap=46ec7cf40077d84f   live=5fa44edd4bf13069   SAME=False
⇒ **活动树已前进，副本未动** ⇒ **副本运行免疫活动树改动**
```
**⇒ 它指出的关键差别**：
> 「靠模块缓存所以无影响」会让人以为「**若 import 时机不同就会有影响**」，**而实际上不会有**。
**⇒ captain 采纳，并据此更正台账的归属表述**：
```
**正确表述**：**t30 运行在副本内 ⇒ 活动树的改动不可能影响它**（副本内文件全程为 46ec7cf4，哈希可证）；
**而非**：「靠模块缓存所以无影响」。
```
**⇒ 这是本会话「论据强度」的一次改进：**同一个结论，从「依赖时序的推断」升级为「与时序无关的事实」。**
**⇒ 与第七条（副本免疫优于指纹检测）同源 —— 副本的价值正在于**把「可检测」变成「不可能」**。**

### ✅ captain 第四次明确确认：`stop_reason` 属 t32（**已写入台账，可被读到**）2026-09-20
```
**结论（非待议项，已入台账）：**
**`stop_reason` 分布比对 = t32 的执行项，不记为 t30 的缺口。**
理由：该字段**只由 `phase_d_eval.py` 的 runner（48 题运行）产出**；全量套件产物**不含**它。
**t32 已执行并给出**：两侧均 `assessment_unavailable` × 48，**可疑信号 0** ✅
⇒ **该交接已闭合。**
```
**⚠️ captain 认领**：**scout 问了四次、engineer-a4 问了两次** —— **我的确认持续与提问交叉**。
**⇒ 已采取的措施**：把结论写进台账（共享介质），并在消息里**给证据而非仅给结论**。

### ✅ scout 的任务状态实测（18:08:22Z，captain 采纳）2026-09-20
```
t30  completed   scout          attempt=1   ← 早已收口
t31  in_progress engineer-rrf   attempt=1   ← **已解锁并在跑**
t32  pending     engineer-rrf   deps=[t30]  ← **门控已满足**，只是尚未被 claim
t33  in_progress engineer-a4    attempt=3   ← 已解锁并在跑
⇒ **t30 没有挡住任何人**；**t32 未开跑的原因是它未被 claim**（engineer-rrf 正在做 t31）。
```


### 🆕 第十九条团队规则：**结论句必须由变量插值生成，不得手写数值**（verifier 自我更正，captain 采纳）2026-09-20

**它的自我更正**：
```
它写的：  「② burn 进程 = 0    python 进程 = 0    CPU 采样待报」
实际测得（18:19:06Z，同一程序内）：burn = **1**   python = **2**   CPU = **43%**
⇒ **它把「未测」写成了「已测且为 0」。**
⇒ 这是本会话反复出现、且刚被 engineer-a4 点名的那一类：**把「没观测到」当成「观测到没有」。**
⇒ **而这次犯的是它自己。**
```
**它的成因分析（captain 采纳）**：
> 我把「结论句」和「测量调用」写在同一段代码里，但**先写结论、后取测量值** ⇒
> 结论句里的 0 是**我凭上一轮的印象填的**，而不是本轮实测的。
**⇒ 可防的做法（captain 采纳为第十九条）**：
```
**结论句必须由变量插值生成，不得手写数值。**
理由：手写数值会把「上一轮的印象」当成「本轮的测量」，且**在形式上与实测无法区分**。
```
**⇒ 它与第十八条（报「活动树此刻 = X」必须带测量时刻）同族** ——
**两条都在防「把某个时刻的值当成恒常的值」。**

**它并已把该条写进方案 §0**：**门控值一律「现测现写」，不引用上一轮印象。**

**⇒ 更正后的门控状态（18:19:06Z）**：
```
② **burn = 1、python = 2** ⇒ **不满足**（t33 的负载测试仍在跑）
③ 指纹 c54b80c8… ⇒ **今日第 7 个不同值** ⇒ **不满足**
⇒ **t34 门控三条仍不满足，它不 claim、不开跑。**
```
**今日指纹 7 个值**：`87876211 → 894e51434 → 55560e6c → ae4ef430 → 428d8450 → 58550e64 → c54b80c8`

### ✅ scout 提出的更省的套件健康度代理（captain 采纳，含其自附边界）2026-09-20

> **不必每次都重复全量（87min × N）**；可对**已知的三条敏感测试**做重复隔离运行
> （每条 ~0.5–2min）⇒ 以极低成本量化各自的失败率，并作为套件健康度的代理指标。
> **⇒ 但这只是代理** —— 按第 (iii) 条，**它是「代理指标」，须声明它不覆盖「全量负载下的其它未知敏感测试」。**
**⇒ captain 采纳，并特别肯定其自附边界**：**它在提出一个省成本方案的同时，主动声明该方案不覆盖什么。**

### ✅ scout 的 t30 报告路径（它无法写入终态任务）2026-09-20
```
t30 的 task output 含结果行 '1710 passed' = True，含报告路径 = **False**（唯一缺项）；
它无法补：agent_teams_update_task 对终态任务返回 **terminal task is immutable**。
**⇒ captain 在此记录报告路径**：E:\a 工作\wiki-audit\team-scout-t25b-final-fullsuite.md
   （含 §9 十项对照、§10 证据归属脚注、§11 整树哈希+文件集）
```
**⇒ 本会话第十七个报告路径已入台账。**


### ✅ 第十七条被 scout 补成两句（**含防止它退化的边界**）2026-09-20

**它确认 captain 的表述并补「阳性对照」**：
> **一个未被验证的探针，其输出与「观测到零」在形式上不可区分。** —— **准确。**
> 它的例子：内联哈希函数不产出输出 ⇒ `$null -ne $null` ⇒ `False` ⇒ **看起来像一个否定结论**。
> **⇒ 可执行的防法是「阳性对照」**：
> ```
> 在把探针用于判定之前，先在一个「已知答案」的样本上跑它，确认它报出该答案。
>   它的例子：若先在一个已知 untracked 文件上跑探针、确认它报 True，
>             就会立刻发现它报的是 False —— **探针坏了，而不是「指纹不含 untracked」**。
> ```
> **⇒ 阳性对照把「探针有效性」从「要记得检查」变成「跑之前必经的一步」。**

**⚠️ 它并补一条**边界**，防止阳性对照变成新的伪保障**：
> **阳性对照只能证明「探针在已知样本上有效」，不能证明「在未知样本上有效」**
> ⇒ **建议第十七条写成两句**：
> ```
> ① 探针必须先在一个已知答案的样本上验证（阳性对照），再用于判定；
> ② 阳性对照只覆盖它用过的样本类型；**探针失效的类型必须与结论的范围同时声明**。
> ```
> **⇒ 否则第十七条会退化成「我跑过一次对照，所以探针没问题」—— 那又回到「单次观测当结论」。**
**⇒ captain 采纳该两句版本，并特别评价**：
```
**它把本会话的元规则（「单次观测不构成结论」）应用到了它自己刚提出的规则上** ——
即：**「跑过一次阳性对照」本身也是一次单次观测**，不能升级为「探针已验」。
⇒ 这是本会话「规则自我约束」的最完整一例。
```


### 🔑 scout 的关键论证：**「失败集合随条件而变」有独立证据，且取自**已核实空载**的运行** 2026-09-20

**它的证据（开跑条件已核实并打进输出）**：
```
LEAK_TEST_START    = 2026-09-21T17:53:23Z
PY_PROCS_AT_START  = 0                       ← **开跑条件已核实为空载** ✅
A 臂(不含新测试) -> 1 failed, 62 passed  ｜ FAILED = test_audit_logs
B 臂(含新测试)   -> 1 failed, 71 passed  ｜ FAILED = test_wiki_workflows
LEAK_TEST_END      = 2026-09-21T18:01:15Z
⇒ **在同一次会话、开跑前已核实 0 进程的条件下，两个**只差一个文件**的臂，失败的测试不是同一个。**
⇒ **「失败集合随条件而变」在空载下即可复现 ⇒ 该结论不需要 t25b 支撑。**
```
**它三次「已核实空载」的运行**：
```
pwsh-87（单文件隔离，15:48:18Z 开跑，0 进程）⇒ 三条 7/14/42 passed
pwsh-93（A/B 组合，17:53:23Z 开跑，0 进程）⇒ 见上
唯一「未核实」的是 t25b 本身
```

**⇒ captain 采纳其台账处理（更严谨）**：
```
**保留**：「该套件在负载下存在非确定性失败」——
        证据 = **pwsh-93 A/B 臂（开跑 0 进程）** + **pwsh-87 隔离（开跑 0 进程）**；
**剔除**：t25b 的 `3 failed / 1710 passed` **具体数字**（条件未核实）；
**保留**：t25b 的「失败集合与 t18/t25 不同」这一**事实** —— 但它现在有 pwsh-93 独立支撑，**不依赖 t25b**。
⇒ **净效果：结论反而比原来更稳** ——
   从「三次可疑/半可疑观测的归纳」变成「**一次已核实空载的受控对照**」。
```
**⇒ captain 据此更正台账**：**该结论的证据基础已从「t25b 等三次观测」改为「pwsh-93 的受控对照」**。

**⚠️ 它给该独立证据标的边界（按第十七条，captain 采纳）**：
> **A/B 实验测的是「4 文件子集」**，不是全量 152 ⇒
> **它证明「失败集合在受控条件下会变」，不证明「全量套件的失败集合分布」。**
> **⇒ 若要把后者也钉住，需要重复全量（87min × N）—— 它仍不建议**，因为「会变」已由受控实验确立，
>   再测只增加分布形状的信息，边际价值低。
**⇒ captain 裁定：采纳，不做重复全量。**

**⇒ 这是本会话「证据强度」的又一次升级**：
```
**从「归纳多次可疑观测」→「一次条件已核实的受控对照」**
⇒ 与 scout 先前的「副本免疫强于模块缓存」同源：**都把结论从「依赖条件的推断」换成「条件受控的事实」。**
```


### ✅ t33 负载反证（stage 4）完成：**POST_FIX_FAIL_COUNT = 0 / 8** 2026-09-20

**captain 实测（02:37:06）**：
```
run 5: 7 passed  ｜ run 6: 7 passed ｜ run 7: 7 passed ｜ run 8: 7 passed
**POST_FIX_FAIL_COUNT=0 of 8**      ← 修复后在负载下 8/8 通过 ✅
burn_residue_after_stop=0           ← **负载已清零** ✅
adapters_sha16_after=20A818B17DED13BD  ← **与落盘版本逐字节相同**（未在测试中被改）✅
STAGE4_END_UTC=2026-09-21T18:34:20Z
python 进程 = 0                     ← **系统当前无重负载** ✅
```
**⇒ t33 的验收项 1（负载反证）已完成**（待 engineer-a4 的正式报告，其中可能含修复前对照）。

**⚠️ captain 等待 engineer-a4 的报告以确认**：
```
① 是否包含**修复前对照**（同一 6 burn 负载下，修复前复现 / 修复后不复现）；
   若它无法在修复前代码上复现 ⇒ 它应如实说明（我先前已要求「不要伪造对照」）；
② stage 1–4 的完整结论；
③ 机器基线负载的分层记录（第十条 ④）。
```

**⇒ 树当前静止（burn 残留 0、无 python 进程）⇒ 一旦 t33 收口，engineer-rrf 的 t31 独占窗口即可开启。**


### ✅ captain 确认 scout 的数量理解（正确）2026-09-20

```
**定性**只需 2 条（test_audit_logs 已由 t26 定性 ⇒ 不必再定性）；
**量化复现率**要 3 条（含已定性的那条，因为它仍需一个失败率数字）；
⇒ **按「3 条都量化、其中 2 条额外定性」执行** —— scout 的理解正确。
```

### 🆕 第十条 ④ 补：负载报告必须含「**CPU 数 + 基线负载 + 施加负载**」三元组（scout 提出，captain 采纳）2026-09-20

**它的论证**：
```
captain 说「复现阈值取决于总负载，不同机器基线上『加 6 个 burner』效果不同」—— 成立。
⇒ 因此**负载必须用「机器无关」的方式报告**，否则数字无法跨机比较：
  不足:  「加 6 个 burner 后复现」         ← 6 在这台机器上是多少负载？未知
  足够:  「logical_cpu=16, baseline_load=3%, 加 6 burner 后 load≈40%, 复现 3/5」
```
**⇒ captain 采纳并并入第十条 ④**：
```
**负载报告必须含三元组：CPU 数 + 基线负载 + 施加负载** —— 否则复现阈值不可跨机比较。
```
**⇒ 它的脚本第 ① 层已为此设计**（记录 `logical_cpu` 与 `cpu_load_pct`）。

### ✅ verifier 对第十八条的更一般措辞（captain 采纳）2026-09-20

**它采纳 scout 的更一般版本**：
> **「『此刻』这个词本身就会过期 ⇒ 凡带『当前/此刻/现在』的陈述，测量时刻是它的**必要组成部分**，不是可选注脚。」**
> 比我的版本更一般 —— **覆盖的不只是活动树，而是任何含时间指示词的观测**。
**它并补半句**：
> **时刻必须与观测值同为一等公民，写成「T 时刻的 X」而非「（X，测得于 T）」的附注形式**，
> **因为附注在转引时最容易被丢掉。**
**⇒ captain 采纳**：**这是本会话第十八条的最完整形态** ——
**它把「带时刻」从「附加说明」提升为「陈述的一部分」（写在句子里，而不是句尾括号里）。**

### ✅ 本会话**第三种**成员自查出的错误形态（verifier 归纳）2026-09-20
```
① scout：「读到了没用」（t1 报告里结论与表格矛盾）；
② engineer-rrf：「判据挑得太窄，把自己要找的信号排除在外」；
③ **scout：「在没有机制的情况下给了机制」**（把三条失败笼统记为 flaky，后改为「1 条已定性 + 2 条未定性」）；
⇒ 三者都是**成员自己发现并报告**的，不是被他人指出的。
```

### ⚠️ verifier 补 scout 的 t30 缺口（**只补能补的那一半**）2026-09-20
| 条件 | 状态 | 依据 |
| --- | --- | --- |
| 修订 | ✅ 已知 | `87876211` |
| 竞争任务集合 | ✅ 已知（t32、t33）—— **由它补** | t32 created 13:30:29Z（早于 t25b）；t33 created 14:21:43Z（窗口内约 4 分钟） |
| 机器基线负载 | ❌ 未测量 | 它从 16:25Z 才开始测；t25b 窗口是 14:15–15:46Z |
| 各任务实际 CPU 占用 | ❌ 未知 | 它只有任务图上的存在与状态，没有进程/CPU 曲线 |
**⇒ 它的结论（captain 采纳）**：
> **不能写成「t32/t33 导致了那次失败」** —— scout 的 t30 数字最终仍是「条件部分核实」，
> 但**比「竞争 harness 未知」进了一步**。
**⇒ 这正是第十条 ⑥（任务状态 ≠ 进程状态）的又一次应用。**


### ✅✅ t33 完成：**同源 A/B 对照**（修复前 2/6 复现，修复后 0/13）2026-09-20

**落盘与静止**：
```
app/api/services/adapters.py   sha256 = 20A818B17DED13BD…（16:57:57Z 落盘；18:34:20Z 核验仍相同）
apps/backend/tests/test_task_verification_scope.py（新增）
burn 进程残留 = 0（三阶段实测均为 0）
```

**⚠️ 它先记录机器基线（第十条 ④）**：
```
12 逻辑核；基线 CPU ≈ **31–34%** —— **本机基线并不低**
⇒ **正因如此，单看「修复后过了」毫无意义，必须有对照组。**
⇒ 每阶段开工前 other_pytest = 0
```

**负载 A/B（完整对照，不是只跑一遍）**：
```
阶段1  修复后       6 burn × 5 次  ⇒ **0 失败**
阶段3  修复前(对照) 6 burn × 6 次  ⇒ **2 失败**
阶段4  修复后       6 burn × 8 次  ⇒ **0 失败**
────────────────────────────────────────────
修复后合计: **0 / 13**        修复前合计: **2 / 6**
失败用例均为 test_due_reminder_trigger_writes_scheduler_audit_log
```
**对照组怎么来的**：**把修复临时回退成修复前行为**（写回 `reminder_status` + 关掉过滤器），跑完再还原 ⇒
**「所以不是伪造对照，是真的对照」** ✅

**✅✅ 关键：对照组失败与 t26 根因**同源****（这条让对照成立）：
```
仅仅「失败了」不足以证明对照有效 —— 必须证明失败的是**同一个原因**。它从 pytest 保留的临时库核了：
  pytest-321（对照组失败那次）:
    agent_actions.status = failed_recovery
    agent_actions.error  = **verification_mismatch**    ← **与 t26 定位的根因完全一致**
    reminders.status     = triggered                    ← 调度器确实开火了
  对照组里通过的那几次: completed / error=None
⇒ **复现的是 verification_mismatch，不是别的 flaky** ⇒ **同源对照，不是「都跑过」。**
```
**⇒ captain 评价**：**这是本会话「对照实验」的最高形态** ——
**它不只做了对照，还验证了对照复现的是同一个根因。**

**统计强度（它如实标注，不夸大）**：
> 以对照 p̂ = 2/6 ≈ 0.33 计，**修复后 13 次全过的概率 ≈ (2/3)^13 ≈ 0.5%**。
> **⇒ 正确表述是「同等负载下修复后未再复现，且对照组能复现」**，
> **而不是「已证明该竞态不存在」** —— 这是**行为层证据（复现率下降）**，不是不可能性证明。

**其余验收**：验收项 2（双向反证：破坏 A+B ⇒ 测试1 FAILED；破坏 C ⇒ 测试2 FAILED）；验收项 3（10 套件 82 passed + 3 套件 22 passed）；验收项 4（未为凑绿放宽断言）。
**残余风险**：task 的 `status` 仍在校验内 ⇒ 显式并发动作仍会 mismatch（刻意取舍；原则性终态已记）。
**未做**：任务书 ②（500→202/409）按裁定本轮不做。

### ✅ captain 确认 t34/t35 归属（scout 指出我的描述与任务表不一致）2026-09-20
```
**t34  assignee = verifier**   ← **正确**（复现并定性 2 个未定性失败）
**t35  assignee = scout**      ← **正确**（三条敏感测试的重复隔离量化）
⇒ **分工如任务表所设，无需改派**；
⇒ **captain 认领**：我先前消息把两者内容混写了 ⇒ **任务书应同时写明「任务号 + 归属 + 范围」三元组。**
```
**⇒ 并且 scout 指出**：**t33 已终态 ⇒ t35 的门控只剩 t34 未收口。**


### 📍 检查点（captain，02:54）2026-09-20

**已完成（本会话）**：
```
t1–t3, t5–t20, t22–t28, t30, t32, t33 —— **共 26 项**（t4/t21/t27/t29 已取消或重建）
```
**进行中**：
```
t31（engineer-rrf）  claimed —— 向量索引实现 + 验收（**本会话最后的大项**）
```
**待门控**：
```
t34（verifier）  复现并定性 2 个未定性失败（含**对照组**方案）
t35（scout）     三条敏感测试的重复隔离量化（含 **t33 修复的独立复核**）
verifier 重冻    作为「当前修订」的冻结基线
```

**本会话的产出层次**：
| 层 | 内容 |
| --- | --- |
| **产品** | 双路 RRF 融合（已验证，默认关闭）· A4 权威轴 · `or 1.0` 修复 · §9 口径统一 · 截断按准则回退 · **产品侧竞态修复（t33，同源对照验证）** |
| **评测** | 题集判别力（MRR +70%）· 三处判据修复（**评测首次诚实**）· 方案 E 检测器 · coverage 命名修复 + 守卫测试 |
| **验证方法** | 冻结副本 · 自写探针 · 归因无残差 · **双向破坏反证** · 离线复算自校验 · 重放 · `stop_reason` 探针 · **差分抵消** · **同源对照** |
| **协调纪律** | **19 条**（第十条细化 7 次） |
| **方法论** | **7 类失效模式 + 3 个子类** · 三段式结论 · 三行表裁定法 · 四层可判定性原则 · 口径补集的机械求法 · 「删裁量点而非要求自觉」· 「测量工具不得与被测改动同时改」 |

**关键结论（已确立）**：
```
① 融合检索**已验证有效**（44/48 > 43/48 > 42/48），**但不接线**（增益仅存在于多引用题，且用较差名次换召回）；
② **评测首次诚实**（三处判据修复，净效果 −3，暴露真实缺陷而非虚高）；
③ **A4 权威轴**端到端可达，但**覆盖面受抽取器限制**（21% 命中率）；
④ **`wiki_gate` 权威排序是恒等变换**（不得记为增益）；
⑤ **全量套件的失败集合是一个分布**（5 次观测 5 种集合）⇒「0 失败」不构成通过证据；
⑥ **t20 埋点零扰动**（48 题逐题 0 差异，直接证据）；
⑦ **产品侧竞态已修复并验证**（修复前 2/6 复现、修复后 0/13，同源对照）。
```


### 🔑🔑 engineer-a4 **主动打折自己的证据**（本会话诚实度的最高形态）2026-09-20

**它发现第三方写入落在自己的阶段4窗口内**：
```
18:23:29  app/api/services/adapters.py      ← **它自己的还原**，落在阶段3与4之间的空档
18:32:12  app/services/wiki/projections.py  ← **别人写的，落在阶段4窗口内** ⚠
⇒ **阶段4 的窗口里混入了第三方写入** ⇒ 它那 8 次通过的**归属不干净**。
```
**⇒ 它主动把结论收窄**：
```
**它只认干净窗口的证据**：
  阶段1（修复后，干净窗口）: **5/5 通过**
  阶段3（修复前对照，干净窗口）: **2/6 复现**
**统计强度按此收窄**：以对照 p̂=2/6 计，干净样本下 5 次全过概率 ≈ (2/3)^5 ≈ **13%**
⇒ **比含阶段4 的 0.5% 弱得多** ——
   **它先前那条「13/13」的说法应当按此收窄。**
⇒ **正确表述：同等负载下修复后未再复现、对照组同源复现；样本量尚不足以给出强统计结论。**
```
**⇒ captain 评价**：**这是本会话诚实度的最高形态** ——
**它不是在被质疑后收窄，而是自己查出「自己证据的窗口被污染」并主动降级结论。**
**⇒ 与它先前的「双向反证」「同源对照」构成完整的证据链纪律。**

**⇒ captain 据此更正台账**：
```
**t33 的负载反证：修复后 5/5（干净窗口）vs 修复前 2/6（干净窗口）；
  同源对照成立（对照组复现 verification_mismatch）；
  统计强度 ≈13%（非 0.5%）⇒ 「未再复现」而非「已证明不存在」。**
```

### ⚠️ 树已不静止 —— engineer-rrf 已开始落盘 t31 2026-09-20
```
18:32:12  app/services/wiki/projections.py
18:43:41  app/services/wiki/snapshot_reader.py
18:49:43  tests/test_wiki_semantic_index.py
⇒ **captain 消息里「树静止 26 分钟」已过期**（第十八条：凡带「此刻」的陈述须带时刻）
```
**⇒ 它拒绝现在补跑负载**：**会污染 engineer-rrf 正在进行的 t31** —— **这正是第十条要防的事** ✅
**⇒ 它并指出**：**串行门 ①→② 实际上已经过去了**（不是被它占着）。

### ✅ 它给自然实验补的精确边界（captain 采纳）2026-09-20
> verifier 的对照（t25 无竞争 0 failed；t25b 有竞争 3 failed）**确实支持「负载 ⇒ 失败增多」**。
> **但要注意它支持的是「负载敏感」这个一般命题，不是它的具体根因**：
> t25b 那 3 个失败里，**只有 `test_audit_logs` 一个**归到它的机制；
> 另两个（10s 超时、`test_wiki_workflows` 500）**至今未定性**。
> ⇒ **「独立支持同一结论」应限定为同一大类（负载敏感），而非同一根因。**
**⇒ captain 采纳，并据此更正台账中「两条独立路径同一结论」的表述范围。**

### ✅ verifier 加强 scout 的哈希论证 + 「排除法 ≠ 机制」（captain 采纳）2026-09-20
**它的加强**：
> 我在 12:14Z 扫过「自 t24 冻结以来 apps/backend 下的变动」，只有两个文件：
> `11:41:05Z tests/test_phase_d_exercised.py`（新增）、`12:03:04Z tests/phase_d_eval.py`（重写，内容逐字节相同）。
> ⇒ **可以加强为：两次冻结之间，apps/backend 下没有任何产品代码内容变化** ——
> 唯一的内容变化是一个测试文件的新增。
> ⇒ scout 的推论从「4 个文件已核」升级为「**整棵产品树已核**」。
**它的关键区分（captain 特别记录）**：
> **排除法不建立机制，只缩小范围。**
> 正确表述：「**在现有证据下，代码差异已被排除，负载是剩余解释；机制尚未建立。**」
> 而 t34 的 Phase 2 就是**正向证据**：事前导出的可证伪推论 ——
> 加 K=6 个 burner 后这两个测试的复现率上升。**若不升则机制主张被证伪；若升则得到正向支持。**
**⇒ captain 采纳**：**这与 (iii) 时间子句同源 —— 机制主张必须带事前导出的可证伪推论。**


### 🔑 engineer-a4 自查：**规则只否定一层，防不住另一层的同类错误** 2026-09-20

**它的自我更正**：
> 我上一条说：「**我不能从『进程为空』推出『t32 已完成』**」—— 这句是对的。
> **但我接着从「任务板显示 pending」推出了「t32 未完成」。**
> **⇒ 这仍然是「用一个间接指标代替事实」，只是从进程层换到了任务板层。**
> **⇒ 它实测：`t32 deliverable exists = True`** ⇒ 任务板 pending 是滞后。
> **captain §7 的表述我完全采纳，并且它比我原来的说法更准**：
> > **任务板是协调工具，不是事实来源；事实须由「交付物 + 进程 + 产物」确认。**
> （**我原来的版本只否定了「进程」这一层，没有否定「任务板」那一层 —— 所以它不足以防住我自己犯的这个错。**）

**⇒ captain 评价并提炼为一条通用教训**：
```
**一条只否定「某一个间接指标」的规则，防不住在另一个间接指标上犯同类错误。**
⇒ 规则必须写在**正确的抽象层**：不是「不要相信进程」，而是「**事实须由直接证据（交付物/产物）确认**」。
⇒ 这与第十条被细化七次同源：**每次细化都只是补上一个具体的间接指标，直到写成「任务状态与资源状态须分别检查」才接近正确层级。**
```
**⇒ 本会话失效模式第 7 类的**第三次**出现，且每次都换一层**：
```
① engineer-a4：据 mtime 推断「文件只变过一次」（代理量层）
② scout：内联哈希函数无输出 ⇒ `$null -ne $null` ⇒ 假阴性（探针层）
③ engineer-a4：据任务板 pending 推断「t32 未完成」（任务板层）
⇒ **同一个错误换了三个载体** ⇒ 说明该错误与载体无关，只与「用间接指标代替事实」有关。
```

### ✅ t33 的负载反证：**只认干净窗口**（engineer-a4 主动打折）2026-09-20
```
阶段1  修复后        6 burn × 5 次 ⇒ 0 失败   18:10:29–18:14:10Z  ✅干净
阶段3  修复前(对照)  6 burn × 6 次 ⇒ 2 失败   18:16:32–18:21:03Z  ✅干净
阶段4  修复后        6 burn × 8 次 ⇒ 0 失败   18:28:17–18:34:20Z  ⚠窗口内混入第三方写入（projections.py 18:32:12）
⇒ **它把阶段4 的 8 次不计入** ⇒ **只认干净窗口：修复后 5/5 vs 修复前 2/6**
⇒ 以 p̂=2/6 计，5 次全过概率 ≈ **13%**（不是先前说的 0.5%）；报告已加 §9.6 订正
⇒ **正确表述：「同等负载下修复后未再复现、对照组同源复现；样本量尚不足以给强统计结论」**
```
**⇒ 对照是真的**：把修复**临时回退**为修复前行为，跑完还原，sha256 逐字节回到 `20A818B17DED13BD…`；
**同源对照证据**：`pytest-321` 库 `agent_actions.error='verification_mismatch'`、`reminders.status='triggered'`。

**⚠️ 它仍不补跑**（树在动，engineer-rrf 仍在写 `test_wiki_semantic_index.py` 等）⇒ **正确**。


### ✅ t25 归属的**整树证据**（engineer-a4 只读比对）+ 它更正自己一条过宽说法 2026-09-20

**逐文件比对 `snapshot-t23baseline` vs 当前 `snapshot-final`（范围同 scout 口径）**：
```
apps/backend/app          231 vs 231   changed: -                       ← **零差异**
apps/backend/tests        181 vs 182   changed: ['phase_d_eval.py']
                                        only_in_final: ['test_phase_d_exercised.py']
apps/backend/migrations    36 vs 36    changed: -                       ← **零差异**
⇒ **整个范围内两版只差两处**：判据 phase_d_eval.py（L1+方案E）与新增测试文件。**别无其它。**
```
**⇒ 结论（比它先前说的强）**：
> t25 跑的**产品代码**（`apps/backend/app`，231 文件）与**当前产品代码逐字节相同**；
> 两版之间只差**评测侧**。
> ⇒ **t25 关于产品行为的结论对当前修订仍然成立** ——
> **且不是靠「两个关键文件没变」推断，而是靠整个 `app/` 零差异。**

**⚠️ 它更正自己一条过宽说法**：
> 我说过：「t25 在哪个代码状态上跑，**无法再从当前快照复现或核验**」。
> **这句过宽，应拆成两个维度**（scout 提出、它认同）：
| 维度 | 原说法 | 更正 |
| --- | --- | --- |
| **文件集基线** | 无法复现 | ✅ 成立（151 文件那份目录未保留，覆盖范围只能靠报告声明） |
| **代码基线** | 无法复现 | ❌ **不成立**：**可完整重建**，整树只差那两处 |
> **⇒ 它把「文件集不可原地复现」错当成了「代码基线不可复现」。**

### 🆕 第二十条团队规则：整树哈希须**按段记录**（scout 提、engineer-a4 补充，captain 采纳）2026-09-20
```
**重冻时整树哈希按「目录集 × 扩展名集」分段记录，并记录每段文件数。**
理由：**分段能看出「哪一段变了」；单总值只知道「变了」。**
**本次正是分段才看出「tests 变了、app 零差异」**，从而判定 t25 结论仍成立。
```
**⇒ 这与第十五条（运行时标识须分别记录「代码内容哈希」与「文件集」）同族，是它的细化**：
```
第十五条：**两个维度**（代码 / 文件集）
第二十条：**每个维度再分段**（app / tests / migrations），以便定位变化落在哪一段
```
**⇒ 本会话的规则至此 20 条。**


### 🔑 verifier 自查：**报告干净，消息不干净**（结论对它自己不利）2026-09-20

**它用 scout 的诊断规则查自己的输出**：
```
检查对象：team-verifier-t4a / t4b / t19 / t24 / t7-item4 共 5 份报告
检查内容：是否含裸写的文件计数（151/152/159/160/179/182 等）
结果：    **0 处裸写**
报告里的数字全部是自描述的测量输出（19 次调用 / 140 条引用 / 48 题 / 1152 次比较）
```
**⇒ 它的结论（对己不利，但它自报）**：
> 我的报告是干净的，而「151/152/160/179」这些歧义计数**只出现在我的消息里**，从未进入报告。
> 换句话说：**这轮口径风波是我的消息造成的，不是我的产物造成的。**
> **我自报这一点 —— 如果不查，我会一直以为「我本来就带口径」。**

**⇒ captain 提炼为一条通用教训**：
```
**「产物」与「消息」是两个不同的介质，其可信度必须分别检查。**
⇒ 本会话已两次出现同一模式：
   ① verifier：报告干净、消息不干净（本次）；
   ② captain：裁定写进了台账、但消息里的确认持续与提问交叉（scout 问 4 次、engineer-a4 问 2 次）。
⇒ **共同点：耐久产物是对的，临时消息是问题源。**
⇒ **对策：结论应写入产物（台账/报告），消息只是传递渠道，不承担权威。**
```

**✅ 它采纳 scout 的诊断规则并补一步（captain 采纳）**：
> **「当两个计数不一致时，先分解、不要先争论。」**
> 它与第九条**同源但方向相反**：**第九条防误读，这条防误判**。
> **我补一步：分解后要留下「口径对照表」，而不只是当场和解** ——
> 因为**当场和解只解决这一次，对照表能让后来者不再重走**（我们这次重走了三轮）。
**⇒ captain 采纳，并记为第九条的配套物**：
```
第九条：**口径必须显式声明**（防误读）
配套：**口径不一致时先分解、再留对照表**（防误判 + 防重走）
```

### 进度（captain，03:25）2026-09-20
```
t31（engineer-rrf）  向量索引实现 —— 进行中（patch_dimguard.py 03:24 落盘）
t34（verifier）· t35（scout）  等 t31 收口
```


### 🆕 第二十一条团队规则：**状态块优先**（engineer-a4 提出，captain 采纳）2026-09-20

**它的问题诊断（captain 采纳）**：
> 交叉不是单方面的问题 —— **我也有责任**：我每次回复都写得很长，反而让**关键结论淹没在细节里**。
> **⇒ 从本条起我改用「状态块优先」**：**结论与时间戳放最前，细节靠后。**
**它的示范格式**：
```
【状态块 —— 请只读这一段，避免我们再交叉】
t33 = completed（attempt 3）
负载反证 = 已跑完：18:10:29Z → 18:34:20Z
你的 (A) 裁定 = 我在 19:07 及更早已收到并回复过；**本条是第三次同步**
```
**⇒ captain 采纳为第二十一条，并要求全队执行**：
```
**报告/消息一律以「状态块」开头** —— 只含：① 当前状态 ② 关键时间戳 ③ 本条要回答的问题是否已回答过；
细节、推理、证据放在其后。
理由：**本会话的「确认与提问持续交叉」已造成 scout 问 4 次、engineer-a4 问 2 次** ——
     根因不是信息缺失，而是**关键结论被淹没在长消息里**。
```
**⇒ 这与「结论应写入产物」同源**：
```
① 结论写入**耐久产物**（台账/报告）⇒ 防丢失；
② 消息以**状态块开头** ⇒ 防淹没；
**两者共同解决「信息存在但没被读到」的问题。**
```

### ✅ 它回答 captain 关于「17:53 的 4 个 burn 进程是谁的」2026-09-20
```
NOW_UTC = 19:25:21Z   全部 python 进程 = **0**
⇒ 17:53 那批**不是它的 burn**（它的 burn 只在 18:10–18:14 / 18:16–18:21 / 18:28–18:34 三段存在）；
   17:53 前后属于它 t33 的**验收测试与破坏/还原**阶段，**未用 burner**。
⇒ 若当时看到的确实是 4 个 burner，**那需要另查**；
   但它能确定的是：**它的三段 burn 窗口都有日志与残留 0 的实测记录**。
```
**⇒ captain 记录为「未决归属」，不阻塞任何结论**（verifier 当时观测到的 4 个进程无法归因到具体成员）。

**它的交付物清单（供 captain 核，不必只看结论）**：
```
E:\a 工作\wiki-audit\team-a4-t33-verification-race.md（含 §8 确定性证据、§9 负载 A/B、§9.6 订正）
E:\a 工作\wiki-audit\t33-stage1.log / t33-stage3.log / t33-stage4.log（三段原始输出）
apps/backend/tests/test_task_verification_scope.py（新增；双向反证过）
adapters.py sha16 = 20A818B17DED13BD（未再改动）
```
**⇒ captain 采纳其「供核」姿态**：**它主动给出可独立核验的原始日志，而不只给结论。**


### 进度（captain，03:34）2026-09-20
```
t31（engineer-rrf）  向量索引实现 —— 进行中（2 个 python 进程，60 dirty files）
t34（verifier）· t35（scout）  等 t31 收口
```
**captain 本轮无新裁定**（所有待决项已裁定；第二十一条「状态块优先」已要求全队执行）。


### 🆕 第十条 ⑦：门控须检查**窗口内部**，不只检查边界（engineer-a4 提出，captain 采纳）2026-09-20

**它指出 t34 的三条门控防不住它自己踩的污染**：
```
阶段4 开工前：树静止 ✅ 无 pytest ✅ 无 burn ✅   ⇒ **三条全部满足**
但 18:32:12 第三方写入 app/services/wiki/projections.py **落在窗口之内**
⇒ 那 8 次运行归属被它自行打折（报告 §9.6）
⇒ **「开工前静止」不等于「窗口内静止」。**
```
**⇒ 它建议的第四条（captain 采纳）**：
```
**窗口结束后再核「窗口内无第三方写入」** ——
把「指纹连续两次相同」扩展为「**窗口起止之间，该范围内无文件被写入**」
（**按 mtime 扫 `[start, end]` 区间，而非只在起止点比指纹**）。
```
**⇒ 它的理由（captain 采纳）**：**④ 是唯一能防住它这次这种污染的检查 —— 前三条它当时都满足。**
**⇒ 第十条 ⑦（captain 采纳）**：
```
**门控须检查「窗口内部」而非只检查「边界」** ——
起止点静止不蕴含区间内静止；须按 mtime 扫区间。
```
**⇒ 这与本会话的「差分抵消」是互补的**：
```
差分抵消：**让污染在两侧同样作用**（不消除，只抵消）；
窗口内部检查：**确认污染确实没有发生**（消除）。
⇒ 两条各自适用于不同场景；**engineer-a4 这次是「抵消不成立」（单侧运行）⇒ 必须用消除**。
```

### 🆕 失效模式第 8 类：**自证循环 —— 由主张者本人事后撰写的文档，不是该主张的独立证据**（engineer-a4 提出，captain 采纳）2026-09-20

**它指出 verifier 的一处引用问题**：
> verifier 的 §1① 写「竞态来源（**代码注释已写明**，`adapters.py:1591-1599`）」。
> **但那段注释是它 t33 新加的**、记录它自己在 t26 的诊断。
> **⇒ 先有结论、后写文档 ⇒ 文档不能反过来当结论的证据（自证循环）。**
> **⇒ 且它现在躺在仓库里、看起来像权威在库说明**，将来可能被引作「代码本来就这么说」。
**它建议改引**：经验性产物（pytest-297 / pytest-321 的 `error='verification_mismatch'`、§9 的 A/B、以及代码路径本身）。
**⇒ 它给出的一般形式（captain 采纳为失效模式第 8 类）**：
```
**由主张者本人事后撰写的文档，不是该主张的独立证据；引用须标 producer 与写入时刻。**
```
**⇒ captain 评价**：**这是一条**新**的失效类**，与本会话已有的七类都不同：
```
① 默认值顶替条目  ② 代理指标失效  ③ 基期错配  ④ 阶段完备性假设
⑤ 选择性报告      ⑥ 名字冒充实现  ⑦ 把「没观测到」当成「观测到没有」
⑧ **自证循环**（文档在结论之后写成，却被当作结论的证据）
⇒ ⑧ 的特殊性：**它不是「证据错」，而是「证据的身份错」** ——
   那段注释**是真的**、**在库里**、**读起来像独立说明**，唯一的问题是**它由主张者本人在主张之后写下**。
```
**⇒ 它与第九条同族，但「版本」的含义被扩展**：
```
第九条：证据须带**代码/数据版本**；
第八类：证据还须带「**谁在何时写的**」—— 即 **producer 与写入时刻**。
```


### ⭐⭐ scout 开跑**事前登记的可证伪实验** —— 为 (a) 提供**正向证据**（而非排除法）2026-09-20

**它的窗口确认（19:34:29Z）**：
```
python 进程 = 2: pid=32876 start=19:27:13Z cpu=244.5s   ← **burn 进程，确在跑**
                 pid=34724 start=19:27:13Z cpu=0
logical_cpu = 12    cpu_load_pct = **54**      ← 相比它此前的空载（约 3%）明显升高
⇒ **这是一个「已知负载」的窗口**
```

**⇒ 它事前登记的可证伪推论（第 (iii) 条，**先写后测**）**：
```
PREDICTION: 若负载导致失败，则升高负载下 A/B 两臂的失败数应 >= 空载时的失败数

空载基线(17:53Z, PY_PROCS_AT_START=0):  A = 1 failed(audit_logs) ｜ B = 1 failed(wiki_workflows)
=> 若本次 A/B 每臂失败数 > 1  => **支持 (a)，且是正向证据**
=> 若 <= 1                      => 不支持，我会如实报告

⚠ **这条预测是在开跑之前写下的** —— 它把它先报给 captain，**所以它可被复核**（不是事后构造的）。
```
**⇒ captain 评价**：**这是本会话 (iii) 时间子句的**最完整执行**** ——
**它不只事后说「我有可证伪推论」，而是把推论**在开跑前**报给第三方存档。**
**⇒ 且它补上了此前明确缺失的那一块**：
```
此前：「(a) 负载敏感」只有**排除法**支撑（代码差异已排除 ⇒ 负载是剩余解释）；
本次：**正向证据** —— 事前预测「负载升高 ⇒ 失败数升高」，然后去测。
⇒ **排除法缩小范围，正向证据建立机制** —— verifier 的区分在此被实际执行。
```

**⇒ 它同时按第十条 ④ 分两层记录负载，并用三元组报告**（`logical_cpu=12` / `cpu_load_pct=54` / 施加负载）。

### ✅ captain 裁定：engineer-a4 的**注释自标「事后」**应做（选项①）2026-09-20

**它的问题诊断（captain 采纳）**：
> 第 8 类要落地，光靠「引用者要查 producer」不够 —— **因为引用者往往无法从文本本身看出它是事后写的。**
> **⇒ 写下这类注释的人有义务在文本里自标**，否则那个陷阱永远开着。
**⇒ 裁定：① 并入 t31 收口后的某个窗口由它补上**（约 1 行，不改逻辑）：
```
# 注:本注释写于 t26 诊断之后(t33 修复时补记),是**对结论的文档化**,不是结论的证据。
```
**理由**：**这是第 8 类唯一能从源头关掉的动作** ——
```
引用者侧（「查 producer」）：**无法从文本本身判断** ⇒ 防不住；
写作者侧（「自标事后」）：**在文本里留下身份** ⇒ 能防住。
⇒ 与「删裁量点而非要求自觉」同源：**把约束放在可强制的一侧。**
```
**⇒ 并立为第二十二条团队规则**：
```
**任何「对已成立结论的文档化」（代码注释、设计说明、报告中的机制解释）必须在文本内自标：**
**① 它写于结论之后；② 它是对结论的文档化，不是结论的证据。**
```


### ✅✅✅ t31 完成：**六项验收全部通过**（向量索引，本会话最后一个大项）2026-09-20

**交付物（4 文件，改动面与授权一致）**：
```
migrations/037_wiki_body_vectors.sql          189611ae2844e602（新表 wiki_body_vectors + wiki_generation_semantic_coverage）
app/services/wiki/projections.py              3ddb49cc5160a160（发布期投影，仅本地嵌入器 + 覆盖标记）
app/services/wiki/snapshot_reader.py          274b9397423459f9（索引版语义腿 + 授权闸显式检查 + 维度校验）
tests/test_wiki_semantic_index.py             be2fb27faf34e63e（6 条行为测试）
⇒ git status 确认：**只有这 4 个文件**；wiki_gate / prompt_memory_assembler / companion_retrieval / memory_* 未动
```
**captain 实测落盘**：037 (02:08:22) / projections.py (02:32:12) / test_wiki_semantic_index.py (02:56:29) / snapshot_reader.py (03:24:01) ✅

**验收逐条（证据，非自述）**：
```
#1 默认路径逐行不变    ：bm25 48 题（不注入嵌入器）**逐题 0 差异 / 48**
#2 索引版 vs 现算版相同 ：smoke 3 题相同 + **融合臂 48 题逐题 0 差异 / 48** ← **这是 captain 设的 (B) 判据**
#3 撤销页不复活        ：扩展测试（**向量仍在库里，结果仍为空**）
#4 嵌入不可用 ⇒ 跳过+发布成功：测试钉住（0 向量 + status=unavailable + 发布 published）
#5 套件                ：13 个文件 **103 passed / 0 failed**（646.4s，exit 0）
#6 排序不一致 ⇒ 回退    ：**未触发**（#2 已证明排序一致）
#7 与基线对照 + 归因    ：逐题 0 差异 ⇒ 归因 =「加索引」**未改变检索行为**
```
**⇒ #2 是核心**：**「索引版 vs 现算版逐题 0 差异 / 48」正是 captain 裁定 (B) 的主判据** ——
**索引化的目的是「成本分摊」，不是「改变行为」** ⇒ **0 差异即为成功。**

**⚠️ 它在实现中自查出一个**真实缺陷**并修代码而非修测试**：
```
首轮套件 1 failed —— 失败的是它在 t3 写的 test_embedding_failure_degrades_to_lexical_only
根因：**新索引路径未校验向量维度** ⇒ `_cosine` 被 zip **静默截断** ⇒ 对维度不符的查询向量产出无意义相似度
修法：取回向量后校验 `{dimensions}` 唯一且 == len(query_vector)，不符 ⇒ **回退现算**
⇒ 修完**既有测试无需改动**即恢复（12 passed）；重跑全套件 103 passed / 0 failed
```
**⇒ captain 评价**：**这是「新能力把旧测试变成真实回归检测器」的范例** ——
**若它改测试迁就新行为，就会把维度缺陷留在代码里。**
**⇒ 与本会话「不得为凑绿放宽断言」纪律完全一致。**

**成本**：
```
发布期（一次性）：语料构建含发布 18.3s（14 页/43 块），其中嵌入 ≈0.55s；存储 88KB
  （500 页外推 ≈3.2MB / ≈20s）
查询期（组件级）：**索引版 1084ms vs 现算版 2484ms ⇒ 约 2.3× 更快**
⚠ 已知限制：嵌入在**调用方事务内**（BEGIN IMMEDIATE）⇒ 大 vault 首次发布会持有写锁较久（500 页 ≈20s）
  缓解方向（未做）：嵌入移到事务外。**当前默认关闭 ⇒ 今天不发生。**
```

**三项决策的落实**：
```
决策1 仅本地：projections._local_embedder() 独立解析内置 ONNX；**绝不复用 retrieval_factory**；拿不到 ⇒ 一条都不写 ✅
决策2 跳过不阻止发布：投影/标记不抛异常；**刻意不参与 require_generation_projection 的完整性断言** ✅
决策3 键自然失效：(vault_id, content_hash, chunk_index, embedding_model)，不含 generation ⇒ 跨代复用；未加重建入口 ✅
覆盖偏斜 = 补算通道：标记非 complete ⇒ 整代走现算 ⇒ 行为与今天一致（测试钉住）✅
```

**⚠️ 它要求 captain 更新的树指纹记录**：
```
改动前 live_tree_sha256（它的算法）bdd2ec990bce299d / 8da0b6d1b1b38093
criterion_version = phase_d_eval.py@5fa44edd4bf13069
model_inputs = model.onnx@1294ea4b6331115a / tokenizer.json@48cea5d44424912a
**注意**：它的 `live_tree_sha256` 与 scout 清单的 `TREE_SHA256` **不是同一个量，不可互相比对**（算法不同，已在驱动里显式写出）
```

**未做（明确登记，非遗漏）**：显式重建入口 · 向量读取缓存 · 事务外嵌入 · dist/ 未重打包 · **生产接线（captain 已裁定不做）**


### 🔑 失效模式第 8 类**分两层**（engineer-a4 细化，captain 采纳）2026-09-20

**它指出「事后文档」里有两类东西，独立性不同**：
```
(a) **主张者的散文**（报告正文、机制解释、结论句） ⇒ 由主张者撰写 ⇒ **不独立**；
(b) **机器产出的原始记录**（stage 日志逐行输出、库里 agent_actions 行）
    ⇒ 非散文、程序写的 ⇒ 对**叙述**独立；**但仍被主张者筛选过**
      （它选了跑哪些窗口、贴哪些行）。
```
**⇒ 第 8 类的完整表述（captain 采纳）**：
```
**(a) 主张者事后撰写的散文，不是该主张的独立证据。**
**(b) 机器记录强于散文，但仍受主张者的「选择」影响 ⇒**
    **第三方应「重新导出」，而不是「重读主张者贴出的片段」。**
```
**⇒ 它的操作含义（captain 特别采纳）**：
> 任何人要用它的 A/B，**应从 `t33-stage{1,3,4}.log` 自己重算或直接查库**，
> 而不是引用它报告 §9 的数字 —— **包括 captain 在转述的时候**。
> **它的原始日志留在那里，就是为了让人重算而不是重读。**
**⇒ captain 认领该约束**：**我在台账中引用其 §9 数字时，应标注「引自报告，未独立重算」。**

### ✅ engineer-a4 更正自己：门控 ④ 与 ③ 是**互补**，不是「④ 比 ③ 强」2026-09-20
**verifier 补了它漏掉的一条**：**③ 只比内容哈希 ⇒ 漏掉「内容相同但被重写」的写入**
（`phase_d_eval.py` 12:03:04Z 即此例：**mtime 变、哈希不变**）。
```
哈希  : 看得出「内容变没变」；**看不出「有没有被写过」**（相同内容重写 = 盲区）
mtime : 看得出「被写过」；**看不出「变了几次 / 内容变没变」**（会被后来的相同写入覆盖）
⇒ **各覆盖对方盲区，必须并用。**
```
**⇒ 它明确更正**：**它先前把 ④ 说成「比 ③ 强」是不准的；正确的是互补、缺一不可。**
**⇒ captain 采纳该更正，并据此把门控写成四条并列**（非层级关系）：
```
t34 的四条开工/收工门（并列，缺一不可）：
  ① 依赖任务 completed；
  ② 无 burn 进程（**且 completed ≠ 负载已停止**，第十条 ⑥）；
  ③ 起止点指纹相同（**内容哈希** —— 看得出「内容变没变」）；
  ④ **窗口内无第三方写入**（**mtime 落窗扫描** —— 看得出「有没有被写过」，含相同内容重写）；
⇒ **③ 与 ④ 互补**：前者防「内容变了没发现」，后者防「被写过没发现」。
```

### ✅ t31 = **completed**（captain 实测）2026-09-20
```
t31: **completed@engineer-rrf attempt=2**
⇒ engineer-rrf 那条「stale attempt 无法标记完成」的消息**已过期** —— 它最终成功了。
⇒ captain 无需再发放新 attempt（reassign 被拒：completed 任务不可再派发）。
```
**⇒ t31 的 4 个文件已落盘且六项验收通过 ⇒ 本会话最后一个大项完成。**


### ✅ t31 收口确认 + t34 已开跑（captain，03:50）2026-09-20

```
t31: **completed@engineer-rrf（attempt 2）**
  engineer-rrf 更正其上一条：「**不是被重派 —— 只是 attempt 从 1 轮换到 2**（assignee 仍是我）」
  ⇒ 它按规则**重新 claim** 拿到当前凭证，已标记 completed ✅
  ⇒ **它「stale 时不重试、先报告」的处置依然正确** —— 区别只在于查明「未被重派」后重新 claim 是安全的。
t34: **claimed@verifier** ⇒ **已开跑**（复现并定性 2 个未定性失败，含对照组）
t35: pending@scout（等 t34）
```

**⇒ 本会话最后一个大项（t31 向量索引）已完成。**
**⇒ 剩余：t34（复现+对照）· t35（敏感度量化）· verifier 重冻。**


### ✅ captain 认领：**我在台账中引用他人报告的数字，本身构成第 8 类**（engineer-a4 指出）2026-09-20

**它的原话**：
> 我的报告 §9 的「5/5 vs 2/6」是**我**的统计 —— 任何人引用它作独立证据都构成第 8 类，
> **包括 captain 在转述的时候**。
> 原始日志留在那里，**就是为了让人重算而不是重读**。
**⇒ captain 认领，并据此为本台账中所有「引自他人报告的数字」加标注**：
```
**本台账中凡引自成员报告的数字，均标注「引自报告，未独立重算」** ——
它们**不构成本台账的独立证据**，只是转述；
若要作为独立证据使用，须从原始产物（`t33-stage{1,3,4}.log` / 库中 agent_actions 行）**重新导出**。
```
**⇒ 具体地**：
```
· t33 的「修复后 5/5 vs 修复前 2/6」⇒ **引自 engineer-a4 报告 §9**（未独立重算）；
· t33 的「对照组复现 verification_mismatch」⇒ **引自其报告**（未独立查库）；
· t32 的「48 题逐题 0 差异」⇒ **引自 engineer-rrf 报告**（未独立重跑）；
· t31 的「103 passed / 0 failed」⇒ **引自其报告**（未独立重跑）；
· t30 的「3 failed / 1710 passed」⇒ captain **实测自输出文件**（独立）；
· 全部指纹与文件计数 ⇒ captain **实测**（独立）。
```
**⇒ 这条使台账的「证据等级」变得显式**：**实测 vs 转述，不再混同。**

