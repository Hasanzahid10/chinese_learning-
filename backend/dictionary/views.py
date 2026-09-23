import random
from django.db.models import Q
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone

from .models import HSKWord,StudyProgress
from .serializers import (DictionaryWordSerializer,StudyProgressSerializer)


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

        words = words.order_by(
            "hsk_level",
            "chinese"
        )[:50]

        serializer = DictionaryWordSerializer(
            words,
            many=True
        )

        return Response({
            "query": query,
            "count": len(serializer.data),
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
    permission_classes = [IsAuthenticated]

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

        progress, created = StudyProgress.objects.get_or_create(
            word=word
        )

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
        })

class StudyProgressView(APIView):
    """
    Return user's study progress.

    Example:
    GET /api/dictionary/study/progress/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        progress = StudyProgress.objects.select_related(
            "word"
        ).all()

        serializer = StudyProgressSerializer(
            progress,
            many=True,
        )

        total_words = HSKWord.objects.count()

        learned_words = StudyProgress.objects.filter(
            is_learned=True
        ).count()

        studied_words = StudyProgress.objects.count()

        return Response(
            {
                "total_words": total_words,
                "studied_words": studied_words,
                "learned_words": learned_words,
                "remaining_words": max(
                    total_words - learned_words,
                    0
                ),
                "progress": serializer.data,
            }
        )