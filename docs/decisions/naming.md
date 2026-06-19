# Naming Decision

Status: Accepted

Date: 2026-06-19

## Decision

Keep the current project name and internal identifiers:

- Product/project name: Agent Pet
- Package and protocol prefix: `agent-pet`
- Repository-facing shorthand: `agentpet`

## Rationale

The current codebase already uses `Agent Pet` and `agent-pet` across backend package metadata, desktop package metadata, Electron IPC channels, tests, documentation, and Live2D assets. Renaming would require a broad cross-module migration with product, package, protocol, documentation, and test impact.

The project positioning is clarified instead of renaming: Agent Pet is a local-first long-term memory companion with a desktop pet entry point. It is not an AI coding-agent monitoring or evaluation desktop tool.

## Consequences

- Existing package names, IPC channels, storage keys, tests, and asset names stay unchanged.
- README should state the positioning clearly near the top to reduce search or repository-name confusion.
- Future public documentation should prefer the phrase "local-first long-term memory companion" when explaining the product category.
