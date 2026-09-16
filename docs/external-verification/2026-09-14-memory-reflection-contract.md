# Memory Retrieval and Reflection Contract Verification

- Accessed: 2026-09-14
- Checkout: local working tree under review
- Declared dependency ranges:
  - `langchain>=1.2,<1.3`
  - `langgraph>=1.1.5,<1.2`
  - `langchain-openai>=1.1.14,<2`
  - `qdrant-client>=1.16,<2` when the vector extra is installed
- Installed versions used by the local verification run:
  - `langchain==1.3.14`
  - `langgraph==1.2.10`
  - `langchain-openai==1.1.14`
  - `qdrant-client==1.17.1`

The installed `langchain` and `langgraph` versions are outside the project's declared ranges. Passing tests in this environment are useful regression evidence, but they do not prove compatibility with the declared ranges.

## Sources and Decisions

### LangGraph workflows and agents

- Source: https://docs.langchain.com/oss/python/langgraph/workflows-agents
- Source type: official documentation
- Applicable versions: current LangGraph documentation as accessed on 2026-09-14; the workflow/agent distinction is architectural rather than tied to a single patch release.
- Key conclusion: workflows use predetermined code paths, while agents choose tools and steps dynamically; routing can use structured output and explicit conditional edges.
- Project mapping: an explicit user-selected memory domain is treated as a deterministic workflow constraint. The semantic model may refine ambiguous requests, but it cannot widen `knowledge_base` to personal memory or daily chat. The enforced scope is passed as structured tool configuration rather than parsed back from prompt prose.

### LangChain human-in-the-loop

- Source: https://docs.langchain.com/oss/python/langchain/human-in-the-loop
- Source type: official documentation
- Applicable versions: the documented core approve/edit/reject lifecycle applies to LangChain 1.x; conditional `when` predicates specifically require `langchain>=1.3.3` and are not used by this project because the declared range is `<1.3`.
- Key conclusion: `approve` executes the original proposed arguments, while `edit` changes them before execution. The documentation warns that significant edits can cause repeated or unexpected actions.
- Project mapping: confirming a reflection proposal must execute the action type and target that were reviewed. Wiki summaries therefore use a server-derived target, validate kind/action/target at proposal construction and confirmation, and execute through a dedicated Wiki summary adapter/reader.

### Qdrant filtering

- Source: https://qdrant.tech/documentation/search/filtering/
- Source type: official documentation
- Applicable versions: payload filtering is supported by the project's declared `qdrant-client>=1.16,<2`; the project does not rely on the newer prefix condition documented for Qdrant 1.19.
- Key conclusion: filters are query-time conditions on payload or point IDs and can express AND, OR, and NOT constraints. Metadata constraints that cannot be represented by embeddings should be applied as filters.
- Project mapping: source isolation belongs at the retrieval call boundary. Prompt text and vector similarity are not trusted to enforce `knowledge_base`, `personal_memory`, or `daily_chat` separation.

### LangChain indexing RFC

- Source: https://github.com/langchain-ai/langchain/pull/23544
- Source type: maintainer RFC, closed without merge; non-normative implementation experience
- Applicable versions: historical design discussion from 2024, not a supported API contract.
- Key conclusion: the proposed retrieval interface makes filters explicit, requires conformance tests, and prefers an explicit unsupported error over silent failure.
- Project mapping: explicit source scope has regression tests at router, semantic override, retrieval call, and citation levels. Failure to recover a structured scope is logged instead of silently pretending that prompt-only enforcement succeeded.

### Tool argument validation experience

- Source: https://forum.langchain.com/t/langchain-langgraph-tool-args-validation-middleware/3910
- Source type: community implementation discussion with LangChain team and expert feedback; supporting evidence only
- Applicable versions: LangChain 1.x agent middleware patterns discussed in June 2026.
- Key conclusion: validate model-generated tool arguments before tool execution and before human approval; write normalized arguments back so validation and execution observe the same values.
- Project mapping: `ReflectionProposal` validation is the first boundary, persisted proposals are validated again immediately before side effects, and the Wiki summary executor receives the same normalized target that policy approved.

## Local Verification

- Targeted memory routing, grounding, reflection workflow, reflection API, and action lifecycle tests: `92 passed`.
- Full backend suite: `1312 passed, 2 skipped`; one pre-existing warning reports that the `live_model` pytest marker is not registered.
- Backend Ruff checks: passed.
- Desktop OpenAPI contract check, hooks lint, and TypeScript typecheck: passed.
- Desktop production build: passed; Vite reported a non-failing large-chunk performance warning.
