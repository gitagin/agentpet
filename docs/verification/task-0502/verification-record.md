# TASK-0502 Verification Record

Date: 2026-06-21
Agent: Codex backend-worker
Status: Completed
Verification Level: L3

## Objective

Implement a real "本地隐私模式" switch. When enabled, sensitive chat input is
handled locally: it performs only local keyword/FTS retrieval, does not send the
raw input to the configured model API, and skips model-driven post-reply memory
and continuity work for that sensitive exchange.

## Changes

- Backend settings now expose `local_privacy_mode` through
  `/api/settings`, `/api/settings/automation`, and the automation settings
  store, persisted in existing `app_state` without adding a SQLite migration.
- Chat creation marks sensitive exchanges when `local_privacy_mode` is enabled
  and `memory_policy.evaluate_memory_content(...)` rejects the user message.
- `LangGraphAgentRuntime` short-circuits sensitive local-privacy exchanges:
  it emits a local status, runs local FTS retrieval only, returns a conservative
  reply, and does not call the chat model.
- The chat persistence layer skips post-reply background memory archival and
  continuity proposal model calls for local-privacy sensitive exchanges.
- Desktop settings expose the "本地隐私模式" toggle in the automatic organization
  card, with copy explaining the privacy vs intelligence tradeoff.
- README, current specification, and changelog now describe the implemented
  mode instead of treating it as future work.

## Verification

### Backend focused first run

Command:

```powershell
Push-Location apps\backend; python -m pytest -q tests/test_local_privacy_mode.py tests/test_agent_runtime_chat.py::test_langgraph_runtime_local_privacy_mode_uses_fts_without_model_call tests/test_api_wiring_mvp.py::test_automation_settings_api_roundtrip tests/test_agent_actions.py::test_agent_action_settings_default_to_opt_in_memory; Pop-Location
```

Result: failed because two assertions looked for the narrower phrase
`本机关键词检索` while the product copy said `在本机记忆里做了关键词检索`.
The implementation path ran; tests were corrected to assert the shared
`关键词检索` wording.

### Backend focused second run

Command:

```powershell
Push-Location apps\backend; python -m pytest -q tests/test_local_privacy_mode.py tests/test_agent_runtime_chat.py::test_langgraph_runtime_local_privacy_mode_uses_fts_without_model_call tests/test_api_wiring_mvp.py::test_automation_settings_api_roundtrip tests/test_agent_actions.py::test_agent_action_settings_default_to_opt_in_memory; Pop-Location
```

Result: failed because a leftover assertion from a neighboring streaming test
expected the old `"你好"` final text. The assertion was corrected to compare
the local-privacy final text with emitted token text.

### Backend focused final run

Command:

```powershell
Push-Location apps\backend; python -m pytest -q tests/test_local_privacy_mode.py tests/test_agent_runtime_chat.py::test_langgraph_runtime_local_privacy_mode_uses_fts_without_model_call tests/test_api_wiring_mvp.py::test_automation_settings_api_roundtrip tests/test_agent_actions.py::test_agent_action_settings_default_to_opt_in_memory; Pop-Location
```

Result:

```text
4 passed in 5.97s
```

### Desktop settings checks

Command:

```powershell
Push-Location apps\desktop; npm run test -- SettingsPanel.test.tsx settingsReducer.test.ts; npm run typecheck; Pop-Location
```

Result:

```text
2 passed test files, 16 passed tests.
tsc --noEmit passed.
```

### Backend broader focused suite

Command:

```powershell
Push-Location apps\backend; python -m pytest -q tests/test_agent_runtime_chat.py tests/test_local_privacy_mode.py tests/test_api_wiring_mvp.py tests/test_agent_actions.py; Pop-Location
```

Result:

```text
53 passed in 84.62s
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

### Sensitive test-string scan

Command:

```powershell
rg -n "sk-local|sk-.*localprivacy|api_key=sk-|Bearer .*localprivacy" apps\backend\tests\test_local_privacy_mode.py apps\backend\tests\test_agent_runtime_chat.py apps\backend\app apps\desktop\src\features\settings
```

Result: no matches.

### Whitespace check

Command:

```powershell
git diff --check
```

Result: passed with LF/CRLF warnings only.

## Network Evidence

`tests/test_local_privacy_mode.py` starts a local HTTP model server and configures
the backend model base URL to that server. With `local_privacy_mode=true`, a
sensitive chat message completes through `/api/chat` and the fake model server's
request counter remains `0`. This verifies the model API was not called for the
sensitive exchange.

## Residual Notes

- The local privacy mode is keyword/policy based. It protects content that the
  current sensitive-content detector catches; it is not a universal network
  isolation mode for all possible messages.
- Non-sensitive messages still use the configured model API when a model is
  configured.
