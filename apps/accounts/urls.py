from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts.views import (
    DeviceRegisterView,
    LoginView,
    LogoutView,
    MeView,
    RefreshView,
    SettingsView,
    UserViewSet,
)

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")

urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/refresh/", RefreshView.as_view(), name="refresh"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("settings/", SettingsView.as_view(), name="settings"),
    path("devices/register/", DeviceRegisterView.as_view(), name="device-register"),
    path("", include(router.urls)),
]
