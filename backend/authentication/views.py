from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import SignUpSerializer


class SignUpView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SignUpSerializer(
            data=request.data
        )

        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = serializer.save()

        refresh = RefreshToken.for_user(user)
        access_token_str = str(refresh.access_token)
        refresh_token_str = str(refresh)

        display_name = getattr(getattr(user, "studentprofile", None), "display_name", "") or user.first_name or user.username

        return Response(
            {
                "message": "Account created successfully.",
                "token": access_token_str,
                "access": access_token_str,
                "access_token": access_token_str,
                "refresh": refresh_token_str,
                "refresh_token": refresh_token_str,
                "token_type": "Bearer",
                "user": {
                    "id": str(user.id),
                    "username": user.username,
                    "email": user.email,
                    "display_name": display_name,
                    "is_staff": getattr(user, "is_staff", False),
                    "is_superuser": getattr(user, "is_superuser", False),
                },
                "tokens": {
                    "access": access_token_str,
                    "refresh": refresh_token_str,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class SignInView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        if not username:
            return Response(
                {"error": "username is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not password:
            return Response(
                {"error": "password is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        username_clean = str(username).strip()
        password_raw = str(password)
        password_trimmed = password_raw.strip()

        # 1. Direct authentication with cleaned username
        user = authenticate(
            username=username_clean,
            password=password_raw,
        )

        # 2. Try with trimmed password if copy-paste included trailing whitespace
        if user is None and password_raw != password_trimmed:
            user = authenticate(
                username=username_clean,
                password=password_trimmed,
            )

        # 3. Case-insensitive email or username lookup
        if user is None:
            from django.contrib.auth import get_user_model
            UserModel = get_user_model()
            user_obj = None

            if "@" in username_clean:
                user_obj = UserModel.objects.filter(email__iexact=username_clean).first()
            if not user_obj:
                user_obj = UserModel.objects.filter(username__iexact=username_clean).first()

            if user_obj:
                user = authenticate(username=user_obj.username, password=password_raw)
                if user is None and password_raw != password_trimmed:
                    user = authenticate(username=user_obj.username, password=password_trimmed)

        if user is None:
            return Response(
                {"error": "Invalid username or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        refresh = RefreshToken.for_user(user)
        access_token_str = str(refresh.access_token)
        refresh_token_str = str(refresh)

        display_name = getattr(getattr(user, "studentprofile", None), "display_name", "") or user.first_name or user.username

        return Response(
            {
                "message": "Signed in successfully.",
                "token": access_token_str,
                "access": access_token_str,
                "access_token": access_token_str,
                "refresh": refresh_token_str,
                "refresh_token": refresh_token_str,
                "token_type": "Bearer",
                "user": {
                    "id": str(user.id),
                    "username": user.username,
                    "email": user.email,
                    "display_name": display_name,
                    "is_staff": getattr(user, "is_staff", False),
                    "is_superuser": getattr(user, "is_superuser", False),
                },
                "tokens": {
                    "access": access_token_str,
                    "refresh": refresh_token_str,
                },
            }
        )


class UserProfileView(APIView):
    permission_classes = [AllowAny]

    def _get_target_user(self, request):
        if request.user and request.user.is_authenticated:
            return request.user
        from django.contrib.auth import get_user_model
        UserModel = get_user_model()
        return UserModel.objects.first()

    def get(self, request):
        user = self._get_target_user(request)
        if not user:
            return Response({"error": "No user found."}, status=status.HTTP_404_NOT_FOUND)

        from .models import StudentProfile
        from dictionary.views import get_student_learning_summary
        profile, _ = StudentProfile.objects.get_or_create(user=user)
        summary = get_student_learning_summary(user)

        data = {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "date_joined": user.date_joined.strftime("%Y-%m-%d %H:%M:%S") if user.date_joined else None,
            "last_login": user.last_login.strftime("%Y-%m-%d %H:%M:%S") if user.last_login else None,
            "is_active": user.is_active,
            "is_staff": user.is_staff,
            # Personal details
            "display_name": profile.display_name or user.username,
            "phone": profile.phone,
            "bio": profile.bio,
            "native_language": profile.native_language,
            # Learning & Goals
            "current_hsk_level": profile.current_hsk_level,
            "target_hsk_level": profile.target_hsk_level,
            "current_streak": profile.current_streak,
            "longest_streak": profile.longest_streak,
            "last_study_date": str(profile.last_study_date) if profile.last_study_date else None,
            "daily_goal_words": profile.daily_goal_words,
            "total_xp": profile.total_xp,
            # Learning summary metrics
            "learned_count": summary["learned_count"],
            "study_count": summary["study_count"],
            "accuracy_pct": summary["accuracy_pct"],
            "due_reviews": summary["due_reviews"],
            "hsk_progress_pct": summary["hsk_progress_pct"],
            "total_words_in_hsk": summary["total_words_in_hsk"],
            "dropout_risk": summary["dropout_risk"],
            "guidance_note": summary["guidance_note"],
            # App Preferences
            "is_pinyin_enabled": profile.is_pinyin_enabled,
            "is_traditional_chinese": profile.is_traditional_chinese,
            "is_reminder_active": profile.is_reminder_active,
            "reminder_time": profile.reminder_time,
            "audio_speed": profile.audio_speed,
            # Security
            "is_two_factor_enabled": profile.is_two_factor_enabled,
        }
        return Response(data)

    def put(self, request):
        return self.patch(request)

    def patch(self, request):
        user = self._get_target_user(request)
        if not user:
            return Response({"error": "No user found."}, status=status.HTTP_404_NOT_FOUND)

        from .models import StudentProfile
        profile, _ = StudentProfile.objects.get_or_create(user=user)

        # Update User model fields if provided
        new_email = request.data.get("email")
        if new_email and new_email != user.email:
            user.email = new_email.strip().lower()
            user.save(update_fields=["email"])

        new_username = request.data.get("username")
        if new_username and new_username != user.username:
            user.username = new_username.strip()
            user.save(update_fields=["username"])

        # Update StudentProfile fields
        profile_fields = [
            "display_name", "phone", "bio", "native_language",
            "target_hsk_level", "current_hsk_level", "daily_goal_words",
            "is_pinyin_enabled", "is_traditional_chinese",
            "is_reminder_active", "reminder_time", "audio_speed",
            "is_two_factor_enabled",
        ]
        updated_fields = []
        for field in profile_fields:
            if field in request.data:
                setattr(profile, field, request.data[field])
                updated_fields.append(field)

        if updated_fields:
            profile.save(update_fields=updated_fields + ["updated_at"])

        return self.get(request)


class ChangePasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        user = request.user if request.user and request.user.is_authenticated else None
        if not user:
            from django.contrib.auth import get_user_model
            UserModel = get_user_model()
            user = UserModel.objects.first()

        old_password = request.data.get("old_password") or request.data.get("current_password")
        new_password = request.data.get("new_password")

        if not old_password or not new_password:
            return Response(
                {"error": "Both current_password and new_password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not user.check_password(old_password):
            return Response(
                {"error": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(new_password) < 6:
            return Response(
                {"error": "New password must be at least 6 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save()

        return Response({"message": "Password updated successfully."})