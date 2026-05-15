from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def new_id() -> str:
    return str(uuid4())


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail


class PageParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = None


class PageMeta(BaseModel):
    next_cursor: str | None = None
