# Electron Migration QA Checklist

This checklist records the desktop shell expectations after replacing the Tauri shell with Electron. It is QA-owned and should not be treated as the Electron implementation plan.

## Active Desktop Config

- [ ] `apps/desktop/package.json` has no Tauri scripts, package aliases, or `@tauri-apps/*` dependencies.
- [ ] `apps/desktop/package-lock.json` has been regenerated without `@tauri-apps/*` packages.
- [ ] `apps/desktop/src-tauri` has been removed from the active desktop app.
- [ ] `apps/desktop/package.json` declares an Electron runtime or dev dependency and has Electron launch/build scripts.

Current review note: satisfied. `package.json` points at Electron, `package-lock.json` has been regenerated without `@tauri-apps/*`, and `apps/desktop/src-tauri` has been removed.

## Electron Security Baseline

- [ ] Renderer windows use `contextIsolation: true`.
- [ ] Renderer windows use `nodeIntegration: false`.
- [ ] Renderer windows use `sandbox: true` unless a documented preload requirement makes it impossible.
- [ ] Renderer windows keep `webSecurity: true`.
- [ ] A preload script exposes only a narrow, typed API surface with `contextBridge`.
- [ ] Navigation and new-window handling deny unexpected external URLs.
- [ ] Electron main launches the Python sidecar on `127.0.0.1` and stops it during app shutdown.
- [ ] Electron main generates a cryptographically random per-launch session token.
- [ ] Electron main passes the session token to the sidecar through environment variables or stdin, never command-line arguments.
- [ ] Electron main does not log, externalize, or persist bearer-token material.
- [ ] Electron main denies or brokers renderer permission requests.
- [ ] Production loads local packaged assets; development loads only the Vite dev origin.
- [ ] A Content Security Policy is documented for packaged renderer assets.
- [ ] Secrets are not exposed through renderer globals, query strings, logs, or persistent browser storage.

Current review note: `apps/desktop/electron/main.cjs` sets the expected BrowserWindow hardening flags and denies unexpected navigation/new-window requests. `apps/desktop/electron/preload.cjs` uses `contextBridge`. Renderer-only UI preferences that previously would have used browser storage now go through an allowlisted Electron UI-state IPC bridge (`agent-pet.live2d-model-id`, `agent-pet.wiki-archive-candidate`), with `sessionStorage` kept only as the browser-development fallback.

## Frontend API Expectations

- [x] Streaming chat uses `fetch` over SSE so protected requests can send `Authorization`.
- [x] Protected streaming endpoints do not use native `EventSource`.
- [x] Frontend source does not use `localStorage`.
- [x] Temporary connection settings use `sessionStorage`; API keys should remain backend-managed and must not be stored in browser storage.
- [x] Persistent renderer UI choices use the allowlisted Electron preload bridge instead of `localStorage`; browser development may fall back to `sessionStorage`.

## Verification Commands

Run the desktop migration validator:

```powershell
Push-Location apps\desktop
node .\scripts\validate-electron-migration.mjs
Pop-Location
```

Run the Vite/esbuild EPERM diagnostic:

```powershell
Push-Location apps\desktop
node .\scripts\diagnose-vite-esbuild.mjs
Pop-Location
```

Run backend regression tests:

```powershell
.\scripts\test-backend.ps1
```
