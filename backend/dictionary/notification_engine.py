"""
Notification Engine for Chinese-Bangla Learning App
Generates intelligent, contextual notifications for learners:
- Streak at Risk warnings
- Spaced Repetition (SRS) due reviews reminders
- Daily 5-minute quiz challenges
- Milestone & Level unlock celebrations
- Admin broadcast announcements
"""
from datetime import timedelta
from typing import List, Dict, Any, Optional
from django.utils import timezone
from django.contrib.auth import get_user_model

from .models import UserNotification, StudyProgress, QuizRecord
from authentication.models import StudentProfile

User = get_user_model()


def generate_smart_notifications(user) -> List[UserNotification]:
    """
    Checks user's current progress and activity state, then automatically
    generates contextual notification reminders if they are not already sent.
    """
    now = timezone.now()
    today = now.date()
    profile, _ = StudentProfile.objects.get_or_create(user=user)
    generated = []

    # 1. Streak at Risk Warning
    # If user has an active streak (>= 1 day) and has NOT studied today
    if profile.current_streak >= 1 and profile.last_active_date != today:
        recent_streak_notif = UserNotification.objects.filter(
            user=user,
            notification_type="streak_warning",
            created_at__gte=now - timedelta(hours=18),
        ).exists()

        if not recent_streak_notif:
            streak = profile.current_streak
            notif = UserNotification.objects.create(
                user=user,
                title=f"🔥 Don't Lose Your {streak}-Day Streak!",
                message=(
                    f"You have an active {streak}-day study streak! "
                    "Complete a quick 5-minute review or quiz today to keep your fire burning."
                ),
                notification_type="streak_warning",
                action_route="/home",
            )
            generated.append(notif)

    # 2. Spaced Repetition (SRS) Due Reviews Reminder
    due_count = StudyProgress.objects.filter(
        user=user,
        next_review__lte=now,
    ).count()

    if due_count >= 3:
        recent_review_notif = UserNotification.objects.filter(
            user=user,
            notification_type="due_review",
            created_at__gte=now - timedelta(hours=12),
        ).exists()

        if not recent_review_notif:
            notif = UserNotification.objects.create(
                user=user,
                title=f"📚 {due_count} Words Waiting for Review!",
                message=(
                    f"You have {due_count} vocabulary flashcards due for review. "
                    "Reviewing them now locks them into your long-term memory!"
                ),
                notification_type="due_review",
                action_route="/flashcards",
            )
            generated.append(notif)

    # 3. Daily 5-Minute Quiz Reminder
    quiz_done_today = QuizRecord.objects.filter(
        user=user,
        completed_at__date=today,
    ).exists()

    if not quiz_done_today:
        recent_quiz_notif = UserNotification.objects.filter(
            user=user,
            notification_type="quiz_reminder",
            created_at__gte=now - timedelta(hours=20),
        ).exists()

        if not recent_quiz_notif:
            notif = UserNotification.objects.create(
                user=user,
                title="⭐ Today's 5-Minute Challenge is Waiting!",
                message="Take 5 quick questions today to sharpen your Mandarin skills and earn +10 bonus XP!",
                notification_type="quiz_reminder",
                action_route="/home",
            )
            generated.append(notif)

    # 4. Level Unlock Milestone Check
    if profile.highest_hsk_level_unlocked > 1:
        milestone_key = f"HSK {profile.highest_hsk_level_unlocked} Unlocked"
        has_milestone_notif = UserNotification.objects.filter(
            user=user,
            notification_type="milestone",
            title__contains=f"HSK {profile.highest_hsk_level_unlocked}",
        ).exists()

        if not has_milestone_notif:
            notif = UserNotification.objects.create(
                user=user,
                title=f"🎉 Congratulations! HSK {profile.highest_hsk_level_unlocked} Unlocked!",
                message=(
                    f"Outstanding progress! You have mastered previous vocabulary and unlocked "
                    f"HSK Level {profile.highest_hsk_level_unlocked}. Start exploring new words!"
                ),
                notification_type="milestone",
                action_route="/flashcards",
            )
            generated.append(notif)

    return generated


def send_admin_broadcast(
    title: str,
    message: str,
    notification_type: str = "admin_broadcast",
    action_route: str = "/home",
    target_user_id: Optional[str] = None,
) -> int:
    """
    Dispatches a notification to all active users or a specific target user.
    Returns the count of created notifications.
    """
    if target_user_id:
        users = User.objects.filter(id=target_user_id)
    else:
        users = User.objects.filter(is_active=True)

    notifications_to_create = [
        UserNotification(
            user=user,
            title=title,
            message=message,
            notification_type=notification_type,
            action_route=action_route,
        )
        for user in users
    ]

    created = UserNotification.objects.bulk_create(notifications_to_create)
    return len(created)
