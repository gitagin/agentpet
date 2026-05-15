# Backend MVP Integration Notes

Integration coverage lives in `apps/backend/tests/test_e2e_backend_mvp.py`.

The suite covers the v1.3 MVP backend wiring contract:

- `GET /api/health` stays unauthenticated and does not expose vault, model, token, or user state.
- Registered non-health MVP APIs require a bearer session token.
- Vault initialization creates and binds a temporary vault when the route is wired.
- Markdown indexing followed by memory search returns citation fields when vault/index/search wiring is present.
- Task creation preserves UTC reminder time and the original parse timezone when task wiring is present.
- Chat creation returns a stream URL and the stream emits SSE events when streaming is present.
- Memory proposal create, confirm, and reject behavior is asserted when proposal routes are wired.

Electron migration note: these backend contracts are unchanged by the desktop shell migration. Electron main/preload should continue to call the same loopback FastAPI endpoints with `Authorization: Bearer <session_token>`, and renderer SSE consumption should remain fetch-streaming based so custom Authorization headers are available.

Routes that still return the explicit foundation `501 not_implemented` error are skipped with a capability-specific reason. Missing routes or non-501 failures are not skipped, because those indicate contract drift rather than intentionally absent wiring.

Current verification status on 2026-04-26 after backend wiring:

- `python -m pytest tests/test_e2e_backend_mvp.py -q`: passed as part of the full backend suite.
- `python -m pytest`: 45 passed, 3 skipped.
- The previous `test_vault_init_creates_and_binds_temp_vault` failure is resolved. `/api/vaults/init` now creates default Vault content when `create_if_missing=true`.
- `python -m compileall app tests/test_e2e_backend_mvp.py`: passed.
