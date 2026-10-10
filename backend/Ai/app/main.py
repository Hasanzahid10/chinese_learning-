import json
import tempfile
import os

import requests

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    UploadFile,
    File,
    Form,
)
from fastapi.responses import StreamingResponse
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from .auth import verify_access_token
from .config import settings
from .ollama import stream_chat
from .prompts import SYSTEM_PROMPT
from .schemas import ChatRequest


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="Chinese Learning AI",
    version="1.0.0",
)


# ============================================================
# BEARER AUTHENTICATION
# ============================================================

security = HTTPBearer()


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root():

    return {
        "status": "ok",
        "service": "Chinese Learning AI",
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
async def health():

    return {
        "status": "healthy",
    }


# ============================================================
# SAVE ASSISTANT MESSAGE
#
# FastAPI → Django
# ============================================================

def save_assistant_message(
    conversation_id: int,
    request_id: str,
    content: str,
):

    print(
        f"[AI → Django] Saving assistant message "
        f"conversation={conversation_id} "
        f"request_id={request_id}"
    )

    try:

        response = requests.post(
            f"{settings.django_url}/api/chatbot/internal/assistant-message/",
            headers={
                "X-Internal-Key": settings.ai_internal_key,
                "Content-Type": "application/json",
            },
            json={
                "conversation_id": conversation_id,
                "request_id": request_id,
                "content": content,
            },
            timeout=15,
        )

    except requests.RequestException as exc:

        print(
            "[AI → Django] Request failed:",
            exc,
        )

        raise HTTPException(
            status_code=503,
            detail="Unable to save assistant message.",
        )

    print(
        f"[AI → Django] Response: "
        f"{response.status_code} "
        f"{response.text}"
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# VERIFY CONVERSATION OWNERSHIP
#
# FastAPI → Django
# ============================================================

def verify_conversation_owner(
    conversation_id: int,
    user_id: int,
):

    print(
        f"[AUTH] Checking ownership "
        f"user={user_id} "
        f"conversation={conversation_id}"
    )

    try:

        response = requests.post(
            f"{settings.django_url}/api/chatbot/internal/conversation-owner/",
            headers={
                "X-Internal-Key": settings.ai_internal_key,
                "Content-Type": "application/json",
            },
            json={
                "conversation_id": conversation_id,
                "user_id": user_id,
            },
            timeout=10,
        )

    except requests.RequestException as exc:

        print(
            "[AUTH] Django ownership request failed:",
            exc,
        )

        raise HTTPException(
            status_code=503,
            detail="Unable to verify conversation ownership.",
        )

    if response.status_code != 200:

        print(
            "[AUTH] Django ownership check returned:",
            response.status_code,
            response.text,
        )

        raise HTTPException(
            status_code=503,
            detail="Unable to verify conversation ownership.",
        )

    data = response.json()

    allowed = data.get(
        "allowed",
        False,
    )

    if not allowed:

        print(
            f"[AUTH] Access denied "
            f"user={user_id} "
            f"conversation={conversation_id}"
        )

        raise HTTPException(
            status_code=403,
            detail="You do not have access to this conversation.",
        )

    print(
        f"[AUTH] Access allowed "
        f"user={user_id} "
        f"conversation={conversation_id}"
    )

    return True


# ============================================================
# BUILD CHAT MESSAGES
#
# Shared by:
#
#   Text
#   Image
#   Voice
#
# ============================================================

def build_messages(
    request: ChatRequest,
    image: str | None = None,
):

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        }
    ]

    # --------------------------------------------------------
    # Conversation history
    # --------------------------------------------------------

    for item in request.history[-10:]:

        if item.role in {
            "user",
            "assistant",
        }:

            messages.append(
                {
                    "role": item.role,
                    "content": item.content,
                }
            )

    # --------------------------------------------------------
    # Current user message
    # --------------------------------------------------------

    user_message = {
        "role": "user",
        "content": request.message,
    }

    # --------------------------------------------------------
    # Optional image
    #
    # Ollama/Qwen2.5VL expects:
    #
    # "images": [
    #     "BASE64_IMAGE"
    # ]
    # --------------------------------------------------------

    if image:

        user_message["images"] = [
            image
        ]

    messages.append(
        user_message
    )

    return messages


# ============================================================
# SSE GENERATOR
#
# Shared streaming implementation
# ============================================================

def generate_ai_stream(
    messages,
    conversation_id: int,
    request_id: str,
):

    full_response = ""

    try:

        print(
            f"[AI] Starting generation "
            f"conversation={conversation_id} "
            f"request_id={request_id}"
        )

        # ----------------------------------------------------
        # Ollama streaming
        # ----------------------------------------------------

        for chunk in stream_chat(
            messages
        ):

            full_response += chunk

            # Send token to frontend
            yield (
                "data: "
                + json.dumps(
                    {
                        "token": chunk
                    },
                    ensure_ascii=False,
                )
                + "\n\n"
            )

        # ----------------------------------------------------
        # Save complete response to Django
        # ----------------------------------------------------

        if full_response.strip():

            try:

                save_result = save_assistant_message(
                    conversation_id=conversation_id,
                    request_id=request_id,
                    content=full_response,
                )

                print(
                    "[AI] Assistant message saved:",
                    save_result,
                )

            except Exception as exc:

                print(
                    "[AI] Failed to save assistant message:",
                    exc,
                )

        # ----------------------------------------------------
        # Stream completion
        # ----------------------------------------------------

        yield (
            "data: "
            + json.dumps(
                {
                    "done": True
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )

        print(
            f"[AI] Generation finished "
            f"conversation={conversation_id} "
            f"request_id={request_id}"
        )

    except Exception as exc:

        print(
            "[AI] Generation error:",
            exc,
        )

        yield (
            "data: "
            + json.dumps(
                {
                    "error": str(exc),
                    "done": True,
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )


# ============================================================
# TEXT + IMAGE CHAT
#
# POST:
#
# /api/ai/chat/stream
#
# Supports:
#
#   text
#   image + text
#   image only
#
# ============================================================

@app.post("/api/ai/chat/stream")
def chat_stream(
    request: ChatRequest,
    credentials: HTTPAuthorizationCredentials = Depends(
        security
    ),
):

    # ========================================================
    # 1. VERIFY JWT
    # ========================================================

    payload = verify_access_token(
        credentials
    )

    user_id = int(
        payload["user_id"]
    )

    print(
        f"[AUTH] JWT verified "
        f"user_id={user_id}"
    )

    # ========================================================
    # 2. VERIFY CONVERSATION OWNERSHIP
    # ========================================================

    verify_conversation_owner(
        conversation_id=request.conversation_id,
        user_id=user_id,
    )

    # ========================================================
    # 3. BUILD MESSAGES
    # ========================================================

    messages = build_messages(
        request=request,
        image=request.image,
    )

    # ========================================================
    # 4. STREAM
    # ========================================================

    return StreamingResponse(
        generate_ai_stream(
            messages=messages,
            conversation_id=request.conversation_id,
            request_id=request.request_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# VOICE → STT → QWEN
#
# POST:
#
# /api/ai/voice/stream
#
# multipart/form-data
#
# Fields:
#
# conversation_id
# request_id
# history
# audio
#
# ============================================================

def transcribe_audio(
    audio_path: str,
):
    """
    Convert speech → text.

    Uses faster-whisper.

    The returned text is then sent to Qwen2.5VL
    like a normal user message.
    """

    try:

        from faster_whisper import WhisperModel

    except ImportError:

        raise HTTPException(
            status_code=500,
            detail=(
                "faster-whisper is not installed. "
                "Install it with: pip install faster-whisper"
            ),
        )

    # --------------------------------------------------------
    # Load model
    #
    # IMPORTANT:
    # For production, load this ONCE at application startup
    # instead of loading it for every request.
    # --------------------------------------------------------

    model = WhisperModel(
        "small",
        device="cpu",
        compute_type="int8",
    )

    segments, info = model.transcribe(
        audio_path,
        beam_size=5,
        vad_filter=True,
    )

    text_parts = []

    for segment in segments:

        text_parts.append(
            segment.text
        )

    text = " ".join(
        text_parts
    ).strip()

    return text


# ============================================================
# VOICE CHAT ENDPOINT
# ============================================================

@app.post("/api/ai/voice/stream")
async def voice_chat_stream(
    conversation_id: int = Form(...),
    request_id: str = Form(...),
    history: str = Form("[]"),
    audio: UploadFile = File(...),
    credentials: HTTPAuthorizationCredentials = Depends(
        security
    ),
):

    # ========================================================
    # 1. VERIFY JWT
    # ========================================================

    payload = verify_access_token(
        credentials
    )

    user_id = int(
        payload["user_id"]
    )

    print(
        f"[VOICE AUTH] JWT verified "
        f"user_id={user_id}"
    )

    # ========================================================
    # 2. VERIFY CONVERSATION OWNERSHIP
    # ========================================================

    verify_conversation_owner(
        conversation_id=conversation_id,
        user_id=user_id,
    )

    # ========================================================
    # 3. VALIDATE AUDIO
    # ========================================================

    allowed_audio_types = {
        "audio/webm",
        "audio/wav",
        "audio/x-wav",
        "audio/mpeg",
        "audio/mp4",
        "audio/ogg",
        "audio/opus",
    }

    if audio.content_type not in allowed_audio_types:

        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported audio format. "
                "Use webm, wav, mp3, mp4, ogg or opus."
            ),
        )

    # ========================================================
    # 4. SAVE TEMPORARY AUDIO
    # ========================================================

    suffix = ".webm"

    if audio.filename:

        _, extension = os.path.splitext(
            audio.filename
        )

        if extension:

            suffix = extension

    temp_path = None

    try:

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as temp_file:

            temp_path = temp_file.name

            content = await audio.read()

            # ------------------------------------------------
            # Basic size protection
            #
            # 10 MB maximum
            # ------------------------------------------------

            max_audio_size = 10 * 1024 * 1024

            if len(content) > max_audio_size:

                raise HTTPException(
                    status_code=413,
                    detail="Audio file is too large. Maximum size is 10 MB.",
                )

            temp_file.write(
                content
            )

        print(
            f"[VOICE] Audio saved: {temp_path}"
        )

        # ====================================================
        # 5. STT
        # ====================================================

        transcribed_text = transcribe_audio(
            temp_path
        )

        print(
            "[VOICE] Transcription:",
            transcribed_text,
        )

        if not transcribed_text:

            raise HTTPException(
                status_code=400,
                detail="Could not understand the audio.",
            )

        # ====================================================
        # 6. PARSE HISTORY
        # ====================================================

        try:

            history_data = json.loads(
                history
            )

        except json.JSONDecodeError:

            raise HTTPException(
                status_code=400,
                detail="Invalid history JSON.",
            )

        # ====================================================
        # 7. BUILD CHAT REQUEST
        # ====================================================

        request_data = ChatRequest(
            conversation_id=conversation_id,
            request_id=request_id,
            message=transcribed_text,
            history=history_data,
        )

        # ====================================================
        # 8. BUILD QWEN MESSAGES
        # ====================================================

        messages = build_messages(
            request=request_data,
        )

        # ====================================================
        # 9. STREAM QWEN RESPONSE
        # ====================================================

        return StreamingResponse(
            generate_ai_stream(
                messages=messages,
                conversation_id=conversation_id,
                request_id=request_id,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    finally:

        # ====================================================
        # 10. DELETE TEMP AUDIO
        # ====================================================

        if temp_path and os.path.exists(
            temp_path
        ):

            try:

                os.remove(
                    temp_path
                )

                print(
                    f"[VOICE] Temporary audio deleted: "
                    f"{temp_path}"
                )

            except Exception as exc:

                print(
                    "[VOICE] Failed to delete temp audio:",
                    exc,
                )
