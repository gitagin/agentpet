# Vite/esbuild EPERM Diagnostics

Scope: Windows `apps/desktop` build failures where `npm run build` fails while Vite loads `vite.config.ts` and esbuild reports `Error: spawn EPERM`.

## Current Reproduction

From `apps\desktop`:

```powershell
npm run build
```

Current result:

```text
failed to load config from <repo-root>\apps\desktop\vite.config.ts
error during build:
Error: spawn EPERM
    at ensureServiceIsRunning (...\node_modules\esbuild\lib\main.js:1975:29)
```

`tsc --noEmit` completes before Vite starts, so the failure is in the Vite/esbuild config-loading path, not TypeScript type checking.

## Diagnostic Script

Run:

```powershell
Push-Location apps\desktop
node .\scripts\diagnose-vite-esbuild.mjs
Pop-Location
```

The script emits JSON with:

- Node/npm/Vite/esbuild versions.
- Expected esbuild JS launcher and Windows platform binary paths.
- Basic filesystem access checks for the launchers.
- Direct spawn checks for `node`, `npm`, the esbuild binary, `npm exec esbuild`, and Vite.

In the current sandboxed run, the script reproduced `EPERM` even for a nested `spawnSync` of `%ProgramFiles%\nodejs\node.exe --version`, and direct execution of `node_modules\@esbuild\win32-x64\esbuild.exe --version` also returned `EPERM`. That means esbuild is likely the first visible symptom of a broader child-process execution block in the environment.

## Triage Steps

1. Run the diagnostic script and save the JSON output with the build log.
2. If `node version` inside the diagnostic fails with `EPERM`, investigate host policy first: endpoint protection, AppLocker/WDAC, controlled folder access, inherited ACLs, or sandbox restrictions on nested process creation.
3. If only `esbuild platform binary direct` fails, reinstall desktop dependencies:

```powershell
Push-Location apps\desktop
npm ci
node .\scripts\diagnose-vite-esbuild.mjs
Pop-Location
```

4. Confirm the platform package matches Windows x64: `node_modules\@esbuild\win32-x64\esbuild.exe`.
5. If host security quarantined the binary, restore or allowlist the workspace only after verifying the lockfile source and package integrity.
6. Re-run `npm run build` after the diagnostic script no longer reports `EPERM`.
