param(
    [string]$WorkDir = ".\.tmp\task-1104",
    [ValidateRange(1, 20)]
    [int]$Runs = 3
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot "apps\backend"
$resolvedWorkDir = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $WorkDir))
$allowedRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot ".tmp"))

if (-not $resolvedWorkDir.StartsWith($allowedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "WorkDir must stay under the repository .tmp directory."
}

New-Item -ItemType Directory -Force -Path $resolvedWorkDir | Out-Null

Push-Location $backendDir
try {
    for ($run = 1; $run -le $Runs; $run++) {
        $env:TASK_1104_DB = Join-Path $resolvedWorkDir ("checkpoint-{0}-{1}.sqlite3" -f $run, [guid]::NewGuid().ToString("N"))
        $env:TASK_1104_RUN = $run.ToString()

        python -c "import os; from datetime import datetime, timedelta, timezone; from app.agents.checkpointer import SQLiteCheckpointStore; from app.storage.database import Database, MigrationRunner; db=Database(os.environ['TASK_1104_DB']); MigrationRunner(db).apply(); SQLiteCheckpointStore(db).save_pending(checkpoint_id='checkpoint-'+os.environ['TASK_1104_RUN'], thread_id='thread-isolated', run_id='run-'+os.environ['TASK_1104_RUN'], graph_version='graph-v1', state_version='state-v1', node_name='action_agent', state={'risk':'high','target_class':'isolated-test'}, expires_at=datetime.now(timezone.utc)+timedelta(hours=1), action_proposal_id='proposal-'+os.environ['TASK_1104_RUN'], idempotency_key='effect-'+os.environ['TASK_1104_RUN'])"
        if ($LASTEXITCODE -ne 0) {
            throw "Checkpoint creation process failed for run $run."
        }

        python -c "import os; from app.agents.checkpointer import SQLiteCheckpointStore; from app.storage.database import Database; store=SQLiteCheckpointStore(Database(os.environ['TASK_1104_DB'])); checkpoint_id='checkpoint-'+os.environ['TASK_1104_RUN']; record=store.load_for_resume(checkpoint_id, graph_version='graph-v1', state_version='state-v1'); decision=store.claim_decision(checkpoint_id=checkpoint_id, decision_id='decision-'+os.environ['TASK_1104_RUN'], decision='approved', policy_version='policy-v1'); assert record.status == 'pending_confirmation'; assert decision.decision == 'approved'; assert store.get(checkpoint_id).status == 'approved'; print('run='+os.environ['TASK_1104_RUN']+' checkpoint='+checkpoint_id+' result=approved')"
        if ($LASTEXITCODE -ne 0) {
            throw "Checkpoint recovery process failed for run $run."
        }
    }
}
finally {
    Remove-Item Env:TASK_1104_DB -ErrorAction SilentlyContinue
    Remove-Item Env:TASK_1104_RUN -ErrorAction SilentlyContinue
    Pop-Location
}

Write-Output "TASK-1104 isolated checkpoint recovery passed for $Runs run(s)."
