from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import SAFE_METHODS, AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Site
from apps.accounts.serializers import (
    LoginSerializer,
    RefreshSerializer,
    SiteSerializer,
    UserSerializer,
)
from apps.common.exceptions import Conflict
from apps.common.permissions import IsOwner


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


class RefreshView(APIView):
    # No authenticator: a client whose access token has just expired must be
    # able to reach this endpoint, and the default JWTAuthentication would
    # reject its stale Authorization header before the view ever ran.
    authentication_classes = []
    permission_classes = [AllowAny]

    def get_authenticate_header(self, request):
        """Preserve 401 on an invalid refresh token.

        DRF's `handle_exception` downgrades `AuthenticationFailed` to 403
        whenever `get_authenticate_header()` is falsy — HTTP forbids a 401
        without a `WWW-Authenticate` header, and with no authenticators there
        is nothing to generate one. The downgrade would be actively harmful
        here: the error envelope maps this exception to
        `code: "authentication_failed"`, so the response would pair that code
        with HTTP 403, and the frontend would report « pas la permission »
        instead of sending the user back to the login screen.
        """
        return 'Bearer realm="api"'

    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            # simplejwt checks the blacklist during construction, so a token
            # invalidated by logout raises here.
            refresh = RefreshToken(serializer.validated_data["refresh_token"])
        except TokenError as exc:
            raise AuthenticationFailed(
                _("Session expirée. Veuillez vous reconnecter.")
            ) from exc
        return Response({"access_token": str(refresh.access_token)})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw = request.data.get("refresh_token")
        if raw:
            try:
                RefreshToken(raw).blacklist()
            except TokenError:
                # Already blacklisted, expired or malformed. The client drops
                # its session either way, so this is not worth an error.
                pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class SettingsView(APIView):
    """A singleton: no id in the path.

    Reading is open to every authenticated role because the invoice and
    receipt documents print the site's header. Writing is the owner's.
    """

    def get_permissions(self):
        if self.request.method in SAFE_METHODS:
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsOwner()]

    def get_object(self):
        try:
            return Site.objects.current()
        except Site.DoesNotExist as exc:
            raise Conflict(
                _(
                    "Aucun établissement n'est configuré. "
                    "Exécutez « python manage.py bootstrap »."
                )
            ) from exc

    def get(self, request):
        return Response(SiteSerializer(self.get_object()).data)

    def patch(self, request):
        serializer = SiteSerializer(
            self.get_object(), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
