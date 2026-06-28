# TASK-0301 Verification Record

Status: Completed at L2 documentation-contract level.

Date: 2026-06-20

Task: Establish layered verification standards and write them into the
development workflow.

## Scope

- Create `docs/verification-policy.md`.
- Define L1-L4 verification levels:
  - L1: unit or component check.
  - L2: contract or integration check.
  - L3: real-path end-to-end check.
  - L4: human usability check.
- State that L1-only evidence cannot mark a feature `Completed`.
- Update `progress.md` so milestone records include a verification level.
- Link the policy from the current documentation index.

## Dependency Note

The task source lists Phase 1 completion as a prerequisite. Phase 1 TASK-0102
and TASK-0103 are still not completed; the user explicitly requested continuing
to Phase 3. This record therefore completes only the TASK-0301 policy work. It
does not convert skipped Phase 1 checks into completion evidence.

## Changed Files

- `docs/verification-policy.md`
- `docs/README.md`
- `progress.md`
- `task.md`
- `docs/verification/task-0301/verification-record.md`

## Verification

```powershell
rg -n "verification-policy|Verification Level|L1|L2|L3|L4|Progress Record Template" docs\verification-policy.md docs\README.md progress.md
```

Result: passed. The command found the policy link, L1-L4 definitions, progress
template, and milestone rows with `Verification Level`.

```powershell
.\scripts\check-mvp-acceptance-gap.ps1
```

Result: passed. Output: `MVP acceptance gap contract passed.`

```powershell
git diff --check
```

Result: passed. Only existing LF/CRLF normalization warnings were printed; no
whitespace errors were reported.

## Result

TASK-0301 DoD is satisfied at L2: the verification policy exists, it is linked
from the docs index, and `progress.md` now uses the verification-level field.
