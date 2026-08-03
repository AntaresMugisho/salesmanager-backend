from django.utils.translation import gettext_lazy as _
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Site
from apps.accounts.serializers import LoginSerializer, UserSerializer
from apps.common.exceptions import Conflict


def _session_payload(user) -> dict:
    try:
        site = Site.objects.current()
    except Site.DoesNotExist as exc:
        raise Conflict(
            _(
                "Aucun établissement n'est configuré. "
                "Exécutez « python manage.py bootstrap »."
            )
        ) from exc

    refresh = RefreshToken.for_user(user)
    return {
        "user": UserSerializer(user).data,
        "site_id": str(site.id),
        "access_token": str(refresh.access_token),
        "refresh_token": str(refresh),
    }


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(_session_payload(serializer.validated_data["user"]))
