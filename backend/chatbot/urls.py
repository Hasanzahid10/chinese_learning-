from django.urls import path

from .views import (
    ConversationListCreateView,
    ConversationDetailView,
    ChatMessageView,
    InternalAssistantMessageView,
    ConversationOwnerView,
)


urlpatterns = [

    # --------------------------------------------------------
    # Conversations
    # --------------------------------------------------------

    path(
        "conversations/",
        ConversationListCreateView.as_view(),
        name="conversation-list-create",
    ),

    path(
        "conversations/<int:pk>/",
        ConversationDetailView.as_view(),
        name="conversation-detail",
    ),

    # --------------------------------------------------------
    # User messages
    # --------------------------------------------------------

    path(
        "conversations/<int:conversation_id>/messages/",
        ChatMessageView.as_view(),
        name="chat-message",
    ),

    # --------------------------------------------------------
    # Internal FastAPI → Django endpoints
    # --------------------------------------------------------

    path(
        "internal/assistant-message/",
        InternalAssistantMessageView.as_view(),
        name="internal-assistant-message",
    ),

    path(
        "internal/conversation-owner/",
        ConversationOwnerView.as_view(),
        name="internal-conversation-owner",
    ),
]
