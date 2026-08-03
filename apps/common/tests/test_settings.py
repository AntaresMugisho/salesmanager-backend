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
