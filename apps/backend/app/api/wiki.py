from fastapi import APIRouter, Depends, Query, Request, status

from ..errors import AppError
from ..models.api import (
    QueryArchiveLintResponse,
    QueryArchiveDetailResponse,
    QueryArchiveHistoryResponse,
    QueryArchiveRequest,
    QueryArchiveResponse,
    WikiIndexResponse,
    WikiIngestApplyRequest,
    WikiIngestApplyResponse,
    WikiIngestPreviewRequest,
    WikiIngestPreviewResponse,
    WikiIngestReviewRequest,
    WikiIngestReviewResponse,
    WikiGraphSummaryResponse,
    WikiLintReportResponse,
    WikiLintRequest,
    WikiLogResponse,
    WikiPageListResponse,
    WikiPageResponse,
    WikiPageWriteRequest,
    WikiSchemaStatus,
    WikiSourceImportPreviewRequest,
    WikiSynthesizeRequest,
    WikiSynthesizeResponse,
)
from ..services.memory import MarkdownWriteError
from ..services.wiki import SensitiveWikiRejectedError, WikiService, WikiWriteError
from ..services.wiki_lint import WikiLintService
from ..services.wiki_workflows import (
    QueryArchiveNotFoundError,
    QueryArchiveRejectedError,
    WikiSourceImportRejectedError,
    WikiWorkflowError,
    WikiWorkflowService,
)
from .wiring import (
    audit_reason,
    record_audit,
    wiki_lint_service_dependency,
    wiki_service_dependency,
    wiki_workflow_service_dependency,
)

router = APIRouter(prefix="/wiki", tags=["wiki"])


@router.get("/pages", response_model=WikiPageListResponse)
async def list_wiki_pages(service: WikiService = Depends(wiki_service_dependency)) -> WikiPageListResponse:
    return WikiPageListResponse(pages=service.list_pages())


@router.get("/schema", response_model=WikiSchemaStatus)
async def get_wiki_schema(
    request: Request,
    service: WikiService = Depends(wiki_service_dependency),
) -> WikiSchemaStatus:
    response = service.get_schema_status()
    record_audit(request, action="wiki.schema.read", result="success", target_path=response.path)
    return response


@router.get("/index", response_model=WikiIndexResponse)
async def get_wiki_index(
    request: Request,
    service: WikiService = Depends(wiki_service_dependency),
) -> WikiIndexResponse:
    response = service.get_index()
    record_audit(request, action="wiki.index.read", result="success", target_path=response.path)
    return response


@router.get("/graph", response_model=WikiGraphSummaryResponse)
async def get_wiki_graph(
    request: Request,
    service: WikiService = Depends(wiki_service_dependency),
) -> WikiGraphSummaryResponse:
    response = service.get_graph_summary()
    record_audit(
        request,
        action="wiki.graph.read",
        result="success",
        reason=audit_reason(
            request,
            nodes=str(response.summary.get("nodes", 0)),
            edges=str(response.summary.get("edges", 0)),
            broken_links=str(response.summary.get("broken_links", 0)),
        ),
    )
    return response


@router.get("/log", response_model=WikiLogResponse)
async def get_wiki_log(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    service: WikiService = Depends(wiki_service_dependency),
) -> WikiLogResponse:
    response = service.get_log(limit=limit)
    record_audit(request, action="wiki.log.read", result="success", target_path=response.path)
    return response


@router.post("/pages", response_model=WikiPageResponse)
async def write_wiki_page(
    page_request: WikiPageWriteRequest,
    request: Request,
    service: WikiService = Depends(wiki_service_dependency),
) -> WikiPageResponse:
    try:
        response = service.write_page(page_request)
    except SensitiveWikiRejectedError as exc:
        record_audit(
            request,
            action="wiki.page.write",
            result="denied",
            target_path=page_request.target_path,
            reason=audit_reason(request, code=exc.code, policy=exc.reason),
        )
        raise AppError(
            code=exc.code,
            message="Wiki 内容未通过记忆污染策略检查。",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={"reason": exc.reason},
        ) from exc
    except (MarkdownWriteError, WikiWriteError) as exc:
        record_audit(
            request,
            action="wiki.page.write",
            result="failed",
            target_path=page_request.target_path,
            reason=audit_reason(request, code=getattr(exc, "code", exc.__class__.__name__)),
        )
        raise AppError(
            code=getattr(exc, "code", "wiki_write_failed"),
            message=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from exc
    record_audit(
        request,
        action="wiki.page.write",
        result="success",
        target_path=response.relative_path,
        reason=audit_reason(request, index_job_id=response.index_job_id),
    )
    return response


@router.post("/synthesize", response_model=WikiSynthesizeResponse)
async def synthesize_wiki_page(
    synthesize_request: WikiSynthesizeRequest,
    request: Request,
    service: WikiWorkflowService = Depends(wiki_workflow_service_dependency),
) -> WikiSynthesizeResponse:
    try:
        response = service.synthesize(synthesize_request)
    except SensitiveWikiRejectedError as exc:
        record_audit(
            request,
            action="wiki.synthesize",
            result="denied",
            target_path=synthesize_request.target_path,
            reason=audit_reason(request, code=exc.code, policy=exc.reason),
        )
        raise AppError(
            code=exc.code,
            message="Wiki 内容未通过记忆污染策略检查。",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={"reason": exc.reason},
        ) from exc
    except (MarkdownWriteError, WikiWriteError, WikiWorkflowError) as exc:
        record_audit(
            request,
            action="wiki.synthesize",
            result="failed",
            target_path=synthesize_request.target_path,
            reason=audit_reason(request, code=getattr(exc, "code", exc.__class__.__name__)),
        )
        raise _workflow_error(exc) from exc
    record_audit(
        request,
        action="wiki.synthesize",
        result="success",
        target_path=response.page.relative_path,
        reason=audit_reason(request, index_job_id=response.page.index_job_id),
    )
    return response


@router.post("/ingest/preview", response_model=WikiIngestPreviewResponse)
async def preview_wiki_ingest(
    ingest_request: WikiIngestPreviewRequest,
    request: Request,
    service: WikiWorkflowService = Depends(wiki_workflow_service_dependency),
) -> WikiIngestPreviewResponse:
    try:
        response = service.preview_ingest(ingest_request)
    except WikiWorkflowError as exc:
        record_audit(
            request,
            action="wiki.ingest.preview",
            result="failed",
            reason=audit_reason(request, code=getattr(exc, "code", exc.__class__.__name__)),
        )
        raise _workflow_error(exc) from exc
    record_audit(
        request,
        action="wiki.ingest.preview",
        result="success",
        reason=audit_reason(request, run_id=response.run_id, source_id=response.source_id),
    )
    return response


@router.post("/import/preview", response_model=WikiIngestPreviewResponse)
async def preview_wiki_import(
    import_request: WikiSourceImportPreviewRequest,
    request: Request,
    service: WikiWorkflowService = Depends(wiki_workflow_service_dependency),
) -> WikiIngestPreviewResponse:
    try:
        response = service.preview_import(import_request)
    except WikiSourceImportRejectedError as exc:
        record_audit(
            request,
            action="wiki.import.preview",
            result="denied",
            reason=audit_reason(request, code=exc.code, policy=exc.reason),
        )
        raise AppError(
            code=exc.code,
            message=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"reason": exc.reason},
        ) from exc
    except WikiWorkflowError as exc:
        record_audit(
            request,
            action="wiki.import.preview",
            result="failed",
            reason=audit_reason(request, code=getattr(exc, "code", exc.__class__.__name__)),
        )
        raise _workflow_error(exc) from exc
    record_audit(
        request,
        action="wiki.import.preview",
        result="success",
        reason=audit_reason(request, run_id=response.run_id, source_id=response.source_id),
    )
    return response


@router.post("/ingest/apply", response_model=WikiIngestApplyResponse)
async def apply_wiki_ingest(
    apply_request: WikiIngestApplyRequest,
    request: Request,
    service: WikiWorkflowService = Depends(wiki_workflow_service_dependency),
) -> WikiIngestApplyResponse:
    try:
        response = service.apply_ingest(apply_request)
    except WikiWorkflowError as exc:
        record_audit(
            request,
            action="wiki.ingest.apply",
            result="failed",
            reason=audit_reason(request, run_id=apply_request.run_id, code=getattr(exc, "code", exc.__class__.__name__)),
        )
        raise _workflow_error(exc) from exc
    record_audit(
        request,
        action="wiki.ingest.apply",
        result="success" if response.status == "applied" else response.status,
        reason=audit_reason(request, run_id=response.run_id, pages_written=str(response.pages_written)),
    )
    return response


@router.post("/ingest/review", response_model=WikiIngestReviewResponse)
async def review_wiki_ingest(
    review_request: WikiIngestReviewRequest,
    request: Request,
    service: WikiWorkflowService = Depends(wiki_workflow_service_dependency),
) -> WikiIngestReviewResponse:
    try:
        response = await service.review_ingest(review_request)
    except WikiWorkflowError as exc:
        record_audit(
            request,
            action="wiki.ingest.review",
            result="failed",
            reason=audit_reason(request, run_id=review_request.run_id, code=getattr(exc, "code", exc.__class__.__name__)),
        )
        raise _workflow_error(exc) from exc
    record_audit(
        request,
        action="wiki.ingest.review",
        result="success" if response.status == "reviewed" else response.status,
        reason=audit_reason(request, run_id=response.run_id, review_id=response.review_id),
    )
    return response


@router.post("/query-archives/lint", response_model=QueryArchiveLintResponse)
async def lint_query_archive(
    archive_request: QueryArchiveRequest,
    request: Request,
    service: WikiWorkflowService = Depends(wiki_workflow_service_dependency),
) -> QueryArchiveLintResponse:
    response = service.lint_query_archive(archive_request)
    record_audit(
        request,
        action="wiki.query_archive.lint",
        result="success" if response.passed else "denied",
        reason=audit_reason(request, errors=",".join(response.errors)),
    )
    return response


@router.get("/query-archives", response_model=QueryArchiveHistoryResponse)
async def list_query_archives(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    service: WikiWorkflowService = Depends(wiki_workflow_service_dependency),
) -> QueryArchiveHistoryResponse:
    response = service.list_query_archives(limit=limit)
    record_audit(
        request,
        action="wiki.query_archive.list",
        result="success",
        reason=audit_reason(request, limit=str(limit), count=str(len(response.archives))),
    )
    return response


@router.get("/query-archives/{archive_id}", response_model=QueryArchiveDetailResponse)
async def read_query_archive(
    archive_id: str,
    request: Request,
    service: WikiWorkflowService = Depends(wiki_workflow_service_dependency),
) -> QueryArchiveDetailResponse:
    try:
        response = service.get_query_archive(archive_id)
    except QueryArchiveNotFoundError as exc:
        record_audit(
            request,
            action="wiki.query_archive.read",
            result="failed",
            reason=audit_reason(request, archive_id=archive_id, code=exc.code),
        )
        raise AppError(
            code=exc.code,
            message="未找到查询归档。",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"archive_id": archive_id},
        ) from exc
    record_audit(
        request,
        action="wiki.query_archive.read",
        result="success",
        target_path=response.target_path,
        reason=audit_reason(request, archive_id=response.id),
    )
    return response


@router.post("/query-archives", response_model=QueryArchiveResponse)
async def archive_query_answer(
    archive_request: QueryArchiveRequest,
    request: Request,
    service: WikiWorkflowService = Depends(wiki_workflow_service_dependency),
) -> QueryArchiveResponse:
    try:
        response = service.archive_query(archive_request)
    except QueryArchiveRejectedError as exc:
        record_audit(
            request,
            action="wiki.query_archive.write",
            result="denied",
            target_path=archive_request.target_path,
            reason=audit_reason(request, code=exc.code, errors=",".join(exc.errors)),
        )
        raise AppError(
            code=exc.code,
            message="查询归档未通过 Wiki 归档检查。",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={"errors": exc.errors},
        ) from exc
    except SensitiveWikiRejectedError as exc:
        record_audit(
            request,
            action="wiki.query_archive.write",
            result="denied",
            target_path=archive_request.target_path,
            reason=audit_reason(request, code=exc.code, policy=exc.reason),
        )
        raise AppError(
            code=exc.code,
            message="Wiki 内容未通过记忆污染策略检查。",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={"reason": exc.reason},
        ) from exc
    except (MarkdownWriteError, WikiWriteError, WikiWorkflowError) as exc:
        record_audit(
            request,
            action="wiki.query_archive.write",
            result="failed",
            target_path=archive_request.target_path,
            reason=audit_reason(request, code=getattr(exc, "code", exc.__class__.__name__)),
        )
        raise _workflow_error(exc) from exc
    record_audit(
        request,
        action="wiki.query_archive.write",
        result="success",
        target_path=response.page.relative_path,
        reason=audit_reason(request, archive_id=response.archive_id, index_job_id=response.page.index_job_id),
    )
    return response


@router.post("/lint", response_model=WikiLintReportResponse)
async def run_wiki_lint(
    lint_request: WikiLintRequest,
    request: Request,
    service: WikiLintService = Depends(wiki_lint_service_dependency),
) -> WikiLintReportResponse:
    try:
        response = service.run(lint_request)
    except (MarkdownWriteError, WikiWriteError) as exc:
        record_audit(
            request,
            action="wiki.lint.run",
            result="failed",
            reason=audit_reason(request, code=getattr(exc, "code", exc.__class__.__name__)),
        )
        raise _workflow_error(exc) from exc
    record_audit(
        request,
        action="wiki.lint.run",
        result="success" if response.summary.get("errors", 0) == 0 else "warning",
        target_path=response.report_page.relative_path if response.report_page else None,
        reason=audit_reason(
            request,
            issues=str(response.summary.get("issues", 0)),
            errors=str(response.summary.get("errors", 0)),
        ),
    )
    return response


def _workflow_error(exc: Exception) -> AppError:
    if isinstance(exc, MarkdownWriteError):
        return AppError("markdown_write_failed", str(exc), status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, WikiWriteError):
        return AppError(exc.code, str(exc), status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, WikiWorkflowError):
        return AppError(exc.code, str(exc), status.HTTP_400_BAD_REQUEST)
    return AppError("wiki_workflow_failed", str(exc), status.HTTP_400_BAD_REQUEST)
