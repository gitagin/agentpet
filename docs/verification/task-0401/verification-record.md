# TASK-0401 Verification Record

Status: Completed at L2 documentation-contract level.

Date: 2026-06-20

Task: Merge conflicting documentation and remove the dual-spec debt.

## Scope

- Compare the old `Development_Documentation.md` against current docs and code
  boundaries.
- Create one current authoritative specification document.
- Move the old `Development_Documentation.md` into `docs/archive/`.
- Add an archive notice to the old document.
- Remove root-level references that treated the old spec as current.

## Changed Files

- `docs/current-specification.md`
- `docs/archive/Development_Documentation.md`
- `README.md`
- `docs/README.md`
- `docs/mvp-acceptance-coverage.md`
- `AGENTS.md`
- `progress.md`
- `task.md`
- `docs/verification/task-0401/verification-record.md`

## Reconciliation Summary

`docs/current-specification.md` maps every old section from 0 through 26 to the
current authoritative source:

- current code and migrations for runtime/schema behavior;
- `docs/verification-policy.md` for L1-L4 verification rules;
- `docs/mvp-acceptance-coverage.md` and `docs/v0.2-validation.md` for
  acceptance boundaries;
- `progress.md` and task verification records for execution state;
- the archived old document only for historical context.

## Verification

```powershell
Test-Path Development_Documentation.md; Test-Path docs\current-specification.md; Test-Path docs\archive\Development_Documentation.md
```

Result: `False`, `True`, `True`.

```powershell
rg -n "Development_Documentation.md|current-specification.md|当前唯一生效|当前生效规格|已归档，不再维护" README.md docs AGENTS.md task.md progress.md
```

Result: passed. Current references point to `docs/current-specification.md` or
the archived old document. Remaining old-document mentions are in archive
history, archive checklist, or explicit archive references.

```powershell
.\scripts\check-mvp-acceptance-gap.ps1
```

Result: passed. Output: `MVP acceptance gap contract passed.`

```powershell
python -m pytest -q tests/test_runbook_contracts.py tests/test_mvp_acceptance_gap_contract.py
```

Result: passed. Output: `9 passed in 1.93s`.

## Result

TASK-0401 DoD is satisfied at L2. The repository has one current effective
specification document, and the old specification has been archived with a clear
notice.
