from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import SAFE_METHODS, AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Device, Site, User
from apps.accounts.serializers import (
    DeviceRegisterSerializer,
    DeviceSerializer,
    LoginSerializer,
    RefreshSerializer,
    SiteSerializer,
    UserSerializer,
    UserWriteSerializer,
)
from apps.accounts.filters import UserFilterSet
from apps.common.exceptions import Conflict
from apps.common.filters import CamelCaseQueryParamsMixin
from apps.common.permissions import IsOwner, RoleScopedPermissionMixin
from apps.common.sequences import next_device_code


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

        # simplejwt only checks the token's own signature and blacklist
        # status above -- it never loads the user. Without this, a
        # deactivated account's refresh token keeps minting valid access
        # tokens forever, even though every endpoint using those tokens
        # correctly 401s. That leaves the standard 401-refresh-retry
        # frontend interceptor looping instead of redirecting to login.
        user_id = refresh.payload.get(api_settings.USER_ID_CLAIM)
        user = User.objects.filter(**{api_settings.USER_ID_FIELD: user_id}).first()
        if user is None or not user.is_active:
            raise AuthenticationFailed(
                _("Session expirée. Veuillez vous reconnecter.")
            )

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


def assert_not_last_owner(user, *, new_role=None, new_is_active=None) -> None:
    """Refuse to remove the last active owner.

    Covers deletion, deactivation and demotion, including the caller acting
    on themselves. Without it a single misclick locks every owner-only
    endpoint, leaving the Django admin as the only recovery path.
    """
    if user.role != User.Role.OWNER:
        return

    stays_owner = (new_role or user.role) == User.Role.OWNER
    stays_active = user.is_active if new_is_active is None else new_is_active
    if stays_owner and stays_active:
        return

    another_owner_remains = (
        User.objects.filter(role=User.Role.OWNER, is_active=True)
        .exclude(pk=user.pk)
        .exists()
    )
    if not another_owner_remains:
        raise Conflict(
            _("Le dernier propriétaire actif ne peut pas être retiré.")
        )


class UserViewSet(
    RoleScopedPermissionMixin, CamelCaseQueryParamsMixin, viewsets.ModelViewSet
):
    queryset = User.objects.all()
    serializer_class = UserWriteSerializer
    # Owner-only for every action, reads included — not the catalogue map.
    # IsOwner's own _active() check already rejects an unauthenticated or
    # inactive user, so dropping IsAuthenticated changes nothing.
    default_permission = IsOwner
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_class = UserFilterSet
    search_fields = ["full_name", "email"]
    ordering_fields = ["full_name", "email", "role", "created_at"]
    ordering = ["full_name"]

    def perform_update(self, serializer):
        assert_not_last_owner(
            serializer.instance,
            new_role=serializer.validated_data.get("role"),
            new_is_active=serializer.validated_data.get("is_active"),
        )
        serializer.save()

    def perform_destroy(self, instance):
        # Deactivate, never destroy: movements, sales and expenses stamp
        # userId and userName, and those historical reads must keep resolving.
        assert_not_last_owner(instance, new_is_active=False)
        instance.is_active = False
        instance.save()


class DeviceRegisterView(APIView):
    """Assign this installation its numbering-series code.

    Idempotent on `install_id`: a device that reinstalls the app keeps its
    code, and a device that calls twice does not consume two. Any signed-in
    user may register the till they are standing at — a cashier setting up a
    new machine should not need the owner.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DeviceRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with transaction.atomic():
            device = Device.objects.filter(install_id=data["install_id"]).first()
            if device:
                device.label = data["label"]
                device.last_seen_at = timezone.now()
                device.save(update_fields=["label", "last_seen_at", "updated_at"])
                return Response(DeviceSerializer(device).data, status=200)

            device = Device.objects.create(
                install_id=data["install_id"],
                code=next_device_code(),
                label=data["label"],
                last_seen_at=timezone.now(),
            )

        return Response(DeviceSerializer(device).data, status=201)
