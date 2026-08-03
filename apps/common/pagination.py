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
