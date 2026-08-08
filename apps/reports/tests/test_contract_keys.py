"""The exact key sets each report puts on the wire.

Transcribed from `stockmanager-frontend/types/dto.ts` lines 304-479 and frozen
here, so this does not depend on the sibling repo being checked out.

This file exists because a live wire check caught what 111 unit tests did not:
the totals block shipped `revenueHt` where the contract says `revenueHT`. The
renderer camelises snake_case, and `revenue_ht` becomes `revenueHt` — close
enough to read past, and `undefined` on the document. Nothing else in the suite
looked at the *spelling* of a key, only at values fetched by the name the
backend happened to use.

A wrong key never raises. It renders as a blank cell.
"""

import pytest

from apps.reports.tests.support import PARAMS, at, dated
from apps.expenses.tests.factories import ExpenseFactory
from apps.sales.models import Sale
from apps.sales.tests.factories import PaymentFactory, SaleLineFactory
from apps.stock.models import StockMovement
from apps.stock.tests.factories import StockLevelFactory, StockMovementFactory

pytestmark = pytest.mark.django_db

META = {"range", "generatedAt"}

FINANCE_SUMMARY = {
    "revenue", "cogs", "grossMargin", "marginRate", "expenses", "netResult",
    "vatCollected", "receipts", "purchaseDisbursements", "disbursements",
    "cashBalance", "receivables", "purchasesWithoutCost",
}


@pytest.fixture
def a_shop_with_everything(site):
    """One of each thing, so every array in every payload is non-empty.

    An empty array has no rows to check keys on, which would make this whole
    module pass vacuously.
    """
    sale_line = SaleLineFactory(
        sale__site=site,
        sale__total=11_600,
        sale__vat_total=1_600,
        sale__discount=1_000,
        quantity=2,
        unit_cost=500,
        line_total=12_600,
        discount_share=1_000,
        vat_amount=1_600,
    )
    dated(Sale, sale_line.sale, at(15))
    PaymentFactory(sale=sale_line.sale, amount=5_000, paid_at=at(16))
    ExpenseFactory(site=site, amount=25_000, category="RENT", spent_at=at(10))
    StockLevelFactory(article=sale_line.article, site=site, quantity=10)
    # Dated into the period: created_at is auto_now_add, so a factory-fresh
    # movement lands on today and falls outside the range, leaving
    # movementSummary, supplierPurchases and journal all empty.
    movement = StockMovementFactory(article=sale_line.article, site=site)
    dated(StockMovement, movement, at(5))
    return sale_line


def fetch(auth_client, manager, endpoint):
    return auth_client(manager).get(f"/api/reports/{endpoint}/", PARAMS).json()


class TestResultReport:
    def test_the_keys_match_the_contract(
        self, auth_client, manager, a_shop_with_everything
    ):
        body = fetch(auth_client, manager, "result")
        assert set(body) == {"meta", "summary", "expenses"}
        assert set(body["meta"]) == META
        assert set(body["summary"]) == FINANCE_SUMMARY
        assert body["expenses"], "no expense rows to check"
        assert set(body["expenses"][0]) == {"category", "amount", "share"}


class TestSalesReport:
    def test_the_keys_match_the_contract(
        self, auth_client, manager, a_shop_with_everything
    ):
        body = fetch(auth_client, manager, "sales")
        assert set(body) == {"meta", "totals", "vat", "customers", "invoices"}
        # revenueHT, not revenueHt. This is the assertion the wire check
        # produced.
        assert set(body["totals"]) == {
            "invoiceCount", "cancelledCount", "totalTtc", "revenueHT",
            "vatCollected", "discounts", "receipts", "receivables",
        }
        assert body["vat"], "no vat rows to check"
        assert set(body["vat"][0]) == {"vatRate", "base", "vatAmount", "total"}
        assert body["customers"], "no customer rows to check"
        assert set(body["customers"][0]) == {
            "customerId", "customerName", "invoiceCount", "total", "paid", "balance",
        }
        assert body["invoices"], "no invoice rows to check"
        assert set(body["invoices"][0]) == {
            "id", "reference", "createdAt", "customerName", "status",
            "total", "paid", "balance",
        }


class TestProfitabilityReport:
    ROW = {"id", "name", "sku", "quantity", "revenue", "cogs", "margin", "marginRate"}

    def test_the_keys_match_the_contract(
        self, auth_client, manager, a_shop_with_everything
    ):
        body = fetch(auth_client, manager, "profitability")
        assert set(body) == {"meta", "categories", "articles", "lowMargin", "totals"}
        assert body["articles"], "no article rows to check"
        assert set(body["articles"][0]) == self.ROW
        assert body["categories"], "no category rows to check"
        assert set(body["categories"][0]) == self.ROW
        assert set(body["totals"]) == {
            "quantity", "revenue", "cogs", "margin", "marginRate",
        }


class TestStockReport:
    def test_the_keys_match_the_contract(
        self, auth_client, manager, a_shop_with_everything
    ):
        body = fetch(auth_client, manager, "stock")
        assert set(body) == {
            "meta", "categories", "stockTotals", "movementSummary",
            "supplierPurchases", "journal",
        }
        assert body["categories"], "no category groups to check"
        group = body["categories"][0]
        assert set(group) == {"categoryId", "categoryName", "articles", "value"}
        assert group["articles"], "no article rows to check"
        assert set(group["articles"][0]) == {
            "articleId", "sku", "name", "unit", "quantity", "purchasePrice",
            "value", "reorderThreshold", "status",
        }
        assert set(body["stockTotals"]) == {"articleCount", "value"}
        assert body["movementSummary"], "no movement summary rows to check"
        assert set(body["movementSummary"][0]) == {
            "type", "reason", "movementCount", "quantity",
        }
        assert body["supplierPurchases"], "no supplier rows to check"
        assert set(body["supplierPurchases"][0]) == {
            "supplierId", "supplierName", "movementCount", "quantity",
            "cost", "withoutCostCount",
        }
        assert body["journal"], "no journal rows to check"
        assert set(body["journal"][0]) == {
            "id", "createdAt", "articleName", "articleSku", "type", "reason",
            "quantity", "quantityBefore", "quantityAfter", "reference", "userName",
        }
