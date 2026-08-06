from django.contrib import admin

from apps.common.models import DocumentSequence


@admin.register(DocumentSequence)
class DocumentSequenceAdmin(admin.ModelAdmin):
    list_display = ["prefix", "year", "last_number"]
    # Visible for support, never editable: hand-editing a counter mints a
    # duplicate reference the next time a document is created.
    readonly_fields = ["prefix", "year", "last_number"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
