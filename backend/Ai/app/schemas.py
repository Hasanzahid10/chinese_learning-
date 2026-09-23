from pydantic import BaseModel, Field


class ChatHistoryItem(BaseModel):

    role: str
    content: str


class ChatRequest(BaseModel):

    conversation_id: int

    request_id: str

    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
    )

    history: list[ChatHistoryItem] = Field(
        default_factory=list,
    )
