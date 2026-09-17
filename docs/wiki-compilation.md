# Wiki compilation

## Workflow

With a configured model, the ingest preview and file-import preview endpoints
run the same compiler. The compiler reads every source segment, extracts quoted
notes and structured candidates, selects related pages from the complete page
catalog, reads selected pages, and proposes complete merged source/entity/concept
pages. The preview does not write source records or knowledge pages. Confirmation
stores the original source and proposal; review and explicit application use the
existing workflow and action lifecycle.

Compilation retains prior source and evidence references. New source page names
include a content-hash suffix, so distinct documents with the same title do not
overwrite each other's source pages. The proposal captures byte hashes for its
read dependencies and write targets. Confirmation and application reject changed
context; full-page replacement requires a target hash. Each run retains its own
compiler metadata, including when another run ingests the same source.

Generated quotations must occur verbatim in the supplied source or selected
page. A valid quotation proves text existence, not that a conclusion follows from
it. Model-detected conflicts appear in the page and set `disputed`; existing
disputes are not automatically cleared. Structured model extraction enters the
existing candidate lifecycle, not automatic fact activation.

The synthesis write workflow now reads and verifies its authoritative source
pages before asking the configured model to produce a synthesis. The supplied
content is the question/draft, not an additional evidence source. The final page
uses the existing independent-source checks, source hashes and write receipts.

Explicit Wiki lint runs add a model comparison across non-report pages and
validate quotations from at least two pages for each semantic finding. These are
review findings, not automatic corrections. `semantic_pages_checked` distinguishes
semantic coverage from structural checks. The lightweight diagnostics queue remains
deterministic and does not start a model call whenever the UI refreshes.

Post-reply summaries use model extraction across the complete answer when a model
is configured. They remain single-source chat summaries, not independent evidence
or automatically verified multi-source knowledge. Topic-page merging is performed
by the ingest compiler; existing historical summaries are not silently rebuilt.

## Limits and failure behavior

- A source has at most 768,000 characters. It is processed in 12,000-character
  segments with 400 characters of overlap. No document tail is silently dropped.
- Catalog selection considers batches of 60 entries and reads at most 24 related
  pages. A proposal contains at most the caller's `max_pages` (maximum 15).
- Each structured model request has a 180,000-character serialized payload limit.
  This is an application size guard, not a provider-independent token estimate.
  Provider context/output limits can still reject a request.
- Semantic lint reads all eligible pages within that same payload limit. Larger
  knowledge bases return a context-limit error; no complete semantic audit is claimed.
- Source, related-page, extraction-schema and context limits fail explicitly.
  Configured-model failures, fabricated quotes and stale context do not fall back
  to an apparently successful compilation.
- Without a configured model, local ingest preserves the existing deterministic
  excerpt workflow and marks it `compilation_status=model_not_configured`.
  Manual synthesis remains available; lint reports zero semantic pages checked.
- The chat ingest tool has a 300-second overall timeout; provider requests retain
  the configured model timeout. Large sources may require the dedicated import UI.
- Normal source and output policy checks precede model dispatch or persistence.
  Existing persisted records are not bulk-recompiled by this change.

## Verification

`tests/test_wiki_compilation.py` exercises consecutive imports, provenance,
conflict markers, candidate extraction, complete long-source coverage, stale
previews, CRLF byte hashes, invalid output, offline state, synthesis and semantic
lint. It uses scripted models and does not establish real-model accuracy, latency,
cost or recall. The broader workflow and lifecycle suites protect existing write,
confirmation and evidence behavior.

## Design references

Accessed 2026-09-17:

- [Karpathy, LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f),
  the April 2026 idea file, not a versioned software dependency. It motivates
  incremental source integration, cross-referenced pages, query reuse and semantic
  maintenance. The SQLite authority and deterministic write gates remain this
  project's implementation choices.
- [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/), Pydantic v2;
  this project requires `>=2.7.4,<3`. Structured outputs use the existing
  `model_json_schema` / `model_validate` pattern and forbid unknown fields. Local
  malformed-output tests verify that rejected output cannot become a page.
