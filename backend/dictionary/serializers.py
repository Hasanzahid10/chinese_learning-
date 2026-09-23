from rest_framework import serializers
from .models import HSKWord ,StudyProgress


class DictionaryWordSerializer(serializers.ModelSerializer):
    class Meta:
        model = HSKWord
        fields = [
            "id",
            "hsk_level",
            "chinese",
            "pinyin",
            "english",
            "bangla",
        ]

class StudyProgressSerializer(serializers.ModelSerializer):
    word = DictionaryWordSerializer(read_only=True)

    class Meta:
        model = StudyProgress
        fields = [
            "id",
            "word",
            "correct_count",
            "wrong_count",
            "is_learned",
            "last_studied",
            "next_review",
        ]