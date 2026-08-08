"""Expense endpoints. Payload from the frontend's `Expense` type."""

import uuid
from datetime import datetime, timezone as dt_timezone

import pytest

from apps.expenses.models import Expense
from apps.expenses.tests.factories import ExpenseFactory

pytestmark = pytest.mark.django_db

LIST_URL = "/api/expenses/"


def detail_url(expense) -> str:
    return f"{LIST_URL}{expense.id}/"


def body(**overrides):
    payload = {
        "category": "RENT",
        "label": "Loyer du mois",
        "amount": 250_000,
        "method": "CASH",
        "spentAt": "2026-07-02",
        "reference": None,
        "note": None,
    }
    payload.update(overrides)
    return payload


class TestRead:
    def test_the_payload_matches_the_frontend_type(self, auth_client, manager, site):
        ExpenseFactory(site=site, user=manager, user_name=manager.full_name)

        response = auth_client(manager).get(LIST_URL)

        assert response.status_code == 200
        assert set(response.json()["results"][0]) == {
            "id",
            "siteId",
            "category",
            "label",
            "amount",
            "method",
            "spentAt",
            "reference",
            "note",
            "userId",
            "userName",
            "createdAt",
        }

    def test_newest_spend_first(self, auth_client, manager, site):
        older = ExpenseFactory(site=site, user=manager, label="Ancienne")
        newer = ExpenseFactory(site=site, user=manager, label="Récente")
        Expense.objects.filter(pk=older.pk).update(
            spent_at=datetime(2026, 7, 1, 12, tzinfo=dt_timezone.utc)
        )
        Expense.objects.filter(pk=newer.pk).update(
            spent_at=datetime(2026, 7, 5, 12, tzinfo=dt_timezone.utc)
        )

        response = auth_client(manager).get(LIST_URL)

        assert [r["label"] for r in response.json()["results"]] == [
            "Récente",
            "Ancienne",
        ]

    def test_filter_by_category(self, auth_client, manager, site):
        ExpenseFactory(site=site, user=manager, category="RENT")
        ExpenseFactory(site=site, user=manager, category="SALARY")

        response = auth_client(manager).get(f"{LIST_URL}?category=SALARY")

        assert response.json()["count"] == 1

    def test_an_invalid_category_is_400(self, auth_client, manager, site):
        response = auth_client(manager).get(f"{LIST_URL}?category=CAVIAR")
        assert response.status_code == 400
        assert "category" in response.json()["fieldErrors"]

    def test_search_covers_label_reference_and_note(self, auth_client, manager, site):
        ExpenseFactory(
            site=site, user=manager, label="Loyer", reference="REF-1", note="Juillet"
        )
        ExpenseFactory(site=site, user=manager, label="Salaires")
        client = auth_client(manager)

        assert client.get(f"{LIST_URL}?search=loyer").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=REF-1").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=juillet").json()["count"] == 1

    def test_date_bounds_use_the_shop_timezone(
        self, auth_client, manager, site, settings
    ):
        """Kinshasa is UTC+1, so 23:30 UTC is already the next local day."""
        settings.SHOP_TIME_ZONE = "Africa/Kinshasa"
        expense = ExpenseFactory(site=site, user=manager)
        Expense.objects.filter(pk=expense.pk).update(
            spent_at=datetime(2026, 7, 1, 23, 30, tzinfo=dt_timezone.utc)
        )

        client = auth_client(manager)
        assert client.get(f"{LIST_URL}?dateFrom=2026-07-02").json()["count"] == 1
        assert client.get(f"{LIST_URL}?dateTo=2026-07-01").json()["count"] == 0


class TestWrite:
    def test_a_manager_can_create(self, auth_client, manager, site):
        response = auth_client(manager).post(LIST_URL, body(), format="json")

        assert response.status_code == 201
        assert response.json()["label"] == "Loyer du mois"
        assert response.json()["amount"] == 250_000
        assert response.json()["userName"] == manager.full_name

    def test_spent_at_is_widened_to_local_noon(
        self, auth_client, manager, site, settings
    ):
        """Noon so that neither a positive nor a negative offset can push the
        instant onto the adjacent day — the very boundary reports slice at."""
        settings.SHOP_TIME_ZONE = "Africa/Kinshasa"

        auth_client(manager).post(LIST_URL, body(spentAt="2026-07-02"), format="json")

        assert Expense.objects.get().spent_at == datetime(
            2026, 7, 2, 11, 0, tzinfo=dt_timezone.utc
        )

    def test_spent_at_lands_on_the_picked_day_west_of_greenwich(
        self, auth_client, manager, site, settings
    ):
        """The bug a DateTimeField parse would have introduced: midnight UTC
        read in a negative offset is the previous day."""
        settings.SHOP_TIME_ZONE = "America/Bogota"

        auth_client(manager).post(LIST_URL, body(spentAt="2026-07-02"), format="json")

        from zoneinfo import ZoneInfo

        stored = Expense.objects.get().spent_at
        assert stored.astimezone(ZoneInfo("America/Bogota")).date().isoformat() == (
            "2026-07-02"
        )

    def test_blank_optionals_become_null(self, auth_client, manager, site):
        response = auth_client(manager).post(
            LIST_URL, body(reference="", note="  "), format="json"
        )
        assert response.json()["reference"] is None
        assert response.json()["note"] is None

    def test_an_expense_can_be_edited(self, auth_client, manager, site):
        """Unlike a sale. An expense is a private record, not a document
        issued to anyone."""
        expense = ExpenseFactory(site=site, user=manager, amount=1_000)

        response = auth_client(manager).patch(
            detail_url(expense), {"amount": 2_000}, format="json"
        )

        assert response.status_code == 200
        expense.refresh_from_db()
        assert expense.amount == 2_000

    def test_an_expense_can_be_deleted(self, auth_client, manager, site):
        """`removeExpense`: nothing references an expense, so unlike a
        customer this deletes outright."""
        expense = ExpenseFactory(site=site, user=manager)

        assert auth_client(manager).delete(detail_url(expense)).status_code == 204
        assert Expense.objects.count() == 0

    def test_unknown_id_is_404_with_the_envelope(self, auth_client, manager, site):
        response = auth_client(manager).get(f"{LIST_URL}{uuid.uuid4()}/")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"


class TestValidation:
    @pytest.mark.parametrize("amount", [0, -1])
    def test_a_non_positive_amount_is_rejected(
        self, auth_client, manager, site, amount
    ):
        response = auth_client(manager).post(
            LIST_URL, body(amount=amount), format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["amount"] == [
            "Le montant doit être supérieur à zéro."
        ]

    def test_a_short_label_is_rejected(self, auth_client, manager, site):
        response = auth_client(manager).post(LIST_URL, body(label="X"), format="json")
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["label"] == [
            "Le libellé doit contenir au moins 2 caractères."
        ]

    def test_an_over_long_label_is_rejected(self, auth_client, manager, site):
        response = auth_client(manager).post(
            LIST_URL, body(label="X" * 121), format="json"
        )
        assert response.status_code == 400
        assert "label" in response.json()["fieldErrors"]

    def test_a_future_date_is_rejected(self, auth_client, manager, site):
        from datetime import timedelta

        from apps.common.dates import shop_today

        tomorrow = shop_today() + timedelta(days=1)
        response = auth_client(manager).post(
            LIST_URL, body(spentAt=tomorrow.isoformat()), format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["spentAt"] == [
            "La date ne peut pas être dans le futur."
        ]

    def test_today_is_accepted_at_any_hour(self, auth_client, manager, site):
        """'An expense dated today is fine at any hour' — the comparison is on
        calendar days, not instants."""
        from apps.common.dates import shop_today

        response = auth_client(manager).post(
            LIST_URL, body(spentAt=shop_today().isoformat()), format="json"
        )
        assert response.status_code == 201

    def test_an_invalid_method_is_rejected(self, auth_client, manager, site):
        response = auth_client(manager).post(
            LIST_URL, body(method="BITCOIN"), format="json"
        )
        assert response.status_code == 400
        assert "method" in response.json()["fieldErrors"]


class TestPermissions:
    @pytest.mark.parametrize("method", ["get", "post", "patch", "delete"])
    def test_a_cashier_is_refused_everything(
        self, auth_client, cashier, manager, site, method
    ):
        """Expenses are manager-and-above for reads too — not the catalogue
        map, where a cashier may read."""
        expense = ExpenseFactory(site=site, user=manager)
        client = auth_client(cashier)
        url = LIST_URL if method in ("get", "post") else detail_url(expense)

        response = getattr(client, method)(url, {}, format="json")

        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"

    def test_an_owner_may_do_everything(self, auth_client, owner, site):
        assert (
            auth_client(owner).post(LIST_URL, body(), format="json").status_code == 201
        )
