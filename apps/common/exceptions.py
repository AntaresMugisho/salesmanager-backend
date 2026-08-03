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
