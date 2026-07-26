@echo off
REM Backlog #11: remove the unreachable supervisor/reviewer/role-contract system.
REM Stages the 14 file deletions with git so they land in your next commit.
REM Modified files were already written to disk by Claude; review with git diff.
cd /d "%~dp0.."
git rm --ignore-unmatch ^
 apps/backend/app/agents/nodes/supervisor.py ^
 apps/backend/app/agents/nodes/evidence_merge.py ^
 apps/backend/app/agents/execution_policy.py ^
 apps/backend/app/agents/roles/retrieval_agent.py ^
 apps/backend/app/agents/roles/memory_agent.py ^
 apps/backend/app/agents/roles/analyst_planner_agent.py ^
 apps/backend/app/agents/roles/action_proposal_agent.py ^
 apps/backend/app/agents/roles/reviewer_agent.py ^
 apps/backend/app/agents/roles/synthesizer_agent.py ^
 apps/backend/tests/test_agent_supervisor.py ^
 apps/backend/tests/test_agent_parallel_fanout.py ^
 apps/backend/tests/test_agent_reviewer.py ^
 apps/backend/tests/test_multi_agent_quality_eval.py ^
 apps/backend/tests/test_agent_failure_injection.py
if errorlevel 1 goto :fail
echo.
echo [OK] 14 dead-path files staged for deletion. Run your tests, then commit.
pause
exit /b 0
:fail
echo.
echo [FAILED] git rm reported a problem - send the output above to Claude.
pause
exit /b 1
