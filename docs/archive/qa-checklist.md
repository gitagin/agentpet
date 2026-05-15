# MVP QA Acceptance Checklist

This checklist tracks the minimum acceptance bar from `Development_Documentation.md` v1.3 for the local-first desktop Agent MVP. Items are written as testable outcomes, not implementation tasks.

## API Contracts

- [ ] `GET /api/health` is callable without `Authorization`.
- [ ] `GET /api/health` returns only service health fields such as `status`, `version`, and `database`.
- [ ] `GET /api/health` never returns `active_vault_id`, vault IDs, vault paths, model provider, model configuration, API keys, usernames, tokens, or authorization headers.
- [ ] Every non-health API requires `Authorization: Bearer <session_token>`.
- [ ] Missing, malformed, or invalid session tokens return `401`.
- [ ] Authenticated-but-forbidden resource access returns `403`.
- [ ] API errors use exactly the documented envelope shape: `{ "error": { "code": "...", "message": "...", "request_id": "...", "details": { ... } } }`.
- [ ] Error responses do not expose stack traces, tokens, API keys, filesystem secrets, or full prompts.
- [ ] Streaming chat uses fetch-compatible SSE over an authenticated request, not native `EventSource` for protected endpoints.

## Documented Status Enums

- [ ] `ConversationStatus`: `active`, `archived`.
- [ ] `MessageStatus`: `partial`, `completed`, `failed`, `cancelled`.
- [ ] `NoteStatus`: `indexed`, `deleted`, `failed`.
- [ ] `MemoryProposalStatus`: `pending`, `confirmed`, `rejected`, `failed`.
- [ ] `TaskStatus`: `pending`, `done`, `cancelled`.
- [ ] `ReminderStatus`: `scheduled`, `unscheduled`, `triggered`, `cancelled`, `failed`.
- [ ] `IndexJobStatus`: `queued`, `running`, `success`, `failed`.
- [ ] `AgentRunStatus`: `running`, `success`, `failed`, `cancelled`.
- [ ] `ToolCallStatus`: `running`, `success`, `failed`, `denied`.
- [ ] `AuditResult`: `allowed`, `denied`, `failed`.

## Security

- [ ] The sidecar binds only to `127.0.0.1`.
- [ ] Session tokens are generated per app launch and are never passed through command-line arguments.
- [ ] Session tokens are not logged, stored in SQLite, exported in diagnostics, or returned by health checks.
- [ ] CORS is restricted to the Electron renderer origins needed by the app and is never the only authorization control.
- [ ] Vault access accepts only user-authorized vault roots.
- [ ] API path inputs for vault files are vault-relative and do not accept arbitrary absolute target paths.
- [ ] `../` traversal is rejected before file access.
- [ ] Symlink, junction, short-path, UNC, and reparse-point escapes are rejected on Windows.
- [ ] Writes to `.obsidian/`, `.git/`, hidden directories, and app index directories are denied by default.
- [ ] Denied security-sensitive operations write an audit log entry without leaking secrets.

## MVP Functional Acceptance

- [ ] Desktop startup shows an operable UI within 10 seconds on Windows.
- [ ] Electron main starts and stops the Python sidecar cleanly.
- [ ] Users can create or bind a Memory Vault.
- [ ] Vault initialization creates the documented default directories and templates.
- [ ] Full indexing of at least 20 Markdown files creates matching `notes`, `note_chunks`, and `note_fts` records.
- [ ] Search returns `relative_path`, snippet, and score for matching Markdown content.
- [ ] Chat responses can cite retrieved vault snippets.
- [ ] Missing auth on streaming chat returns `401` and produces no SSE events.
- [ ] Memory proposals remain pending until explicit user confirmation.
- [ ] Confirmed memory writes update Markdown, proposal status, index data, and audit logs.
- [ ] If target file content hash changes after proposal creation, confirmation returns `409` and requires a regenerated diff.
- [ ] Rejected proposals never write to Markdown.
- [ ] Reminder scheduling supports `scheduled`, `unscheduled`, `triggered`, `cancelled`, and `failed`.
- [ ] Natural-language reminder parsing stores UTC time and preserves the timezone used for parsing.
- [ ] Sensitive memory such as API keys, passwords, tokens, addresses, phone numbers, medical conclusions, legal conclusions, or financial conclusions is rejected by default or requires explicit safe confirmation before any write.

## Verification Commands

- [ ] From `apps/backend`: `python -m pytest tests/test_contracts_*.py tests/test_security_contracts_*.py`.
- [ ] From `apps/backend`: run the full backend test suite before MVP acceptance.
