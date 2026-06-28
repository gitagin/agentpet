# TASK-0501 Verification Record

Date: 2026-06-20
Agent: Codex docs-worker
Status: Completed
Verification Level: L2

## Objective

Rewrite the README product narrative so "local-first" is no longer presented as
the core privacy promise. The current narrative is "记忆透明可控 + 跨工具可迁移".

## Changes

- `README.md`: rewrote the product narrative around memory transparency,
  controllability, reversibility, and migration.
- `README.md`: added `数据流向说明` with a Mermaid diagram that separates the
  LLM API request path from local structured-memory and Markdown/Vault storage.
- `README.md`: explicitly discloses that conversation content is sent to the
  selected LLM API when a remote or OpenAI-compatible model service is used.
- `README.md`: removed misleading wording that could imply all conversation
  content stays on the local machine.

## Verification

### Misleading privacy wording search

Command:

```powershell
rg -n "本地优先|对话内容完全不离开本机|永远不离开本机|不离开本机|隐私安全|本地化" README.md
```

Result: no matches.

### Required narrative and data-flow wording search

Command:

```powershell
rg -n "记忆透明可控|跨工具可迁移|数据流向说明|对话内容会发送|LLM API|结构化记忆|Markdown / Vault|对话请求会离开本机" README.md
```

Result: matched the README narrative, disclosure, and data-flow section.

### Diagram signal search

Command:

```powershell
rg -n "flowchart TD|所选 LLM API|本机结构化记忆|用户审阅、撤回、导出、迁移" README.md
```

Result: matched the Mermaid diagram and its key nodes.

### MVP acceptance consistency

Command:

```powershell
.\scripts\check-mvp-acceptance-gap.ps1
```

Result:

```text
MVP acceptance gap contract passed.
```

### Whitespace check

Command:

```powershell
git diff --check
```

Result: passed with LF/CRLF warnings only.

## Residual Notes

- This task was documentation-only when completed. The local privacy mode
  described by TASK-0502 was implemented later and is tracked separately in
  `docs/verification/task-0502/verification-record.md`.
- The README still mentions local storage for structured memory and Markdown
  files, but it no longer uses that as a claim that model requests never leave
  the machine.
