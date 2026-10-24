from pydantic import BaseModel, Field


class ChatHistoryItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    conversation_id: int

    request_id: str

    message: str = Field(
        default="",
        max_length=2000,
    )

    history: list[ChatHistoryItem] = Field(
        default_factory=list,
    )

    # Optional image sent as base64
    image: str | None = None

    # Optional MIME type, for example:
    # image/jpeg
    # image/png
    # image/webp
    image_mime_type: str | None = None
