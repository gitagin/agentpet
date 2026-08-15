from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..utils.metric_references import PUBLIC_REFERENCE_PATTERN, is_public_reference


RecallFeedbackSignal = Literal[
    "helpful",
    "incorrect",
    "missing",
    "context_repeated",
    "context_not_repeated",
    "wiki_reused",
]


class MetricValueResponse(BaseModel):
    numerator: int | float = 0
    denominator: int | float = 0
    sample_size: int = 0
    window_days: Literal[7, 30]
    value: float | None = None
    p50_ms: float | None = None
    p95_ms: float | None = None
    queue_peak: int | None = None
    revocation_count: int = 0
    evidence_status: Literal["sufficient", "insufficient_sample"]


class LocalImpactResponse(BaseModel):
    metric_version: str
    window_days: Literal[7, 30]
    generated_at: str
    sample_size: int
    evidence_status: Literal["sufficient", "insufficient_sample"]
    failure_counts: dict[str, int] = Field(default_factory=dict)
    metrics: dict[str, MetricValueResponse] = Field(default_factory=dict)


class RecallFeedbackRequest(BaseModel):
    signal: RecallFeedbackSignal
    reference: str = Field(min_length=1, max_length=160, pattern=PUBLIC_REFERENCE_PATTERN)
    source_scope: str = Field(default="personal_memory", max_length=40, pattern=r"^[A-Za-z0-9_:-]+$")
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    repetition_count: int | None = Field(default=None, ge=0, le=1000)
    answer_reference: str | None = Field(default=None, max_length=160, pattern=PUBLIC_REFERENCE_PATTERN)
    wiki_reference: str | None = Field(default=None, max_length=160, pattern=PUBLIC_REFERENCE_PATTERN)

    @field_validator("reference", "answer_reference", "wiki_reference")
    @classmethod
    def require_public_reference(cls, value: str | None) -> str | None:
        if value is not None and not is_public_reference(value):
            raise ValueError("public_reference_invalid")
        return value


class RecallFeedbackResponse(BaseModel):
    status: Literal["recorded", "replayed"]
    event_id: str
    signal: RecallFeedbackSignal


SidecarRecoveryCause = Literal[
    "process_exited",
    "spawn_failed",
    "startup_failed",
    "readiness_failed",
]


class SidecarRecoveryRequest(BaseModel):
    incident_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    unhealthy_at: datetime
    ready_at: datetime
    cause: SidecarRecoveryCause
    restart_attempt: int = Field(ge=1, le=5)

    @field_validator("unhealthy_at", "ready_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp_timezone_required")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_interval(self) -> "SidecarRecoveryRequest":
        if self.ready_at < self.unhealthy_at:
            raise ValueError("recovery_interval_invalid")
        if self.ready_at - self.unhealthy_at > timedelta(days=30):
            raise ValueError("recovery_interval_too_long")
        return self


class SidecarRecoveryResponse(BaseModel):
    status: Literal["recorded", "replayed"]
    incident_id: str
    unhealthy_event_id: str
    ready_event_id: str
    recovery_time_ms: int = Field(ge=0)
