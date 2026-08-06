from django.contrib import admin

from apps.stock.models import StockLevel, StockMovement


@admin.register(StockLevel)
class StockLevelAdmin(admin.ModelAdmin):
    list_display = ["article", "quantity", "reorder_threshold"]
    search_fields = ["article__sku", "article__name"]


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = [
        "created_at",
        "article",
        "type",
        "reason",
        "quantity",
        "quantity_before",
        "quantity_after",
        "user_name",
    ]
    list_filter = ["type", "reason"]
    search_fields = ["article__sku", "article__name", "reference"]
    # Append-only. The admin must not offer a way to rewrite the ledger.
    readonly_fields = [f.name for f in StockMovement._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
