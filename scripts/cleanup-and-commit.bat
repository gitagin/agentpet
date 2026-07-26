@echo off
REM Clean up test/verification artifacts, re-check lint, then commit the batch.
REM Keeps the reusable tools (run-verification.bat, generate-openapi.ps1,
REM generate-api-types.bat). Refuses to commit if ruff is red.
setlocal
cd /d "%~dp0.."

echo ==== [1/4] cleaning temporary test artifacts ====
if exist verification-report.txt del /q verification-report.txt && echo   deleted verification-report.txt
if exist apps\backend\mypy-report.txt del /q apps\backend\mypy-report.txt && echo   deleted mypy-report.txt
if exist apps\backend\mypy-services.txt del /q apps\backend\mypy-services.txt && echo   deleted mypy-services.txt
if exist apps\backend\mypy-agents-api.txt del /q apps\backend\mypy-agents-api.txt && echo   deleted mypy-agents-api.txt
if exist apps\backend\.coverage del /q apps\backend\.coverage && echo   deleted .coverage
if exist apps\backend\.tmp rmdir /s /q apps\backend\.tmp && echo   deleted apps\backend\.tmp\
if exist apps\backend\tmpb_m66lhf rmdir /s /q apps\backend\tmpb_m66lhf && echo   deleted apps\backend\tmpb_m66lhf\

echo ==== [2/4] retiring finished one-shot helpers (git rm) ====
git rm -q --ignore-unmatch apps/backend/mypy-probe.ini scripts/apply-deadcode-removal.bat
echo   retired mypy-probe.ini + apply-deadcode-removal.bat

echo ==== [3/4] ruff gate ====
cd apps\backend
ruff check app/
if errorlevel 1 (
  echo.
  echo [STOP] ruff is red - NOT committing. Send the output above to Claude.
  pause
  exit /b 1
)
echo   ruff: all checks passed
cd ..\..

echo ==== [4/4] commit ====
git add -A
echo.
git status --short
echo.
set /p CONFIRM=Commit all of the above? [Y/N]: 
if /i not "%CONFIRM%"=="Y" (
  echo Skipped commit. Changes remain staged for your review.
  pause
  exit /b 0
)
git commit -m "fix-backlog: #11 dead-code removal (-4083 lines), #16 fts default + vector extra, #9/#10 closeout, workspace cleanup"
echo.
echo [OK] Committed. Tell Claude to start the next batch (#8 + #19 + #7).
pause
