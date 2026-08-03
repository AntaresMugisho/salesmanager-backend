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

        if not user.is_active or not user.check_password(attrs["password"]):
            raise InvalidCredentials()

        attrs["user"] = user
        return attrs
