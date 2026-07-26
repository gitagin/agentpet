@echo off
REM One-click verification battery for the current fix batch (#11 + #16).
REM Runs every check on both apps and writes ALL output to
REM   E:\agentproject\verification-report.txt
REM When it finishes, just tell Claude "done" - Claude fetches the log itself.
setlocal
cd /d "%~dp0.."
set LOG=%CD%\verification-report.txt

echo ==== VERIFICATION RUN ==== > "%LOG%"
echo repo: %CD% >> "%LOG%"

echo [1/7] staging dead-code deletions with git...
echo. >> "%LOG%"
echo ==== [1/7] git rm dead files ==== >> "%LOG%"
git rm --ignore-unmatch apps/backend/app/agents/nodes/supervisor.py apps/backend/app/agents/nodes/evidence_merge.py apps/backend/app/agents/execution_policy.py apps/backend/app/agents/roles/retrieval_agent.py apps/backend/app/agents/roles/memory_agent.py apps/backend/app/agents/roles/analyst_planner_agent.py apps/backend/app/agents/roles/action_proposal_agent.py apps/backend/app/agents/roles/reviewer_agent.py apps/backend/app/agents/roles/synthesizer_agent.py apps/backend/tests/test_agent_supervisor.py apps/backend/tests/test_agent_parallel_fanout.py apps/backend/tests/test_agent_reviewer.py apps/backend/tests/test_multi_agent_quality_eval.py apps/backend/tests/test_agent_failure_injection.py >> "%LOG%" 2>&1
echo [1/7] exitcode=%errorlevel% >> "%LOG%"

echo [2/7] regenerating openapi.json...
echo. >> "%LOG%"
echo ==== [2/7] openapi export ==== >> "%LOG%"
cd apps\backend
python -m app.openapi_export >> "%LOG%" 2>&1
echo [2/7] exitcode=%errorlevel% >> "%LOG%"

echo [3/7] ruff...
echo. >> "%LOG%"
echo ==== [3/7] ruff check app/ ==== >> "%LOG%"
ruff check app/ >> "%LOG%" 2>&1
echo [3/7] exitcode=%errorlevel% >> "%LOG%"

echo [4/7] mypy (may take a few minutes)...
echo. >> "%LOG%"
echo ==== [4/7] mypy ==== >> "%LOG%"
mypy >> "%LOG%" 2>&1
echo [4/7] exitcode=%errorlevel% >> "%LOG%"

echo [5/7] pytest (10-15 minutes, please wait)...
echo. >> "%LOG%"
echo ==== [5/7] pytest -m "not live_model" ==== >> "%LOG%"
pytest -m "not live_model" >> "%LOG%" 2>&1
echo [5/7] exitcode=%errorlevel% >> "%LOG%"

echo [6/7] desktop npm install + api types...
echo. >> "%LOG%"
echo ==== [6/7] npm install + generate:api-types ==== >> "%LOG%"
cd ..\desktop
call npm install >> "%LOG%" 2>&1
echo [6/7-install] exitcode=%errorlevel% >> "%LOG%"
call npm run generate:api-types >> "%LOG%" 2>&1
echo [6/7-types] exitcode=%errorlevel% >> "%LOG%"

echo [7/7] desktop tests + typecheck...
echo. >> "%LOG%"
echo ==== [7/7] npm run test + typecheck ==== >> "%LOG%"
call npm run test >> "%LOG%" 2>&1
echo [7/7-test] exitcode=%errorlevel% >> "%LOG%"
call npm run typecheck >> "%LOG%" 2>&1
echo [7/7-typecheck] exitcode=%errorlevel% >> "%LOG%"

echo. >> "%LOG%"
echo ==== SUMMARY: grep "exitcode=" above; 0 means pass ==== >> "%LOG%"
echo.
echo All steps finished. Log: %LOG%
echo Tell Claude "done" - the log will be fetched automatically.
pause
