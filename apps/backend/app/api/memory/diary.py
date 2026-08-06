"""结构化聊天日记记忆端点。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from ...errors import AppError
from ...models.api import (
    DiaryMemoryObjectResponse,
    DiaryMemorySearchRequest,
    DiaryMemorySearchResponse,
    DiaryMemorySourceResponse,
)
from ...services.diary_memory import DiaryMemoryNotFoundError, DiaryMemorySearch
from .dependencies import diary_memory_service_dependency

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/diary/search", response_model=DiaryMemorySearchResponse)
async def search_diary_memory(
    search_request: DiaryMemorySearchRequest,
    service=Depends(diary_memory_service_dependency),
) -> DiaryMemorySearchResponse:
    records = service.search(
        DiaryMemorySearch(
            query=search_request.query,
            type=search_request.type,
            topic=search_request.topic,
            emotion=search_request.emotion,
            people=tuple(search_request.people),
            min_importance=search_request.min_importance,
            from_=search_request.from_,
            to=search_request.to,
            top_k=search_request.top_k,
        )
    )
    return DiaryMemorySearchResponse(objects=[_diary_memory_response(record) for record in records])


@router.get("/diary/{object_id}", response_model=DiaryMemoryObjectResponse)
async def get_diary_memory_object(
    object_id: str,
    service=Depends(diary_memory_service_dependency),
) -> DiaryMemoryObjectResponse:
    try:
        record = service.get(object_id)
    except DiaryMemoryNotFoundError as exc:
        raise AppError(
            code="diary_memory_not_found",
            message="未找到结构化聊天日记记忆。",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"object_id": object_id},
        ) from exc
    return _diary_memory_response(record)


def _diary_memory_response(record) -> DiaryMemoryObjectResponse:
    return DiaryMemoryObjectResponse(
        id=record.id,
        vault_id=record.vault_id,
        type=record.type,
        summary=record.summary,
        topic=record.topic,
        emotion=record.emotion,
        people=list(record.people),
        keywords=list(record.keywords),
        importance=record.importance,
        confidence=record.confidence,
        occurred_at=record.occurred_at,
        timezone=record.timezone,
        status=record.status.value,
        extraction_model=record.extraction_model,
        created_at=record.created_at,
        updated_at=record.updated_at,
        sources=[
            DiaryMemorySourceResponse(
                source_type=source.source_type,
                source_id=source.source_id,
                conversation_id=source.conversation_id,
                user_message_id=source.user_message_id,
                assistant_message_id=source.assistant_message_id,
                agent_run_id=source.agent_run_id,
                markdown_path=source.markdown_path,
                note_id=source.note_id,
                chunk_id=source.chunk_id,
            )
            for source in record.sources
        ],
    )
