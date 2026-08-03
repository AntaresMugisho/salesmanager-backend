"""Shared fixtures.

Django imports live inside the fixture bodies: this module is imported
before `django.setup()` has run.
"""

import pytest


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def site(db):
    from apps.accounts.tests.factories import SiteFactory

    return SiteFactory()


@pytest.fixture
def owner(db):
    from apps.accounts.tests.factories import OwnerFactory

    return OwnerFactory(password="motdepasse-de-test")


@pytest.fixture
def manager(db):
    from apps.accounts.tests.factories import ManagerFactory

    return ManagerFactory(password="motdepasse-de-test")


@pytest.fixture
def cashier(db):
    from apps.accounts.tests.factories import CashierFactory

    return CashierFactory(password="motdepasse-de-test")


@pytest.fixture
def auth_client(api_client):
    """Authenticate the client as any user: `auth_client(owner)`."""
    from rest_framework_simplejwt.tokens import RefreshToken

    def authenticate(user):
        token = RefreshToken.for_user(user).access_token
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return api_client

    return authenticate
