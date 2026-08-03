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
