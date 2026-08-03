from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Site, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "full_name", "role", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("email", "full_name")
    ordering = ("full_name",)
    readonly_fields = ("created_at", "updated_at", "last_login")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Identité"), {"fields": ("full_name", "avatar_url")}),
        (_("Rôle et accès"), {"fields": ("role", "is_active", "is_staff", "is_superuser")}),
        (_("Dates"), {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "full_name", "role", "password1", "password2"),
            },
        ),
    )


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("name", "tax_number", "phone")

    def has_add_permission(self, request):
        # One site per deployment.
        return not Site.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
