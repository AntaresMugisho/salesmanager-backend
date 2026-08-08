from django.contrib import admin

from apps.sales.models import Customer, Payment, Sale, SaleLine


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["name", "contact_name", "phone", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "contact_name", "email"]


class SaleLineInline(admin.TabularInline):
    model = SaleLine
    extra = 0
    readonly_fields = [f.name for f in SaleLine._meta.fields]
    can_delete = False


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = [
        "reference",
        "created_at",
        "customer_name",
        "status",
        "total",
        "user_name",
    ]
    list_filter = ["status"]
    search_fields = ["reference", "customer_name", "note"]
    inlines = [SaleLineInline]
    # An issued invoice is not editable from the admin. Cancellation is an API
    # action with stock consequences; doing it here would change a status
    # without giving the stock back.
    readonly_fields = [f.name for f in Sale._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["sale", "paid_at", "amount", "method", "user_name"]
    list_filter = ["method"]
    search_fields = ["sale__reference", "reference"]
    readonly_fields = [f.name for f in Payment._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
