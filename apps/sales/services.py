"""Sale writers.

Every stock change still goes through `apply_movement`. A sale does not get
its own way to change a quantity.
"""

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.common.dates import at_local_noon, shop_today
from apps.common.money import format_cents
from apps.common.sequences import next_reference
from apps.sales.models import Payment, Sale, SaleLine
from apps.sales.totals import LineInput, compute_sale_totals
from apps.stock.services import apply_movement


def _clean(value: str | None) -> str | None:
    return value.strip() or None if value else None


@transaction.atomic
def create_sale(
    *,
    lines: list[dict],
    user,
    site,
    customer=None,
    discount: int = 0,
    discount_rate=None,
    note: str | None = None,
    reference: str | None = None,
    sale_id=None,
    allow_negative: bool = False,
) -> Sale:
    """Write one sale header, one line per article, and one OUT / SALE
    movement per line — all or nothing.

    Prices, names and VAT rates are snapshotted here and never resolved back
    to the article afterwards: repricing an article must not rewrite an
    existing sale.

    Stock posts immediately. There is no draft or pending state between the
    sale and its stock impact.

    Allocation shares this atomic block, so a line that exceeds available
    stock rolls the invoice number back too — a rejected sale leaves no gap in
    the numbering.
    """
    cleaned_note = _clean(note)

    snapshots = [
        {
            "article": row["article"],
            "quantity": row["quantity"],
            "unit_price": row["unit_price"],
            "article_name": row["article"].name,
            "article_sku": row["article"].sku,
            "unit": row["article"].unit,
            "unit_cost": row["article"].purchase_price,
            "vat_rate": row["article"].vat_rate,
        }
        for row in lines
    ]

    totals = compute_sale_totals(
        [
            LineInput(
                quantity=row["quantity"],
                unit_price=row["unit_price"],
                vat_rate=row["vat_rate"],
            )
            for row in snapshots
        ],
        discount=discount,
    )

    # Checked here rather than inside compute_sale_totals, which reports the
    # arithmetic faithfully and leaves the ruling to its callers — the same
    # split the frontend makes.
    if totals.discount > totals.subtotal:
        raise serializers.ValidationError(
            {"discount": [_("La remise ne peut pas dépasser le total de la vente.")]}
        )

    # A sale replayed from a device's queue arrives with the number already
    # printed on the customer's receipt. Only an online sale is numbered here.
    reference = reference or next_reference("FA", shop_today().year)

    sale = Sale.objects.create(
        # Spread, never `id=sale_id`: passing None explicitly would override
        # the model's uuid4 default with NULL.
        **({"id": sale_id} if sale_id else {}),
        reference=reference,
        site=site,
        customer=customer,
        customer_name=customer.name if customer else None,
        customer_address=customer.address if customer else None,
        customer_tax_number=customer.tax_number if customer else None,
        status=Sale.Status.COMPLETED,
        subtotal=totals.subtotal,
        discount=totals.discount,
        discount_rate=discount_rate,
        total=totals.total,
        vat_total=totals.vat_total,
        note=cleaned_note,
        user=user,
        user_name=user.full_name,
    )

    for index, row in enumerate(snapshots):
        apply_movement(
            article=row["article"],
            site=site,
            type="OUT",
            reason="SALE",
            quantity=row["quantity"],
            unit_cost=None,
            reference=reference,
            note=cleaned_note,
            user=user,
            sale=sale,
            field_prefix=f"lines.{index}.",
            allow_negative=allow_negative,
        )

        SaleLine.objects.create(
            sale=sale,
            article=row["article"],
            article_name=row["article_name"],
            article_sku=row["article_sku"],
            unit=row["unit"],
            quantity=row["quantity"],
            unit_price=row["unit_price"],
            unit_cost=row["unit_cost"],
            vat_rate=row["vat_rate"],
            line_total=totals.lines[index].line_total,
            discount_share=totals.lines[index].discount_share,
            vat_amount=totals.lines[index].vat_amount,
        )

    return sale


@transaction.atomic
def add_payment(
    *,
    sale: Sale,
    amount: int,
    method: str,
    paid_at,
    user,
    reference: str | None = None,
    note: str | None = None,
    payment_id=None,
) -> Payment:
    """Record a payment against a sale.

    Overpayment is rejected rather than accepted and netted off later: a
    payment that would take the total received above the sale total is a
    mistake at the moment it is typed, and it is cheaper to refuse it than to
    explain a negative balance afterwards.

    `paid_at` is a `datetime.date` from the picker, widened to local noon.
    """
    if sale.status == Sale.Status.CANCELLED:
        raise serializers.ValidationError(
            {
                "amount": [
                    _("Cette vente est annulée : aucun paiement ne peut être ajouté.")
                ]
            }
        )

    paid_so_far = (
        Payment.objects.filter(sale=sale).aggregate(total=Sum("amount"))["total"] or 0
    )
    balance = sale.total - paid_so_far

    if amount > balance:
        raise serializers.ValidationError(
            {
                "amount": [
                    _("Le montant dépasse le solde restant dû (%(balance)s).")
                    % {"balance": format_cents(balance)}
                ]
            }
        )

    return Payment.objects.create(
        # Spread, never `id=payment_id`: passing None explicitly would
        # override the model's uuid4 default with NULL.
        **({"id": payment_id} if payment_id else {}),
        sale=sale,
        amount=amount,
        method=method,
        paid_at=at_local_noon(paid_at),
        reference=_clean(reference),
        note=_clean(note),
        user=user,
        user_name=user.full_name,
    )


@transaction.atomic
def cancel_sale(*, sale: Sale, reason: str | None, user) -> Sale:
    """Cancel a sale and give its stock back.

    Movements are append-only, so this never deletes them. Each line's OUT is
    compensated by an IN / RETURN carrying the SAME sale, which is why the
    sale detail can show both halves and why the movement journal links them
    to one document.

    Money already received is NOT refunded here — this sub-project does not
    move money out. The frontend reports it as « Remboursement dû ».
    """
    if sale.status == Sale.Status.CANCELLED:
        raise serializers.ValidationError(
            {"reason": [_("Cette vente est déjà annulée.")]}
        )

    cleaned_reason = _clean(reason)
    note = cleaned_reason or str(
        _("Annulation de la vente %(reference)s") % {"reference": sale.reference}
    )

    for line in sale.lines.select_related("article"):
        apply_movement(
            article=line.article,
            site=sale.site,
            type="IN",
            reason="RETURN",
            quantity=line.quantity,
            unit_cost=None,
            reference=sale.reference,
            note=note,
            user=user,
            sale=sale,
        )

    sale.status = Sale.Status.CANCELLED
    sale.cancelled_at = timezone.now()
    sale.cancel_reason = cleaned_reason
    sale.save(update_fields=["status", "cancelled_at", "cancel_reason", "updated_at"])
    return sale
