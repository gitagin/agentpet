from __future__ import annotations

import html
import inspect
import json
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.models.api import (
    MemorySearchResult,
    QueryArchiveDetailResponse,
    QueryArchiveHistoryItem,
    QueryArchiveHistoryResponse,
    QueryArchiveLintResponse,
    QueryArchiveRequest,
    QueryArchiveResponse,
    WikiLintProposal,
    WikiLintRequest,
    WikiIngestApplyRequest,
    WikiIngestApplyResponse,
    WikiIngestConfirmRequest,
    WikiIngestPagePlan,
    WikiIngestPageResult,
    WikiIngestPreviewRequest,
    WikiIngestPreviewResponse,
    WikiIngestReviewFinding,
    WikiIngestReviewRequest,
    WikiIngestReviewResponse,
    WikiPageResponse,
    WikiPageWriteRequest,
    WikiQueryArchiveProposal,
    WikiSourceImportPreviewRequest,
    WikiSynthesisProposal,
    WikiSynthesizeRequest,
    WikiSynthesizeResponse,
)
from app.models.common import new_id
from app.models.enums import AgentId
from app.services.chat_model import ChatModelError
from app.utils.hash import sha256_hex
from app.utils.time import utc_now_iso
from app.services.wiki import WikiService, slugify_wiki_title
from app.storage.database import Database
from app.storage.markdown import parse_markdown

class WikiReviewModelProtocol(Protocol):
    def complete(self, *, user_message: str, system_prompt: str | None = None): ...


ReviewModelResolver = Callable[[AgentId], WikiReviewModelProtocol | None]


class WikiWorkflowError(Exception):
    code = "wiki_workflow_failed"


class QueryArchiveRejectedError(WikiWorkflowError):
    code = "query_archive_rejected"

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("查询归档未通过检查。")


class QueryArchiveNotFoundError(WikiWorkflowError):
    code = "query_archive_not_found"

    def __init__(self, archive_id: str) -> None:
        self.archive_id = archive_id
        super().__init__(f"未找到查询归档：{archive_id}")


class WikiIngestApplyRejectedError(WikiWorkflowError):
    code = "wiki_ingest_apply_rejected"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class WikiSourceImportRejectedError(WikiWorkflowError):
    code = "wiki_source_import_rejected"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class WikiIngestPreviewTokenError(WikiWorkflowError):
    code = "wiki_ingest_preview_token_invalid"


_PREVIEW_TOKEN_TTL_SECONDS = 600.0


@dataclass(frozen=True)
class _CachedIngestPreview:
    request: WikiIngestPreviewRequest
    response: WikiIngestPreviewResponse
    intent_key: str
    scope_key: str
    expires_at: float


@dataclass(frozen=True)
class _StoredPagePlan:
    id: str
    title: str
    target_path: str
    operation: str
    section: str | None
    content: str
    tags: list[str]
    links: list[str]


@dataclass(frozen=True)
class _StoredIngestRun:
    id: str
    source_id: str | None
    source_title: str
    source_type: str
    source_uri: str | None
    raw_content: str
    page_plans: list[_StoredPagePlan]


_INGEST_PREVIEW_CACHE: dict[str, _CachedIngestPreview] = {}
