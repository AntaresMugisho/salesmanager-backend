from rest_framework import serializers

from apps.accounts.models import User
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
