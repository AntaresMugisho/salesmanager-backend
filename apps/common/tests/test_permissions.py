"""Permission classes, exercised directly.

The endpoint-level matrix lives with the endpoints; this covers the classes
themselves, including the French denial messages that reach the user's
toast.
"""

import pytest
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.accounts.tests.factories import (
    CashierFactory,
    ManagerFactory,
    OwnerFactory,
)
from apps.common.permissions import IsManagerOrAbove, IsOwner, ReadOnlyForCashier

pytestmark = pytest.mark.django_db


def check(permission_class, user, method="get"):
    request = getattr(APIRequestFactory(), method)("/")
    request.user = user
    return permission_class().has_permission(request, APIView())


@pytest.mark.parametrize(
    ("factory", "allowed"),
    [(OwnerFactory, True), (ManagerFactory, False), (CashierFactory, False)],
)
def test_is_owner(factory, allowed):
    assert check(IsOwner, factory()) is allowed


@pytest.mark.parametrize(
    ("factory", "allowed"),
    [(OwnerFactory, True), (ManagerFactory, True), (CashierFactory, False)],
)
def test_is_manager_or_above(factory, allowed):
    assert check(IsManagerOrAbove, factory()) is allowed


@pytest.mark.parametrize("factory", [OwnerFactory, ManagerFactory, CashierFactory])
def test_read_only_for_cashier_allows_every_role_to_read(factory):
    assert check(ReadOnlyForCashier, factory(), "get") is True


@pytest.mark.parametrize(
    ("factory", "allowed"),
    [(OwnerFactory, True), (ManagerFactory, True), (CashierFactory, False)],
)
def test_read_only_for_cashier_restricts_writes(factory, allowed):
    assert check(ReadOnlyForCashier, factory(), "post") is allowed


def test_anonymous_is_denied_everywhere():
    from django.contrib.auth.models import AnonymousUser

    for permission_class in (IsOwner, IsManagerOrAbove, ReadOnlyForCashier):
        assert check(permission_class, AnonymousUser()) is False


def test_inactive_user_is_denied():
    assert check(IsOwner, OwnerFactory(is_active=False)) is False


def test_denial_messages_are_french():
    assert "propriétaire" in str(IsOwner.message).lower()
    assert str(IsManagerOrAbove.message).strip() != ""


def test_factories_produce_distinct_emails():
    """Later sub-projects create many users per test."""
    assert CashierFactory().email != CashierFactory().email
