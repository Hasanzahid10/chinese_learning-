"""
Django settings for config project.
"""

import os
from datetime import timedelta
from pathlib import Path
import environ

# Custom Authentication User Model
AUTH_USER_MODEL = 'authentication.User'

# ============================================================
# BASE
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
env.read_env(os.path.join(BASE_DIR, ".env"))


# ============================================================
# SECURITY
# ============================================================

SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default=env("DJANGO_JWT_SECRET_KEY", default="django-insecure-fa=z1ds4u8gcbwu+g6symjs0%#6t%brbv#z6=y^$b4@$7=rz_a")
)

DEBUG = env.bool(
    "DEBUG",
    default=True,
)

ALLOWED_HOSTS = env.list(
    "ALLOWED_HOSTS",
    default=["*"],
)


# ============================================================
# APPLICATIONS
# ============================================================

INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third party
    "rest_framework",
    "corsheaders",

    # Project
    "dictionary.apps.DictionaryConfig",
    "chatbot.apps.ChatbotConfig",
    "authentication",
]


# ============================================================
# MIDDLEWARE
# ============================================================

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# ============================================================
# URL / APPLICATION
# ============================================================

ROOT_URLCONF = "config.urls"

WSGI_APPLICATION = "config.wsgi.application"


# ============================================================
# TEMPLATES
# ============================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# ============================================================
# DATABASE (PostgreSQL for VPS / SQLite for local)
# ============================================================

USE_SQLITE = env.bool('USE_SQLITE', default=False)
DB_ENGINE_TYPE = env('DB_ENGINE', default='').lower()
DB_PORT = str(env('DB_PORT', default='3306'))

if USE_SQLITE:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
elif 'DATABASE_URL' in os.environ or 'DATABASE_URL' in env:
    DATABASES = {
        'default': env.db('DATABASE_URL')
    }
elif DB_ENGINE_TYPE == 'postgresql' or DB_PORT == '5432':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': env('DB_NAME', default='hanbandb'),
            'USER': env('DB_USER', default='hanbanuser'),
            'PASSWORD': env('DB_PASSWORD', default=''),
            'HOST': env('DB_HOST', default='127.0.0.1'),
            'PORT': DB_PORT,
            'CONN_MAX_AGE': 600,
        }
    }
else:
    # Default: MySQL / MariaDB (Port 3306)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': env('DB_NAME', default='hanbandb'),
            'USER': env('DB_USER', default='hanbanuser'),
            'PASSWORD': env('DB_PASSWORD', default=''),
            'HOST': env('DB_HOST', default='127.0.0.1'),
            'PORT': DB_PORT,
            'OPTIONS': {
                'charset': 'utf8mb4',
            },
        }
    }


# ============================================================
# PASSWORD VALIDATION
# ============================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# ============================================================
# INTERNATIONALIZATION
# ============================================================

LANGUAGE_CODE = "en-us"

TIME_ZONE = "Asia/Dhaka"

USE_I18N = True

USE_TZ = True


# ============================================================
# STATIC & MEDIA FILES
# ============================================================

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# ============================================================
# DEFAULT PRIMARY KEY
# ============================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ============================================================
# DJANGO REST FRAMEWORK & SIMPLE JWT
# ============================================================

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "SIGNING_KEY": env("DJANGO_JWT_SECRET_KEY", default="django-insecure-jwt-key"),
    "ALGORITHM": "HS256",
}


# ============================================================
# FASTAPI / AI SERVICE
# ============================================================

AI_SERVICE_URL = env(
    "AI_SERVICE_URL",
    default="http://127.0.0.1:8001",
)

AI_INTERNAL_KEY = env(
    "AI_INTERNAL_KEY",
    default="ai-internal-secret-key"
)


# ============================================================
# CORS & CSRF
# ============================================================

CORS_ALLOW_ALL_ORIGINS = True

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=[
        "https://admin.hanban.site",
        "https://hanban.site",
        "https://api.hanban.site",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
)

CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=[
        "https://admin.hanban.site",
        "https://api.hanban.site",
        "https://hanban.site",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
)


# ============================================================
# PRODUCTION SECURITY
# ============================================================

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"
