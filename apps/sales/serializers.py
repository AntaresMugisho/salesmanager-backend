import re
import unicodedata

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.sales.models import Customer

PHONE_PATTERN = re.compile(r"^[\d\s+().-]{6,20}$")


def french_sort_key(value: str) -> tuple[str, str]:
    """Approximate `localeCompare(fr-FR)` for sorting article names.

    Python's default sort is by code point, which puts « Épicerie » after
    « Zzz » because É is U+00C9. Stripping accents via NFKD puts it back
    beside « E », which is what a French reader expects.

    An approximation, deliberately: it does not implement CLDR tailoring, and
    names differing only by accent fall back to their original form. Full
    collation would mean PyICU, which is not worth a dependency for invoice
    line order.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return (stripped.casefold(), value)


class CustomerSerializer(serializers.ModelSerializer):
    """The frontend's `Customer`. Validation mirrors
    `features/customers/schema.ts`."""

    contact_name = serializers.CharField(
        max_length=80, required=False, allow_blank=True, allow_null=True
    )
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    phone = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )
    address = serializers.CharField(
        max_length=200, required=False, allow_blank=True, allow_null=True
    )
    tax_number = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    notes = serializers.CharField(
        max_length=500, required=False, allow_blank=True, allow_null=True
    )

    OPTIONAL_FIELDS = (
        "contact_name",
        "email",
        "phone",
        "address",
        "tax_number",
        "notes",
    )

    class Meta:
        model = Customer
        fields = [
            "id",
            "name",
            "contact_name",
            "email",
            "phone",
            "address",
            "tax_number",
            "notes",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_name(self, value):
        name = value.strip()
        if len(name) < 2:
            raise serializers.ValidationError(
                _("Le nom doit contenir au moins 2 caractères.")
            )
        if len(name) > 80:
            raise serializers.ValidationError(
                _("Le nom ne peut pas dépasser 80 caractères.")
            )
        existing = Customer.objects.filter(name__iexact=name)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError(_("Un client porte déjà ce nom."))
        return name

    def validate_phone(self, value):
        if not value or not value.strip():
            return value
        if not PHONE_PATTERN.match(value.strip()):
            raise serializers.ValidationError(_("Numéro de téléphone invalide."))
        return value

    def validate(self, attrs):
        for field in self.OPTIONAL_FIELDS:
            if field in attrs:
                value = attrs[field]
                attrs[field] = value.strip() or None if value else None
        return attrs
