# Security Review Notes

Scope: MVP security hardening review for backend API behavior, Vault and memory write targets, and model key response handling.

Electron migration note: the desktop shell must keep backend security boundaries unchanged. Electron main is responsible for sidecar lifecycle and per-launch token generation; the token must be passed to the sidecar by environment variable or stdin, never by command-line argument. Renderer code should receive only the minimal API connection contract through preload IPC.

## Covered By Tests

- `apps/backend/tests/test_security_hardening_mvp.py` verifies `/api/settings/model-key` does not return the submitted model API key in plaintext.
- `/api/health` remains unauthenticated but returns only health fields; the test binds a Vault and submits a model key first, then asserts the health payload does not include Vault IDs, Vault paths, auth tokens, model config fields, or the submitted key.
- All non-health MVP API routes are expected to return `401` without `Authorization`, including all current chat stream URL variants before SSE starts.
- Memory proposal target paths reject traversal, absolute paths, hidden directories, and non-Markdown targets before creating a pending proposal.
- Vault initialization rejects a file path target instead of treating it as a Vault directory.

## Sensitive Memory Policy

Sensitive memory proposal classification is enforced before a proposal is inserted. API key-like strings, bearer tokens, password or token assignments, and private-key headers are rejected with a structured `422` response. The response includes a policy reason but does not echo the submitted secret.

## Electron Shell Security Notes

- BrowserWindow must use `contextIsolation: true` and `nodeIntegration: false`.
- Preload must expose a small allowlist of IPC methods; renderer code must not receive raw `ipcRenderer`, `fs`, `child_process`, or environment access.
- Electron main may open native dialogs and manage sidecar processes, but Obsidian Vault business reads/writes must remain in the Python sidecar so path validation and audit behavior stay centralized.
- Production CORS should allow only the packaged Electron renderer origin or file-app origin required by the final packaging strategy, while Authorization remains mandatory for non-health routes.

## Residual Risk

- `/api/settings/model-key` persists model key status and masking metadata for MVP, but it is not yet integrated with Windows Credential Manager or an equivalent OS credential store.
- Path traversal tests cover API-level memory targets and file-vs-directory Vault binding. Lower-level symlink and Windows reparse-point coverage exists in storage tests, but junction-specific enforcement still needs Windows integration coverage.
- Electron shell hardening is documentation-only until the migrated main/preload implementation and packaging scripts land.
