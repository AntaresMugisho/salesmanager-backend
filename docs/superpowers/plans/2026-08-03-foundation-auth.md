# Foundation & Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Django/DRF backend's identity model and wire conventions — custom user with roles, the `Site` singleton, JWT auth, owner-only user management — so the five later sub-projects have a settled foundation to build on.

**Architecture:** Domain apps under an `apps/` package. `apps/common` holds everything shared: a UUID model base, the error envelope, pagination, permissions, and a camelCase query-param translator. `apps/accounts` holds `User` and `Site` plus the auth, settings and user-management endpoints. All JSON is camelCase in both directions; all human-readable messages are French.

**Tech Stack:** Django 6.0.7, DRF 3.17.1, djangorestframework-simplejwt 5.5.1, djangorestframework-camel-case 1.4.2, django-cors-headers 4.9.0, dj-database-url 3.1.2, antares-dotenv 1.1.0, pytest 9.1.1 + pytest-django 4.12.0 + factory-boy 3.3.3. SQLite in development.

## Global Constraints

Every task's requirements implicitly include this section.

- **Spec:** `docs/superpowers/specs/2026-08-03-foundation-auth-design.md`. It is authoritative; this plan implements it.
- **The API contract is fixed by the frontend.** `/media/antares/Data/coding/stockmanager/stockmanager-frontend/types/domain.ts` and `types/dto.ts` define every payload. Read them before changing a field name. Do not invent fields.
- **All JSON is camelCase**, both directions, including error bodies. Serializers stay snake_case; the renderer converts.
- **All human-readable strings are French.** `error.message` is rendered straight into a toast by the frontend. Wrap messages in `gettext_lazy as _`.
- **`LANGUAGE_CODE = "fr-fr"`, `TIME_ZONE = "UTC"`, `USE_TZ = True`, `USE_I18N = True`.**
- **Money is never touched in this sub-project.** No decimal or float arithmetic appears anywhere here.
- **TDD.** Write the failing test, watch it fail, implement, watch it pass, commit. Never write implementation before its test.
- **Commit after every task**, using the message given in the task's final step.
- **Nullable text fields are `null=True`, never `blank=""` as the stored value.** The frontend's types promise `string | null`. Serializers must emit `null`, not `""`.
- **`python manage.py check` must pass** at the end of every task.
- **Never return a traceback in a response**, regardless of `DEBUG`.

## Verified Environment Facts

These were confirmed by running the libraries at the installed versions. Do not re-derive them; do not assume the opposite.

1. `camelize()` recurses into nested dicts, so `{"field_errors": {"full_name": [...]}}` renders as `{"fieldErrors": {"fullName": [...]}}` automatically. The exception handler builds snake_case keys and lets the renderer convert.
2. `camelize()` converts **per dot-separated segment**: `sale_lines.0.unit_cost` → `saleLines.0.unitCost`. This is exactly react-hook-form's array path format, so flattening nested serializer errors to dotted paths is correct.
3. `underscoreize()` converts query-parameter **names** but **not values**. `ordering=-createdAt` survives as `-createdAt`. **Ordering values must be translated by hand** — this is the single silent-failure risk the spec names.
4. `underscoreize()` accepts a `QueryDict` and returns a mutable `QueryDict`, so `.setlist()` works on the result.
5. Parser classes are `CamelCaseJSONParser`, `CamelCaseFormParser`, `CamelCaseMultiPartParser`. Renderers are `CamelCaseJSONRenderer`, `CamelCaseBrowsableAPIRenderer`.
6. pytest 9.1.1 and pytest-django 4.12.0 work together on this Python 3.13 environment.
7. **Django 6.0 removed positional arguments to `Model.save()`.** Overrides must be `def save(self, **kwargs)` and call `super().save(**kwargs)`.
8. `antares_dotenv.env(key, default)` **coerces types**: `"true"` → `True`, `"20"` → `20`, and **a value containing a comma becomes a list**. A single-value `ALLOWED_HOSTS=localhost` therefore returns a *string*, not a list. Always pass such values through the `_as_list()` helper in Task 1.
9. simplejwt's `RefreshToken(raw)` checks the blacklist during construction when `token_blacklist` is installed, raising `TokenError`. No manual blacklist lookup is needed.
13. **DRF downgrades `AuthenticationFailed` to 403 when a view has `authentication_classes = []`.** `handle_exception` refuses to emit a 401 without a `WWW-Authenticate` header, and with no authenticators `get_authenticate_header()` returns `None`. Confirmed: the same view returns 403 bare and 401 once `get_authenticate_header` is overridden. This bites `RefreshView`, which must keep `authentication_classes = []` so a client with a just-expired access token can still reach it.
10. **`antares_dotenv.env()` cannot find this project's `.env`.** It calls python-dotenv's `load_dotenv()` with no path; python-dotenv locates the file by walking up from the *calling frame's* file, which is `antares_dotenv/core.py` inside site-packages. Discovery therefore starts in the virtualenv and never reaches the project root, so every call returns its default. Confirmed: `find_dotenv()` called from a project file finds the `.env`, while `env("SECRET_KEY")` returns `None` against the same `.env`. Settings must call `load_dotenv(BASE_DIR / ".env")` explicitly; `env()` is then used only for its type coercion.
11. **A root `conftest.py` cannot set environment variables for settings.** pytest-django imports the settings module during `pytest_load_initial_conftests`, before the root `conftest.py` is imported. Confirmed with a settings module reading `os.environ[...]`: the run dies with `KeyError` despite a `conftest.py` that sets it. Test-time environment belongs in `stockmanager/settings_test.py`.
12. **DRF's system check imports `DEFAULT_PAGINATION_CLASS` eagerly**, unlike `EXCEPTION_HANDLER`, which resolves lazily on the first exception. Naming a not-yet-written pagination class breaks `manage.py check` immediately. It is registered in Task 3, alongside the module.

## File Structure

| Path | Responsibility |
|---|---|
| `requirements.txt` | pinned dependencies |
| `.env.example` / `.env` | configuration; `.env` is gitignored |
| `pytest.ini` | pytest + pytest-django wiring |
| `stockmanager/settings_test.py` | sets test env vars, then star-imports settings |
| `conftest.py` | shared fixtures only (Task 6) |
| `stockmanager/settings.py` | env-driven configuration, DRF/JWT/CORS wiring |
| `stockmanager/urls.py` | mounts `/api/` and `/admin/` |
| `apps/common/models.py` | `UUIDModel` abstract base |
| `apps/common/exceptions.py` | `Conflict`, `InvalidCredentials`, error-envelope handler, `flatten_errors` |
| `apps/common/pagination.py` | `StandardPagination` |
| `apps/common/filters.py` | `camel_to_snake`, `underscoreize_ordering`, `CamelCaseQueryParamsMixin` |
| `apps/common/permissions.py` | `IsOwner`, `IsManagerOrAbove`, `ReadOnlyForCashier` |
| `apps/accounts/models.py` | `User` + `UserManager`, `Site` + `SiteManager` |
| `apps/accounts/serializers.py` | user, login, refresh, site serializers |
| `apps/accounts/views.py` | auth views, `SettingsView`, `UserViewSet` |
| `apps/accounts/urls.py` | the `/api/` routes |
| `apps/accounts/admin.py` | admin registration |
| `apps/accounts/management/commands/bootstrap.py` | idempotent Site + Owner creation |
| `apps/accounts/tests/factories.py` | `SiteFactory`, `UserFactory` + role traits — **imported by all later sub-projects** |

**Task order note:** `AUTH_USER_MODEL` is *not* set in Task 1. It is set in Task 4, together with the `User` model and its initial migration, so no migration is ever generated against Django's default user. Do not add it early.

---

### Task 1: Project configuration

**Files:**
- Modify: `requirements.txt`
- Create: `.env.example`, `.env`, `pytest.ini`, `stockmanager/settings_test.py`
- Modify: `stockmanager/settings.py` (full rewrite)
- Create: `apps/__init__.py`, `apps/common/__init__.py`, `apps/common/apps.py`, `apps/accounts/__init__.py`, `apps/accounts/apps.py`
- Create: `apps/common/tests/__init__.py`, `apps/accounts/tests/__init__.py`
- Test: `apps/common/tests/test_settings.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a working `pytest` run; `apps.common` and `apps.accounts` as installed apps with labels `common` and `accounts`; settings constants `REST_FRAMEWORK`, `SIMPLE_JWT`, `LANGUAGE_CODE`.

- [ ] **Step 1: Write the failing test**

Create `apps/common/tests/test_settings.py`:

```python
"""The wire conventions are configuration, so they are asserted as configuration.

A later sub-project that swaps a renderer or loosens authentication should
fail here, loudly, rather than silently changing the contract.
"""

from django.conf import settings


def test_language_is_french():
    assert settings.LANGUAGE_CODE == "fr-fr"
    assert settings.USE_I18N is True


def test_time_is_utc_and_aware():
    assert settings.TIME_ZONE == "UTC"
    assert settings.USE_TZ is True


def test_json_is_camel_case_in_both_directions():
    renderers = settings.REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"]
    parsers = settings.REST_FRAMEWORK["DEFAULT_PARSER_CLASSES"]
    assert renderers == (
        "djangorestframework_camel_case.render.CamelCaseJSONRenderer",
    )
    assert "djangorestframework_camel_case.parser.CamelCaseJSONParser" in parsers


def test_authentication_is_jwt_only():
    """No session-auth fallback: a stale admin cookie must never authenticate
    an API call."""
    assert settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] == (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    )


def test_endpoints_require_authentication_by_default():
    assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == (
        "rest_framework.permissions.IsAuthenticated",
    )


def test_error_envelope_handler_is_installed():
    assert (
        settings.REST_FRAMEWORK["EXCEPTION_HANDLER"]
        == "apps.common.exceptions.api_exception_handler"
    )


def test_page_size_matches_the_frontend_default():
    """`services/service-utils.ts` hardcodes DEFAULT_PAGE_SIZE = 20."""
    assert settings.REST_FRAMEWORK["PAGE_SIZE"] == 20


def test_secret_key_is_not_the_scaffold_default():
    assert not settings.SECRET_KEY.startswith("django-insecure-")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest apps/common/tests/test_settings.py -v`

Expected: FAIL — pytest cannot find `pytest.ini` / `DJANGO_SETTINGS_MODULE`, or `KeyError: 'DEFAULT_RENDERER_CLASSES'`.

- [ ] **Step 3: Pin the dependencies**

Replace `requirements.txt`:

```
antares-dotenv==1.1.0
asgiref==3.12.1
Django==6.0.7
dj-database-url==3.1.2
django-cors-headers==4.9.0
djangorestframework==3.17.1
djangorestframework-camel-case==1.4.2
djangorestframework_simplejwt==5.5.1
PyJWT==2.13.0
python-dotenv==1.2.2
sqlparse==0.5.5

# Development
factory-boy==3.3.3
pytest==9.1.1
pytest-cov==7.1.0
pytest-django==4.12.0
```

Install with `python -m pip install -r requirements.txt`.

- [ ] **Step 4: Create the app package skeletons**

`apps/__init__.py`, `apps/common/__init__.py`, `apps/accounts/__init__.py`, `apps/common/tests/__init__.py`, `apps/accounts/tests/__init__.py` are all empty files.

`apps/common/apps.py`:

```python
from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.common"
    label = "common"
```

`apps/accounts/apps.py`:

```python
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
```

The explicit `label` keeps migration paths and future FK references short (`accounts.User`, not `apps.accounts.User`).

- [ ] **Step 5: Write the environment files**

`.env.example` (committed):

```
# Copy to .env and fill in. `python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"`
SECRET_KEY=replace-me
DEBUG=true
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=sqlite:///db.sqlite3
CORS_ALLOWED_ORIGINS=http://localhost:3000
ACCESS_TOKEN_LIFETIME_MINUTES=60
REFRESH_TOKEN_LIFETIME_DAYS=7
```

Create `.env` as a copy with a real generated `SECRET_KEY`. `.env` is already gitignored.

- [ ] **Step 6: Rewrite `stockmanager/settings.py`**

```python
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
    # DEFAULT_PAGINATION_CLASS is added in Task 3, when the module exists.
    # Unlike EXCEPTION_HANDLER, DRF's system check imports it eagerly, so
    # naming it here would break `manage.py check` for two whole tasks.
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
```

- [ ] **Step 7: Write the pytest wiring**

Tests must not depend on a developer's `.env` — it is gitignored, so a fresh
clone and any future CI would have none. The environment therefore has to be
set before `stockmanager/settings.py` is imported.

**A root `conftest.py` cannot do this.** pytest-django resolves
`DJANGO_SETTINGS_MODULE` and imports the settings module during
`pytest_load_initial_conftests`, which runs *before* the root `conftest.py`
is imported. Verified: a `conftest.py` setting `os.environ` still leaves
settings.py raising `KeyError` on the same variable.

A dedicated test settings module has no such ordering problem, because the
assignments and the import live in one file, in order.

`stockmanager/settings_test.py`:

```python
"""Settings for the test suite.

The environment is populated *before* `stockmanager.settings` is imported —
which is the whole point of this module. A root conftest.py cannot do this:
pytest-django imports the settings module during
`pytest_load_initial_conftests`, before conftest.py is loaded.

`setdefault` means a real environment variable still wins, so CI can point
the suite at another database without editing this file.
"""

import os

os.environ.setdefault("SECRET_KEY", "insecure-key-for-tests-only")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
# pytest-django appends "testserver" to ALLOWED_HOSTS itself; naming it here
# only produces a duplicate entry.
os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:3000")

from stockmanager.settings import *  # noqa: E402,F401,F403
```

`pytest.ini`:

```ini
[pytest]
DJANGO_SETTINGS_MODULE = stockmanager.settings_test
python_files = test_*.py
addopts = -q --strict-markers
testpaths = apps
```

No root `conftest.py` is created in this task. Task 6 creates one, for
fixtures only.

- [ ] **Step 8: Run the test to verify it passes**

Run: `python -m pytest apps/common/tests/test_settings.py -v`
Expected: 8 passed.

`test_error_envelope_handler_is_installed` passes even though `apps.common.exceptions` does not exist yet: DRF resolves `EXCEPTION_HANDLER` lazily, on the first exception, and this test only reads the settings dictionary. Task 2 creates the module before any endpoint exists, so nothing ever tries to import it in between. **Do not create a placeholder module** — a stub that raises would be dead code by the end of the next task.

- [ ] **Step 9: Verify the project checks out**

Run: `python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Configure project from environment, wire DRF conventions

Env-driven settings via antares-dotenv, camelCase renderer/parser, JWT-only
authentication, French locale, apps/ package with common and accounts
skeletons, and the pytest harness."
```

---

### Task 2: The error envelope

**Files:**
- Create: `apps/common/models.py`
- Modify: `apps/common/exceptions.py` (replaces the Task 1 placeholder)
- Test: `apps/common/tests/test_exceptions.py`

**Interfaces:**
- Consumes: settings from Task 1.
- Produces: `apps.common.models.UUIDModel` (abstract; fields `id: UUIDField` pk, `created_at`, `updated_at`); `apps.common.exceptions.Conflict` (409), `InvalidCredentials` (400, carries `field_errors`), `flatten_errors(detail, prefix="") -> dict[str, list[str]]`, `api_exception_handler(exc, context)`.

- [ ] **Step 1: Write the failing test**

Create `apps/common/tests/test_exceptions.py`:

```python
"""The error envelope is the frontend's `ApiError`.

`lib/form-errors.ts` calls `setError(field)` with each fieldErrors key
verbatim, and a key matching no mounted field renders nothing anywhere — so
the keys are as much a part of the contract as the status code.
"""

import pytest
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework.test import APIRequestFactory

from apps.common.exceptions import (
    Conflict,
    InvalidCredentials,
    api_exception_handler,
    flatten_errors,
)


def handle(exc):
    context = {"view": None, "request": APIRequestFactory().get("/")}
    return api_exception_handler(exc, context)


# ---- flatten_errors ------------------------------------------------------


def test_flatten_keeps_a_simple_field_error():
    assert flatten_errors({"email": ["Adresse invalide."]}) == {
        "email": ["Adresse invalide."]
    }


def test_flatten_keeps_every_message_for_one_field():
    assert flatten_errors({"password": ["Trop court.", "Trop courant."]}) == {
        "password": ["Trop court.", "Trop courant."]
    }


def test_flatten_labels_a_bare_list_as_non_field_errors():
    assert flatten_errors(["Erreur globale."]) == {
        "non_field_errors": ["Erreur globale."]
    }


def test_flatten_uses_dotted_paths_for_nested_serializers():
    """react-hook-form addresses array fields as `lines.1.quantity`, and
    camelize converts per segment, so dotted paths are what RHF needs."""
    detail = {"lines": [{}, {"quantity": ["Doit être positif."]}]}
    assert flatten_errors(detail) == {"lines.1.quantity": ["Doit être positif."]}


def test_flatten_coerces_messages_to_plain_strings():
    detail = {"email": [drf_exceptions.ErrorDetail("Pris.", code="unique")]}
    result = flatten_errors(detail)
    assert result == {"email": ["Pris."]}
    assert type(result["email"][0]) is str


# ---- the envelope --------------------------------------------------------


def test_validation_error_envelope():
    response = handle(drf_exceptions.ValidationError({"email": ["Pris."]}))
    assert response.status_code == 400
    assert response.data == {
        "code": "validation_error",
        "message": "Les données envoyées sont invalides.",
        "field_errors": {"email": ["Pris."]},
    }


def test_invalid_credentials_carries_its_own_field_errors():
    response = handle(InvalidCredentials())
    assert response.status_code == 400
    assert response.data["code"] == "invalid_credentials"
    assert response.data["message"] == "Identifiants invalides."
    assert "email" in response.data["field_errors"]


def test_not_authenticated_envelope():
    response = handle(drf_exceptions.NotAuthenticated())
    assert response.status_code == 401
    assert response.data["code"] == "authentication_failed"
    assert "field_errors" not in response.data


def test_permission_denied_keeps_the_permission_class_message():
    """A permission class sets a French `message`; it must survive."""
    response = handle(drf_exceptions.PermissionDenied("Réservé au propriétaire."))
    assert response.status_code == 403
    assert response.data["code"] == "permission_denied"
    assert response.data["message"] == "Réservé au propriétaire."


def test_http404_maps_to_not_found():
    response = handle(Http404())
    assert response.status_code == 404
    assert response.data["code"] == "not_found"


def test_conflict_envelope():
    response = handle(Conflict("Dernier propriétaire."))
    assert response.status_code == 409
    assert response.data["code"] == "conflict"
    assert response.data["message"] == "Dernier propriétaire."


def test_unhandled_exception_is_a_bare_500_with_no_traceback():
    response = handle(ZeroDivisionError("division by zero"))
    assert response.status_code == 500
    assert response.data == {
        "code": "server_error",
        "message": "Une erreur interne est survenue.",
    }
    assert "division" not in str(response.data)


@pytest.mark.parametrize("debug", [True, False])
def test_unhandled_exception_hides_the_traceback_under_both_debug_settings(
    settings, debug
):
    settings.DEBUG = debug
    response = handle(ZeroDivisionError("division by zero"))
    assert response.data["code"] == "server_error"
    assert "division" not in str(response.data)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest apps/common/tests/test_exceptions.py -v`
Expected: FAIL — `ImportError: cannot import name 'Conflict'`.

- [ ] **Step 3: Write `apps/common/models.py`**

```python
from uuid import uuid4

from django.db import models


class UUIDModel(models.Model):
    """Base for every domain model in every sub-project.

    UUID primary keys because the frontend's `UUID` type says so, and because
    they let the frontend mint optimistic ids if it ever needs to.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
```

- [ ] **Step 4: Write `apps/common/exceptions.py`**

```python
"""The error envelope.

Every failure leaves this backend shaped like the frontend's `ApiError`:

    { "code": ..., "message": ..., "fieldErrors": { field: [msg, ...] } }

`field_errors` is written snake_case here; the camelCase renderer converts
the wrapper *and* the field keys inside it on the way out.
"""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from django.utils.translation import gettext_lazy as _
from rest_framework import exceptions as drf_exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class Conflict(drf_exceptions.APIException):
    status_code = 409
    default_detail = _("Cette action est en conflit avec l'état actuel des données.")
    default_code = "conflict"


class InvalidCredentials(drf_exceptions.APIException):
    """Login failure.

    Unknown email, wrong password and inactive account all raise this, with
    an identical body: distinguishing them would let an unauthenticated
    caller enumerate accounts.
    """

    status_code = 400
    default_detail = _("Identifiants invalides.")
    default_code = "invalid_credentials"
    field_errors = {"email": [_("Aucun compte ne correspond à ces identifiants.")]}


MESSAGES = {
    "validation_error": _("Les données envoyées sont invalides."),
    "authentication_failed": _("Authentification requise."),
    "permission_denied": _("Vous n'avez pas la permission d'effectuer cette action."),
    "not_found": _("Ressource introuvable."),
    "conflict": Conflict.default_detail,
    "server_error": _("Une erreur interne est survenue."),
}


def flatten_errors(detail, prefix: str = "") -> dict[str, list[str]]:
    """Flatten DRF's nested error structure to `{path: [message, ...]}`.

    Paths are dotted — `lines.1.quantity` — which is both react-hook-form's
    array-field syntax and a shape `camelize` converts segment by segment.
    """
    flat: dict[str, list[str]] = {}

    if isinstance(detail, dict):
        for key, value in detail.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            flat.update(flatten_errors(value, path))
        return flat

    if isinstance(detail, list):
        messages = [str(item) for item in detail if not isinstance(item, (dict, list))]
        if messages:
            flat[prefix or "non_field_errors"] = messages
        for index, item in enumerate(detail):
            if isinstance(item, (dict, list)):
                path = f"{prefix}.{index}" if prefix else str(index)
                flat.update(flatten_errors(item, path))
        return flat

    flat[prefix or "non_field_errors"] = [str(detail)]
    return flat


def _code_for(exc) -> str:
    if isinstance(exc, drf_exceptions.ValidationError):
        return "validation_error"
    if isinstance(
        exc, (drf_exceptions.NotAuthenticated, drf_exceptions.AuthenticationFailed)
    ):
        return "authentication_failed"
    if isinstance(exc, drf_exceptions.PermissionDenied):
        return "permission_denied"
    if isinstance(exc, (drf_exceptions.NotFound, Http404)):
        return "not_found"
    return str(getattr(exc, "default_code", None) or "server_error")


def _message_for(exc, code: str) -> str:
    # A bare-string detail is a deliberate message — a permission class's
    # `message`, or Conflict("..."). Anything structured is field detail, so
    # the envelope's message falls back to the generic one for the code.
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str):
        return str(detail)
    return str(MESSAGES.get(code, MESSAGES["server_error"]))


def api_exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        exc = drf_exceptions.ValidationError(
            exc.message_dict if hasattr(exc, "message_dict") else list(exc.messages)
        )

    response = drf_exception_handler(exc, context)

    if response is None:
        logger.error(
            "Unhandled exception in %s", context.get("view"), exc_info=exc
        )
        return Response(
            {"code": "server_error", "message": str(MESSAGES["server_error"])},
            status=500,
        )

    code = _code_for(exc)
    body = {"code": code, "message": _message_for(exc, code)}

    field_errors = None
    if isinstance(exc, drf_exceptions.ValidationError):
        field_errors = flatten_errors(exc.detail)
    elif getattr(exc, "field_errors", None):
        field_errors = {
            key: [str(message) for message in messages]
            for key, messages in exc.field_errors.items()
        }
    if field_errors:
        body["field_errors"] = field_errors

    response.data = body
    return response
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest apps/common/tests/test_exceptions.py -v`
Expected: 15 passed.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add UUID model base and the error envelope

Every failure now renders as the frontend's ApiError. Nested serializer
errors flatten to dotted react-hook-form paths, and unhandled exceptions
return a bare 500 with no traceback under any DEBUG setting."
```

---

### Task 3: Pagination and camelCase query parameters

**Files:**
- Create: `apps/common/pagination.py`, `apps/common/filters.py`
- Modify: `stockmanager/settings.py` (register `DEFAULT_PAGINATION_CLASS`)
- Test: `apps/common/tests/test_filters.py`, `apps/common/tests/test_pagination.py`, `apps/common/tests/test_settings.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `apps.common.pagination.StandardPagination`; `apps.common.filters.camel_to_snake(str) -> str`, `underscoreize_ordering(str) -> str`, `CamelCaseQueryParamsMixin` (a view mixin overriding `initial`).

> **Why this task is tested in isolation rather than through an endpoint:** a mistranslated filter returns *unfiltered results* — a wrong answer, not an error. No status code changes, no exception is raised, and no frontend type check catches it. Every list endpoint in sub-projects 2 through 6 depends on this module.

- [ ] **Step 1: Write the failing test**

Create `apps/common/tests/test_filters.py`:

```python
"""Query-param translation.

`djangorestframework-camel-case` converts request *bodies* only. The
frontend also sends camelCase *query parameters* — `categoryId`, `pageSize`,
`dateFrom` — and camelCase *ordering values* like `-createdAt`. The library
handles the names; the values are this module's job.
"""

import pytest
from django.http import QueryDict
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.common.filters import (
    CamelCaseQueryParamsMixin,
    camel_to_snake,
    underscoreize_ordering,
)


@pytest.mark.parametrize(
    ("camel", "snake"),
    [
        ("createdAt", "created_at"),
        ("categoryId", "category_id"),
        ("stockStatus", "stock_status"),
        ("reorderThreshold", "reorder_threshold"),
        ("name", "name"),
        ("", ""),
    ],
)
def test_camel_to_snake(camel, snake):
    assert camel_to_snake(camel) == snake


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("createdAt", "created_at"),
        ("-createdAt", "-created_at"),
        ("name", "name"),
        ("-name", "-name"),
        ("-createdAt,name", "-created_at,name"),
        ("", ""),
    ],
)
def test_underscoreize_ordering(value, expected):
    """The descending marker must survive translation."""
    assert underscoreize_ordering(value) == expected


class _Probe(CamelCaseQueryParamsMixin, APIView):
    permission_classes = []
    authentication_classes = []
    seen = None

    def get(self, request):
        from rest_framework.response import Response

        type(self).seen = dict(request.query_params.items())
        return Response({})


def call(query_string):
    _Probe.seen = None
    request = APIRequestFactory().get(f"/?{query_string}")
    _Probe.as_view()(request)
    return _Probe.seen


def test_param_names_are_translated():
    assert call("categoryId=abc&pageSize=50") == {
        "category_id": "abc",
        "page_size": "50",
    }


def test_ordering_values_are_translated():
    """The library does NOT do this — it converts names, not values."""
    assert call("ordering=-createdAt")["ordering"] == "-created_at"


def test_already_snake_case_params_are_untouched():
    assert call("date_from=2026-07-01")["date_from"] == "2026-07-01"


def test_values_that_are_not_ordering_are_left_alone():
    """A search term or a status code must never be case-mangled."""
    seen = call("search=Crème&stockStatus=OUT_OF_STOCK")
    assert seen["search"] == "Crème"
    assert seen["stock_status"] == "OUT_OF_STOCK"


def test_underscoreize_returns_a_mutable_query_dict():
    """Guards the assumption `CamelCaseQueryParamsMixin` relies on."""
    from djangorestframework_camel_case.util import underscoreize

    result = underscoreize(QueryDict("a=1").copy())
    result.setlist("b", ["2"])  # must not raise
    assert result["b"] == "2"
```

Create `apps/common/tests/test_pagination.py`:

```python
"""The envelope is exactly { count, next, previous, results }."""

from rest_framework.test import APIRequestFactory

from apps.common.pagination import StandardPagination


def paginate(query_string, items):
    paginator = StandardPagination()
    request_factory = APIRequestFactory()
    from rest_framework.request import Request

    request = Request(request_factory.get(f"/?{query_string}"))
    page = paginator.paginate_queryset(items, request)
    return paginator, page


def test_default_page_size_matches_the_frontend():
    _, page = paginate("", list(range(100)))
    assert len(page) == 20


def test_page_size_param_in_snake_case():
    _, page = paginate("page_size=5", list(range(100)))
    assert len(page) == 5


def test_page_size_param_in_camel_case():
    """Works even on a view that forgot CamelCaseQueryParamsMixin."""
    _, page = paginate("pageSize=5", list(range(100)))
    assert len(page) == 5


def test_page_size_is_capped():
    _, page = paginate("pageSize=5000", list(range(1000)))
    assert len(page) == 500


def test_the_cap_admits_the_largest_page_the_frontend_asks_for():
    """`pageSize: 500` appears in three frontend components that need every
    active article at once. Capping below it truncates silently."""
    _, page = paginate("pageSize=500", list(range(1000)))
    assert len(page) == 500


def test_nonsense_page_size_falls_back_to_the_default():
    _, page = paginate("pageSize=abc", list(range(100)))
    assert len(page) == 20


def test_envelope_shape():
    paginator, page = paginate("", list(range(100)))
    body = paginator.get_paginated_response(page).data
    assert set(body) == {"count", "next", "previous", "results"}
    assert body["count"] == 100
    assert body["previous"] is None
    assert body["next"].startswith("http")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest apps/common/tests/test_filters.py apps/common/tests/test_pagination.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.common.filters'`.

- [ ] **Step 3: Write `apps/common/filters.py`**

```python
"""camelCase query parameters.

`djangorestframework-camel-case` converts request and response *bodies*. It
does not touch the query string, and it does not touch parameter *values* —
so `ordering=-createdAt` arrives untranslated and would silently sort by
nothing at all. Both halves are handled here.
"""

import re

from djangorestframework_camel_case.util import underscoreize

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])([A-Z])")


def camel_to_snake(value: str) -> str:
    return _CAMEL_BOUNDARY.sub(r"_\1", value).lower()


def underscoreize_ordering(value: str) -> str:
    """Translate a DRF ordering value, preserving the `-` descending marker."""
    fields = []
    for raw in value.split(","):
        field = raw.strip()
        if not field:
            continue
        if field.startswith("-"):
            fields.append("-" + camel_to_snake(field[1:]))
        else:
            fields.append(camel_to_snake(field))
    return ",".join(fields)


class CamelCaseQueryParamsMixin:
    """Rewrite the query string to snake_case before any filtering runs.

    Mix into any view with query parameters. Rewriting `request._request.GET`
    rather than intercepting each filter backend means pagination, search,
    ordering and every future filter see the translated names without
    knowing this mixin exists.
    """

    ordering_query_param = "ordering"

    def initial(self, request, *args, **kwargs):
        params = underscoreize(request.query_params.copy())
        if self.ordering_query_param in params:
            params.setlist(
                self.ordering_query_param,
                [
                    underscoreize_ordering(value)
                    for value in params.getlist(self.ordering_query_param)
                ],
            )
        request._request.GET = params
        super().initial(request, *args, **kwargs)
```

- [ ] **Step 4: Write `apps/common/pagination.py`**

```python
from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """The frontend's `Paginated<T>`: { count, next, previous, results }.

    Both `page_size` and `pageSize` are accepted. A list view that forgets
    `CamelCaseQueryParamsMixin` would otherwise silently ignore the
    frontend's page size and always return 20 rows.
    """

    page_size = 20
    # 500, not a rounder 100: the frontend asks for `pageSize: 500` when it
    # needs every active article at once (sale-line-editor, sale-totals-footer,
    # movement-form-dialog) and 200 for category/supplier/customer pickers.
    # A lower cap truncates *silently* — no error, just a short `results` —
    # and sale-totals-footer then reads VAT rates from a Map built off that
    # short page, falling back to 0 for anything missing. That prints a wrong
    # tax total on a real invoice.
    max_page_size = 500
    page_size_query_param = "page_size"

    def get_page_size(self, request):
        raw = request.query_params.get(
            self.page_size_query_param
        ) or request.query_params.get("pageSize")
        if not raw:
            return self.page_size
        try:
            requested = int(raw)
        except (TypeError, ValueError):
            return self.page_size
        if requested <= 0:
            return self.page_size
        return min(requested, self.max_page_size)
```

- [ ] **Step 5: Register the pagination class**

Task 1 deliberately left `DEFAULT_PAGINATION_CLASS` out, because DRF's system
check imports it eagerly and the module did not exist yet. It does now. Add
to `REST_FRAMEWORK` in `stockmanager/settings.py`, replacing the comment that
stands in for it:

```python
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.StandardPagination",
```

Add the matching assertion to `apps/common/tests/test_settings.py`:

```python
def test_pagination_class_is_registered():
    assert (
        settings.REST_FRAMEWORK["DEFAULT_PAGINATION_CLASS"]
        == "apps.common.pagination.StandardPagination"
    )
```

Run: `python manage.py check`
Expected: no issues — this is what would have failed had Task 1 named the class early.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest apps/common/tests/ -v`
Expected: all pass (settings, exceptions, filters, pagination).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add pagination and camelCase query-param translation

The camel-case library converts bodies only, so ordering values like
-createdAt are translated by hand. Pagination accepts both pageSize and
page_size so a view that omits the mixin still honours the frontend."
```

---

### Task 4: The User model

**Files:**
- Create: `apps/accounts/models.py`, `apps/accounts/migrations/__init__.py`
- Modify: `stockmanager/settings.py` (add `AUTH_USER_MODEL`)
- Test: `apps/accounts/tests/test_user_model.py`

**Interfaces:**
- Consumes: `apps.common.models.UUIDModel`.
- Produces: `apps.accounts.models.User` with fields `id, email, full_name, role, avatar_url, is_active, is_staff, created_at, updated_at`; `User.Role` (`OWNER`/`MANAGER`/`CASHIER`); properties `is_owner`, `is_manager_or_above`; `User.objects.create_user(email, full_name, password=None, **extra)` and `create_superuser(...)`. `AUTH_USER_MODEL = "accounts.User"`.

- [ ] **Step 1: Write the failing test**

Create `apps/accounts/tests/test_user_model.py`:

```python
import pytest
from django.contrib.auth import get_user_model

User = get_user_model()

pytestmark = pytest.mark.django_db


def test_email_is_the_username_field():
    assert User.USERNAME_FIELD == "email"
    assert "full_name" in User.REQUIRED_FIELDS


def test_create_user_hashes_the_password():
    user = User.objects.create_user("a@shop.cd", "Alice Nkusi", "s3cret-pw")
    assert user.password != "s3cret-pw"
    assert user.check_password("s3cret-pw")


def test_new_users_default_to_cashier():
    user = User.objects.create_user("a@shop.cd", "Alice Nkusi", "pw")
    assert user.role == User.Role.CASHIER
    assert user.is_active is True
    assert user.is_staff is False


def test_create_superuser_is_always_an_owner():
    user = User.objects.create_superuser("o@shop.cd", "Olivier Kabila", "pw")
    assert user.role == User.Role.OWNER
    assert user.is_staff is True
    assert user.is_superuser is True


def test_email_is_stored_lowercase():
    user = User.objects.create_user("Alice@Shop.CD", "Alice Nkusi", "pw")
    assert user.email == "alice@shop.cd"


def test_email_lookup_is_case_insensitive():
    User.objects.create_user("alice@shop.cd", "Alice Nkusi", "pw")
    assert User.objects.get_by_natural_key("ALICE@SHOP.CD") is not None


def test_duplicate_email_differing_only_in_case_is_rejected():
    """Normalisation at save time is what enforces this on SQLite."""
    from django.db.utils import IntegrityError

    User.objects.create_user("alice@shop.cd", "Alice Nkusi", "pw")
    with pytest.raises(IntegrityError):
        User.objects.create_user("ALICE@SHOP.CD", "Alice Bis", "pw")


def test_create_user_requires_an_email():
    with pytest.raises(ValueError):
        User.objects.create_user("", "Alice Nkusi", "pw")


def test_create_user_requires_a_full_name():
    with pytest.raises(ValueError):
        User.objects.create_user("a@shop.cd", "", "pw")


def test_id_is_a_uuid():
    from uuid import UUID

    user = User.objects.create_user("a@shop.cd", "Alice Nkusi", "pw")
    assert isinstance(user.id, UUID)


@pytest.mark.parametrize(
    ("role", "owner", "manager_or_above"),
    [
        ("OWNER", True, True),
        ("MANAGER", False, True),
        ("CASHIER", False, False),
    ],
)
def test_role_helpers(role, owner, manager_or_above):
    user = User.objects.create_user("a@shop.cd", "Alice Nkusi", "pw", role=role)
    assert user.is_owner is owner
    assert user.is_manager_or_above is manager_or_above


def test_role_labels_are_french():
    assert str(User.Role.OWNER.label) == "Propriétaire"
    assert str(User.Role.MANAGER.label) == "Gérant"
    assert str(User.Role.CASHIER.label) == "Caissier"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest apps/accounts/tests/test_user_model.py -v`
Expected: FAIL — `apps.accounts.models` has no `User`, so `get_user_model()` still returns Django's.

- [ ] **Step 3: Write `apps/accounts/models.py`**

Create `apps/accounts/migrations/__init__.py` (empty) first, then:

```python
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import UUIDModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, full_name, password, **extra):
        if not email:
            raise ValueError(_("Une adresse e-mail est obligatoire."))
        if not full_name:
            raise ValueError(_("Un nom complet est obligatoire."))
        user = self.model(
            email=self.normalize_email(email).lower(),
            full_name=full_name,
            **extra,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, full_name, password=None, **extra):
        extra.setdefault("role", User.Role.CASHIER)
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, full_name, password, **extra)

    def create_superuser(self, email, full_name, password=None, **extra):
        extra["is_staff"] = True
        extra["is_superuser"] = True
        extra["role"] = User.Role.OWNER
        return self._create_user(email, full_name, password, **extra)

    def get_by_natural_key(self, username):
        return self.get(email__iexact=username)


class User(UUIDModel, AbstractBaseUser, PermissionsMixin):
    """Replaces django.contrib.auth.User.

    Set as AUTH_USER_MODEL in sub-project 1 because swapping it once other
    apps hold foreign keys to it is a rewrite, not a migration.
    """

    class Role(models.TextChoices):
        OWNER = "OWNER", _("Propriétaire")
        MANAGER = "MANAGER", _("Gérant")
        CASHIER = "CASHIER", _("Caissier")

    email = models.EmailField(_("adresse e-mail"), unique=True)
    full_name = models.CharField(_("nom complet"), max_length=150)
    role = models.CharField(
        _("rôle"), max_length=16, choices=Role.choices, default=Role.CASHIER
    )
    avatar_url = models.URLField(_("avatar"), max_length=500, null=True, blank=True)
    is_active = models.BooleanField(_("actif"), default=True)
    is_staff = models.BooleanField(_("accès à l'administration"), default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        verbose_name = _("utilisateur")
        verbose_name_plural = _("utilisateurs")
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name

    def save(self, **kwargs):
        # Django 6 removed positional arguments to Model.save().
        #
        # Lowercasing here is what enforces case-insensitive uniqueness: the
        # unique index is on the stored value, and SQLite has no reliable
        # functional index. A Postgres migration should add one and demote
        # this to belt-and-braces.
        self.email = self.email.strip().lower()
        super().save(**kwargs)

    @property
    def is_owner(self) -> bool:
        return self.role == self.Role.OWNER

    @property
    def is_manager_or_above(self) -> bool:
        return self.role in {self.Role.OWNER, self.Role.MANAGER}
```

- [ ] **Step 4: Point settings at the new user model**

In `stockmanager/settings.py`, immediately after `AUTH_PASSWORD_VALIDATORS`:

```python
AUTH_USER_MODEL = "accounts.User"
```

- [ ] **Step 5: Generate the migration**

Run: `python manage.py makemigrations accounts`
Expected: `Create model User` in `apps/accounts/migrations/0001_initial.py`.

- [ ] **Step 6: Run the test to verify it passes**

Run: `python -m pytest apps/accounts/tests/test_user_model.py -v`
Expected: 14 passed.

Then `python manage.py check` — expected: no issues.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add the custom User model with Owner/Manager/Cashier roles

Email is the username field, normalised to lowercase on save so
case-insensitive uniqueness holds on SQLite. Set as AUTH_USER_MODEL now
because changing it once other apps hold FKs is a rewrite."
```

---

### Task 5: The Site singleton

**Files:**
- Modify: `apps/accounts/models.py`
- Test: `apps/accounts/tests/test_site_model.py`

**Interfaces:**
- Consumes: `apps.common.models.UUIDModel`.
- Produces: `apps.accounts.models.Site` with fields `id, name, address, phone, email, tax_number, invoice_footer, is_default, created_at, updated_at`; `Site.objects.current() -> Site` raising `Site.DoesNotExist` when unconfigured. **Later sub-projects call `Site.objects.current()` instead of threading `site_id` through.**

- [ ] **Step 1: Write the failing test**

Create `apps/accounts/tests/test_site_model.py`:

```python
import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.models import Site

pytestmark = pytest.mark.django_db


def make_site(**overrides):
    values = {"name": "Alimentation Maisha", "address": "12 av. Kasa-Vubu, Goma"}
    values.update(overrides)
    return Site.objects.create(**values)


def test_current_returns_the_only_site():
    site = make_site()
    assert Site.objects.current() == site


def test_current_raises_when_unconfigured():
    """An unconfigured deployment is a server misconfiguration, and
    `manage.py bootstrap` is the fix."""
    with pytest.raises(Site.DoesNotExist):
        Site.objects.current()


def test_a_second_site_is_refused_by_the_save_guard():
    make_site()
    with pytest.raises(ValidationError):
        make_site(name="Deuxième")


def test_a_second_site_is_refused_by_the_database_too():
    """The partial unique index is the real constraint; the save guard only
    makes the failure comprehensible."""
    make_site()
    with pytest.raises(IntegrityError), transaction.atomic():
        Site.objects.bulk_create(
            [Site(name="Deuxième", address="ailleurs", is_default=True)]
        )


def test_optional_fields_default_to_null_not_blank():
    """The frontend's type promises `string | null`."""
    site = make_site()
    assert site.phone is None
    assert site.email is None
    assert site.tax_number is None
    assert site.invoice_footer is None


def test_updating_the_existing_site_is_allowed():
    site = make_site()
    site.name = "Alimentation Maisha SARL"
    site.save()
    site.refresh_from_db()
    assert site.name == "Alimentation Maisha SARL"


def test_id_is_a_uuid():
    from uuid import UUID

    assert isinstance(make_site().id, UUID)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest apps/accounts/tests/test_site_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'Site'`.

- [ ] **Step 3: Add `Site` to `apps/accounts/models.py`**

Add these imports at the top:

```python
from django.core.exceptions import ValidationError
from django.db.models import Q
```

Append to the module:

```python
class SiteManager(models.Manager):
    def current(self):
        """The single Site row.

        Later sub-projects call this rather than threading a `site_id`
        through their signatures. A `siteId` arriving from the client is
        accepted and ignored — never used to filter — so the frontend needs
        no change today and real multi-site scoping stays a migration rather
        than a rewrite.
        """
        site = self.filter(is_default=True).first() or self.order_by("created_at").first()
        if site is None:
            raise Site.DoesNotExist(_("Aucun établissement n'est configuré."))
        return site


class Site(UUIDModel):
    name = models.CharField(_("nom"), max_length=200)
    address = models.TextField(_("adresse"))
    phone = models.CharField(_("téléphone"), max_length=50, null=True, blank=True)
    email = models.EmailField(_("adresse e-mail"), null=True, blank=True)
    tax_number = models.CharField(
        _("numéro d'identification fiscale"), max_length=100, null=True, blank=True
    )
    invoice_footer = models.TextField(_("pied de facture"), null=True, blank=True)
    is_default = models.BooleanField(_("établissement par défaut"), default=True)

    objects = SiteManager()

    class Meta:
        verbose_name = _("établissement")
        verbose_name_plural = _("établissements")
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=Q(is_default=True),
                name="unique_default_site",
            )
        ]

    def __str__(self):
        return self.name

    def save(self, **kwargs):
        if self._state.adding and Site.objects.exists():
            raise ValidationError(_("Un seul établissement peut exister."))
        super().save(**kwargs)
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations accounts`
Expected: `Create model Site` in `0002_site.py`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest apps/accounts/tests/test_site_model.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add the Site singleton with current() accessor

One row per deployment, enforced by a partial unique index with a save
guard for a comprehensible error. Site.objects.current() is what later
sub-projects call instead of threading siteId through."
```

---

### Task 6: Test factories and permission classes

**Files:**
- Create: `apps/accounts/tests/factories.py`, `apps/common/permissions.py`, `conftest.py`
- Test: `apps/common/tests/test_permissions.py`

**Interfaces:**
- Consumes: `User`, `Site` from Tasks 4 and 5.
- Produces: `SiteFactory`, `UserFactory`, `OwnerFactory`, `ManagerFactory`, `CashierFactory` — **imported by every later sub-project, so treat their signatures as public**. `apps.common.permissions.IsOwner`, `IsManagerOrAbove`, `ReadOnlyForCashier`. Fixtures `api_client`, `site`, `owner`, `manager`, `cashier`, `auth_client`.

- [ ] **Step 1: Write the failing test**

Create `apps/common/tests/test_permissions.py`:

```python
"""Permission classes, exercised directly.

The endpoint-level matrix lives with the endpoints; this covers the classes
themselves, including the French denial messages that reach the user's
toast.
"""

import pytest
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.accounts.tests.factories import (
    CashierFactory,
    ManagerFactory,
    OwnerFactory,
)
from apps.common.permissions import IsManagerOrAbove, IsOwner, ReadOnlyForCashier

pytestmark = pytest.mark.django_db


def check(permission_class, user, method="get"):
    request = getattr(APIRequestFactory(), method)("/")
    request.user = user
    return permission_class().has_permission(request, APIView())


@pytest.mark.parametrize(
    ("factory", "allowed"),
    [(OwnerFactory, True), (ManagerFactory, False), (CashierFactory, False)],
)
def test_is_owner(factory, allowed):
    assert check(IsOwner, factory()) is allowed


@pytest.mark.parametrize(
    ("factory", "allowed"),
    [(OwnerFactory, True), (ManagerFactory, True), (CashierFactory, False)],
)
def test_is_manager_or_above(factory, allowed):
    assert check(IsManagerOrAbove, factory()) is allowed


@pytest.mark.parametrize("factory", [OwnerFactory, ManagerFactory, CashierFactory])
def test_read_only_for_cashier_allows_every_role_to_read(factory):
    assert check(ReadOnlyForCashier, factory(), "get") is True


@pytest.mark.parametrize(
    ("factory", "allowed"),
    [(OwnerFactory, True), (ManagerFactory, True), (CashierFactory, False)],
)
def test_read_only_for_cashier_restricts_writes(factory, allowed):
    assert check(ReadOnlyForCashier, factory(), "post") is allowed


def test_anonymous_is_denied_everywhere():
    from django.contrib.auth.models import AnonymousUser

    for permission_class in (IsOwner, IsManagerOrAbove, ReadOnlyForCashier):
        assert check(permission_class, AnonymousUser()) is False


def test_inactive_user_is_denied():
    assert check(IsOwner, OwnerFactory(is_active=False)) is False


def test_denial_messages_are_french():
    assert "propriétaire" in str(IsOwner.message).lower()
    assert str(IsManagerOrAbove.message).strip() != ""


def test_factories_produce_distinct_emails():
    """Later sub-projects create many users per test."""
    assert CashierFactory().email != CashierFactory().email
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest apps/common/tests/test_permissions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.accounts.tests.factories'`.

- [ ] **Step 3: Write `apps/accounts/tests/factories.py`**

```python
"""Shared test factories.

Every later sub-project imports these rather than rolling its own users and
site, so their signatures are effectively public. `SiteFactory` is a
`django_get_or_create` on `is_default` because only one Site may exist.
"""

import factory
from factory.django import DjangoModelFactory

from apps.accounts.models import Site, User


class SiteFactory(DjangoModelFactory):
    class Meta:
        model = Site
        django_get_or_create = ("is_default",)

    name = "Alimentation Maisha"
    address = "12 avenue Kasa-Vubu, Goma"
    phone = "+243 990 000 000"
    email = "contact@maishanimungu.com"
    tax_number = "A1234567B"
    invoice_footer = "Paiement à 30 jours."
    is_default = True


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@maishanimungu.com")
    full_name = factory.Sequence(lambda n: f"Utilisateur {n}")
    role = User.Role.CASHIER
    is_active = True

    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        if not create:
            return
        obj.set_password(extracted or "motdepasse-de-test")
        obj.save()


class OwnerFactory(UserFactory):
    role = User.Role.OWNER
    is_staff = True


class ManagerFactory(UserFactory):
    role = User.Role.MANAGER


class CashierFactory(UserFactory):
    role = User.Role.CASHIER
```

- [ ] **Step 4: Write `apps/common/permissions.py`**

```python
"""Role permissions.

DRF renders `message` as the 403's detail, and the error envelope keeps a
bare-string detail as the envelope's `message` — so these strings reach the
user's toast directly and must be French.

The full role matrix lives in the spec. Only the owner-gated rows are
enforceable in sub-project 1; the rest is implemented as its sub-project
lands.
"""

from django.utils.translation import gettext_lazy as _
from rest_framework.permissions import SAFE_METHODS, BasePermission


def _active(request) -> bool:
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.is_active)


class IsOwner(BasePermission):
    message = _("Cette action est réservée au propriétaire.")

    def has_permission(self, request, view) -> bool:
        return _active(request) and request.user.is_owner


class IsManagerOrAbove(BasePermission):
    message = _("Cette action est réservée au gérant ou au propriétaire.")

    def has_permission(self, request, view) -> bool:
        return _active(request) and request.user.is_manager_or_above


class ReadOnlyForCashier(BasePermission):
    """Everyone authenticated may read; only manager and above may write."""

    message = _("Cette action est réservée au gérant ou au propriétaire.")

    def has_permission(self, request, view) -> bool:
        if not _active(request):
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_manager_or_above
```

- [ ] **Step 5: Add the shared fixtures**

Create the root `conftest.py`. Test-time environment lives in
`stockmanager/settings_test.py`, not here — this file is fixtures only:

```python
"""Shared fixtures.

Django imports live inside the fixture bodies: this module is imported
before `django.setup()` has run.
"""

import pytest


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def site(db):
    from apps.accounts.tests.factories import SiteFactory

    return SiteFactory()


@pytest.fixture
def owner(db):
    from apps.accounts.tests.factories import OwnerFactory

    return OwnerFactory(password="motdepasse-de-test")


@pytest.fixture
def manager(db):
    from apps.accounts.tests.factories import ManagerFactory

    return ManagerFactory(password="motdepasse-de-test")


@pytest.fixture
def cashier(db):
    from apps.accounts.tests.factories import CashierFactory

    return CashierFactory(password="motdepasse-de-test")


@pytest.fixture
def auth_client(api_client):
    """Authenticate the client as any user: `auth_client(owner)`."""
    from rest_framework_simplejwt.tokens import RefreshToken

    def authenticate(user):
        token = RefreshToken.for_user(user).access_token
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return api_client

    return authenticate
```

The imports are inside the fixtures because this module is imported before Django is configured.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest apps/common/tests/test_permissions.py -v`
Expected: 15 passed.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add shared test factories and role permission classes

Factories are imported by every later sub-project, so their signatures are
public. Denial messages are French because DRF renders them as the
envelope's message, which the frontend toasts verbatim."
```

---

### Task 7: Login

**Files:**
- Create: `apps/accounts/serializers.py`, `apps/accounts/views.py`, `apps/accounts/urls.py`
- Modify: `stockmanager/urls.py`
- Test: `apps/accounts/tests/test_login.py`

**Interfaces:**
- Consumes: `User`, `Site`, `InvalidCredentials`, `Conflict`, factories, fixtures.
- Produces: `UserSerializer` (fields `id, full_name, email, avatar_url, role`), `LoginSerializer`; `POST /api/auth/login/` returning `{user, siteId, accessToken, refreshToken}`.

- [ ] **Step 1: Write the failing test**

Create `apps/accounts/tests/test_login.py`:

```python
"""Login.

Unknown email, wrong password and inactive account must be
indistinguishable: anything else lets an unauthenticated caller enumerate
accounts.
"""

import pytest

from apps.accounts.tests.factories import CashierFactory

pytestmark = pytest.mark.django_db

URL = "/api/auth/login/"


def test_login_returns_the_session(api_client, site):
    user = CashierFactory(email="alice@shop.cd", password="motdepasse-de-test")

    response = api_client.post(
        URL, {"email": "alice@shop.cd", "password": "motdepasse-de-test"}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"user", "siteId", "accessToken", "refreshToken"}
    assert body["siteId"] == str(site.id)
    assert body["accessToken"]
    assert body["refreshToken"]
    assert body["user"] == {
        "id": str(user.id),
        "fullName": user.full_name,
        "email": "alice@shop.cd",
        "avatarUrl": None,
        "role": "CASHIER",
    }


def test_the_payload_is_camel_case(api_client, site):
    CashierFactory(email="alice@shop.cd", password="motdepasse-de-test")
    response = api_client.post(
        URL, {"email": "alice@shop.cd", "password": "motdepasse-de-test"}, format="json"
    )
    body = response.json()
    assert "site_id" not in body
    assert "full_name" not in body["user"]


def test_login_is_case_insensitive_on_email(api_client, site):
    CashierFactory(email="alice@shop.cd", password="motdepasse-de-test")
    response = api_client.post(
        URL, {"email": "ALICE@SHOP.CD", "password": "motdepasse-de-test"}, format="json"
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    "credentials",
    [
        {"email": "inconnu@shop.cd", "password": "motdepasse-de-test"},
        {"email": "alice@shop.cd", "password": "mauvais-mot-de-passe"},
    ],
    ids=["unknown-email", "wrong-password"],
)
def test_failures_are_indistinguishable(api_client, site, credentials):
    CashierFactory(email="alice@shop.cd", password="motdepasse-de-test")
    response = api_client.post(URL, credentials, format="json")

    assert response.status_code == 400
    assert response.json() == {
        "code": "invalid_credentials",
        "message": "Identifiants invalides.",
        "fieldErrors": {
            "email": ["Aucun compte ne correspond à ces identifiants."]
        },
    }


def test_inactive_account_gets_the_same_response(api_client, site):
    CashierFactory(
        email="alice@shop.cd", password="motdepasse-de-test", is_active=False
    )
    response = api_client.post(
        URL, {"email": "alice@shop.cd", "password": "motdepasse-de-test"}, format="json"
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_credentials"


def test_missing_fields_are_a_validation_error(api_client, site):
    response = api_client.post(URL, {}, format="json")
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation_error"
    assert set(body["fieldErrors"]) == {"email", "password"}


def test_login_needs_no_token(api_client, site):
    """The endpoint must be reachable without credentials.

    Asserting the exact status, not merely `!= 401`: a 404 would satisfy the
    looser assertion, so the test would have passed before the endpoint
    existed.
    """
    response = api_client.post(URL, {}, format="json")
    assert response.status_code == 400


def test_login_ignores_a_malformed_authorization_header(api_client, site):
    """`authentication_classes = []` is what makes this pass: otherwise DRF
    would reject the header before the view ran."""
    CashierFactory(email="alice@shop.cd", password="motdepasse-de-test")
    api_client.credentials(HTTP_AUTHORIZATION="Bearer pas-un-jeton")
    response = api_client.post(
        URL, {"email": "alice@shop.cd", "password": "motdepasse-de-test"}, format="json"
    )
    assert response.status_code == 200


def test_login_reports_an_unconfigured_deployment(api_client):
    """No Site row: actionable 409 rather than an opaque 500."""
    CashierFactory(email="alice@shop.cd", password="motdepasse-de-test")
    response = api_client.post(
        URL, {"email": "alice@shop.cd", "password": "motdepasse-de-test"}, format="json"
    )
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    assert "bootstrap" in response.json()["message"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest apps/accounts/tests/test_login.py -v`
Expected: FAIL — 404, no URL is registered.

- [ ] **Step 3: Write `apps/accounts/serializers.py`**

```python
from rest_framework import serializers

from apps.accounts.models import User
from apps.common.exceptions import InvalidCredentials


class UserSerializer(serializers.ModelSerializer):
    """The frontend's `User`, plus `role`.

    Renders as { id, fullName, email, avatarUrl, role }.
    """

    class Meta:
        model = User
        fields = ["id", "full_name", "email", "avatar_url", "role"]
        read_only_fields = fields


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        user = User.objects.filter(email__iexact=attrs["email"].strip()).first()

        if user is None:
            # Hash anyway, so an unknown email does not return measurably
            # faster than a wrong password.
            User().set_password(attrs["password"])
            raise InvalidCredentials()

        # Evaluated unconditionally, and deliberately not inlined into the
        # condition below: `or` short-circuits, so `not user.is_active or
        # not user.check_password(...)` would skip the hash entirely for a
        # deactivated account and answer ~1e6x faster than a wrong password.
        # That difference is trivially observable and enumerates every
        # deactivated account — which is precisely what this endpoint's
        # identical error bodies exist to prevent.
        password_ok = user.check_password(attrs["password"])

        if not user.is_active or not password_ok:
            raise InvalidCredentials()

        attrs["user"] = user
        return attrs
```

- [ ] **Step 4: Write `apps/accounts/views.py`**

```python
from django.utils.translation import gettext_lazy as _
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Site
from apps.accounts.serializers import LoginSerializer, UserSerializer
from apps.common.exceptions import Conflict


def _session_payload(user) -> dict:
    try:
        site = Site.objects.current()
    except Site.DoesNotExist as exc:
        raise Conflict(
            _(
                "Aucun établissement n'est configuré. "
                "Exécutez « python manage.py bootstrap »."
            )
        ) from exc

    refresh = RefreshToken.for_user(user)
    return {
        "user": UserSerializer(user).data,
        "site_id": str(site.id),
        "access_token": str(refresh.access_token),
        "refresh_token": str(refresh),
    }


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(_session_payload(serializer.validated_data["user"]))
```

- [ ] **Step 5: Wire the URLs**

`apps/accounts/urls.py`:

```python
from django.urls import path

from apps.accounts.views import LoginView

urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="login"),
]
```

`stockmanager/urls.py`:

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.accounts.urls")),
]
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python -m pytest apps/accounts/tests/test_login.py -v`
Expected: 9 passed.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add the login endpoint

One round-trip returning user, site and both tokens. Unknown email, wrong
password and inactive account are indistinguishable, down to a dummy hash
so the timing does not leak either."
```

---

### Task 8: Refresh, logout and me

**Files:**
- Modify: `apps/accounts/serializers.py`, `apps/accounts/views.py`, `apps/accounts/urls.py`
- Test: `apps/accounts/tests/test_auth_session.py`

**Interfaces:**
- Consumes: everything from Task 7.
- Produces: `POST /api/auth/refresh/` → `{accessToken}`; `POST /api/auth/logout/` → 204; `GET /api/auth/me/` → `User`.

- [ ] **Step 1: Write the failing test**

Create `apps/accounts/tests/test_auth_session.py`:

```python
import pytest

from apps.accounts.tests.factories import CashierFactory

pytestmark = pytest.mark.django_db

LOGIN = "/api/auth/login/"
REFRESH = "/api/auth/refresh/"
LOGOUT = "/api/auth/logout/"
ME = "/api/auth/me/"


@pytest.fixture
def session(api_client, site):
    CashierFactory(email="alice@shop.cd", password="motdepasse-de-test")
    response = api_client.post(
        LOGIN, {"email": "alice@shop.cd", "password": "motdepasse-de-test"},
        format="json",
    )
    return response.json()


def bearer(api_client, token):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client


# ---- refresh -------------------------------------------------------------


def test_refresh_returns_a_new_access_token(api_client, session):
    response = api_client.post(
        REFRESH, {"refreshToken": session["refreshToken"]}, format="json"
    )
    assert response.status_code == 200
    assert set(response.json()) == {"accessToken"}
    assert response.json()["accessToken"]


def test_refresh_rejects_a_garbage_token(api_client, session):
    """401, not 403.

    Without `RefreshView.get_authenticate_header`, DRF downgrades this to
    403 while the envelope still says `authentication_failed` — a
    contradiction that would send the frontend down its permission-denied
    path instead of back to the login screen.
    """
    response = api_client.post(REFRESH, {"refreshToken": "pas-un-jeton"}, format="json")
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_failed"


def test_refresh_requires_the_field(api_client, session):
    response = api_client.post(REFRESH, {}, format="json")
    assert response.status_code == 400
    assert "refreshToken" in response.json()["fieldErrors"]


# ---- logout --------------------------------------------------------------


def test_logout_blacklists_the_refresh_token(api_client, session):
    client = bearer(api_client, session["accessToken"])
    assert (
        client.post(LOGOUT, {"refreshToken": session["refreshToken"]}, format="json").status_code
        == 204
    )

    client.credentials()
    response = client.post(
        REFRESH, {"refreshToken": session["refreshToken"]}, format="json"
    )
    assert response.status_code == 401


def test_logout_is_idempotent(api_client, session):
    client = bearer(api_client, session["accessToken"])
    payload = {"refreshToken": session["refreshToken"]}
    assert client.post(LOGOUT, payload, format="json").status_code == 204
    assert client.post(LOGOUT, payload, format="json").status_code == 204


def test_logout_tolerates_a_garbage_token(api_client, session):
    """The client's only sensible reaction either way is to drop its
    session, so a bad token is not worth an error."""
    client = bearer(api_client, session["accessToken"])
    response = client.post(LOGOUT, {"refreshToken": "pas-un-jeton"}, format="json")
    assert response.status_code == 204


def test_logout_requires_authentication(api_client, session):
    response = api_client.post(
        LOGOUT, {"refreshToken": session["refreshToken"]}, format="json"
    )
    assert response.status_code == 401


# ---- me ------------------------------------------------------------------


def test_me_returns_the_current_user(api_client, session):
    client = bearer(api_client, session["accessToken"])
    response = client.get(ME)
    assert response.status_code == 200
    assert response.json() == session["user"]


def test_me_rejects_anonymous_callers(api_client, site):
    response = api_client.get(ME)
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_failed"


def test_me_rejects_a_session_cookie(client, site):
    """JWT only — a stale admin cookie must never authenticate an API call."""
    user = CashierFactory(email="alice@shop.cd", password="motdepasse-de-test")
    client.force_login(user)
    assert client.get(ME).status_code == 401
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest apps/accounts/tests/test_auth_session.py -v`
Expected: FAIL — 404 on the new routes.

- [ ] **Step 3: Add the serializer**

Append to `apps/accounts/serializers.py`:

```python
class RefreshSerializer(serializers.Serializer):
    refresh_token = serializers.CharField()
```

- [ ] **Step 4: Add the views**

Add to the imports in `apps/accounts/views.py`:

```python
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.exceptions import TokenError

from apps.accounts.serializers import RefreshSerializer
```

Append:

```python
class RefreshView(APIView):
    # No authenticator: a client whose access token has just expired must be
    # able to reach this endpoint, and the default JWTAuthentication would
    # reject its stale Authorization header before the view ever ran.
    authentication_classes = []
    permission_classes = [AllowAny]

    def get_authenticate_header(self, request):
        """Preserve 401 on an invalid refresh token.

        DRF's `handle_exception` downgrades `AuthenticationFailed` to 403
        whenever `get_authenticate_header()` is falsy — HTTP forbids a 401
        without a `WWW-Authenticate` header, and with no authenticators there
        is nothing to generate one. The downgrade would be actively harmful
        here: the error envelope maps this exception to
        `code: "authentication_failed"`, so the response would pair that code
        with HTTP 403, and the frontend would report « pas la permission »
        instead of sending the user back to the login screen.
        """
        return 'Bearer realm="api"'

    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            # simplejwt checks the blacklist during construction, so a token
            # invalidated by logout raises here.
            refresh = RefreshToken(serializer.validated_data["refresh_token"])
        except TokenError as exc:
            raise AuthenticationFailed(
                _("Session expirée. Veuillez vous reconnecter.")
            ) from exc
        return Response({"access_token": str(refresh.access_token)})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw = request.data.get("refresh_token")
        if raw:
            try:
                RefreshToken(raw).blacklist()
            except TokenError:
                # Already blacklisted, expired or malformed. The client drops
                # its session either way, so this is not worth an error.
                pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user
```

- [ ] **Step 5: Register the routes**

`apps/accounts/urls.py`:

```python
from django.urls import path

from apps.accounts.views import LoginView, LogoutView, MeView, RefreshView

urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/refresh/", RefreshView.as_view(), name="refresh"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/me/", MeView.as_view(), name="me"),
]
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python -m pytest apps/accounts/tests/test_auth_session.py -v`
Expected: 10 passed.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add refresh, logout and me endpoints

Logout blacklists the refresh token and is idempotent. A session cookie
cannot authenticate an API call: JWT is the only authentication class."
```

---

### Task 9: Settings

**Files:**
- Modify: `apps/accounts/serializers.py`, `apps/accounts/views.py`, `apps/accounts/urls.py`
- Test: `apps/accounts/tests/test_settings_endpoint.py`

**Interfaces:**
- Consumes: `Site`, `IsOwner`, fixtures.
- Produces: `SiteSerializer`; `GET /api/settings/` (any authenticated) and `PATCH /api/settings/` (owner only), both returning the frontend's `Site`.

- [ ] **Step 1: Write the failing test**

Create `apps/accounts/tests/test_settings_endpoint.py`:

```python
"""The settings singleton — no id in the path."""

import pytest

pytestmark = pytest.mark.django_db

URL = "/api/settings/"


def test_get_returns_the_site(auth_client, site, cashier):
    response = auth_client(cashier).get(URL)
    assert response.status_code == 200
    assert response.json() == {
        "id": str(site.id),
        "name": site.name,
        "address": site.address,
        "isDefault": True,
        "phone": site.phone,
        "email": site.email,
        "taxNumber": site.tax_number,
        "invoiceFooter": site.invoice_footer,
    }


def test_any_authenticated_role_may_read(auth_client, site, owner, manager, cashier):
    for user in (owner, manager, cashier):
        assert auth_client(user).get(URL).status_code == 200


def test_anonymous_may_not_read(api_client, site):
    assert api_client.get(URL).status_code == 401


def test_owner_may_update(auth_client, site, owner):
    response = auth_client(owner).patch(
        URL,
        {"name": "Alimentation Maisha SARL", "taxNumber": "B7654321A"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Alimentation Maisha SARL"
    assert response.json()["taxNumber"] == "B7654321A"
    site.refresh_from_db()
    assert site.tax_number == "B7654321A"


@pytest.mark.parametrize("role", ["manager", "cashier"])
def test_non_owners_may_not_update(auth_client, site, request, role):
    user = request.getfixturevalue(role)
    response = auth_client(user).patch(URL, {"name": "Piraté"}, format="json")
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
    assert "propriétaire" in response.json()["message"].lower()


def test_blank_name_is_rejected(auth_client, site, owner):
    response = auth_client(owner).patch(URL, {"name": "   "}, format="json")
    assert response.status_code == 400
    assert "name" in response.json()["fieldErrors"]


def test_blank_address_is_rejected(auth_client, site, owner):
    response = auth_client(owner).patch(URL, {"address": ""}, format="json")
    assert response.status_code == 400
    assert "address" in response.json()["fieldErrors"]


def test_empty_optional_fields_become_null(auth_client, site, owner):
    """The frontend's type promises `string | null`, never `""`."""
    response = auth_client(owner).patch(
        URL, {"phone": "", "taxNumber": "", "invoiceFooter": ""}, format="json"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["phone"] is None
    assert body["taxNumber"] is None
    assert body["invoiceFooter"] is None


def test_explicit_nulls_are_accepted(auth_client, site, owner):
    response = auth_client(owner).patch(URL, {"phone": None}, format="json")
    assert response.status_code == 200
    assert response.json()["phone"] is None


def test_id_and_is_default_are_read_only(auth_client, site, owner):
    original = str(site.id)
    response = auth_client(owner).patch(
        URL, {"id": "00000000-0000-0000-0000-000000000000", "isDefault": False},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["id"] == original
    assert response.json()["isDefault"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest apps/accounts/tests/test_settings_endpoint.py -v`
Expected: FAIL — 404.

- [ ] **Step 3: Add `SiteSerializer`**

Append to `apps/accounts/serializers.py`:

```python
class SiteSerializer(serializers.ModelSerializer):
    """The frontend's `Site`.

    The optional fields accept `""` as well as `null` because the settings
    form submits every field, and an untouched input posts an empty string.
    Both normalise to `None` — the frontend's type promises `string | null`.
    """

    phone = serializers.CharField(
        max_length=50, required=False, allow_blank=True, allow_null=True
    )
    email = serializers.EmailField(
        required=False, allow_blank=True, allow_null=True
    )
    tax_number = serializers.CharField(
        max_length=100, required=False, allow_blank=True, allow_null=True
    )
    invoice_footer = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )

    OPTIONAL_FIELDS = ("phone", "email", "tax_number", "invoice_footer")

    class Meta:
        model = Site
        fields = [
            "id",
            "name",
            "address",
            "is_default",
            "phone",
            "email",
            "tax_number",
            "invoice_footer",
        ]
        read_only_fields = ["id", "is_default"]

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError(
                _("Le nom de l'établissement est obligatoire.")
            )
        return value.strip()

    def validate_address(self, value):
        if not value.strip():
            raise serializers.ValidationError(_("L'adresse est obligatoire."))
        return value.strip()

    def validate(self, attrs):
        for field in self.OPTIONAL_FIELDS:
            if field in attrs:
                value = attrs[field]
                attrs[field] = value.strip() or None if value else None
        return attrs
```

Note `allow_blank=True` on `EmailField` permits `""`, which `validate` then turns into `None`; a non-empty value is still validated as an address.

- [ ] **Step 4: Add `SettingsView`**

Add to the imports in `apps/accounts/views.py`:

```python
from rest_framework.permissions import SAFE_METHODS

from apps.accounts.serializers import SiteSerializer
from apps.common.permissions import IsOwner
```

Append:

```python
class SettingsView(APIView):
    """A singleton: no id in the path.

    Reading is open to every authenticated role because the invoice and
    receipt documents print the site's header. Writing is the owner's.
    """

    def get_permissions(self):
        if self.request.method in SAFE_METHODS:
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsOwner()]

    def get_object(self):
        try:
            return Site.objects.current()
        except Site.DoesNotExist as exc:
            raise Conflict(
                _(
                    "Aucun établissement n'est configuré. "
                    "Exécutez « python manage.py bootstrap »."
                )
            ) from exc

    def get(self, request):
        return Response(SiteSerializer(self.get_object()).data)

    def patch(self, request):
        serializer = SiteSerializer(
            self.get_object(), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
```

- [ ] **Step 5: Register the route**

Add to `urlpatterns` in `apps/accounts/urls.py`:

```python
    path("settings/", SettingsView.as_view(), name="settings"),
```

and add `SettingsView` to the import.

- [ ] **Step 6: Run the test to verify it passes**

Run: `python -m pytest apps/accounts/tests/test_settings_endpoint.py -v`
Expected: 11 passed.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add the settings singleton endpoint

Any authenticated role reads it, since the printed documents need the site
header; only the owner writes. Empty optional fields normalise to null,
never an empty string."
```

---

### Task 10: User management

**Files:**
- Modify: `apps/accounts/serializers.py`, `apps/accounts/views.py`, `apps/accounts/urls.py`
- Test: `apps/accounts/tests/test_users_endpoint.py`

**Interfaces:**
- Consumes: `User`, `IsOwner`, `Conflict`, `CamelCaseQueryParamsMixin`, `StandardPagination`, factories.
- Produces: `UserWriteSerializer`; `UserViewSet` at `/api/users/` — list, create, retrieve, partial update, destroy — owner-only, with `assert_not_last_owner`.

- [ ] **Step 1: Write the failing test**

Create `apps/accounts/tests/test_users_endpoint.py`:

```python
"""Owner-only user management, plus the last-owner guard.

Without that guard a single misclick locks every owner-only endpoint —
including the one that would undo it.
"""

import pytest

from apps.accounts.models import User
from apps.accounts.tests.factories import CashierFactory, ManagerFactory, OwnerFactory

pytestmark = pytest.mark.django_db

URL = "/api/users/"


# ---- permissions ---------------------------------------------------------


@pytest.mark.parametrize("role", ["manager", "cashier"])
def test_non_owners_are_refused(auth_client, site, request, role):
    user = request.getfixturevalue(role)
    assert auth_client(user).get(URL).status_code == 403


def test_anonymous_is_refused(api_client, site):
    assert api_client.get(URL).status_code == 401


# ---- list ----------------------------------------------------------------


def test_list_is_paginated(auth_client, site, owner):
    CashierFactory.create_batch(3)
    body = auth_client(owner).get(URL).json()
    assert set(body) == {"count", "next", "previous", "results"}
    assert body["count"] == 4


def test_list_rows_are_camel_case(auth_client, site, owner):
    row = auth_client(owner).get(URL).json()["results"][0]
    assert set(row) == {"id", "fullName", "email", "avatarUrl", "role"}


def test_list_honours_camel_case_page_size(auth_client, site, owner):
    CashierFactory.create_batch(5)
    body = auth_client(owner).get(f"{URL}?pageSize=2").json()
    assert len(body["results"]) == 2
    assert body["count"] == 6


def test_list_honours_camel_case_ordering(auth_client, site, owner):
    """End-to-end proof that ordering *values* are translated."""
    CashierFactory(full_name="Zoé Amani")
    CashierFactory(full_name="Aline Byamungu")
    names = [
        row["fullName"]
        for row in auth_client(owner).get(f"{URL}?ordering=-fullName").json()["results"]
    ]
    assert names == sorted(names, reverse=True)


def test_list_supports_search(auth_client, site, owner):
    CashierFactory(full_name="Zoé Amani")
    results = auth_client(owner).get(f"{URL}?search=Amani").json()["results"]
    assert [row["fullName"] for row in results] == ["Zoé Amani"]


# ---- create --------------------------------------------------------------


def test_owner_creates_a_user(auth_client, site, owner):
    response = auth_client(owner).post(
        URL,
        {
            "email": "nouveau@shop.cd",
            "fullName": "Nouveau Caissier",
            "password": "un-mot-de-passe-solide",
            "role": "CASHIER",
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["email"] == "nouveau@shop.cd"
    assert "password" not in response.json()
    assert User.objects.get(email="nouveau@shop.cd").check_password(
        "un-mot-de-passe-solide"
    )


def test_duplicate_email_differing_only_in_case_is_rejected(auth_client, site, owner):
    CashierFactory(email="alice@shop.cd")
    response = auth_client(owner).post(
        URL,
        {
            "email": "ALICE@SHOP.CD",
            "fullName": "Alice Bis",
            "password": "un-mot-de-passe-solide",
            "role": "CASHIER",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "email" in response.json()["fieldErrors"]


def test_weak_password_is_rejected(auth_client, site, owner):
    response = auth_client(owner).post(
        URL,
        {
            "email": "nouveau@shop.cd",
            "fullName": "Nouveau Caissier",
            "password": "1234",
            "role": "CASHIER",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "password" in response.json()["fieldErrors"]


def test_unknown_role_is_rejected(auth_client, site, owner):
    response = auth_client(owner).post(
        URL,
        {
            "email": "nouveau@shop.cd",
            "fullName": "Nouveau",
            "password": "un-mot-de-passe-solide",
            "role": "ADMIN",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "role" in response.json()["fieldErrors"]


# ---- update --------------------------------------------------------------


def test_owner_updates_a_role(auth_client, site, owner):
    target = CashierFactory()
    response = auth_client(owner).patch(
        f"{URL}{target.id}/", {"role": "MANAGER"}, format="json"
    )
    assert response.status_code == 200
    target.refresh_from_db()
    assert target.role == User.Role.MANAGER


def test_owner_changes_a_password(auth_client, site, owner):
    target = CashierFactory()
    response = auth_client(owner).patch(
        f"{URL}{target.id}/", {"password": "un-autre-mot-de-passe"}, format="json"
    )
    assert response.status_code == 200
    target.refresh_from_db()
    assert target.check_password("un-autre-mot-de-passe")


# ---- delete --------------------------------------------------------------


def test_delete_deactivates_rather_than_destroys(auth_client, site, owner):
    """Movements and sales stamp userName; the row must survive."""
    target = CashierFactory()
    assert auth_client(owner).delete(f"{URL}{target.id}/").status_code == 204
    target.refresh_from_db()
    assert target.is_active is False
    assert User.objects.filter(pk=target.pk).exists()


# ---- last-owner guard ----------------------------------------------------


def test_the_last_owner_cannot_be_deleted(auth_client, site, owner):
    response = auth_client(owner).delete(f"{URL}{owner.id}/")
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    owner.refresh_from_db()
    assert owner.is_active is True


def test_the_last_owner_cannot_be_demoted(auth_client, site, owner):
    response = auth_client(owner).patch(
        f"{URL}{owner.id}/", {"role": "MANAGER"}, format="json"
    )
    assert response.status_code == 409
    owner.refresh_from_db()
    assert owner.role == User.Role.OWNER


def test_the_last_owner_cannot_be_deactivated(auth_client, site, owner):
    response = auth_client(owner).patch(
        f"{URL}{owner.id}/", {"isActive": False}, format="json"
    )
    assert response.status_code == 409
    owner.refresh_from_db()
    assert owner.is_active is True


def test_an_owner_may_be_demoted_when_another_active_owner_remains(
    auth_client, site, owner
):
    other = OwnerFactory()
    response = auth_client(owner).patch(
        f"{URL}{other.id}/", {"role": "MANAGER"}, format="json"
    )
    assert response.status_code == 200


def test_an_inactive_owner_does_not_count_towards_the_guard(auth_client, site, owner):
    OwnerFactory(is_active=False)
    assert auth_client(owner).delete(f"{URL}{owner.id}/").status_code == 409


def test_a_manager_is_not_protected_by_the_guard(auth_client, site, owner):
    target = ManagerFactory()
    assert auth_client(owner).delete(f"{URL}{target.id}/").status_code == 204
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest apps/accounts/tests/test_users_endpoint.py -v`
Expected: FAIL — 404.

- [ ] **Step 3: Add `UserWriteSerializer`**

Add to the imports in `apps/accounts/serializers.py`:

```python
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
```

Append:

```python
class UserWriteSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = [
            "id",
            "full_name",
            "email",
            "avatar_url",
            "role",
            "is_active",
            "password",
        ]
        read_only_fields = ["id"]
        extra_kwargs = {
            "avatar_url": {"required": False, "allow_null": True},
            "email": {"required": True},
            "full_name": {"required": True},
        }

    def validate_email(self, value):
        # Case-insensitive, because that is how login resolves an account.
        existing = User.objects.filter(email__iexact=value.strip())
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError(
                _("Cette adresse e-mail est déjà utilisée.")
            )
        return value.strip().lower()

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        if not password:
            raise serializers.ValidationError(
                {"password": [_("Un mot de passe est obligatoire.")]}
            )
        return User.objects.create_user(
            email=validated_data.pop("email"),
            full_name=validated_data.pop("full_name"),
            password=password,
            **validated_data,
        )

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance

    def to_representation(self, instance):
        return UserSerializer(instance).data
```

`to_representation` delegating to `UserSerializer` keeps one read shape: a created user renders exactly like a listed one, and `password` and `is_active` never leak into a response.

Note the create/list read shape therefore omits `isActive`. That matches the frontend's `User` type, which has no such field.

- [ ] **Step 4: Add `UserViewSet`**

Add to the imports in `apps/accounts/views.py`:

```python
from rest_framework import filters, viewsets

from apps.accounts.models import User
from apps.accounts.serializers import UserWriteSerializer
from apps.common.filters import CamelCaseQueryParamsMixin
```

Append:

```python
def assert_not_last_owner(user, *, new_role=None, new_is_active=None) -> None:
    """Refuse to remove the last active owner.

    Covers deletion, deactivation and demotion, including the caller acting
    on themselves. Without it a single misclick locks every owner-only
    endpoint, leaving the Django admin as the only recovery path.
    """
    if user.role != User.Role.OWNER:
        return

    stays_owner = (new_role or user.role) == User.Role.OWNER
    stays_active = user.is_active if new_is_active is None else new_is_active
    if stays_owner and stays_active:
        return

    another_owner_remains = (
        User.objects.filter(role=User.Role.OWNER, is_active=True)
        .exclude(pk=user.pk)
        .exists()
    )
    if not another_owner_remains:
        raise Conflict(
            _("Le dernier propriétaire actif ne peut pas être retiré.")
        )


class UserViewSet(CamelCaseQueryParamsMixin, viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserWriteSerializer
    permission_classes = [IsAuthenticated, IsOwner]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["full_name", "email"]
    ordering_fields = ["full_name", "email", "role", "created_at"]
    ordering = ["full_name"]

    def perform_update(self, serializer):
        assert_not_last_owner(
            serializer.instance,
            new_role=serializer.validated_data.get("role"),
            new_is_active=serializer.validated_data.get("is_active"),
        )
        serializer.save()

    def perform_destroy(self, instance):
        # Deactivate, never destroy: movements, sales and expenses stamp
        # userId and userName, and those historical reads must keep resolving.
        assert_not_last_owner(instance, new_is_active=False)
        instance.is_active = False
        instance.save()
```

- [ ] **Step 5: Register the routes**

`apps/accounts/urls.py`:

```python
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts.views import (
    LoginView,
    LogoutView,
    MeView,
    RefreshView,
    SettingsView,
    UserViewSet,
)

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")

urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/refresh/", RefreshView.as_view(), name="refresh"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("settings/", SettingsView.as_view(), name="settings"),
    path("", include(router.urls)),
]
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python -m pytest apps/accounts/tests/test_users_endpoint.py -v`
Expected: 20 passed.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add owner-only user management with a last-owner guard

DELETE deactivates rather than destroys, because later sub-projects stamp
userName onto movements and sales. The last active owner cannot be
deleted, deactivated or demoted, including by themselves."
```

---

### Task 11: Bootstrap command, admin, and documentation

**Files:**
- Create: `apps/accounts/management/__init__.py`, `apps/accounts/management/commands/__init__.py`, `apps/accounts/management/commands/bootstrap.py`
- Create: `apps/accounts/admin.py`, `README.md`
- Test: `apps/accounts/tests/test_bootstrap.py`

**Interfaces:**
- Consumes: `User`, `Site`.
- Produces: `python manage.py bootstrap` (idempotent, accepts `--email`, `--full-name`, `--password`, `--site-name`, `--site-address`); admin registration for `User` and `Site`.

- [ ] **Step 1: Write the failing test**

Create `apps/accounts/tests/test_bootstrap.py`:

```python
import pytest
from django.core.management import call_command

from apps.accounts.models import Site, User

pytestmark = pytest.mark.django_db

ARGS = dict(
    email="proprio@shop.cd",
    full_name="Olivier Kabila",
    password="un-mot-de-passe-solide",
    site_name="Alimentation Maisha",
    site_address="12 avenue Kasa-Vubu, Goma",
)


def run(**overrides):
    call_command("bootstrap", **{**ARGS, **overrides})


def test_bootstrap_creates_a_site_and_an_owner():
    run()
    site = Site.objects.current()
    assert site.name == "Alimentation Maisha"

    owner = User.objects.get(email="proprio@shop.cd")
    assert owner.role == User.Role.OWNER
    assert owner.is_staff is True
    assert owner.check_password("un-mot-de-passe-solide")


def test_bootstrap_is_idempotent():
    run()
    run(site_name="Ignoré", email="autre@shop.cd")
    assert Site.objects.count() == 1
    assert Site.objects.current().name == "Alimentation Maisha"


def test_bootstrap_does_not_add_a_second_owner_when_one_exists():
    run()
    run(email="autre@shop.cd")
    assert User.objects.filter(role=User.Role.OWNER).count() == 1


def test_bootstrap_creates_the_owner_when_only_the_site_exists():
    Site.objects.create(name="Déjà là", address="quelque part")
    run()
    assert User.objects.filter(role=User.Role.OWNER, is_active=True).count() == 1


def test_bootstrap_rejects_a_weak_password():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        run(password="1234")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest apps/accounts/tests/test_bootstrap.py -v`
Expected: FAIL — `CommandError: Unknown command: 'bootstrap'`.

- [ ] **Step 3: Write the command**

Create the two empty `__init__.py` files, then `apps/accounts/management/commands/bootstrap.py`:

```python
"""Bring a fresh database to a working login.

Idempotent: re-running against a populated database reports what exists and
changes nothing. Exists so a fresh clone does not need the admin to get
started, and so `Site.objects.current()` never raises in a real deployment.
"""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Site, User


class Command(BaseCommand):
    help = "Create the site and the first owner account."

    def add_arguments(self, parser):
        parser.add_argument("--email")
        parser.add_argument("--full-name")
        parser.add_argument("--password")
        parser.add_argument("--site-name")
        parser.add_argument("--site-address")

    def handle(self, *args, **options):
        with transaction.atomic():
            self._ensure_site(options)
            self._ensure_owner(options)

    def _ask(self, options, key, prompt, secret=False):
        value = options.get(key)
        if value:
            return value
        if secret:
            from getpass import getpass

            value = getpass(f"{prompt} : ")
        else:
            value = input(f"{prompt} : ")
        value = value.strip()
        if not value:
            raise CommandError(f"{prompt} est obligatoire.")
        return value

    def _ensure_site(self, options):
        if Site.objects.exists():
            self.stdout.write(
                f"Établissement déjà configuré : {Site.objects.current().name}"
            )
            return
        site = Site.objects.create(
            name=self._ask(options, "site_name", "Nom de l'établissement"),
            address=self._ask(options, "site_address", "Adresse"),
        )
        self.stdout.write(self.style.SUCCESS(f"Établissement créé : {site.name}"))

    def _ensure_owner(self, options):
        if User.objects.filter(role=User.Role.OWNER, is_active=True).exists():
            self.stdout.write("Un propriétaire actif existe déjà.")
            return

        email = self._ask(options, "email", "Adresse e-mail du propriétaire")
        full_name = self._ask(options, "full_name", "Nom complet")
        password = self._ask(options, "password", "Mot de passe", secret=True)

        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc

        owner = User.objects.create_superuser(
            email=email, full_name=full_name, password=password
        )
        self.stdout.write(self.style.SUCCESS(f"Propriétaire créé : {owner.email}"))
```

- [ ] **Step 4: Write `apps/accounts/admin.py`**

```python
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Site, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "full_name", "role", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("email", "full_name")
    ordering = ("full_name",)
    readonly_fields = ("created_at", "updated_at", "last_login")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Identité"), {"fields": ("full_name", "avatar_url")}),
        (_("Rôle et accès"), {"fields": ("role", "is_active", "is_staff", "is_superuser")}),
        (_("Dates"), {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "full_name", "role", "password1", "password2"),
            },
        ),
    )


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("name", "tax_number", "phone")

    def has_add_permission(self, request):
        # One site per deployment.
        return not Site.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
```

- [ ] **Step 5: Write `README.md`**

```markdown
# StockManager — Backend

API Django/DRF de l'application de gestion de stock. Le contrat est défini
par `stockmanager-frontend` : les charges utiles sont en camelCase et les
messages d'erreur en français.

## Démarrage

```bash
python -m pip install -r requirements.txt
cp .env.example .env          # puis renseigner SECRET_KEY
python manage.py migrate
python manage.py bootstrap    # crée l'établissement et le propriétaire
python manage.py runserver
```

## Rôles

| | Propriétaire | Gérant | Caissier |
|---|---|---|---|
| Utilisateurs et rôles | oui | — | — |
| Paramètres | oui | — | — |
| Catalogue : écriture | oui | oui | — |
| Catalogue : lecture | oui | oui | oui |
| Mouvements de stock | oui | oui | — |
| Ventes et encaissements | oui | oui | oui |
| Annulation d'une vente | oui | oui | — |
| Dépenses, finances, rapports | oui | oui | — |

Seules les lignes réservées au propriétaire sont appliquées dans le
sous-projet 1 ; les autres arrivent avec leur sous-projet.

## Conventions

Toute erreur est rendue sous la forme du type `ApiError` du frontend :

```json
{ "code": "validation_error",
  "message": "Les données envoyées sont invalides.",
  "fieldErrors": { "email": ["Cette adresse e-mail est déjà utilisée."] } }
```

Les paramètres de requête sont acceptés en camelCase
(`?pageSize=50&ordering=-createdAt`) via `CamelCaseQueryParamsMixin`.
La bibliothèque camel-case ne traduit **pas** les valeurs de tri : c'est
`apps/common/filters.py` qui s'en charge.

## Tests

```bash
python -m pytest
python -m pytest --cov=apps --cov-report=term-missing
```

## Documents

- Spécifications : `docs/superpowers/specs/`
- Plans d'implémentation : `docs/superpowers/plans/`
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest apps/accounts/tests/test_bootstrap.py -v`
Expected: 5 passed.

- [ ] **Step 7: Run the whole suite and check the project**

Run: `python -m pytest -v`
Expected: every test passes — roughly 105 across settings, exceptions, filters, pagination, permissions, models, login, session, settings endpoint, users endpoint and bootstrap.

Run: `python manage.py check` — expected: no issues.
Run: `python manage.py makemigrations --check --dry-run` — expected: `No changes detected`.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Add the bootstrap command, admin registration and README

bootstrap brings a fresh database to a working login and is idempotent.
The admin refuses to add a second site or delete the existing one."
```

---

## Definition of Done

- [ ] `python -m pytest` — all pass.
- [ ] `python manage.py check` — no issues.
- [ ] `python manage.py makemigrations --check --dry-run` — no pending changes.
- [ ] A fresh clone reaches a working login via `migrate` + `bootstrap`.
- [ ] Every response body, error body and query parameter is camelCase.
- [ ] Every user-facing message is French.
- [ ] No traceback appears in any response under either `DEBUG` setting.

## Handoff to Sub-project 2

What the catalogue sub-project inherits, and must not re-derive:

- `UUIDModel` as the base for `Category`, `Supplier` and `Article`.
- `Site.objects.current()` instead of a `site_id` parameter.
- `CamelCaseQueryParamsMixin` on **every** list view — `ArticleListParams` sends `categoryId`, `supplierId`, `isActive`, `stockStatus` and `ordering=-createdAt`.
- `StandardPagination`, already the default.
- `IsManagerOrAbove` / `ReadOnlyForCashier` for write endpoints; the role matrix in the spec is authoritative.
- `SiteFactory`, `UserFactory` and the role factories, imported rather than re-written.
- `Conflict` for refusing a delete that would orphan history — `removeCategory` and `removeSupplier` in the frontend both expect 409.

## Deliberately Not Built

Password reset, email sending, avatar upload, rate limiting, refresh-token rotation, OpenAPI schema generation, Docker, CI. None is required by any frontend screen that exists today.
