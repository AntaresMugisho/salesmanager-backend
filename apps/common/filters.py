"""camelCase query parameters.

`djangorestframework-camel-case` converts request and response *bodies*. It
does not touch the query string, and it does not touch parameter *values* —
so `ordering=-createdAt` arrives untranslated and would silently sort by
nothing at all. Both halves are handled here.
"""

import re

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django_filters import rest_framework as drf_filters
from djangorestframework_camel_case.util import underscoreize
from rest_framework import serializers
from rest_framework.filters import OrderingFilter

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


_TRUE = {"true", "1"}
_FALSE = {"false", "0"}


class StrictBooleanField(forms.Field):
    # A plain text widget, because django-filter's BooleanWidget maps an
    # unrecognised value to None inside `value_from_datadict` — before any
    # field validation runs. With that widget in place `clean()` below never
    # sees "banana" and the filter silently does nothing.
    widget = forms.TextInput

    def clean(self, value):
        if value in self.empty_values:
            return None
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ValidationError(
            _("Valeur invalide : « true » ou « false » attendu."), code="invalid"
        )


class StrictBooleanFilter(drf_filters.BooleanFilter):
    """A boolean filter that rejects what it cannot parse.

    An unparseable value returns 400 rather than being dropped. A dropped
    filter returns *more* rows than the caller asked for while looking like a
    correct response, which is the worst failure mode a filter has.
    """

    field_class = StrictBooleanField

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", forms.TextInput)
        super().__init__(*args, **kwargs)


class AliasedOrderingFilter(OrderingFilter):
    """`OrderingFilter` that rejects unknown terms and maps public sort keys.

    Two departures from DRF:

    1. `remove_invalid_fields` silently *drops* an unrecognised term and falls
       back to the default ordering. Here an unknown term is a 400, matching
       how every other query parameter behaves.
    2. A view may declare `ordering_aliases = {"stock": "stock_quantity"}`, so
       the public sort key and the queryset expression can differ. DRF
       compares terms against queryset names directly and has no way to
       express this.
    """

    def remove_invalid_fields(self, queryset, fields, view, request):
        aliases = getattr(view, "ordering_aliases", {}) or {}
        valid = {
            item[0]
            for item in self.get_valid_fields(queryset, view, {"request": request})
        }
        valid |= set(aliases)

        resolved = []
        for term in fields:
            descending = term.startswith("-")
            name = term[1:] if descending else term
            if name not in valid:
                raise serializers.ValidationError(
                    {
                        self.ordering_param: [
                            _("Tri invalide : « %(field)s » n'est pas un tri autorisé.")
                            % {"field": name}
                        ]
                    }
                )
            target = aliases.get(name, name)
            resolved.append(f"-{target}" if descending else target)
        return resolved
