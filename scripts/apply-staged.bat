@echo off
REM The Claude bridge currently fails silently when OVERWRITING existing files
REM (new files are fine), so the new versions were staged as new files under
REM .claude-staged\ mirroring the repo layout. This script copies them into
REM place, checks a few sentinels, then cleans up.
setlocal
cd /d "%~dp0.."

if not exist ".claude-staged" (
  echo [FAILED] .claude-staged folder not found - nothing to apply. Tell Claude.
  pause
  exit /b 1
)

echo ==== [1/3] copying staged files over the working tree ====
xcopy ".claude-staged\*" "." /E /Y /I /Q
if errorlevel 1 goto :fail

echo ==== [2/3] sentinel checks ====
findstr /C:"degraded" "apps\desktop\electron\sidecar.js" >nul || goto :sentinelfail
findstr /C:"compare_digest" "apps\backend\app\auth.py" >nul || goto :sentinelfail
findstr /C:"createAppWindow" "apps\desktop\electron\windows.js" >nul || goto :sentinelfail
findstr /C:"import json" "apps\backend\app\agents\graph_runtime.py" >nul && goto :sentinelfail
echo   all 4 sentinels OK

echo ==== [3/3] cleanup ====
rmdir /s /q ".claude-staged"
if exist "scripts\write-probe.txt" del /q "scripts\write-probe.txt"
echo.
echo [OK] All files applied. Now double-click scripts\run-verification.bat again.
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
