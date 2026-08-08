"""Range parsing for the three finance reads.

A plain function rather than a Serializer, and deliberately so. The wire keys
are `from` and `to`; `from` is a Python keyword, so it cannot be a field name,
and every rename trick (`source="from"` plus a `to_internal_value` shuffle)
puts the *declared* name in `serializer.errors` — the client would receive
`fieldErrors.start` where the form has a field called `from`, and see nothing.
Verified during planning; this shape produces the right keys by construction.
"""

from datetime import date

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers


def parse_range(query_params) -> tuple[date, date]:
    """Both bounds required and inclusive, `from` no later than `to`.

    `isValidRange` refuses an inverted range in the browser before sending, so
    one that arrives inverted is a bug worth reporting rather than silently
    swapping.
    """
    errors: dict = {}
    values: dict = {}

    for key in ("from", "to"):
        raw = query_params.get(key)
        if not raw:
            errors[key] = [_("Ce champ est obligatoire.")]
            continue
        try:
            values[key] = date.fromisoformat(raw)
        except ValueError:
            errors[key] = [_("Date invalide : format attendu AAAA-MM-JJ.")]

    if errors:
        raise serializers.ValidationError(errors)

    if values["from"] > values["to"]:
        raise serializers.ValidationError(
            {"from": [_("La date de début doit précéder la date de fin.")]}
        )

    return values["from"], values["to"]
