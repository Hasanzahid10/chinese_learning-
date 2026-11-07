import os
import uuid

from django.shortcuts import get_object_or_404
from django.db.models import Q

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle

from authentication.permissions import IsActiveUser, HasInternalAIKey
from .models import Conversation, ChatMessage
from .serializers import (
    ConversationSerializer,
    ConversationDetailSerializer,
    ChatMessageSerializer,
)


# ============================================================
# INTERNAL: SAVE ASSISTANT MESSAGE
# FastAPI → Django
# ============================================================

class InternalAssistantMessageView(APIView):

    permission_classes = [HasInternalAIKey]

    def post(self, request):

        # ----------------------------------------------------
        # Verify FastAPI internal key
        # ----------------------------------------------------

        internal_key = request.headers.get(
            "X-Internal-Key"
        )

        expected_key = os.environ.get(
            "AI_INTERNAL_KEY"
        )

        if (
            not expected_key
            or internal_key != expected_key
        ):
            return Response(
                {
                    "error": "Unauthorized"
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # ----------------------------------------------------
        # Get request data
        # ----------------------------------------------------

        conversation_id = request.data.get(
            "conversation_id"
        )

        content = request.data.get(
            "content",
            "",
        ).strip()

        request_id = request.data.get(
            "request_id"
        )

        # ----------------------------------------------------
        # Validate conversation_id
        # ----------------------------------------------------

        if not conversation_id:
            return Response(
                {
                    "error": "conversation_id is required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # Validate content
        # ----------------------------------------------------

        if not content:
            return Response(
                {
                    "error": "content is required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # Validate request_id
        # ----------------------------------------------------

        if not request_id:
            return Response(
                {
                    "error": "request_id is required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:

            request_uuid = uuid.UUID(
                str(request_id)
            )

        except ValueError:

            return Response(
                {
                    "error": "Invalid request_id."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # Find conversation
        # ----------------------------------------------------

        conversation = get_object_or_404(
            Conversation,
            id=conversation_id,
        )

        # ----------------------------------------------------
        # DUPLICATE PROTECTION
        # ----------------------------------------------------

        existing_message = ChatMessage.objects.filter(
            request_id=request_uuid,
            role="assistant",
        ).first()

        if existing_message:

            print(
                f"[AI → Django] Duplicate request "
                f"ignored: {request_uuid}"
            )

            return Response(
                {
                    "id": existing_message.id,
                    "conversation_id": conversation.id,
                    "role": existing_message.role,
                    "content": existing_message.content,
                    "duplicate": True,
                },
                status=status.HTTP_200_OK,
            )

        # ----------------------------------------------------
        # Create assistant message
        # ----------------------------------------------------

        message = ChatMessage.objects.create(
            conversation=conversation,
            role="assistant",
            content=content,
            request_id=request_uuid,
        )

        conversation.save(
            update_fields=["updated_at"]
        )

        print(
            f"[AI → Django] Assistant message saved "
            f"id={message.id}"
        )

        return Response(
            {
                "id": message.id,
                "conversation_id": conversation.id,
                "role": message.role,
                "content": message.content,
                "duplicate": False,
            },
            status=status.HTTP_201_CREATED,
        )


# ============================================================
# INTERNAL: CHECK CONVERSATION OWNERSHIP
# FastAPI → Django
# ============================================================

class ConversationOwnerView(APIView):

    permission_classes = [HasInternalAIKey]

    def post(self, request):

        # ----------------------------------------------------
        # Verify FastAPI internal key
        # ----------------------------------------------------

        internal_key = request.headers.get(
            "X-Internal-Key"
        )

        expected_key = os.environ.get(
            "AI_INTERNAL_KEY"
        )

        if (
            not expected_key
            or internal_key != expected_key
        ):
            return Response(
                {
                    "error": "Unauthorized"
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # ----------------------------------------------------
        # Get request data
        # ----------------------------------------------------

        conversation_id = request.data.get(
            "conversation_id"
        )

        user_id = request.data.get(
            "user_id"
        )

        # ----------------------------------------------------
        # Validate conversation_id
        # ----------------------------------------------------

        if not conversation_id:
            return Response(
                {
                    "error": "conversation_id is required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # Validate user_id
        # ----------------------------------------------------

        if not user_id:
            return Response(
                {
                    "error": "user_id is required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # Check ownership
        # ----------------------------------------------------

        exists = Conversation.objects.filter(
            id=conversation_id,
            user_id=user_id,
        ).exists()

        return Response(
            {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "allowed": exists,
            },
            status=status.HTTP_200_OK,
        )


# ============================================================
# CONVERSATIONS (Authenticated & Protected)
# ============================================================

class ConversationListCreateView(APIView):

    permission_classes = [IsAuthenticated, IsActiveUser]

    # --------------------------------------------------------
    # GET /api/chatbot/conversations/
    # --------------------------------------------------------

    def get(self, request):
        user = request.user
        conversations = Conversation.objects.filter(user=user)

        # If no conversation exists yet, automatically create an active one with welcoming message
        if not conversations.exists():
            default_conv = Conversation.objects.create(
                user=user,
                title="Chinese Learning Practice",
                mode="chinese",
            )
            ChatMessage.objects.create(
                conversation=default_conv,
                role="assistant",
                content=(
                    "你好！我是你的中文 AI 老师。今天你想练习什么？\n\n"
                    "• Pinyin: Nǐ hǎo! Wǒ shì nǐ de zhōngwén AI lǎoshī. Jīntiān nǐ xiǎng liànxí shénme?\n"
                    "• Meaning: Hello! I am your Chinese AI Tutor. What would you like to practice today?\n\n"
                    "Key Vocabulary:\n"
                    "- 你好 (nǐ hǎo) = Hello\n"
                    "- 老师 (lǎoshī) = Tutor / Teacher\n"
                    "- 练习 (liànxí) = Practice"
                )
            )
            conversations = Conversation.objects.filter(user=user)

        serializer = ConversationSerializer(
            conversations,
            many=True,
        )

        return Response(serializer.data)

    # --------------------------------------------------------
    # POST /api/chatbot/conversations/
    # --------------------------------------------------------

    def post(self, request):
        user = request.user
        title = str(request.data.get("title", "New Chat")).strip()[:100]
        mode = str(request.data.get("mode", "chinese")).strip()[:30]

        conversation = Conversation.objects.create(
            user=user,
            title=title or "New Chat",
            mode=mode or "chinese",
        )

        serializer = ConversationSerializer(conversation)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# ============================================================
# CONVERSATION DETAIL (IDOR Protected)
# ============================================================

class ConversationDetailView(APIView):

    permission_classes = [IsAuthenticated, IsActiveUser]

    # --------------------------------------------------------
    # GET /api/chatbot/conversations/<id>/
    # --------------------------------------------------------

    def get(self, request, pk):
        user = request.user
        if user.is_staff or user.is_superuser:
            conversation = Conversation.objects.filter(id=pk).first()
        else:
            conversation = Conversation.objects.filter(id=pk, user=user).first()

        if not conversation:
            return Response(
                {"error": "Conversation not found or access denied."},
                status=status.HTTP_404_NOT_FOUND,
            )

        messages_data = []
        for msg in conversation.messages.all():
            content = msg.content
            # Extract structured parts if present
            pinyin = ""
            meaning = ""
            if "• Pinyin:" in content:
                parts = content.split("• Pinyin:")
                first_line = parts[0].strip()
                rest = parts[1]
                if "• Meaning:" in rest:
                    m_parts = rest.split("• Meaning:")
                    pinyin = m_parts[0].strip()
                    meaning_and_more = m_parts[1].strip()
                    meaning = meaning_and_more.split("\n\n")[0].strip()
                else:
                    pinyin = rest.split("\n\n")[0].strip()
                chinese_text = first_line
            else:
                chinese_text = content

            messages_data.append({
                "id": str(msg.id),
                "sender": "user" if msg.role == "user" else "ai",
                "role": msg.role,
                "text": chinese_text,
                "content": content,
                "pinyin": pinyin if pinyin else None,
                "bangla": meaning if meaning else None,
                "timestamp": msg.created_at.isoformat(),
            })

        return Response({
            "id": conversation.id,
            "title": conversation.title,
            "mode": conversation.mode,
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "messages": messages_data,
        })


# ============================================================
# USER CHAT MESSAGE & AI GENERATION (Throttled & Hardened)
# ============================================================

class ChatMessageView(APIView):

    permission_classes = [IsAuthenticated, IsActiveUser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_tutor"

    # --------------------------------------------------------
    # POST
    # /api/chatbot/conversations/<id>/messages/
    # --------------------------------------------------------

    def post(
        self,
        request,
        conversation_id,
    ):
        user = request.user
        conversation = Conversation.objects.filter(id=conversation_id, user=user).first()

        if not conversation:
            conversation = Conversation.objects.create(
                user=user,
                title="Chinese Practice",
                mode="chinese",
            )

        raw_content = request.data.get("message", "").strip()
        if not raw_content:
            return Response(
                {"error": "Message is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # DoS guard: limit message length to 500 characters
        content = raw_content[:500]

        try:
            hsk_level = max(1, min(int(request.data.get("hsk_level", 1) or 1), 6))
        except (ValueError, TypeError):
            hsk_level = 1

        # 1. Save user message
        user_message = ChatMessage.objects.create(
            conversation=conversation,
            role="user",
            content=content,
        )

        # 2. Generate Intelligent AI Tutor Response
        from .ai_tutor_engine import generate_ai_tutor_response
        ai_reply = generate_ai_tutor_response(
            conversation=conversation,
            user_text=content,
            user=user,
            hsk_level=hsk_level,
        )

        # 3. Save assistant message
        full_content = ai_reply.get("content", ai_reply.get("chinese", ""))
        assistant_message = ChatMessage.objects.create(
            conversation=conversation,
            role="assistant",
            content=full_content,
        )

        conversation.save(
            update_fields=["updated_at"]
        )

        return Response(
            {
                "id": str(assistant_message.id),
                "conversation_id": conversation.id,
                "role": "assistant",
                "sender": "ai",
                "content": full_content,
                "text": ai_reply.get("chinese", full_content),
                "pinyin": ai_reply.get("pinyin", ""),
                "bangla": ai_reply.get("bangla", ""),
                "vocabulary": ai_reply.get("vocabulary", []),
                "created_at": assistant_message.created_at.isoformat(),
                "user_message": {
                    "id": str(user_message.id),
                    "role": "user",
                    "sender": "user",
                    "text": user_message.content,
                    "content": user_message.content,
                    "created_at": user_message.created_at.isoformat(),
                },
            },
            status=status.HTTP_201_CREATED,
        )


# ============================================================
# DIRECT AI CHAT ENDPOINT (Throttled & Hardened)
# ============================================================

class DirectChatView(APIView):

    permission_classes = [IsAuthenticated, IsActiveUser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_tutor"

    def post(self, request):
        user = request.user
        conv_id = request.data.get("conversation_id")
        conversation = None
        if conv_id:
            conversation = Conversation.objects.filter(id=conv_id, user=user).first()

        if not conversation:
            conversation = Conversation.objects.filter(user=user).first()
            if not conversation:
                conversation = Conversation.objects.create(
                    user=user,
                    title="Chinese Practice Session",
                    mode="chinese",
                )

        raw_content = request.data.get("message", "").strip()
        if not raw_content:
            return Response(
                {"error": "Message is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # DoS guard: limit message length to 500 characters
        content = raw_content[:500]

        try:
            hsk_level = max(1, min(int(request.data.get("hsk_level", 1) or 1), 6))
        except (ValueError, TypeError):
            hsk_level = 1

        # 1. Save user message
        user_message = ChatMessage.objects.create(
            conversation=conversation,
            role="user",
            content=content,
        )

        # 2. Generate Intelligent AI Tutor Response
        from .ai_tutor_engine import generate_ai_tutor_response
        ai_reply = generate_ai_tutor_response(
            conversation=conversation,
            user_text=content,
            user=user,
            hsk_level=hsk_level,
        )

        # 3. Save assistant message
        full_content = ai_reply.get("content", ai_reply.get("chinese", ""))
        assistant_message = ChatMessage.objects.create(
            conversation=conversation,
            role="assistant",
            content=full_content,
        )

        conversation.save(update_fields=["updated_at"])

        return Response(
            {
                "id": str(assistant_message.id),
                "conversation_id": conversation.id,
                "role": "assistant",
                "sender": "ai",
                "content": full_content,
                "text": ai_reply.get("chinese", full_content),
                "pinyin": ai_reply.get("pinyin", ""),
                "bangla": ai_reply.get("bangla", ""),
                "vocabulary": ai_reply.get("vocabulary", []),
                "created_at": assistant_message.created_at.isoformat(),
                "user_message": {
                    "id": str(user_message.id),
                    "role": "user",
                    "sender": "user",
                    "text": user_message.content,
                    "content": user_message.content,
                    "created_at": user_message.created_at.isoformat(),
                },
            },
            status=status.HTTP_200_OK,
        )
