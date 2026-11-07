import re
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()

# Known disposable/temporary email provider domains used by bot spammers
DISPOSABLE_EMAIL_DOMAINS = {
    "mailinator.com", "tempmail.com", "10minutemail.com", "guerrillamail.com",
    "sharklasers.com", "yopmail.com", "dispostable.com", "temp-mail.org",
    "fakemailgenerator.com", "throwawaymail.com", "getairmail.com",
    "crazymailing.com", "trashmail.com", "mohmal.com", "maildrop.cc",
    "nada.ltd", "burnermail.io", "inboxkitten.com", "tempail.com",
}

# Protected system usernames that cannot be registered by public users
RESERVED_USERNAMES = {
    "admin", "administrator", "root", "superuser", "hanban", "system",
    "support", "moderator", "mod", "api", "billing", "owner", "staff",
    "test", "bot", "official", "null", "undefined",
}


class SignUpSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={"input_type": "password"},
    )

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "password",
        ]

    def validate_username(self, value):
        val = str(value).strip()
        if len(val) < 3 or len(val) > 30:
            raise serializers.ValidationError("Username must be between 3 and 30 characters.")

        if not re.match(r"^[a-zA-Z0-9_.-]+$", val):
            raise serializers.ValidationError(
                "Username may only contain letters, numbers, underscores, dashes, and periods."
            )

        if val.lower() in RESERVED_USERNAMES:
            raise serializers.ValidationError("This username is reserved and cannot be used.")

        if User.objects.filter(username__iexact=val).exists():
            raise serializers.ValidationError("Username already exists.")

        return val

    def validate_email(self, value):
        val = str(value).strip().lower()

        # Strict email regex format check
        if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", val):
            raise serializers.ValidationError("Please provide a valid email address.")

        domain = val.split("@")[-1]
        if domain in DISPOSABLE_EMAIL_DOMAINS:
            raise serializers.ValidationError(
                "Disposable/temporary email addresses are not allowed. Please use a valid personal email."
            )

        if User.objects.filter(email__iexact=val).exists():
            raise serializers.ValidationError("An account with this email already exists.")

        return val

    def validate(self, attrs):
        # Anti-Bot Honeypot Trap: Reject if hidden bot field is filled
        if hasattr(self, "initial_data") and isinstance(self.initial_data, dict):
            bot_trap = self.initial_data.get("bot_check") or self.initial_data.get("website")
            if bot_trap and str(bot_trap).strip():
                raise serializers.ValidationError("Bot registration detected and blocked.")

        # Enforce Django's official password policy validators (Common, length, numeric, similarity)
        raw_password = attrs.get("password")
        if raw_password:
            try:
                validate_password(raw_password)
            except Exception as e:
                # Extract clean error messages
                error_messages = getattr(e, "messages", [str(e)])
                raise serializers.ValidationError({"password": error_messages})

        return attrs

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
            "created_at",
            "updated_at",
        ]
