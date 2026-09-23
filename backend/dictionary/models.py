from django.conf import settings
from django.db import models


class HSKWord(models.Model):

    hsk_level = models.PositiveSmallIntegerField(
        db_index=True
    )

    chinese = models.CharField(
        max_length=100,
        db_index=True
    )

    pinyin = models.CharField(
        max_length=200,
        db_index=True
    )

    english = models.TextField(
        blank=True
    )

    bangla = models.TextField(
        blank=True
    )

    class Meta:
        ordering = ["hsk_level", "id"]

    def __str__(self):
        return f"{self.chinese} - HSK {self.hsk_level}"



class StudyProgress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="study_progress",
    )

    word = models.ForeignKey(
        HSKWord,
        on_delete=models.CASCADE,
        related_name="study_progress",
    )

    correct_count = models.PositiveIntegerField(default=0)
    wrong_count = models.PositiveIntegerField(default=0)

    is_learned = models.BooleanField(default=False)

    last_studied = models.DateTimeField(
        null=True,
        blank=True,
    )

    next_review = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "word"],
                name="unique_user_word_progress",
            )
        ]
        ordering = ["next_review", "id"]

    def __str__(self):
        return f"{self.user} - {self.word.chinese}"