from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class SignUpSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=8,
    )

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "password",
        ]

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError(
                "Username already exists."
            )

        return value

    def validate_email(self, value):
        value = value.strip().lower()

        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "Email already exists."
            )

        return value

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
        )

        return user


class StudentProfileSerializer(serializers.ModelSerializer):
    class Meta:
        from .models import StudentProfile
        model = StudentProfile
        fields = [
            "display_name",
            "phone",
            "bio",
            "native_language",
            "current_hsk_level",
            "target_hsk_level",
            "current_streak",
            "longest_streak",
            "last_study_date",
            "daily_goal_words",
            "total_xp",
            "coins",
            "highest_hsk_level_unlocked",
            "is_pinyin_enabled",
            "is_traditional_chinese",
            "is_reminder_active",
            "reminder_time",
            "audio_speed",
            "is_two_factor_enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "current_streak",
            "longest_streak",
            "last_study_date",
            "total_xp",
            "coins",
            "highest_hsk_level_unlocked",
            "created_at",
            "updated_at",
        ]


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)