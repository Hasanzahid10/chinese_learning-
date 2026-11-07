import json
import platform
import random
from datetime import date, timedelta
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q, Sum, Avg, Count
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle

from authentication.permissions import IsAdminOrSuperuser, IsActiveUser

from authentication.models import StudentProfile
from .models import HSKWord, StudyProgress, UserAchievement, QuizRecord, UserNotification
from .serializers import (DictionaryWordSerializer, StudyProgressSerializer)
from .gamification_engine import (
    get_user_rank_info,
    calculate_hsk_unlocks,
    check_and_award_achievements,
    generate_daily_quiz,
    evaluate_daily_quiz,
)
from .notification_engine import (
    generate_smart_notifications,
    send_admin_broadcast,
)


def update_student_streak(user):
    """
    Computes daily streak.
    - If studied today already: keep streak.
    - If studied yesterday: streak + 1.
    - If gap > 1 day: reset streak to 1.
    """
    if not user:
        return 1
    profile, _ = StudentProfile.objects.get_or_create(user=user)
    today = date.today()
    last_date = profile.last_study_date

    if last_date == today:
        return profile.current_streak
    elif last_date == today - timedelta(days=1):
        profile.current_streak += 1
        if profile.current_streak > profile.longest_streak:
            profile.longest_streak = profile.current_streak
        profile.last_study_date = today
        profile.save()
    else:
        profile.current_streak = 1
        if profile.longest_streak == 0:
            profile.longest_streak = 1
        profile.last_study_date = today
        profile.save()

    return profile.current_streak


def get_student_learning_summary(user):
    """
    Returns high-resolution learning metrics, HSK phase progress %, accuracy,
    and dropout risk prediction.
    """
    profile, _ = StudentProfile.objects.get_or_create(user=user)
    all_user_progress = StudyProgress.objects.filter(user=user)

    total_studied = all_user_progress.count()
    total_learned = all_user_progress.filter(is_learned=True).count()

    total_correct = sum(all_user_progress.values_list("correct_count", flat=True)) or 0
    total_wrong = sum(all_user_progress.values_list("wrong_count", flat=True)) or 0
    total_attempts = total_correct + total_wrong
    accuracy = round((total_correct / total_attempts) * 100, 1) if total_attempts > 0 else 0.0

    now = timezone.now()
    due_reviews = all_user_progress.filter(next_review__lte=now).count()

    current_level = profile.current_hsk_level or 1
    total_words_in_hsk = HSKWord.objects.filter(hsk_level=current_level).count() or 150
    learned_in_hsk = all_user_progress.filter(word__hsk_level=current_level, is_learned=True).count()
    hsk_progress_pct = round((learned_in_hsk / total_words_in_hsk) * 100, 1) if total_words_in_hsk > 0 else 0.0

    is_promotion_ready = (hsk_progress_pct >= 80.0 and current_level < 6)

    today = date.today()
    if profile.last_study_date == today:
        status_label = "active_today"
        dropout_risk = "safe"
    elif profile.last_study_date == today - timedelta(days=1):
        status_label = "active_yesterday"
        dropout_risk = "safe"
    elif profile.last_study_date and profile.last_study_date >= today - timedelta(days=3):
        status_label = "inactive_recently"
        dropout_risk = "moderate"
    else:
        status_label = "inactive_long"
        dropout_risk = "high"

    if due_reviews > 0:
        guidance_note = f"আজকের জন্য {due_reviews}টি রিভিশন শব্দ অপেক্ষারত।"
    elif is_promotion_ready:
        guidance_note = f"চমৎকার! HSK {current_level} প্রায় শেষ ({hsk_progress_pct}%), HSK {current_level+1} আনলক করার উপযুক্ত!"
    elif accuracy < 65.0 and total_attempts > 10:
        guidance_note = "ভুলের হার কিছুটা বেশি। নতুন শব্দের আগে রিভিশন কার্ড বারবার ঝালাই করুন।"
    elif total_studied == 0:
        guidance_note = f"এখনো পড়া শুরু হয়নি। HSK {current_level}-এর প্রথম কার্ড দিয়ে শুরু করুন।"
    else:
        guidance_note = f"প্রতিদিন ১০টি শব্দ লক্ষ্য নিয়ে HSK {current_level} এগিয়ে চলছে।"

    rank_info = get_user_rank_info(profile.total_xp)
    hsk_unlocks = calculate_hsk_unlocks(user)

    total_words_system = HSKWord.objects.count()
    stage_1_learning = all_user_progress.filter(mastery_level=1).count()
    stage_2_familiar = all_user_progress.filter(mastery_level=2).count()
    stage_3_mastered = total_learned
    stage_0_new = max(0, total_words_system - total_studied)

    achievements_list = [
        {
            "key": ach.badge_key,
            "title": ach.title,
            "description": ach.description,
            "icon": ach.icon,
            "unlocked_at": ach.unlocked_at.strftime("%Y-%m-%d %H:%M"),
        }
        for ach in user.achievements.all()
    ]

    return {
        "current_streak": profile.current_streak,
        "longest_streak": profile.longest_streak,
        "last_study_date": str(profile.last_study_date) if profile.last_study_date else None,
        "current_hsk_level": current_level,
        "target_hsk_level": profile.target_hsk_level,
        "highest_hsk_level_unlocked": profile.highest_hsk_level_unlocked or 1,
        "hsk_progress_pct": hsk_progress_pct,
        "learned_count": total_learned,
        "study_count": total_studied,
        "total_words_in_hsk": total_words_in_hsk,
        "learned_in_hsk": learned_in_hsk,
        "accuracy_pct": accuracy,
        "total_correct": total_correct,
        "total_wrong": total_wrong,
        "due_reviews": due_reviews,
        "dropout_risk": dropout_risk,
        "status_label": status_label,
        "guidance_note": guidance_note,
        "is_promotion_ready": is_promotion_ready,
        "daily_goal_words": profile.daily_goal_words,
        # Gamification Core Metrics
        "total_xp": profile.total_xp,
        "coins": profile.coins,
        "rank": rank_info,
        "hsk_learning_path": hsk_unlocks["levels"],
        "mastery_counts": {
            "new": stage_0_new,
            "learning": stage_1_learning,
            "familiar": stage_2_familiar,
            "mastered": stage_3_mastered,
        },
        "achievements": {
            "total_unlocked": len(achievements_list),
            "badges": achievements_list,
        },
        # Profile & Personal Details
        "display_name": profile.display_name or user.username,
        "phone": profile.phone,
        "bio": profile.bio,
        "native_language": profile.native_language,
        # App Preferences
        "is_pinyin_enabled": profile.is_pinyin_enabled,
        "is_traditional_chinese": profile.is_traditional_chinese,
        "is_reminder_active": profile.is_reminder_active,
        "reminder_time": profile.reminder_time,
        "audio_speed": profile.audio_speed,
        "is_two_factor_enabled": profile.is_two_factor_enabled,
    }


class DictionarySearchView(APIView):

    def get(self, request):
        query = request.GET.get("q", "").strip()[:100]
        hsk = request.GET.get("hsk")

        words = HSKWord.objects.all()

        if query:
            words = words.filter(
                Q(chinese__icontains=query)
                | Q(pinyin__icontains=query)
                | Q(english__icontains=query)
                | Q(bangla__icontains=query)
            )

        if hsk:
            try:
                words = words.filter(
                    hsk_level=int(hsk)
                )
            except ValueError:
                return Response(
                    {"error": "hsk must be a number from 1 to 6"},
                    status=400
                )

        total_count = words.count()

        # Pagination support (capped for DoS prevention)
        try:
            page = max(1, int(request.GET.get("page", 1)))
        except (ValueError, TypeError):
            page = 1

        page_size_param = str(request.GET.get("page_size", "50")).strip().lower()
        try:
            page_size = max(10, min(int(page_size_param), 200))
        except (ValueError, TypeError):
            page_size = 50

        offset = (page - 1) * page_size
        words = words.order_by("hsk_level", "id")[offset : offset + page_size]

        serializer = DictionaryWordSerializer(
            words,
            many=True
        )

        total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 1

        return Response({
            "query": query,
            "count": len(serializer.data),
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "results": serializer.data,
        })


class DictionaryDetailView(APIView):

    def get(self, request, pk):
        word = get_object_or_404(
            HSKWord,
            pk=pk
        )

        serializer = DictionaryWordSerializer(word)

        return Response(serializer.data)

#=================================
# Add study view card
#================================
class StudyCardView(APIView):
    permission_classes = [AllowAny]

    def _get_target_user(self, request):
        if request.user and request.user.is_authenticated:
            return request.user
        return None

    def get(self, request):
        hsk = request.GET.get("hsk")
        limit = int(request.GET.get("limit", 15) or 15)
        now = timezone.now()
        user = self._get_target_user(request)

        words = HSKWord.objects.all()

        # Optional HSK filter (1 to 6)
        if hsk:
            try:
                hsk_num = int(hsk)
                if hsk_num in range(1, 7):
                    words = words.filter(hsk_level=hsk_num)
            except (ValueError, TypeError):
                pass

        # Exclude words already learned by THIS user
        learned_ids = []
        if user:
            learned_ids = list(
                StudyProgress.objects.filter(
                    user=user, is_learned=True
                ).values_list("word_id", flat=True)
            )
        available_words = words.exclude(id__in=learned_ids) if learned_ids else words

        # 1. Priority: Words that are due for review for this user
        due_words = []
        if user:
            due_ids = list(
                StudyProgress.objects.filter(
                    user=user,
                    is_learned=False,
                    next_review__lte=now,
                ).values_list("word_id", flat=True)[:limit]
            )
            if due_ids:
                due_words = list(available_words.filter(id__in=due_ids))

        # 2. Priority: New words never studied
        needed = limit - len(due_words)
        new_words = []
        if needed > 0:
            if user:
                studied_ids = list(
                    StudyProgress.objects.filter(user=user).values_list("word_id", flat=True)
                )
                new_qs = available_words.exclude(id__in=studied_ids)
            else:
                new_qs = available_words
            new_words = list(new_qs[:needed])

        # 3. Priority: Upcoming words waiting for review
        selected_words = due_words + new_words
        needed = limit - len(selected_words)
        if needed > 0 and user:
            upcoming_ids = list(
                StudyProgress.objects.filter(
                    user=user,
                    is_learned=False,
                    next_review__gt=now,
                ).order_by("next_review").values_list("word_id", flat=True)[:needed]
            )
            if upcoming_ids:
                upcoming_words = list(available_words.filter(id__in=upcoming_ids))
                selected_words.extend(upcoming_words)

        # Fallback if deck is empty
        if not selected_words:
            selected_words = list(words[:limit])

        serializer = DictionaryWordSerializer(selected_words, many=True)
        cards_data = serializer.data

        return Response({
            "card": cards_data[0] if cards_data else None,
            "cards": cards_data,
            "results": cards_data,
            "total_count": len(cards_data),
            "due_count": len(due_words),
            "study_type": "due_review" if due_words else "new",
        })

#=================================
# Answer part sections
#================================
class StudyAnswerView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        word_id = request.data.get("word_id")
        correct = request.data.get("correct")

        if word_id is None:
            return Response(
                {"error": "word_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if correct is None:
            return Response(
                {"error": "correct is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        word = get_object_or_404(
            HSKWord,
            id=word_id,
        )

        user = request.user if request.user and request.user.is_authenticated else None
        if not user:
            # Anonymous answer: do not modify database or first user/admin account
            return Response({
                "message": "Answer recorded locally.",
                "progress": None,
                "current_streak": 0,
                "is_learned": False,
                "mastery_level": 0,
                "xp_earned": 10 if correct else 0,
                "total_xp": 0,
                "coins": 0,
                "rank": {"title": "Novice", "tier": 1},
                "new_badges_unlocked": [],
            })

        progress, created = StudyProgress.objects.get_or_create(
            user=user,
            word=word,
        )

        streak = update_student_streak(user)
        now = timezone.now()

        profile, _ = StudentProfile.objects.get_or_create(user=user)
        xp_earned = 0

        if correct:
            progress.correct_count += 1
            xp_earned = 10
            profile.total_xp += 10

            if progress.correct_count >= 5:
                progress.is_learned = True
                progress.mastery_level = 3
                progress.next_review = now + timezone.timedelta(days=7)
                # Bonus XP for mastering a word
                profile.total_xp += 15
                xp_earned += 15
            elif progress.correct_count >= 3:
                progress.mastery_level = 2
                progress.next_review = now + timezone.timedelta(days=3)
            elif progress.correct_count >= 1:
                progress.mastery_level = 1
                progress.next_review = now + timezone.timedelta(days=1)

        else:
            progress.wrong_count += 1
            progress.is_learned = False
            progress.mastery_level = 1 if progress.mastery_level > 0 else 0
            progress.next_review = now + timezone.timedelta(minutes=10)

        progress.last_studied = now
        progress.save()
        profile.save(update_fields=["total_xp"])

        new_badges = check_and_award_achievements(user)
        rank_info = get_user_rank_info(profile.total_xp)

        serializer = StudyProgressSerializer(progress)

        return Response({
            "message": "Answer recorded.",
            "progress": serializer.data,
            "current_streak": streak,
            "is_learned": progress.is_learned,
            "mastery_level": progress.mastery_level,
            "xp_earned": xp_earned,
            "total_xp": profile.total_xp,
            "coins": profile.coins,
            "rank": rank_info,
            "new_badges_unlocked": new_badges,
        })


class StudyProgressView(APIView):
    """
    Return user's study progress.

    Example:
    GET /api/dictionary/study/progress/
    """
    permission_classes = [AllowAny]

    def get(self, request):
        user = request.user if request.user and request.user.is_authenticated else None
        if not user:
            total_words = HSKWord.objects.count()
            return Response({
                "total_words": total_words,
                "studied_words": 0,
                "learned_words": 0,
                "remaining_words": total_words,
                "progress": [],
            })

        progress = StudyProgress.objects.filter(user=user).select_related(
            "word"
        )

        serializer = StudyProgressSerializer(
            progress,
            many=True,
        )

        total_words = HSKWord.objects.count()
        learned_words = progress.filter(is_learned=True).count()
        studied_words = progress.count()

        return Response({
            "total_words": total_words,
            "studied_words": studied_words,
            "learned_words": learned_words,
            "remaining_words": max(total_words - learned_words, 0),
            "progress": serializer.data,
        })


class UserLearningStatusView(APIView):
    """
    Returns student's live learning status, daily streak, HSK phase progress %,
    and smart recommendations. Used by Mobile App.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        user = request.user if request.user and request.user.is_authenticated else None
        if not user:
            return Response({
                "current_streak": 0,
                "longest_streak": 0,
                "current_hsk_level": 1,
                "hsk_progress_pct": 0,
                "learned_count": 0,
                "study_count": 0,
                "total_words_in_hsk": 150,
                "learned_in_hsk": 0,
                "accuracy_pct": 0,
                "due_reviews": 0,
                "dropout_risk": "safe",
                "guidance_note": "লগইন করে প্রতিদিনের স্ট্রিক ও অগ্রগতি ট্র্যাক করুন।",
                "daily_goal_words": 10,
            })

        display_name = getattr(getattr(user, "studentprofile", None), "display_name", "") or user.first_name or user.username
        summary = get_student_learning_summary(user)
        return Response({
            "user": {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
                "display_name": display_name,
            },
            **summary,
        })


class DailyQuizView(APIView):
    """
    Daily 5-minute quiz endpoint:
    GET: returns dynamic 5-question quiz for requested HSK level.
    POST: grades quiz submission, awards XP/Coins, updates word mastery & badges.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        user = request.user if request.user and request.user.is_authenticated else None
        try:
            hsk_level = int(request.query_params.get("level", 1))
        except (ValueError, TypeError):
            hsk_level = 1

        quiz_data = generate_daily_quiz(user, hsk_level=hsk_level, count=5)
        return Response(quiz_data)

    def post(self, request):
        user = request.user if request.user and request.user.is_authenticated else None
        hsk_level = int(request.data.get("hsk_level", 1))
        answers = request.data.get("answers", [])
        if not isinstance(answers, list):
            return Response({"error": "answers must be a list"}, status=status.HTTP_400_BAD_REQUEST)

        if not user:
            correct_count = sum(1 for a in answers if a.get("word_id") and a.get("word_id") == a.get("selected_word_id"))
            return Response({
                "score": correct_count,
                "total_questions": len(answers),
                "accuracy_pct": round((correct_count / len(answers) * 100), 1) if answers else 0,
                "xp_earned": correct_count * 10,
                "coins_earned": 5 if correct_count == len(answers) else 0,
                "total_xp": 0,
                "coins": 0,
                "rank": {"title": "Novice", "tier": 1},
                "new_badges_unlocked": [],
                "feedback": "লগইন করে প্রতিদিনের কুইজের XP ও ব্যাজ সংরক্ষণ করুন!",
            })

        result = evaluate_daily_quiz(user, hsk_level=hsk_level, answers=answers)
        return Response(result)


# ============================================================
# ADMIN CONTROL PANEL APIS (Gold Standard Protected)
# ============================================================

class AdminStatsView(APIView):
    permission_classes = [IsAdminOrSuperuser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "admin_action"

    def get(self, request):
        UserModel = get_user_model()
        from chatbot.models import Conversation, ChatMessage

        hsk_counts = {}
        for lvl in range(1, 7):
            hsk_counts[lvl] = HSKWord.objects.filter(hsk_level=lvl).count()

        total_words = HSKWord.objects.count()
        total_users = UserModel.objects.count()
        active_users = UserModel.objects.filter(is_active=True).count()
        total_convs = Conversation.objects.count()
        total_msgs = ChatMessage.objects.count()
        total_study = StudyProgress.objects.count()
        learned_words = StudyProgress.objects.filter(is_learned=True).count()

        # Gamification aggregate metrics
        total_xp_awarded = StudentProfile.objects.aggregate(total=Sum('total_xp'))['total'] or 0
        total_coins_awarded = StudentProfile.objects.aggregate(total=Sum('coins'))['total'] or 0
        avg_streak = round(StudentProfile.objects.aggregate(avg=Avg('current_streak'))['avg'] or 0, 1)

        # SRS Word Mastery Distribution
        mastery_stats = {
            "mastered": StudyProgress.objects.filter(mastery_level=3).count(),
            "familiar": StudyProgress.objects.filter(mastery_level=2).count(),
            "learning": StudyProgress.objects.filter(mastery_level=1).count(),
            "new": StudyProgress.objects.filter(mastery_level=0).count(),
        }

        # HSK Learner Distribution (Highest unlocked HSK tier)
        hsk_user_distribution = {}
        for lvl in range(1, 7):
            hsk_user_distribution[lvl] = StudentProfile.objects.filter(highest_hsk_level_unlocked=lvl).count()

        # Most popular HSK level
        most_popular_hsk = 1
        if hsk_user_distribution:
            most_popular_hsk = max(hsk_user_distribution.items(), key=lambda x: x[1])[0]

        total_quizzes = QuizRecord.objects.count()
        total_badges = UserAchievement.objects.count()

        return Response({
            "status": "healthy",
            "total_words": total_words,
            "words_by_hsk": hsk_counts,
            "total_users": total_users,
            "active_users": active_users,
            "total_conversations": total_convs,
            "total_messages": total_msgs,
            "total_study_records": total_study,
            "learned_words": learned_words,
            "gamification": {
                "total_xp_awarded": total_xp_awarded,
                "total_coins_awarded": total_coins_awarded,
                "average_streak": avg_streak,
                "most_popular_hsk": most_popular_hsk,
                "hsk_user_distribution": hsk_user_distribution,
                "mastery_stats": mastery_stats,
                "total_quizzes_taken": total_quizzes,
                "total_badges_unlocked": total_badges,
            },
            "system": {
                "database": "SQLite (db.sqlite3)" if getattr(settings, 'USE_SQLITE', True) else "PostgreSQL",
                "python": platform.python_version(),
                "os": platform.system(),
                "api_host": request.build_absolute_uri('/')[:-1] if hasattr(request, 'build_absolute_uri') else "https://api.hanban.site",
                "ai_service_url": getattr(settings, 'AI_SERVICE_URL', 'http://127.0.0.1:8001'),
            }
        })


class AdminWordDetailView(APIView):
    permission_classes = [IsAdminOrSuperuser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "admin_action"

    def post(self, request):
        serializer = DictionaryWordSerializer(data=request.data)
        if serializer.is_valid():
            word = serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, pk):
        word = get_object_or_404(HSKWord, pk=pk)
        serializer = DictionaryWordSerializer(word, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        word = get_object_or_404(HSKWord, pk=pk)
        word.delete()
        return Response({"message": f"Word {pk} deleted successfully."}, status=status.HTTP_200_OK)


class AdminImportHSKView(APIView):
    permission_classes = [IsAdminOrSuperuser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "admin_action"

    def post(self, request):
        level = request.data.get("level", "all")
        data_dir = Path(__file__).resolve().parent.parent / "data" / "hsk_json"

        levels_to_import = range(1, 7) if str(level).lower() == "all" else [int(level)]
        results = {}

        for lvl in levels_to_import:
            json_file = data_dir / f"hsk-{lvl}.json"
            if not json_file.exists():
                results[f"hsk_{lvl}"] = {"error": f"File {json_file.name} not found"}
                continue

            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    entries = json.load(f)

                created_count = 0
                for item in entries:
                    chinese = str(item.get("Chinese", "")).strip()
                    pinyin = str(item.get("Pinyin", "")).strip()
                    english = str(item.get("EN", "")).strip()
                    bangla = str(item.get("BN", "")).strip()

                    if not chinese:
                        continue

                    _, created = HSKWord.objects.get_or_create(
                        chinese=chinese,
                        hsk_level=lvl,
                        defaults={
                            "pinyin": pinyin,
                            "english": english,
                            "bangla": bangla,
                        }
                    )
                    if created:
                        created_count += 1

                results[f"hsk_{lvl}"] = {
                    "total_in_file": len(entries),
                    "newly_imported": created_count,
                    "current_total": HSKWord.objects.filter(hsk_level=lvl).count(),
                }
            except Exception as e:
                results[f"hsk_{lvl}"] = {"error": str(e)}

        return Response({
            "message": "Import completed",
            "results": results,
            "overall_words": HSKWord.objects.count()
        })


class AdminUserListView(APIView):
    permission_classes = [IsAdminOrSuperuser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "admin_action"

    def get(self, request, pk=None):
        UserModel = get_user_model()
        target_id = pk or request.query_params.get("id")
        if target_id:
            u = get_object_or_404(UserModel, pk=target_id)
            summary = get_student_learning_summary(u)
            recent_quizzes = list(QuizRecord.objects.filter(user=u).order_by("-completed_at")[:10].values(
                "id", "hsk_level", "score", "total_questions", "xp_earned", "coins_earned", "completed_at"
            ))
            recent_mastered = list(StudyProgress.objects.filter(user=u, mastery_level=3).select_related("word").order_by("-last_studied")[:15].values(
                "word__chinese", "word__pinyin", "word__bangla", "word__english", "word__hsk_level", "correct_count", "last_studied"
            ))
            return Response({
                "id": str(u.id),
                "username": u.username,
                "email": u.email,
                "is_staff": u.is_staff,
                "is_active": u.is_active,
                "date_joined": u.date_joined.strftime("%Y-%m-%d %H:%M") if u.date_joined else "",
                "last_login": u.last_login.strftime("%Y-%m-%d %H:%M") if u.last_login else "Never logged in",
                "recent_quizzes": recent_quizzes,
                "recent_mastered_words": recent_mastered,
                **summary,
            })

        users = UserModel.objects.all().order_by("-date_joined")[:100]
        data = []
        for u in users:
            summary = get_student_learning_summary(u)
            try:
                from chatbot.models import Conversation
                ai_count = Conversation.objects.filter(user=u).count()
            except Exception:
                ai_count = 0

            data.append({
                "id": str(u.id),
                "username": u.username,
                "email": u.email,
                "is_staff": u.is_staff,
                "is_active": u.is_active,
                "date_joined": u.date_joined.strftime("%Y-%m-%d %H:%M") if u.date_joined else "",
                "last_login": u.last_login.strftime("%Y-%m-%d %H:%M") if u.last_login else "Never logged in",
                "ai_conversations_count": ai_count,
                **summary,
            })
        return Response(data)

    def patch(self, request, pk):
        UserModel = get_user_model()
        user = get_object_or_404(UserModel, pk=pk)
        if "is_active" in request.data:
            user.is_active = bool(request.data["is_active"])
        if "is_staff" in request.data:
            user.is_staff = bool(request.data["is_staff"])
        user.save()
        return Response({"message": f"User {user.username} updated."})


class AdminConversationListView(APIView):
    permission_classes = [IsAdminOrSuperuser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "admin_action"

    def get(self, request):
        from chatbot.models import Conversation
        convs = Conversation.objects.select_related("user").prefetch_related("messages").all().order_by("-updated_at")[:50]
        data = []
        for c in convs:
            msgs = [{"role": m.role, "content": m.content, "time": m.created_at.strftime("%H:%M:%S")} for m in c.messages.all()]
            data.append({
                "id": c.id,
                "user": c.user.username if c.user else "Anonymous",
                "title": c.title,
                "mode": c.mode,
                "message_count": len(msgs),
                "created_at": c.created_at.strftime("%Y-%m-%d %H:%M"),
                "messages": msgs,
            })
        return Response(data)

    def delete(self, request, pk):
        from chatbot.models import Conversation
        conv = get_object_or_404(Conversation, pk=pk)
        conv.delete()
        return Response({"message": f"Conversation {pk} deleted successfully."})


class AdminDataFilesView(APIView):
    permission_classes = [IsAdminOrSuperuser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "admin_action"

    def get(self, request):
        data_dir = Path(__file__).resolve().parent.parent / "data" / "hsk_json"
        files_info = []
        total_file_entries = 0
        total_db_entries = HSKWord.objects.count()

        for lvl in range(1, 7):
            fpath = data_dir / f"hsk-{lvl}.json"
            if fpath.exists():
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        entries = json.load(f)
                    file_cnt = len(entries)
                    total_file_entries += file_cnt
                    db_cnt = HSKWord.objects.filter(hsk_level=lvl).count()
                    size_kb = round(fpath.stat().st_size / 1024, 1)
                    sample = entries[:5] if entries else []
                    files_info.append({
                        "level": lvl,
                        "filename": fpath.name,
                        "size_kb": size_kb,
                        "file_count": file_cnt,
                        "db_count": db_cnt,
                        "is_synced": db_cnt >= file_cnt,
                        "sample": sample,
                    })
                except Exception as e:
                    files_info.append({
                        "level": lvl,
                        "filename": fpath.name,
                        "error": str(e),
                    })

        return Response({
            "data_directory": str(data_dir),
            "total_files": len(files_info),
            "total_file_entries": total_file_entries,
            "total_db_entries": total_db_entries,
            "files": files_info,
        })


class UserNotificationListView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        user = request.user
        try:
            generate_smart_notifications(user)
        except Exception:
            pass

        notifications = UserNotification.objects.filter(user=user).order_by("-created_at")
        unread_count = notifications.filter(is_read=False).count()

        now = timezone.now()
        data = []
        for n in notifications[:60]:
            diff = now - n.created_at
            if diff.total_seconds() < 60:
                time_ago = "Just now"
            elif diff.total_seconds() < 3600:
                mins = int(diff.total_seconds() // 60)
                time_ago = f"{mins}m ago"
            elif diff.total_seconds() < 86400:
                hours = int(diff.total_seconds() // 3600)
                time_ago = f"{hours}h ago"
            else:
                days = int(diff.total_seconds() // 86400)
                time_ago = f"{days}d ago"

            data.append({
                "id": n.id,
                "title": n.title,
                "message": n.message,
                "notification_type": n.notification_type,
                "action_route": n.action_route,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat(),
                "time_ago": time_ago,
            })

        return Response({
            "unread_count": unread_count,
            "total_count": notifications.count(),
            "notifications": data,
        })


class NotificationMarkReadView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def post(self, request, pk):
        notif = get_object_or_404(UserNotification, pk=pk, user=request.user)
        notif.is_read = True
        notif.save(update_fields=["is_read"])
        return Response({
            "success": True,
            "id": notif.id,
            "is_read": True,
        })


class NotificationMarkAllReadView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def post(self, request):
        updated = UserNotification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({
            "success": True,
            "updated_count": updated,
        })


class NotificationClearAllView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def post(self, request):
        deleted_count, _ = UserNotification.objects.filter(user=request.user).delete()
        return Response({
            "success": True,
            "deleted_count": deleted_count,
        })


class AdminNotificationBroadcastView(APIView):
    permission_classes = [IsAdminOrSuperuser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "admin_action"

    def get(self, request):
        """Returns recent broadcast log for Admin console."""
        recent = UserNotification.objects.order_by("-created_at")[:40]
        logs = []
        for n in recent:
            logs.append({
                "id": n.id,
                "user_name": n.user.username if n.user else "Anonymous",
                "user_email": n.user.email if n.user else "",
                "title": n.title,
                "message": n.message,
                "notification_type": n.notification_type,
                "is_read": n.is_read,
                "created_at": n.created_at.strftime("%Y-%m-%d %H:%M"),
            })
        return Response({
            "total_notifications_sent": UserNotification.objects.count(),
            "unread_notifications": UserNotification.objects.filter(is_read=False).count(),
            "recent_logs": logs,
        })

    def post(self, request):
        """Admin dispatches broadcast or targeted push message."""
        title = request.data.get("title", "").strip()
        message = request.data.get("message", "").strip()
        notification_type = request.data.get("notification_type", "admin_broadcast")
        action_route = request.data.get("action_route", "/home")
        target_user_id = request.data.get("target_user_id", None)

        if not title or not message:
            return Response(
                {"error": "Both 'title' and 'message' are required fields."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sent_count = send_admin_broadcast(
            title=title,
            message=message,
            notification_type=notification_type,
            action_route=action_route,
            target_user_id=target_user_id,
        )

        return Response({
            "success": True,
            "message": f"Successfully delivered notification to {sent_count} learner(s).",
            "sent_count": sent_count,
        })


