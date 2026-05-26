from typing import Literal

from pydantic import BaseModel, Field


class HealthComponentResponse(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    reason: str | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    database: str
    components: dict[str, HealthComponentResponse] = Field(default_factory=dict)


class DiagnosticsDatabaseStatus(BaseModel):
    path_configured: bool
    reachable: bool
    quick_check: str | None = None
    migration_versions: list[str] = Field(default_factory=list)
    table_counts: dict[str, int] = Field(default_factory=dict)


class DiagnosticsVaultStatus(BaseModel):
    configured: bool
    active_vault_id: str | None = None
    vault_count: int = 0
    names: list[str] = Field(default_factory=list)


class DiagnosticsIndexJobSummary(BaseModel):
    id: str
    vault_id: str
    type: str
    status: str
    files_seen: int
    files_indexed: int
    error: str | None = None
    created_at: str
    updated_at: str


class DiagnosticsAuditLogSummary(BaseModel):
    id: str
    actor: str
    action: str
    target_path_present: bool
    target_name: str | None = None
    result: str
    reason: str | None = None
    created_at: str


class DiagnosticsExportResponse(BaseModel):
    generated_at: str
    app: dict[str, str]
    database: DiagnosticsDatabaseStatus
    vault: DiagnosticsVaultStatus
    model_configured: bool
    recent_index_jobs: list[DiagnosticsIndexJobSummary] = Field(default_factory=list)
    recent_audit_logs: list[DiagnosticsAuditLogSummary] = Field(default_factory=list)


class LocalStateResetRequest(BaseModel):
    confirmation: str


class LocalStateResetResponse(BaseModel):
    status: str
    cleared_tables: dict[str, int] = Field(default_factory=dict)
    removed_paths: list[str] = Field(default_factory=list)
