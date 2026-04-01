from typing import Any

from pydantic import BaseModel


class ChatRequest(BaseModel):
    query: str
    user_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]]


class IngestResponse(BaseModel):
    message: str
    chunks_processed: int
