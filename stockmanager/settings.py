"""Django settings for the stockmanager backend.

Configuration comes from the environment via `antares_dotenv.env`, which
coerces types: "true" becomes True, "20" becomes 20, and — importantly — a
value containing a comma becomes a list. `_as_list` exists because a
single-valued ALLOWED_HOSTS would otherwise arrive as a bare string.
"""

from datetime import timedelta
from pathlib import Path

import dj_database_url
from antares_dotenv import env
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# `antares_dotenv.env()` calls python-dotenv's `load_dotenv()` with no path.
# python-dotenv then locates the .env by walking up from the *calling frame's*
# file — which is `antares_dotenv/core.py`, inside site-packages. It therefore
# searches upward from the virtualenv and never sees this project's .env, so
# every `env()` call returns its default.
#
# Loading explicitly from BASE_DIR fixes discovery. `env()` is still used
# below for its type coercion; it reads from os.environ, which this populates.
load_dotenv(BASE_DIR / ".env")


def _as_list(value) -> list[str]:
    """Normalise an env value to a list of strings.

    `env()` returns a list only when the raw value contains a comma, so a
    single-entry setting comes back as a plain string. Both shapes, plus a
    missing value, have to end up as a list.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


# SECURITY: no default. An unset SECRET_KEY must fail loudly, not silently
# fall back to a value an attacker could guess.
#
# str() because env() coerces: a secret that happened to be all digits would
# otherwise arrive as an int, and one containing a comma as a list.
_secret_key = env("SECRET_KEY")
if not _secret_key:
    raise RuntimeError(
        "SECRET_KEY is not set. Copy .env.example to .env and fill it in."
    )
SECRET_KEY = str(_secret_key)

DEBUG = bool(env("DEBUG", False))
ALLOWED_HOSTS = _as_list(env("ALLOWED_HOSTS", "localhost,127.0.0.1"))

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "apps.common",
    "apps.accounts",
]

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

ROOT_URLCONF = "stockmanager.urls"

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

WSGI_APPLICATION = "stockmanager.wsgi.application"

DATABASES = {
    "default": dj_database_url.parse(
        str(env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}")),
        conn_max_age=600,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# The frontend renders `error.message` straight into a toast, so an English
# string is a user-visible bug rather than a cosmetic one.
LANGUAGE_CODE = "fr-fr"
USE_I18N = True

# `ISODateTime` in the frontend is documented as a Z-suffixed instant;
# formatting for display is the frontend's job.
TIME_ZONE = "UTC"
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_RENDERER_CLASSES": (
        "djangorestframework_camel_case.render.CamelCaseJSONRenderer",
    ),
    "DEFAULT_PARSER_CLASSES": (
        "djangorestframework_camel_case.parser.CamelCaseJSONParser",
        "djangorestframework_camel_case.parser.CamelCaseFormParser",
        "djangorestframework_camel_case.parser.CamelCaseMultiPartParser",
    ),
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(env("ACCESS_TOKEN_LIFETIME_MINUTES", 60))
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=int(env("REFRESH_TOKEN_LIFETIME_DAYS", 7))
    ),
    # Rotation is deliberately out of scope for sub-project 1; adding it later
    # invalidates nothing.
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

CORS_ALLOWED_ORIGINS = _as_list(env("CORS_ALLOWED_ORIGINS", "http://localhost:3000"))
# The frontend sends a bearer token, not a cookie.
CORS_ALLOW_CREDENTIALS = False

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
