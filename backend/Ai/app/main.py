import json

import requests

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
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
#
# This happens ONLY after the complete AI response
# has been generated.
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
#
# This prevents:
#
# User A
#    ↓
# JWT user_id = 1
#    ↓
# conversation_id = 999
#    ↓
# access User B's conversation
#
# Django checks:
#
# conversation_id belongs to user_id?
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
# AI CHAT STREAM
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
    # 3. BUILD AI MESSAGE HISTORY
    # ========================================================

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        }
    ]

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

    # ========================================================
    # 4. ADD CURRENT USER MESSAGE
    # ========================================================

    messages.append(
        {
            "role": "user",
            "content": request.message,
        }
    )

    # ========================================================
    # 5. STREAM RESPONSE
    # ========================================================

    def generate():

        full_response = ""

        try:

            print(
                f"[AI] Starting generation "
                f"conversation={request.conversation_id} "
                f"request_id={request.request_id}"
            )

            for chunk in stream_chat(
                messages
            ):

                full_response += chunk

                # --------------------------------------------
                # Send token to frontend
                # --------------------------------------------

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

            # =================================================
            # 6. SAVE COMPLETE RESPONSE TO DJANGO
            # =================================================

            if full_response.strip():

                try:

                    save_result = save_assistant_message(
                        conversation_id=request.conversation_id,
                        request_id=request.request_id,
                        content=full_response,
                    )

                    print(
                        "[AI] Assistant message saved:",
                        save_result,
                    )

                except Exception as exc:

                    print(
                        "[AI] Failed to save assistant "
                        "message:",
                        exc,
                    )

            # =================================================
            # 7. STREAM COMPLETE
            # =================================================

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
                f"conversation={request.conversation_id} "
                f"request_id={request.request_id}"
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

    # ========================================================
    # 8. RETURN SSE STREAM
    # ========================================================

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
