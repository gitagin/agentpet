# Verification Policy

Status: active

Date: 2026-06-20

Owner: coordinator

This document defines the verification levels used by this repository. It is
the rule for progress records, task status, and acceptance wording. When a task
document, `progress.md`, or an acceptance matrix conflicts with current command
output or human evidence, the evidence wins.

## Verification Levels

| Level | Name | What It Proves | Typical Evidence | May Mark Completed? |
| --- | --- | --- | --- | --- |
| L1 | Unit or component check | A small function, component, parser, or formatter works in isolation. | Focused unit tests, component tests, type checks, lint checks, static script checks. | No, not by itself. Use `Implemented (unverified)` unless the task is explicitly documentation-only and has no runtime claim. |
| L2 | Contract or integration check | A module boundary, API contract, renderer/service contract, migration contract, or documentation contract works against current code. | Backend API tests, migration tests, focused integration tests, Electron permission/package checks, acceptance-matrix drift checks, docs contract checks. | Yes only when the task DoD asks for automated/code-contract evidence and no real-path or human evidence is required. |
| L3 | Real-path end-to-end check | The feature works through the real product path with isolated or backed-up state. | Runbook smoke, local backend plus desktop flow, isolated Vault/database trial, real export/import file check, real rollback with state inspection. | Yes for runtime tasks that require real-path behavior, if the DoD does not require a non-developer human. |
| L4 | Human usability check | A real person can complete the workflow and the experience is understandable. | User-confirmed manual run, screen recording, screenshot set, tester notes, usability report. | Yes for tasks that require manual validation or non-developer usability evidence. |

## Status Rules

- `Completed` requires every DoD item for that task to be satisfied at the
  required verification level.
- A feature with only L1 evidence must not be marked `Completed`; write
  `Implemented (unverified)` or `In Progress`.
- If a task explicitly requires manual verification, user confirmation, or a
  non-developer trial, automated tests cannot replace it. The status remains
  `In Progress`, `Partial`, or `Skipped`, depending on the actual decision.
- If the user asks to skip a required verification step, record `Skipped` and
  state that it is not completion evidence.
- `Covered` in an acceptance matrix means current implementation has evidence
  matching the matrix row. `Partial` means the core path exists but at least one
  required verification detail is missing. `Gap` means the outcome is not
  implemented.
- Never write "passed", "covered", or "completed" for a command that was not
  actually run or a human check that was not actually performed.

## Evidence Rules

Every task record must include:

- the verification level, such as `L2`;
- the exact commands or human evidence used;
- the command result or human decision;
- skipped checks and why they were skipped;
- residual risk when the evidence level is lower than the task's real user
  impact.

Sensitive values must not be copied into evidence records. Do not record real
session tokens, authorization headers, API keys, private keys, or credential
file contents.

## Progress Template

Use this milestone row shape in `progress.md`:

```markdown
| Date | Status | Verification Level | Summary | Verification |
| --- | --- | --- | --- | --- |
| 2026-06-20 | Completed | L2 | Short task summary. | Exact command/evidence summary. |
```

Use `None` for planning-only entries that do not claim implementation or
validation. Use `Skipped` as the status and the closest attempted evidence level
when a required validation step is intentionally skipped.

## Agent Workflow Rules

- Before changing a status, read the relevant task DoD and current evidence.
- Prefer focused verification that matches the modified surface, then run the
  broader contract check when the task touches shared policy or acceptance
  state.
- Do not promote skipped Phase 1 human validations to `Completed`.
- When a task is documentation-only, L2 can be satisfied by updating the
  relevant retained contract document or `progress.md` and passing repository
  documentation or acceptance drift checks. Do not create a new Markdown file
  solely to prove that another Markdown file changed.
- When a task changes renderer permissions, storage safety, Vault writes,
  schema, or rollback behavior, use the stronger project-specific checks listed
  in `AGENTS.md` in addition to the task-specific tests.
- Store complete per-task command logs, screenshots and temporary evidence under
  ignored `output/verification/task-XXXX/`; do not recreate `docs/verification/`.
  Keep only durable status summaries in `progress.md` and public acceptance
  boundaries in `docs/mvp-acceptance-coverage.md`.
