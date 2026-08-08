from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.common.dates import at_local_noon, shop_today
from apps.expenses.models import Expense
from apps.sales.models import Payment


class SpentAtField(serializers.DateTimeField):
    """Reads as an ISO instant, writes as a bare calendar date.

    The contract is asymmetric on purpose: `Expense.spentAt` is an
    `ISODateTime`, but `ExpenseCreateDto.spentAt` is "2026-07-30" from a date
    picker. Reading the input through a DateField rather than a DateTimeField
    is not a style choice — `DateTimeField("2026-07-02")` yields midnight UTC,
    and `.astimezone(shop).date()` on that is the *previous* day for any shop
    west of Greenwich. Parsing a date involves no timezone at all, and
    `at_local_noon` then puts it on the right instant for any offset.
    """

    def to_internal_value(self, data):
        day = serializers.DateField().to_internal_value(data)
        # Calendar-day comparison: an expense dated today is fine at any hour.
        if day > shop_today():
            raise serializers.ValidationError(
                _("La date ne peut pas être dans le futur.")
            )
        return at_local_noon(day)


class ExpenseSerializer(serializers.ModelSerializer):
    """The frontend's `Expense`."""

    site_id = serializers.UUIDField(read_only=True)
    user_id = serializers.UUIDField(read_only=True)
    spent_at = SpentAtField()
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    reference = serializers.CharField(
        max_length=40, required=False, allow_blank=True, allow_null=True
    )
    note = serializers.CharField(
        max_length=500, required=False, allow_blank=True, allow_null=True
    )
    amount = serializers.IntegerField(
        min_value=1,
        error_messages={
            "min_value": _("Le montant doit être supérieur à zéro."),
            "invalid": _("Le montant doit être supérieur à zéro."),
        },
    )

    OPTIONAL_FIELDS = ("reference", "note")

    class Meta:
        model = Expense
        fields = [
            "id",
            "site_id",
            "category",
            "label",
            "amount",
            "method",
            "spent_at",
            "reference",
            "note",
            "user_id",
            "user_name",
            "created_at",
        ]
        read_only_fields = ["id", "site_id", "user_id", "user_name", "created_at"]

    def validate_label(self, value):
        label = value.strip()
        if len(label) < 2:
            raise serializers.ValidationError(
                _("Le libellé doit contenir au moins 2 caractères.")
            )
        if len(label) > 120:
            raise serializers.ValidationError(
                _("Le libellé ne peut pas dépasser 120 caractères.")
            )
        return label

    def validate(self, attrs):
        for field in self.OPTIONAL_FIELDS:
            if field in attrs:
                value = attrs[field]
                attrs[field] = value.strip() or None if value else None
        return attrs
