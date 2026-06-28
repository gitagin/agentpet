# TASK-0402 Verification Record

Date: 2026-06-20
Agent: Codex coordinator
Status: Completed
Verification Level: L2

## Objective

Correct version semantics so the repository no longer presents the current
checkout as a ready `0.2.0` product while Phase 1 validation remains incomplete.
Update `CHANGELOG.md` into the required three-part structure:
新增功能 / 修复 / 已知限制.

## Changes

- `apps/backend/pyproject.toml`: changed Python package metadata from `0.2.0`
  to PEP 440 compatible `0.0.1a0`.
- `apps/backend/app/config.py`: changed runtime/API version display from
  `0.2.0` to `0.0.1-alpha`.
- `apps/desktop/package.json` and root metadata in
  `apps/desktop/package-lock.json`: changed desktop package version from
  `0.2.0` to `0.0.1-alpha`.
- `apps/backend/tests/test_diagnostics_export.py`,
  `apps/backend/tests/test_contracts_api_models.py`, and
  `apps/desktop/src/App.test.tsx`: updated hardcoded version expectations.
- `CHANGELOG.md`: replaced the flat Unreleased list with
  `0.0.1-alpha - 2026-06-20` and the required three categories.
- `docs/current-specification.md`, `docs/v0.2-validation.md`, and
  `docs/README.md`: documented that the historical `v0.2.0` label is
  superseded and that the current boundary is alpha.
- `progress.md` and `task.md`: updated coordinator status and task index.

## Verification

### Version marker search

Command:

```powershell
rg -n "0\.0\.1-alpha|0\.0\.1a0" apps\backend\pyproject.toml apps\backend\app\config.py apps\backend\tests apps\desktop\package.json apps\desktop\package-lock.json apps\desktop\src\App.test.tsx docs\v0.2-validation.md docs\current-specification.md CHANGELOG.md
```

Result: matched the updated backend package version, backend runtime version,
desktop package version, desktop lockfile root metadata, test expectations, and
documentation/changelog markers.

### Backend contract tests

Command:

```powershell
Push-Location apps\backend; python -m pytest -q tests/test_diagnostics_export.py tests/test_contracts_api_models.py tests/test_runbook_contracts.py tests/test_mvp_acceptance_gap_contract.py; Pop-Location
```

Result:

```text
25 passed in 5.95s
```

### Desktop package/type checks

Command:

```powershell
Push-Location apps\desktop; npm run typecheck; npm run package:check; Pop-Location
```

Result: `tsc --noEmit` passed; `validate-electron-packaging.mjs` passed and
reported `agent-pet-desktop@0.0.1-alpha`.

### Desktop focused test

Command:

```powershell
Push-Location apps\desktop; npm run test -- App.test.tsx; Pop-Location
```

Result:

```text
1 passed file, 20 passed tests.
```

### MVP acceptance consistency

Command:

```powershell
.\scripts\check-mvp-acceptance-gap.ps1
```

Result:

```text
MVP acceptance gap contract passed.
```

## Residual Notes

- Remaining `0.2.0` mentions in `docs/v0.2-validation.md` are explicitly
  historical or future-gate references.
- Remaining `0.2.0` mentions in `apps/desktop/package-lock.json` belong to
  third-party dependencies, not this project package.
- Skipped or incomplete Phase 1 human validations remain non-completion
  evidence.
