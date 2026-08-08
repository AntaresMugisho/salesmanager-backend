"""POST /api/sales/{id}/cancel/."""

import pytest

from apps.catalogue.tests.factories import ArticleFactory
from apps.sales.services import create_sale
from apps.sales.tests.factories import PaymentFactory
from apps.stock.models import StockLevel, StockMovement
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db


def stocked(site, quantity=100):
    article = ArticleFactory()
    StockLevelFactory(article=article, site=site, quantity=quantity)
    return article


def make(site, user, articles=None, quantity=2):
    articles = articles or [stocked(site)]
    return create_sale(
        lines=[
            {"article": a, "quantity": quantity, "unit_price": 5_000} for a in articles
        ],
        user=user,
        site=site,
    )


def url(sale):
    return f"/api/sales/{sale.id}/cancel/"


class TestCancel:
    def test_a_manager_can_cancel(self, auth_client, manager, site, owner):
        sale = make(site, owner)
        response = auth_client(manager).post(url(sale), {"reason": None}, format="json")

        assert response.status_code == 200
        assert response.json()["status"] == "CANCELLED"
        assert response.json()["cancelledAt"] is not None

    def test_the_reason_is_recorded(self, auth_client, manager, site, owner):
        sale = make(site, owner)
        response = auth_client(manager).post(
            url(sale), {"reason": "Erreur de saisie"}, format="json"
        )
        assert response.json()["cancelReason"] == "Erreur de saisie"

    def test_a_blank_reason_becomes_null(self, auth_client, manager, site, owner):
        sale = make(site, owner)
        response = auth_client(manager).post(url(sale), {"reason": "  "}, format="json")
        assert response.json()["cancelReason"] is None


class TestStockRestoration:
    def test_each_line_gets_a_compensating_in_return(
        self, auth_client, manager, site, owner
    ):
        """Movements are append-only, so cancelling never deletes them."""
        first, second = stocked(site), stocked(site)
        sale = make(site, owner, [first, second])

        auth_client(manager).post(url(sale), {"reason": None}, format="json")

        movements = sale.movements.all()
        assert movements.filter(type="OUT", reason="SALE").count() == 2
        assert movements.filter(type="IN", reason="RETURN").count() == 2

    def test_the_original_movements_are_untouched(
        self, auth_client, manager, site, owner
    ):
        sale = make(site, owner)
        original = sale.movements.get()

        auth_client(manager).post(url(sale), {"reason": None}, format="json")
        original.refresh_from_db()

        assert original.type == "OUT"
        assert original.reason == "SALE"

    def test_stock_returns_to_its_pre_sale_level(
        self, auth_client, manager, site, owner
    ):
        article = stocked(site, quantity=50)
        sale = make(site, owner, [article], quantity=8)
        assert StockLevel.objects.get(article=article).quantity == 42

        auth_client(manager).post(url(sale), {"reason": None}, format="json")

        assert StockLevel.objects.get(article=article).quantity == 50

    def test_the_compensating_movement_carries_the_same_sale(
        self, auth_client, manager, site, owner
    ):
        """Which is why the movement journal can link both halves to one
        document."""
        sale = make(site, owner)
        auth_client(manager).post(url(sale), {"reason": None}, format="json")

        assert sale.movements.count() == 2
        assert all(m.sale_id == sale.id for m in sale.movements.all())

    def test_the_compensating_note_defaults_to_naming_the_sale(
        self, auth_client, manager, site, owner
    ):
        sale = make(site, owner)
        auth_client(manager).post(url(sale), {"reason": None}, format="json")

        compensating = sale.movements.get(type="IN")
        assert compensating.note == f"Annulation de la vente {sale.reference}"

    def test_a_supplied_reason_becomes_the_note(self, auth_client, manager, site, owner):
        sale = make(site, owner)
        auth_client(manager).post(url(sale), {"reason": "Client parti"}, format="json")

        assert sale.movements.get(type="IN").note == "Client parti"


class TestBalance:
    def test_a_cancelled_sale_owes_nothing(self, auth_client, manager, site, owner):
        sale = make(site, owner)
        auth_client(manager).post(url(sale), {"reason": None}, format="json")

        payload = auth_client(manager).get(f"/api/sales/{sale.id}/").json()
        assert payload["balance"] == 0

    def test_money_already_received_is_not_refunded(
        self, auth_client, manager, site, owner
    ):
        """This sub-project does not move money out. The frontend reports it
        as « Remboursement dû »."""
        sale = make(site, owner)
        PaymentFactory(sale=sale, user=owner, amount=4_000)

        auth_client(manager).post(url(sale), {"reason": None}, format="json")

        payload = auth_client(manager).get(f"/api/sales/{sale.id}/").json()
        assert payload["paidAmount"] == 4_000
        assert payload["balance"] == 0
        assert len(payload["payments"]) == 1


class TestGuards:
    def test_cancelling_twice_is_rejected(self, auth_client, manager, site, owner):
        sale = make(site, owner)
        auth_client(manager).post(url(sale), {"reason": None}, format="json")

        response = auth_client(manager).post(url(sale), {"reason": None}, format="json")

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["reason"] == [
            "Cette vente est déjà annulée."
        ]

    def test_a_second_cancellation_posts_no_extra_movements(
        self, auth_client, manager, site, owner
    ):
        sale = make(site, owner)
        auth_client(manager).post(url(sale), {"reason": None}, format="json")
        before = StockMovement.objects.count()

        auth_client(manager).post(url(sale), {"reason": None}, format="json")

        assert StockMovement.objects.count() == before

    def test_a_cashier_may_not_cancel(self, auth_client, cashier, site, owner):
        sale = make(site, owner)
        response = auth_client(cashier).post(url(sale), {"reason": None}, format="json")
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"
