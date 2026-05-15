# Documentation Index

This directory keeps only current validation and trial entrypoints at the top level. Historical notes and one-off checklists live in `docs/archive/`.

## Current Documents

| File | Purpose |
| --- | --- |
| `v0.2-validation.md` | Current release contract and completed bump record for `v0.2.0`. Start here when auditing the v0.2 release boundary. |
| `v0.1-validation.md` | Legacy local runnable core-loop gate. Use only when checking the older v0.1 baseline or inherited MVP assumptions. |
| `mvp-acceptance-coverage.md` | Canonical `Covered` / `Partial` / `Gap` matrix used by `scripts/check-mvp-acceptance-gap.ps1` and backend tests. |
| `runbook.md` | Windows local trial commands and smoke workflow. Required by backend runbook contract tests. |
| `electron-migration-checklist.md` | Electron security baseline checked by `apps/desktop/scripts/validate-electron-migration.mjs`. |

## Archived Documents

`docs/archive/` contains older planning, diagnostics, migration notes, and pre-v0.2 trial material. Treat those files as historical context, not current release contracts.

Archived files include:

- `agent-work-plan.md`
- `integration-notes.md`
- `qa-checklist.md`
- `runbook-smoke-progress.md`
- `security-review.md`
- `user-testing-zh.md`
- `vite-esbuild-eperm-diagnostics.md`
- `windows-electron-trial-packaging.md`

## Maintenance Rules

- Do not mark a status `Covered` unless implementation or validation evidence exists.
- Keep `Covered` / `Partial` / `Gap` spelling exact in acceptance documents.
- Keep `mvp-acceptance-coverage.md`, `runbook.md`, and `electron-migration-checklist.md` at the top level unless the scripts/tests that reference them are updated first.
- Add new release-gate material to `v0.2-validation.md` until a later version document is intentionally introduced.
