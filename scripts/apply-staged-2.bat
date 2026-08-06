@echo off
REM Round 2 staged delivery: backlog #12 (api/memory.py split into a router
REM package). Bridge overwrite writes are still unreliable, so everything is
REM staged under .claude-staged\ and this script applies it.
setlocal
cd /d "%~dp0.."

if not exist ".claude-staged" (
  echo [FAILED] .claude-staged folder not found - nothing to apply. Tell Claude.
  pause
  exit /b 1
)

echo ==== [1/4] copying staged files over the working tree ====
xcopy ".claude-staged\*" "." /E /Y /I /Q
if errorlevel 1 goto :fail

echo ==== [2/4] removing the old monolith (replaced by the package) ====
if exist "apps\backend\app\api\memory.py" del /q "apps\backend\app\api\memory.py" && echo   deleted apps\backend\app\api\memory.py

echo ==== [3/4] sentinel checks ====
if exist "apps\backend\app\api\memory.py" goto :sentinelfail
if not exist "apps\backend\app\api\memory\__init__.py" goto :sentinelfail
findstr /C:"rglob" "apps\backend\tests\test_renderer_allowlist_contract.py" >nul || goto :sentinelfail
findstr /C:"app.api.memory.*" "apps\backend\pyproject.toml" >nul || goto :sentinelfail
findstr /C:"MemoryReviewQueries" "apps\backend\app\services\memory_review.py" >nul || goto :sentinelfail
findstr /C:"_GRAPH_FACT_ACTIONS" "apps\backend\app\api\memory\graph.py" >nul || goto :sentinelfail
echo   all 6 sentinels OK

echo ==== [4/4] cleanup ====
rmdir /s /q ".claude-staged"
echo.
echo [OK] Applied. Now double-click scripts\run-verification.bat.
echo IMPORTANT: after it finishes, tell Claude FIRST - do NOT run
echo cleanup-and-commit.bat yet (Claude needs to read the report before
echo it gets deleted).
pause
exit /b 0

:sentinelfail
echo.
echo [FAILED] A sentinel check failed - the staged copy did not apply cleanly.
echo Send this output to Claude.
pause
exit /b 1

:fail
echo.
echo [FAILED] xcopy failed. Send this output to Claude.
pause
exit /b 1
