"""
Gamification & Personalized Learning Path Engine
Handles:
- XP & Rank Tiers (Novice -> Grandmaster)
- Automated Badge & Achievement Evaluator
- Word Mastery Stages (0: New, 1: Learning, 2: Familiar, 3: Mastered)
- HSK 1-6 Progressive Lock/Unlock Calculator (80% Mastery Threshold)
- Dynamic Daily 5-Minute Quiz Generator & Evaluator
"""
import random
from datetime import date, timedelta
from typing import Dict, Any, List
from django.utils import timezone
from .models import HSKWord, StudyProgress, UserAchievement, QuizRecord
from authentication.models import StudentProfile


def get_user_rank_info(total_xp: int) -> Dict[str, Any]:
    """Calculates user level tier and progress to next rank."""
    tiers = [
        {"level": 1, "name_en": "Novice", "name_bn": "নতুন শিক্ষার্থী", "min_xp": 0, "max_xp": 100, "icon": "seedling"},
        {"level": 2, "name_en": "Explorer", "name_bn": "অভিযাত্রী", "min_xp": 101, "max_xp": 300, "icon": "compass"},
        {"level": 3, "name_en": "Scholar", "name_bn": "পণ্ডিত", "min_xp": 301, "max_xp": 600, "icon": "book-open"},
        {"level": 4, "name_en": "Master", "name_bn": "মাস্টার", "min_xp": 601, "max_xp": 1200, "icon": "award"},
        {"level": 5, "name_en": "Grandmaster", "name_bn": "গ্র্যান্ডমাস্টার", "min_xp": 1201, "max_xp": 999999, "icon": "crown"},
    ]

    for tier in tiers:
        if total_xp <= tier["max_xp"]:
            range_xp = tier["max_xp"] - tier["min_xp"]
            current_in_tier = max(0, total_xp - tier["min_xp"])
            progress_pct = round((current_in_tier / range_xp) * 100, 1) if range_xp > 0 else 100.0
            return {
                "rank_level": tier["level"],
                "rank_name_en": tier["name_en"],
                "rank_name_bn": tier["name_bn"],
                "rank_icon": tier["icon"],
                "next_rank_xp": tier["max_xp"],
                "progress_to_next_rank_pct": progress_pct,
            }

    last_tier = tiers[-1]
    return {
        "rank_level": last_tier["level"],
        "rank_name_en": last_tier["name_en"],
        "rank_name_bn": last_tier["name_bn"],
        "rank_icon": last_tier["icon"],
        "next_rank_xp": total_xp,
        "progress_to_next_rank_pct": 100.0,
    }


def calculate_hsk_unlocks(user) -> Dict[str, Any]:
    """
    Calculates completion and lock/unlock status for HSK levels 1 to 6.
    By default: HSK 1 is UNLOCKED.
    HSK N+1 automatically unlocks when user achieves >= 80% mastery in HSK N.
    """
    profile, _ = StudentProfile.objects.get_or_create(user=user)
    highest_unlocked = profile.highest_hsk_level_unlocked or 1

    user_progress = StudyProgress.objects.filter(user=user)
    hsk_levels_data = {}

    can_unlock_next = True

    for level in range(1, 7):
        total_words_in_level = HSKWord.objects.filter(hsk_level=level).count() or 150
        mastered_in_level = user_progress.filter(
            word__hsk_level=level,
            is_learned=True
        ).count()

        percentage = round((mastered_in_level / total_words_in_level) * 100, 1) if total_words_in_level > 0 else 0.0

        # Unlocked if level 1, or previous level is >= 80%, or profile has recorded unlock
        is_unlocked = (level == 1) or (level <= highest_unlocked) or can_unlock_next

        if is_unlocked and level > highest_unlocked:
            highest_unlocked = level
            profile.highest_hsk_level_unlocked = highest_unlocked
            profile.save(update_fields=["highest_hsk_level_unlocked"])

        # Next level requirement check (80% threshold)
        can_unlock_next = is_unlocked and (percentage >= 80.0)

        hsk_levels_data[f"hsk_{level}"] = {
            "level": level,
            "title": f"HSK {level}",
            "is_unlocked": is_unlocked,
            "mastered_words": mastered_in_level,
            "total_words": total_words_in_level,
            "mastery_percentage": percentage,
            "required_for_next": 80.0,
            "is_completed": percentage >= 80.0,
        }

    return {
        "highest_unlocked_level": highest_unlocked,
        "levels": hsk_levels_data,
    }


def check_and_award_achievements(user) -> List[Dict[str, Any]]:
    """Evaluates user progress against badge criteria and awards new achievements."""
    profile, _ = StudentProfile.objects.get_or_create(user=user)
    existing_keys = set(UserAchievement.objects.filter(user=user).values_list("badge_key", flat=True))

    all_progress = StudyProgress.objects.filter(user=user)
    total_studied = all_progress.count()
    total_mastered = all_progress.filter(is_learned=True).count()
    streak = profile.current_streak

    badge_rules = [
        {
            "key": "first_step",
            "title": "First Step",
            "description": "Started your Chinese journey by practicing your first word.",
            "icon": "sparkles",
            "condition": total_studied >= 1,
        },
        {
            "key": "streak_3",
            "title": "3-Day Fire",
            "description": "Maintained a continuous 3-day learning streak.",
            "icon": "flame",
            "condition": streak >= 3,
        },
        {
            "key": "streak_7",
            "title": "Weekly Warrior",
            "description": "7 days of dedicated Chinese study without breaking streak.",
            "icon": "zap",
            "condition": streak >= 7,
        },
        {
            "key": "streak_30",
            "title": "Monthly Legend",
            "description": "Incredible dedication: 30 days continuous study streak!",
            "icon": "trophy",
            "condition": streak >= 30,
        },
        {
            "key": "vocab_50",
            "title": "Vocab Builder",
            "description": "Reached 50 words in your Chinese learning portfolio.",
            "icon": "book-open",
            "condition": total_studied >= 50,
        },
        {
            "key": "master_10",
            "title": "Permanent Memory",
            "description": "Mastered 10 words into your long-term memory.",
            "icon": "brain",
            "condition": total_mastered >= 10,
        },
        {
            "key": "hsk1_master",
            "title": "HSK 1 Champion",
            "description": "Achieved 80% mastery of all official HSK 1 vocabulary.",
            "icon": "award",
            "condition": (
                all_progress.filter(word__hsk_level=1, is_learned=True).count() >= 120
            ),
        },
        {
            "key": "quiz_ace",
            "title": "Quiz Master",
            "description": "Achieved a perfect 100% score on a Daily Quiz.",
            "icon": "star",
            "condition": (
                QuizRecord.objects.filter(user=user, score__gte=5).exists()
            ),
        },
    ]

    newly_awarded = []
    for badge in badge_rules:
        if badge["condition"] and badge["key"] not in existing_keys:
            ach = UserAchievement.objects.create(
                user=user,
                badge_key=badge["key"],
                title=badge["title"],
                description=badge["description"],
                icon=badge["icon"],
            )
            existing_keys.add(badge["key"])
            newly_awarded.append({
                "key": ach.badge_key,
                "title": ach.title,
                "description": ach.description,
                "icon": ach.icon,
            })

            # Bonus XP for unlocking badge
            profile.total_xp += 50
            profile.save(update_fields=["total_xp"])

    return newly_awarded


def generate_daily_quiz(user, hsk_level: int = 1, count: int = 5) -> Dict[str, Any]:
    """Generates a dynamic 5-question multiple choice quiz for the learner."""
    words = list(HSKWord.objects.filter(hsk_level=hsk_level))
    if len(words) < count:
        words = list(HSKWord.objects.all()[:count])

    quiz_words = random.sample(words, min(count, len(words)))
    questions = []

    for word in quiz_words:
        # Correct answer
        correct_meaning = word.bangla if word.bangla else word.english
        correct_option = {
            "id": word.id,
            "text": correct_meaning,
            "english": word.english,
            "bangla": word.bangla,
            "is_correct": True,
        }

        # 3 Distractor options from other words in the same HSK level
        distractors = [w for w in words if w.id != word.id]
        chosen_distractors = random.sample(distractors, min(3, len(distractors)))
        options = [correct_option]
        for d in chosen_distractors:
            d_meaning = d.bangla if d.bangla else d.english
            options.append({
                "id": d.id,
                "text": d_meaning,
                "english": d.english,
                "bangla": d.bangla,
                "is_correct": False,
            })

        random.shuffle(options)

        questions.append({
            "word_id": word.id,
            "chinese": word.chinese,
            "pinyin": word.pinyin,
            "options": options,
            "correct_word_id": word.id,
            "correct_answer": correct_meaning,
        })

    return {
        "hsk_level": hsk_level,
        "total_questions": len(questions),
        "reward_xp": 30,
        "reward_coins": 5,
        "questions": questions,
    }


def evaluate_daily_quiz(user, hsk_level: int, answers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Evaluates quiz submissions, records progress, awards XP/Coins, and checks badges.
    Each answer dict: { "word_id": int, "selected_word_id": int }
    """
    profile, _ = StudentProfile.objects.get_or_create(user=user)
    correct_count = 0
    total = len(answers)

    for item in answers:
        word_id = item.get("word_id")
        selected_id = item.get("selected_word_id")
        if word_id and selected_id and word_id == selected_id:
            correct_count += 1
            # Update word study progress
            try:
                word = HSKWord.objects.get(id=word_id)
                prog, _ = StudyProgress.objects.get_or_create(user=user, word=word)
                prog.correct_count += 1
                if prog.correct_count >= 5:
                    prog.is_learned = True
                    prog.mastery_level = 3
                elif prog.correct_count >= 2:
                    prog.mastery_level = 2
                else:
                    prog.mastery_level = 1
                prog.save()
            except Exception:
                pass

    # Award XP & Coins
    base_xp = correct_count * 10
    bonus_xp = 20 if (correct_count == total and total > 0) else 0
    total_xp_awarded = base_xp + bonus_xp

    base_coins = max(1, correct_count)
    bonus_coins = 3 if (correct_count == total and total > 0) else 0
    total_coins_awarded = base_coins + bonus_coins

    profile.total_xp += total_xp_awarded
    profile.coins += total_coins_awarded
    profile.save(update_fields=["total_xp", "coins"])

    # Record Quiz History
    QuizRecord.objects.create(
        user=user,
        hsk_level=hsk_level,
        score=correct_count,
        total_questions=total,
        xp_earned=total_xp_awarded,
        coins_earned=total_coins_awarded,
    )

    # Check for achievements
    new_badges = check_and_award_achievements(user)

    return {
        "score": correct_count,
        "total_questions": total,
        "percentage": round((correct_count / total) * 100, 1) if total > 0 else 0.0,
        "xp_earned": total_xp_awarded,
        "coins_earned": total_coins_awarded,
        "current_total_xp": profile.total_xp,
        "current_coins": profile.coins,
        "new_badges_unlocked": new_badges,
    }
