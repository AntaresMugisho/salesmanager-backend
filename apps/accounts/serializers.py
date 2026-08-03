from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounts.models import Site, User
from apps.common.exceptions import InvalidCredentials


class UserSerializer(serializers.ModelSerializer):
    """The frontend's `User`, plus `role`.

    Renders as { id, fullName, email, avatarUrl, role }.
    """

    class Meta:
        model = User
        fields = ["id", "full_name", "email", "avatar_url", "role"]
        read_only_fields = fields


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        user = User.objects.filter(email__iexact=attrs["email"].strip()).first()

        if user is None:
            # Hash anyway, so an unknown email does not return measurably
            # faster than a wrong password.
            User().set_password(attrs["password"])
            raise InvalidCredentials()

        # Evaluated unconditionally, and deliberately not inlined into the
        # condition below: `or` short-circuits, so `not user.is_active or
        # not user.check_password(...)` would skip the hash entirely for a
        # deactivated account and answer ~1e6x faster than a wrong password.
        # That difference is trivially observable and enumerates every
        # deactivated account — which is precisely what this endpoint's
        # identical error bodies exist to prevent.
        password_ok = user.check_password(attrs["password"])

        if not user.is_active or not password_ok:
            raise InvalidCredentials()

        attrs["user"] = user
        return attrs


class RefreshSerializer(serializers.Serializer):
    refresh_token = serializers.CharField()


class SiteSerializer(serializers.ModelSerializer):
    """The frontend's `Site`.

    The optional fields accept `""` as well as `null` because the settings
    form submits every field, and an untouched input posts an empty string.
    Both normalise to `None` — the frontend's type promises `string | null`.
    """

    phone = serializers.CharField(
        max_length=50, required=False, allow_blank=True, allow_null=True
    )
    email = serializers.EmailField(
        required=False, allow_blank=True, allow_null=True
    )
    tax_number = serializers.CharField(
        max_length=100, required=False, allow_blank=True, allow_null=True
    )
    invoice_footer = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )

    OPTIONAL_FIELDS = ("phone", "email", "tax_number", "invoice_footer")

    class Meta:
        model = Site
        fields = [
            "id",
            "name",
            "address",
            "is_default",
            "phone",
            "email",
            "tax_number",
            "invoice_footer",
        ]
        read_only_fields = ["id", "is_default"]

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError(
                _("Le nom de l'établissement est obligatoire.")
            )
        return value.strip()

    def validate_address(self, value):
        if not value.strip():
            raise serializers.ValidationError(_("L'adresse est obligatoire."))
        return value.strip()

    def validate(self, attrs):
        for field in self.OPTIONAL_FIELDS:
            if field in attrs:
                value = attrs[field]
                attrs[field] = value.strip() or None if value else None
        return attrs
