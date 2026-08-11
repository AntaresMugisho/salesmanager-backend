from django.contrib import admin

from apps.catalogue.models import Article, Category, Supplier


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "description"]
    search_fields = ["name"]


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["name", "contact_name", "phone", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "contact_name", "email"]


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ["sku", "name", "category", "sale_price", "is_active"]
    list_filter = ["is_active", "unit", "category"]
    search_fields = ["sku", "name", "barcode"]
    autocomplete_fields = ["category", "supplier"]
    # Without this the admin is a hole in a rule the rest of the system now
    # enforces. On the add form the field renders empty and read-only, and
    # save() fills it — the admin wraps its changeform view in a transaction,
    # which is what next_sku needs.
    readonly_fields = ["sku"]
