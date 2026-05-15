# Windows Electron Trial Packaging

This note covers the minimal Windows trial distribution path for `apps/desktop`.
It intentionally does not change frontend source code or bundle a Python
runtime.

## Current Packaging Choice

The desktop package is configured for `electron-builder` because the app already
uses a conventional Electron `main` entry and only needs a Windows directory
package and zip archive for trial sharing.

Configured outputs:

- `dir`: unpacked Windows app directory for local smoke testing.
- `zip`: zipped Windows app directory for trial distribution.

The configured output directory is `apps/desktop/release`.

## Sidecar Resource Layout

The packaged Electron main process searches for the Python backend in this
order:

1. `AGENT_PET_BACKEND_DIR`, when set, pointing at a directory containing
   `app/main.py`.
2. Electron packaged resources: `resources/backend`.
3. Electron packaged resources: `resources/sidecar`.
4. Development checkout fallbacks near `apps/desktop` and `apps/backend`.

`apps/desktop/package.json` uses `build.extraResources` to copy only the backend
source needed by `python -m uvicorn app.main:app` into `resources/backend`:

- included: `app/**/*`, `migrations/**/*`, and `pyproject.toml`;
- excluded: `__pycache__`, `.pytest_cache`, `*.pyc`, virtual environments, and
  SQLite/database files.

This is deliberate. Do not point `extraResources` at a prepared Python
environment such as `.venv`, `venv`, or `env`; install backend dependencies on
the trial machine or provide a separately prepared runtime outside this package.
If a frozen sidecar is introduced later, place its launchable directory under
`resources/sidecar` and keep generated caches, test artifacts, local databases,
and credentials out of the package.

## Install State

`electron-builder` is declared in `apps/desktop/package.json` and the workspace
lockfile has been refreshed. `npm run package:check` should now pass after the
renderer has been built.

If a fresh checkout does not have `node_modules`, run from `apps/desktop`:

```powershell
npm install
```

## Readiness Check

Run from `apps/desktop`:

```powershell
npm run package:check
```

Expected ready result:

- Electron entry files are present.
- `dist/index.html` is present after a renderer build.
- Windows package scripts and `electron-builder` config are present.
- `electron-builder is installed` passes.
- `package-lock includes electron-builder` passes.

## Build and Package

From `apps/desktop`:

```powershell
npm run build
npm run package:check
npm run package:win:dir
npm run package:win:zip
```

Shortcut:

```powershell
npm run package:win
```

`package:win` currently produces the zip target. Use `package:win:dir` when you
want only the unpacked directory for faster local inspection.

## Trial Distribution Limits

This package contains the Electron shell, built React/Vite renderer assets, and
the Python backend source under `resources/backend`. It does not include a
frozen Python runtime or backend executable. On a trial machine, Python and the
backend dependencies must still be available, or `AGENT_PET_BACKEND_DIR` must
point to a separately prepared backend directory containing `app/main.py`.

For a machine without a separately prepared Python backend, the packaged app can
start but the sidecar status will report `BACKEND_NOT_FOUND` or a Python spawn /
readiness error.

The Electron main process generates the per-launch session token and injects it
into the managed sidecar as `AGENT_PET_SESSION_TOKEN`. Do not pass this token as
a command-line argument, write it to packaged files, or include it in
`extraResources`.
