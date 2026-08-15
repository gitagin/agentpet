# Evidence-First Demo Script

This script demonstrates the local personal LLM Wiki and memory graph using an
isolated `.tmp` data directory. Do not bind a real Vault, expose a token, or
configure a provider that contains private real-user data. Every success is
paired with a failure or a stated evidence gap.

## Setup

```powershell
python -m pytest apps/backend/tests/test_action_lifecycle_wiring.py apps/backend/tests/test_production_checkpoint_resume.py apps/backend/tests/test_production_action_recovery.py -q
if ($LASTEXITCODE -ne 0) { throw "DEMO_BACKEND_GATE_FAILED" }
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-portfolio-claims.ps1
if ($LASTEXITCODE -ne 0) { throw "DEMO_CLAIM_GATE_FAILED" }
```

State the boundary aloud: this is one local Windows user; the model provider
may be remote for non-private input; SQLite and Markdown are authoritative;
FTS is the default retrieval path; Kuzu is optional and rebuildable.

## Main journey

1. **Capture a source.** Import a seeded Markdown note or say “请记住我在这个
   项目中偏好证据优先”。Show the immutable source hash and a candidate with
   evidence. Explain that a model suggestion is not yet an active fact.
2. **Confirm and inspect.** Confirm the low-risk preference. Open `图谱` and
   select the relation. The evidence rail must show entity, relation, source,
   Wiki binding, lifecycle and the action receipt in that order.
3. **Cross-session recall.** Start a new conversation and ask the same fixed
   question. Show the cited answer and the source path. Then search for a seeded
   unknown question and show an explicit no-evidence response rather than a
   plausible completion.
4. **Correct.** Change the preference value. Show the new claim and the
   `supersedes` relation, then ask again. The old claim must not enter the
   answer context. This is the business use: less repeated explanation while
   preserving the right to correct the record.
5. **Forget.** Forget the claim and repeat the question. Show the old fact as
   forgotten/archived and absent from recall. Do not delete the source silently.

## Side-effect and recovery pair

6. Create a task or Wiki page through the current runtime. Inspect the
   `agent_actions` row: claim, idempotency key, authoritative read-back,
   verified receipt and terminal status are visible. Do not infer OS notification
   delivery from this row.
7. Open a supported high-risk Wiki write. Show the original target in the
   checkpoint, reject it, and show zero file effect. Repeat with approval and
   show one page and one terminal receipt; replay the same decision and show no
   second effect.
8. Use the isolated recovery test/report to explain an effect-before-receipt
   crash. The recovery reader finds the existing marker and returns the original
   receipt. Never demonstrate recovery by manually inserting a receipt or by
   running a second adapter call.

## Degradation pair

9. Remove or corrupt the optional Kuzu generation. Refresh the graph page. The
   UI must remain usable, label the source as SQLite and display the fallback
   reason in diagnostics. Do not say the projection is fully healthy.
10. Make the model endpoint unavailable. Browse the local Wiki/FTS path and
    show the bounded provider error. A failed model call must not create a
    memory candidate or Wiki page.
11. Deny notification permission or stop the sidecar only when the relevant
    Windows/manual runner is available. Otherwise mark the step `Partial` and
    show the saved fault report; do not substitute a unit test or screenshot.

## Evidence to show

- Runtime wiring and replay: `apps/backend/tests/test_action_lifecycle_wiring.py`,
  `apps/backend/tests/test_production_checkpoint_resume.py`,
  `apps/backend/tests/test_production_action_recovery.py`,
  `output/verification/LLMWIKI-002/action-journey-report.json`.
- Memory/Wiki journeys: `output/verification/LLMWIKI-004/journey-report.json`,
  `output/verification/LLMWIKI-006/journey/wiki-journey-report.json`.
- Synthetic baseline: `output/verification/LLMWIKI-011/eval-20260814/report.json`.
- Fault matrix: `output/verification/LLMWIKI-013/faults/fault-matrix-report.md`
  (`15 Passed / 0 Failed / 3 Partial`: four real isolated sidecar/API passes,
  eleven deterministic backend-harness passes; packaged Electron sidecar crash,
  real Windows sleep/resume and Windows notification denial remain open).
- Visual status: `output/verification/LLMWIKI-013/visual/visual-report.json`
  (automatic Vite + Chrome gate passed; packaged Electron, Windows DPI and
  manual failure-state review remain `Partial`).

Close by saying what the demo does **not** prove: no real 24-hour soak, no
7-day user denominator, no universal accuracy, no hosted availability and no
business percentage. The frozen baseline is `57/100`; the last independently
audited score is `62/100` (2026-08-11). The 2026-08-14 L3 journeys are evidence
for the next whole-tier review, not an automatic score increase.
