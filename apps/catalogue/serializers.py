import re

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.catalogue.models import Category, Supplier

PHONE_PATTERN = re.compile(r"^[\d\s+().-]{6,20}$")


class CategorySerializer(serializers.ModelSerializer):
    """The frontend's `Category`.

    `articleCount` is annotated by the queryset, never stored — see
    `CategoryViewSet.get_queryset`.
    """

    description = serializers.CharField(
        max_length=200, required=False, allow_blank=True, allow_null=True
    )
    article_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = ["id", "name", "description", "article_count"]
        read_only_fields = ["id"]

    def validate_name(self, value):
        name = value.strip()
        if len(name) < 2:
            raise serializers.ValidationError(
                _("Le nom doit contenir au moins 2 caractères.")
            )
        if len(name) > 60:
            raise serializers.ValidationError(
                _("Le nom ne peut pas dépasser 60 caractères.")
            )
        # Case-insensitive, matching the frontend's
        # `toLocaleLowerCase("fr-FR")` comparison. A functional unique index
        # backs this up under a race; this is what produces the message.
        existing = Category.objects.filter(name__iexact=name)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError(_("Une catégorie porte déjà ce nom."))
        return name

    def validate(self, attrs):
        if "description" in attrs:
            value = attrs["description"]
            attrs["description"] = value.strip() or None if value else None
        return attrs


class SupplierSerializer(serializers.ModelSerializer):
    """The frontend's `Supplier`. Validation mirrors
    `features/suppliers/schema.ts`."""

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
    notes = serializers.CharField(
        max_length=500, required=False, allow_blank=True, allow_null=True
    )

    OPTIONAL_FIELDS = ("contact_name", "email", "phone", "address", "notes")

    class Meta:
        model = Supplier
        fields = [
            "id",
            "name",
            "contact_name",
            "email",
            "phone",
            "address",
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
        existing = Supplier.objects.filter(name__iexact=name)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError(_("Un fournisseur porte déjà ce nom."))
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
