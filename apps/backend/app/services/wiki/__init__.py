from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_legacy_wiki_path = Path(__file__).resolve().parent.parent / "wiki.py"
_legacy_spec = importlib.util.spec_from_file_location("app.services._wiki_legacy", _legacy_wiki_path)
if _legacy_spec is None or _legacy_spec.loader is None:
    raise ImportError("Unable to load legacy wiki service module")
_legacy_wiki = importlib.util.module_from_spec(_legacy_spec)
sys.modules[_legacy_spec.name] = _legacy_wiki
_legacy_spec.loader.exec_module(_legacy_wiki)

SensitiveWikiRejectedError = _legacy_wiki.SensitiveWikiRejectedError
WikiConflictError = _legacy_wiki.WikiConflictError
WikiService = _legacy_wiki.WikiService
WikiWriteError = _legacy_wiki.WikiWriteError
resolve_wiki_path = _legacy_wiki.resolve_wiki_path
slugify_wiki_title = _legacy_wiki.slugify_wiki_title
utc_now_iso_from_mtime = _legacy_wiki.utc_now_iso_from_mtime
WIKI_CORE_PATHS = _legacy_wiki.WIKI_CORE_PATHS
WIKI_TARGET_ABSENT_HASH = _legacy_wiki.WIKI_TARGET_ABSENT_HASH
WIKI_INDEX_PATH = _legacy_wiki.WIKI_INDEX_PATH
WIKI_LOG_PATH = _legacy_wiki.WIKI_LOG_PATH
WIKI_ROOT = _legacy_wiki.WIKI_ROOT
WIKI_SCHEMA_PATH = _legacy_wiki.WIKI_SCHEMA_PATH

from .common import (
    QueryArchiveNotFoundError,
    QueryArchiveRejectedError,
    ReviewModelResolver,
    WikiIngestApplyRejectedError,
    WikiIngestPreviewTokenError,
    WikiReviewModelProtocol,
    WikiSourceImportRejectedError,
    WikiWorkflowError,
)
from .workflows import WikiWorkflowService

__all__ = [
    "QueryArchiveNotFoundError",
    "QueryArchiveRejectedError",
    "ReviewModelResolver",
    "SensitiveWikiRejectedError",
    "WIKI_CORE_PATHS",
    "WIKI_TARGET_ABSENT_HASH",
    "WIKI_INDEX_PATH",
    "WIKI_LOG_PATH",
    "WIKI_ROOT",
    "WIKI_SCHEMA_PATH",
    "WikiIngestApplyRejectedError",
    "WikiIngestPreviewTokenError",
    "WikiReviewModelProtocol",
    "WikiConflictError",
    "WikiService",
    "WikiSourceImportRejectedError",
    "WikiWriteError",
    "WikiWorkflowError",
    "WikiWorkflowService",
    "resolve_wiki_path",
    "slugify_wiki_title",
    "utc_now_iso_from_mtime",
]
