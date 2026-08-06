@echo off
REM Backlog #9: generate both desktop API types and the Electron proxy route
REM artifact from the committed apps/backend/openapi.json snapshot.
REM Outputs: apps\desktop\src\types.gen.ts and
REM          apps\desktop\electron\proxy-routes.generated.json
cd /d "%~dp0..\apps\desktop"
echo === npm install ===
call npm install
if errorlevel 1 goto :fail
echo.
echo === generate OpenAPI-derived desktop contracts ===
call npm run generate:api-contracts
if errorlevel 1 goto :fail
echo.
echo [OK] Desktop API contracts generated. Commit them together with openapi.json.
pause
exit /b 0
:fail
echo.
echo [FAILED] Something went wrong - send the output above to Claude.
pause
exit /b 1
