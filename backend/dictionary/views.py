import json
import platform
import random
from datetime import date, timedelta
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated

from authentication.models import StudentProfile
from .models import HSKWord, StudyProgress
from .serializers import (DictionaryWordSerializer, StudyProgressSerializer)


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

    return {
        "current_streak": profile.current_streak,
        "longest_streak": profile.longest_streak,
        "last_study_date": str(profile.last_study_date) if profile.last_study_date else None,
        "current_hsk_level": current_level,
        "target_hsk_level": profile.target_hsk_level,
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
        "total_xp": profile.total_xp,
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
        query = request.GET.get("q", "").strip()
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

        # Pagination support
        try:
            page = max(1, int(request.GET.get("page", 1)))
        except (ValueError, TypeError):
            page = 1

        page_size_param = str(request.GET.get("page_size", "50")).strip().lower()
        if page_size_param in ("all", "0", "-1"):
            page_size = 10000
        else:
            try:
                page_size = max(10, min(int(page_size_param), 1000))
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
    permission_classes = [IsAuthenticated]
    def get(self, request):
        hsk = request.GET.get("hsk")
        now = timezone.now()

        words = HSKWord.objects.all()

        # Optional HSK filter
        if hsk:
            try:
                hsk = int(hsk)

                if hsk not in range(1, 7):
                    return Response(
                        {"error": "hsk must be between 1 and 6"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                words = words.filter(hsk_level=hsk)

            except ValueError:
                return Response(
                    {"error": "hsk must be a number from 1 to 6"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # ---------------------------------------------------------
        # 1. EXCLUDE WORDS ALREADY LEARNED
        # ---------------------------------------------------------
        available_words = words.exclude(
            study_progress__is_learned=True
        )

        # ---------------------------------------------------------
        # 2. FIND WORDS THAT ARE DUE FOR REVIEW
        #
        # next_review IS NULL = never studied
        # next_review <= now = review is due
        # ---------------------------------------------------------
        due_words = available_words.filter(
            Q(study_progress__next_review__isnull=True)
            | Q(study_progress__next_review__lte=now)
        ).distinct()

        # ---------------------------------------------------------
        # 3. PRIORITY:
        #    First choose due words.
        # ---------------------------------------------------------
        due_count = due_words.count()

        if due_count > 0:
            random_index = random.randint(0, due_count - 1)
            word = due_words[random_index]

            serializer = DictionaryWordSerializer(word)

            return Response({
                "card": serializer.data,
                "show_answer": False,
                "study_type": "due_review",
            })

        # ---------------------------------------------------------
        # 4. NO DUE WORDS
        #
        # Look for completely new words that have no progress.
        # ---------------------------------------------------------
        new_words = available_words.filter(
            study_progress__isnull=True
        )

        new_count = new_words.count()

        if new_count > 0:
            random_index = random.randint(0, new_count - 1)
            word = new_words[random_index]

            serializer = DictionaryWordSerializer(word)

            return Response({
                "card": serializer.data,
                "show_answer": False,
                "study_type": "new",
            })

        # ---------------------------------------------------------
        # 5. EVERYTHING IS CURRENTLY WAITING FOR REVIEW
        # ---------------------------------------------------------
        upcoming_words = available_words.filter(
            study_progress__next_review__gt=now
        ).order_by(
            "study_progress__next_review"
        )

        upcoming_word = upcoming_words.first()

        if upcoming_word:
            progress = upcoming_word.study_progress.first()

            serializer = DictionaryWordSerializer(upcoming_word)

            return Response({
                "card": serializer.data,
                "show_answer": False,
                "study_type": "upcoming_review",
                "next_review": progress.next_review,
            })

        # ---------------------------------------------------------
        # 6. NOTHING LEFT TO STUDY
        # ---------------------------------------------------------
        return Response({
            "message": "Congratulations! You have learned all available words.",
            "study_type": "completed",
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
            UserModel = get_user_model()
            user = UserModel.objects.first()

        progress, created = StudyProgress.objects.get_or_create(
            user=user,
            word=word,
        )

        streak = update_student_streak(user)
        now = timezone.now()

        if correct:
            progress.correct_count += 1

            if progress.correct_count >= 5:
                progress.is_learned = True
                progress.next_review = now + timezone.timedelta(days=7)

            elif progress.correct_count >= 3:
                progress.next_review = now + timezone.timedelta(days=3)

            else:
                progress.next_review = now + timezone.timedelta(days=1)

        else:
            progress.wrong_count += 1
            progress.is_learned = False
            progress.next_review = now + timezone.timedelta(minutes=10)

        progress.last_studied = now
        progress.save()

        serializer = StudyProgressSerializer(progress)

        return Response({
            "message": "Answer recorded.",
            "progress": serializer.data,
            "current_streak": streak,
            "is_learned": progress.is_learned,
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
            UserModel = get_user_model()
            user = UserModel.objects.first()

        progress = StudyProgress.objects.filter(user=user).select_related(
            "word"
        ) if user else StudyProgress.objects.select_related("word").all()

        serializer = StudyProgressSerializer(
            progress,
            many=True,
        )

        total_words = HSKWord.objects.count()
        learned_words = progress.filter(is_learned=True).count() if user else 0
        studied_words = progress.count() if user else 0

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
            UserModel = get_user_model()
            user = UserModel.objects.first()

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

        summary = get_student_learning_summary(user)
        return Response({
            "user": {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
            },
            **summary,
        })


# ============================================================
# ADMIN CONTROL PANEL APIS
# ============================================================

class AdminStatsView(APIView):
    permission_classes = [AllowAny]

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
            "system": {
                "database": "SQLite (db.sqlite3)" if getattr(settings, 'USE_SQLITE', True) else "PostgreSQL",
                "python": platform.python_version(),
                "os": platform.system(),
                "api_host": "http://127.0.0.1:8000",
                "ai_service_url": getattr(settings, 'AI_SERVICE_URL', 'http://127.0.0.1:8001'),
            }
        })


class AdminWordDetailView(APIView):
    permission_classes = [AllowAny]

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
    permission_classes = [AllowAny]

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
    permission_classes = [AllowAny]

    def get(self, request):
        UserModel = get_user_model()
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
                "last_login": u.last_login.strftime("%Y-%m-%d %H:%M") if u.last_login else "কখনো লগইন করেনি",
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
    permission_classes = [AllowAny]

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
    permission_classes = [AllowAny]

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
