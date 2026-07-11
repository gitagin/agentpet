from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1)


class ChatAcceptedResponse(BaseModel):
    conversation_id: str
    message_id: str
    agent_run_id: str
    stream_url: str


class ChatStreamEvent(BaseModel):
    event: str
    data: dict[str, str]


class ChatDailyHistoryMessage(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    status: str
    created_at: str
    updated_at: str
    agent_run_id: str | None = None


class ChatDailyHistoryResponse(BaseModel):
    date: str
    timezone: str
    conversation_id: str | None = None
    messages: list[ChatDailyHistoryMessage]
    has_more: bool = False
