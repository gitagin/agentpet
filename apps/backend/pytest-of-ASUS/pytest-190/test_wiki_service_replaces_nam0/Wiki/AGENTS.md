# LLM Wiki Schema

## Goal
Maintain a growing markdown wiki from immutable source material. The assistant is a wiki maintainer, not a one-off chat bot.

## Layers
- Raw sources are read-only evidence. Do not rewrite or replace them.
- Wiki markdown is the maintained knowledge layer under `Wiki/`.
- This schema defines page contracts, workflow rules, and quality checks.

## Required Files
- `Wiki/index.md` is the content map. Every maintained page must have an entry.
- `Wiki/log.md` is the append-only operation timeline.
- `Wiki/AGENTS.md` is this rule layer.

## Page Types
- source: one source summary and citations.
- entity: person, company, project, paper, file, decision, or other named object.
- concept: reusable idea or term.
- synthesis: conclusion drawn from multiple pages or sources.
- comparison: structured contrast between entities, concepts, or approaches.
- report: operational output such as lint or query archive reports.

## Ingest
1. Preserve the raw source and source hash.
2. Create or update a source page.
3. Update related entity, concept, synthesis, or comparison pages.
4. Update `Wiki/index.md`.
5. Append `Wiki/log.md`.
6. Run lint or record the lint summary.

## Query
1. Read `Wiki/index.md` first to identify relevant pages.
2. Read relevant wiki pages and necessary raw sources.
3. Answer only from evidence.
4. Archive reusable answers or propose page updates.
5. Append `Wiki/log.md`.

## Lint
Check contradictions, stale statements, orphan pages, broken links, missing index entries, missing log records, duplicate concepts, naming drift, and schema/frontmatter gaps.

## Writing Rules
- Keep pages concise, structured, and linkable.
- Start with conclusions, then evidence.
- Important claims need source references.
- Do not merge conflicts silently; record the conflicting sources and the difference.
