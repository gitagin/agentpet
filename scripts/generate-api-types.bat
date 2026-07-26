@echo off
REM Backlog #9-2: install openapi-typescript and generate desktop API types
REM from the committed apps/backend/openapi.json snapshot.
REM Double-click this file, or run it from cmd. Output: apps\desktop\src\types.gen.ts
cd /d "%~dp0..\apps\desktop"
echo === npm install ===
call npm install
if errorlevel 1 goto :fail
echo.
echo === generate src\types.gen.ts ===
call npm run generate:api-types
if errorlevel 1 goto :fail
echo.
echo [OK] src\types.gen.ts generated. Commit it together with openapi.json.
pause
exit /b 0
:fail
echo.
echo [FAILED] Something went wrong - send the output above to Claude.
pause
exit /b 1
