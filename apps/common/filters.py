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
