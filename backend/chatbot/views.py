import os
import uuid

from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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

    permission_classes = [AllowAny]

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

    permission_classes = [AllowAny]

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
# CONVERSATIONS
# ============================================================

class ConversationListCreateView(APIView):

    permission_classes = [IsAuthenticated]

    # --------------------------------------------------------
    # GET /api/chatbot/conversations/
    # --------------------------------------------------------

    def get(self, request):

        conversations = Conversation.objects.filter(
            user=request.user
        )

        serializer = ConversationSerializer(
            conversations,
            many=True,
        )

        return Response(
            serializer.data
        )

    # --------------------------------------------------------
    # POST /api/chatbot/conversations/
    # --------------------------------------------------------

    def post(self, request):

        title = request.data.get(
            "title",
            "New Chat",
        )

        mode = request.data.get(
            "mode",
            "chinese",
        )

        conversation = Conversation.objects.create(
            user=request.user,
            title=title,
            mode=mode,
        )

        serializer = ConversationSerializer(
            conversation
        )

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


# ============================================================
# CONVERSATION DETAIL
# ============================================================

class ConversationDetailView(APIView):

    permission_classes = [IsAuthenticated]

    # --------------------------------------------------------
    # GET /api/chatbot/conversations/<id>/
    # --------------------------------------------------------

    def get(self, request, pk):

        conversation = get_object_or_404(
            Conversation,
            id=pk,
            user=request.user,
        )

        serializer = ConversationDetailSerializer(
            conversation
        )

        return Response(
            serializer.data
        )


# ============================================================
# USER CHAT MESSAGE
# Django saves USER message immediately.
# FastAPI handles AI generation separately.
# ============================================================

class ChatMessageView(APIView):

    permission_classes = [IsAuthenticated]

    # --------------------------------------------------------
    # POST
    # /api/chatbot/conversations/<id>/messages/
    # --------------------------------------------------------

    def post(
        self,
        request,
        conversation_id,
    ):

        conversation = get_object_or_404(
            Conversation,
            id=conversation_id,
            user=request.user,
        )

        content = request.data.get(
            "message",
            "",
        ).strip()

        if not content:

            return Response(
                {
                    "error": "Message is required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # Save user message
        # ----------------------------------------------------

        message = ChatMessage.objects.create(
            conversation=conversation,
            role="user",
            content=content,
        )

        conversation.save(
            update_fields=["updated_at"]
        )

        serializer = ChatMessageSerializer(
            message
        )

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )
