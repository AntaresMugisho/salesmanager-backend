from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
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


class UserDetailSerializer(UserSerializer):
    """`UserSerializer` plus `is_active`, for the owner-only users endpoint.

    Kept separate from `UserSerializer` rather than adding the field there:
    `UserSerializer` is also the session user shape returned by
    `/auth/login/` and `/auth/me/`, where the frontend's `User` type has no
    `isActive` field and a login test asserts the exact key set.
    """

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + ["is_active"]
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


class UserWriteSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = [
            "id",
            "full_name",
            "email",
            "avatar_url",
            "role",
            "is_active",
            "password",
        ]
        read_only_fields = ["id"]
        extra_kwargs = {
            "avatar_url": {"required": False, "allow_null": True},
            "email": {"required": True},
            "full_name": {"required": True},
        }

    def validate_email(self, value):
        # Case-insensitive, because that is how login resolves an account.
        existing = User.objects.filter(email__iexact=value.strip())
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError(
                _("Cette adresse e-mail est déjà utilisée.")
            )
        return value.strip().lower()

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        if not password:
            raise serializers.ValidationError(
                {"password": [_("Un mot de passe est obligatoire.")]}
            )
        return User.objects.create_user(
            email=validated_data.pop("email"),
            full_name=validated_data.pop("full_name"),
            password=password,
            **validated_data,
        )

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance

    def to_representation(self, instance):
        return UserDetailSerializer(instance).data
