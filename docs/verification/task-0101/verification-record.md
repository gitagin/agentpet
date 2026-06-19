# TASK-0101 Manual Verification Record

Status: In Progress - waiting for human screen recording and operation notes.

Task: Core interaction path, desktop pet entry.

Goal: prove that double-clicking the Pet window opens the main stage/control
window in a real desktop run.

## Evidence Files

Place replayable evidence in this folder:

- Recording: TODO, for example `task-0101-double-click-pet-entry.mp4`
- Optional screenshots: TODO
- Raw runtime logs: TODO

Do not mark this task completed until the recording is present and replayable.

## Test Environment

- Date/time:
- Windows user/profile:
- Machine or account freshness:
- Commit under test:
- Backend mode:
- Desktop mode:
- Notes about existing sidecar or Electron processes:

## Required Manual Steps

1. Start from a clean trial environment, fresh user account, or documented
   clean workspace state.
2. Install or start the Electron desktop application from the current checkout.
3. Start screen recording before interacting with the Pet window.
4. Confirm the Pet window is visible.
5. Double-click the Pet window.
6. Confirm whether the main stage/control window opens.
7. Stop recording and save it under this directory.
8. Record any abnormal behavior, delay, focus issue, or failure.

## Expected Result

- Pet window is visible.
- Double-clicking the Pet window opens the main stage/control window.
- The recording clearly shows both the double-click action and the resulting
  opened window.

## Actual Result

Pending human verification.

## README Boundary Check

Current README still states that the real desktop-pet entry has not completed
visual confirmation. Keep that boundary until the evidence above exists.

## Completion Checklist

- [ ] Replayable screen recording exists in `docs/verification/task-0101/`.
- [ ] Operation notes are filled in.
- [ ] Success/failure result is explicitly recorded.
- [ ] README validation boundary is updated only if the recording proves success.
- [ ] Any failure case is captured as a follow-up task instead of hidden.
