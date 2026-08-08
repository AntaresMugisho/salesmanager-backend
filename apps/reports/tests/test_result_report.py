"""The compte de résultat.

Deliberately thin: every figure is already computed and tested in
`apps.finance.aggregate`. These tests therefore check the *wiring* — that the
range reaches the fold, that the meta block is right, and that the figures
equal what /finances/summary/ returns for the same period — rather than
re-testing the arithmetic.
"""

import pytest

from apps.expenses.tests.factories import ExpenseFactory
from apps.reports.tests.support import PARAMS, at, dated
from apps.sales.models import Sale
from apps.sales.tests.factories import PaymentFactory, SaleLineFactory

pytestmark = pytest.mark.django_db

URL = "/api/reports/result/"


class TestPermissions:
    def test_a_cashier_is_refused(self, auth_client, cashier, site):
        assert auth_client(cashier).get(URL, PARAMS).status_code == 403

    def test_anonymous_is_refused(self, api_client, site):
        assert api_client.get(URL, PARAMS).status_code == 401

    def test_a_manager_is_allowed(self, auth_client, manager, site):
        assert auth_client(manager).get(URL, PARAMS).status_code == 200

    def test_an_owner_is_allowed(self, auth_client, owner, site):
        assert auth_client(owner).get(URL, PARAMS).status_code == 200


class TestTheRange:
    """`parse_range` is reused from apps.finance, so these tests exist to prove
    the reuse is wired, not to re-test the parser."""

    def test_both_bounds_are_required(self, auth_client, manager, site):
        response = auth_client(manager).get(URL)
        assert response.status_code == 400
        # The project's exception handler wraps field errors in `fieldErrors`;
        # `parse_range` supplies the keys inside it.
        assert response.json()["fieldErrors"] == {
            "from": ["Ce champ est obligatoire."],
            "to": ["Ce champ est obligatoire."],
        }

    def test_an_inverted_range_is_refused(self, auth_client, manager, site):
        response = auth_client(manager).get(
            URL, {"from": "2026-07-31", "to": "2026-07-01"}
        )
        assert response.status_code == 400
        assert "from" in response.json()["fieldErrors"]

    def test_a_malformed_date_is_refused(self, auth_client, manager, site):
        response = auth_client(manager).get(
            URL, {"from": "31/07/2026", "to": "2026-07-31"}
        )
        assert response.status_code == 400
        assert "from" in response.json()["fieldErrors"]


class TestTheMeta:
    def test_it_echoes_the_range_it_was_asked_for(self, auth_client, manager, site):
        response = auth_client(manager).get(URL, PARAMS)
        assert response.json()["meta"]["range"] == {
            "from": "2026-07-01",
            "to": "2026-07-31",
        }

    def test_it_carries_a_generated_at_stamp(self, auth_client, manager, site):
        response = auth_client(manager).get(URL, PARAMS)
        assert response.json()["meta"]["generatedAt"].endswith("Z")


class TestAnEmptyPeriod:
    def test_it_is_a_zeroed_answer_not_a_404(self, auth_client, manager, site):
        # A shop that sold nothing in July still has a July compte de résultat,
        # and it reads zero.
        response = auth_client(manager).get(URL, PARAMS)
        assert response.status_code == 200
        body = response.json()
        assert body["summary"]["revenue"] == 0
        assert body["summary"]["netResult"] == 0
        assert body["summary"]["marginRate"] == 0
        assert body["expenses"] == []


class TestAgainstFinance:
    """The report must equal /finances for the same period, field by field.

    Asserted against the live endpoints rather than against literals: a literal
    would still pass if both surfaces drifted together.
    """

    @pytest.fixture
    def a_period_with_activity(self, site):
        sale_line = SaleLineFactory(
            sale__site=site,
            quantity=2,
            unit_cost=3_000,
            line_total=11_600,
            vat_amount=1_600,
        )
        # `created_at` is auto_now_add: passing it to the factory is silently
        # ignored, so it must be forced after the insert.
        dated(Sale, sale_line.sale, at(15))
        PaymentFactory(sale=sale_line.sale, amount=5_000, paid_at=at(16))
        ExpenseFactory(site=site, amount=2_000, category="RENT", spent_at=at(10))
        return sale_line.sale

    def test_the_summary_block_equals_the_finance_endpoint(
        self, auth_client, manager, a_period_with_activity
    ):
        client = auth_client(manager)
        report = client.get(URL, PARAMS).json()
        finance = client.get("/api/finance/summary/", PARAMS).json()

        assert report["summary"] == finance

    def test_the_expense_breakdown_equals_the_finance_breakdown(
        self, auth_client, manager, a_period_with_activity
    ):
        client = auth_client(manager)
        report = client.get(URL, PARAMS).json()
        breakdown = client.get("/api/finance/breakdown/", PARAMS).json()

        assert report["expenses"] == breakdown["expenses"]

    def test_the_figures_are_not_all_zero(
        self, auth_client, manager, a_period_with_activity
    ):
        # Guards the two tests above: an all-zero payload would satisfy them
        # even if the range never reached the fold.
        body = auth_client(manager).get(URL, PARAMS).json()
        assert body["summary"]["revenue"] > 0
        assert body["expenses"] != []
