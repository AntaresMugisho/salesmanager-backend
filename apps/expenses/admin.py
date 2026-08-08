from django.contrib import admin

from apps.expenses.models import Expense


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    """Editable, unlike the sales and movement admins.

    An expense is a private record that nothing references, and the API allows
    the same — so an admin that refused edits would be stricter than the thing
    it administers.
    """

    list_display = ["spent_at", "category", "label", "amount", "method", "user_name"]
    list_filter = ["category", "method"]
    search_fields = ["label", "reference", "note"]
    date_hierarchy = "spent_at"
