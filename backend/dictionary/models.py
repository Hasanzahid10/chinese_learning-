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
    mastery_level = models.PositiveSmallIntegerField(default=0)  # 0: New, 1: Learning, 2: Familiar, 3: Mastered

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
        return f"{self.user} - {self.word.chinese} (Lvl {self.mastery_level})"


class UserAchievement(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="achievements",
    )
    badge_key = models.CharField(max_length=50, db_index=True)
    title = models.CharField(max_length=100)
    description = models.CharField(max_length=255)
    icon = models.CharField(max_length=50, default="trophy")
    unlocked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "badge_key"],
                name="unique_user_achievement",
            )
        ]
        ordering = ["-unlocked_at"]

    def __str__(self):
        return f"{self.user} - {self.title}"


class QuizRecord(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="quiz_records",
    )
    hsk_level = models.PositiveSmallIntegerField(default=1)
    score = models.PositiveSmallIntegerField(default=0)
    total_questions = models.PositiveSmallIntegerField(default=5)
    xp_earned = models.PositiveIntegerField(default=0)
    coins_earned = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-completed_at"]

    def __str__(self):
        return f"{self.user} - Quiz HSK {self.hsk_level} ({self.score}/{self.total_questions})"


class UserNotification(models.Model):
    NOTIFICATION_TYPES = [
        ("streak_warning", "Streak at Risk"),
        ("due_review", "SRS Due Reviews"),
        ("milestone", "Progress Milestone"),
        ("quiz_reminder", "Daily Quiz Reminder"),
        ("achievement", "Achievement Unlocked"),
        ("admin_broadcast", "Admin Announcement"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(
        max_length=30,
        choices=NOTIFICATION_TYPES,
        default="streak_warning",
        db_index=True,
    )
    action_route = models.CharField(max_length=100, default="/home")
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.notification_type}] {self.title} -> {self.user}"