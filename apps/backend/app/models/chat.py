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
