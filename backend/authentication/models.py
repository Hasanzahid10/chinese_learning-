import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class User(AbstractUser):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )


class StudentProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="student_profile",
    )
    # Personal Identity
    display_name = models.CharField(max_length=150, blank=True, default="")
    phone = models.CharField(max_length=30, blank=True, default="")
    bio = models.TextField(blank=True, default="")
    native_language = models.CharField(max_length=50, default="Bangla")

    # Learning Goals & Phase
    current_hsk_level = models.PositiveSmallIntegerField(default=1)  # 1 to 6
    target_hsk_level = models.PositiveSmallIntegerField(default=3)   # 1 to 6
    current_streak = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    last_study_date = models.DateField(null=True, blank=True)
    daily_goal_words = models.PositiveSmallIntegerField(default=10)
    total_xp = models.PositiveIntegerField(default=0)

    # App Preferences (Synced from App)
    is_pinyin_enabled = models.BooleanField(default=True)
    is_traditional_chinese = models.BooleanField(default=False)
    is_reminder_active = models.BooleanField(default=True)
    reminder_time = models.CharField(max_length=10, default="20:00")
    audio_speed = models.CharField(max_length=10, default="1.0x")

    # Security & Two-Factor Authentication
    is_two_factor_enabled = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        name = self.display_name or self.user.username
        return f"{name} - HSK {self.current_hsk_level} (Streak: {self.current_streak}d)"


@receiver(post_save, sender=User)
def create_student_profile(sender, instance, created, **kwargs):
    if created:
        StudentProfile.objects.get_or_create(user=instance)
