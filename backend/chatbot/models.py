import uuid

from django.conf import settings
from django.db import models


class Conversation(models.Model):

    MODE_CHOICES = [
        ("chinese", "中文聊天"),
        ("english_to_chinese", "English → Chinese"),
        ("bangla_to_chinese", "Bangla → Chinese"),
        ("chinese_to_english", "Chinese → English"),
        ("chinese_to_bangla", "Chinese → Bangla"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_conversations",
    )

    title = models.CharField(
        max_length=200,
        blank=True,
    )

    mode = models.CharField(
        max_length=30,
        choices=MODE_CHOICES,
        default="chinese",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or "New Chat"


class ChatMessage(models.Model):

    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
    ]

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
    )

    content = models.TextField()

    # Identifies one AI generation request.
    # Same request_id can never create two assistant messages.
    request_id = models.UUIDField(
        null=True,
        blank=True,
        unique=True,
        db_index=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.role}: {self.content[:50]}"
