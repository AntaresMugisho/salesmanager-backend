"""Hand-built facts, so a builder can be tested without a database.

Deliberately the same shape as `apps.finance.facts.load_facts` returns,
including the three fields the reports added.
"""

from decimal import Decimal

from apps.reports.tests.support import at


def sale(
    id="s1",
    day=15,
    month=7,
    status="COMPLETED",
    total=11_600,
    vat_total=1_600,
    discount=0,
    customer_id=None,
    customer_name=None,
    **kw,
):
    # `month` is a named parameter, not **kw: a stray kw key would silently
    # become a fact field and leave the date on the default July day.
    row = {
        "id": id,
        "created_at": at(day, month=month),
        "status": status,
        "total": total,
        "vat_total": vat_total,
        "reference": f"FA-2026-{id}",
        "customer_id": customer_id,
        "customer_name": customer_name,
        "discount": discount,
    }
    row.update(kw)
    return row


def line(
    sale_id="s1",
    article_id="a1",
    quantity=2,
    line_total=11_600,
    discount_share=0,
    vat_amount=1_600,
    unit_cost=3_000,
    vat_rate="16.00",
    **kw,
):
    row = {
        "sale_id": sale_id,
        "article_id": article_id,
        "article_name": "Article",
        "article_sku": "ART-1",
        "quantity": quantity,
        "line_total": line_total,
        "discount_share": discount_share,
        "vat_amount": vat_amount,
        "unit_cost": unit_cost,
        "vat_rate": Decimal(vat_rate),
    }
    row.update(kw)
    return row


def payment(sale_id="s1", amount=5_000, day=16):
    return {"sale_id": sale_id, "amount": amount, "paid_at": at(day)}


def expense(amount=2_000, category="RENT", day=10):
    return {"category": category, "amount": amount, "spent_at": at(day)}


def purchase(quantity=10, unit_cost=800, day=5):
    return {"quantity": quantity, "unit_cost": unit_cost, "created_at": at(day)}


def facts(**kw):
    base = {"sales": [], "lines": [], "payments": [], "expenses": [], "purchases": []}
    base.update(kw)
    return base
