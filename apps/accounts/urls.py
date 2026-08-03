from django.urls import path

from apps.accounts.views import (
    LoginView,
    LogoutView,
    MeView,
    RefreshView,
    SettingsView,
)

urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/refresh/", RefreshView.as_view(), name="refresh"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("settings/", SettingsView.as_view(), name="settings"),
]
