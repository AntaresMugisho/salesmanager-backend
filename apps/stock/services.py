"""The single writer of a stock quantity.

Mirrors `applyMovementLine` in the frontend's `services/stock.ts`, down to the
constraint that motivates it: the read of the current level and the write of
the new one must be serialised, or two concurrent movements both read the same
stale `quantity_before` and one silently overwrites the other's result.

Sub-project 3's transactions and sub-project 4's sales post through this same
function. Neither gets its own way to change a quantity.
"""

from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.common.dates import shop_today
from apps.common.sequences import next_reference
from apps.stock.models import StockLevel, StockMovement, StockTransaction


def _clean(value: str | None) -> str | None:
    return value.strip() or None if value else None


@transaction.atomic
def apply_movement(
    *,
    article,
    site,
    type: str,
    reason: str,
    quantity: int,
    user,
    unit_cost: int | None = None,
    reference: str | None = None,
    note: str | None = None,
    stock_transaction=None,
    sale=None,
    field_prefix: str = "",
) -> StockMovement:
    """Post one movement and update the level it applies to.

    `quantity` is a delta for IN and OUT, and the counted *target* for
    ADJUSTMENT — the recorded quantity is then the delta that was applied.

    `stock_transaction` links this movement to the header it is a line of.
    Named `stock_transaction` rather than `transaction` because that name is
    bound to `django.db.transaction` in this module — shadowing it inside the
    function that opens the atomic block is how a subtle bug gets written.

    `sale` does the same for a sale's lines. A movement carries at most one of
    the two, and this is the third and final caller of the single writer:
    neither sales nor transactions grow their own way to change a quantity.

    `field_prefix` routes validation errors to a form row: passing
    `"lines.2."` produces the key `lines.2.quantity`, which is
    react-hook-form's array-field syntax and what sub-project 3 needs.
    """
    # select_for_update is a silent no-op on SQLite — verified,
    # connection.features.has_select_for_update is False and the call neither
    # locks nor raises. It is written now because it costs nothing and becomes
    # correct on Postgres without a code change.
    level = (
        StockLevel.objects.select_for_update()
        .filter(article=article, site=site)
        .first()
    )
    quantity_before = level.quantity if level else 0
    field = f"{field_prefix}quantity"

    if type == StockMovement.Type.IN:
        quantity_after = quantity_before + quantity
        recorded = quantity
    elif type == StockMovement.Type.OUT:
        if quantity > quantity_before:
            raise serializers.ValidationError(
                {
                    field: [
                        _(
                            "Stock insuffisant : %(available)d unité(s) "
                            "disponible(s) actuellement."
                        )
                        % {"available": quantity_before}
                    ]
                }
            )
        quantity_after = quantity_before - quantity
        recorded = quantity
    else:
        # ADJUSTMENT: `quantity` is what the shelf was counted at.
        quantity_after = quantity
        recorded = abs(quantity - quantity_before)
        if recorded == 0:
            raise serializers.ValidationError(
                {field: [_("La quantité comptée est identique au stock actuel.")]}
            )

    if level is None:
        StockLevel.objects.create(article=article, site=site, quantity=quantity_after)
    else:
        level.quantity = quantity_after
        level.save(update_fields=["quantity", "updated_at"])

    return StockMovement.objects.create(
        article=article,
        site=site,
        type=type,
        reason=reason,
        quantity=recorded,
        quantity_before=quantity_before,
        quantity_after=quantity_after,
        unit_cost=unit_cost,
        reference=_clean(reference),
        note=_clean(note),
        transaction=stock_transaction,
        sale=sale,
        user=user,
        user_name=user.full_name,
    )


@transaction.atomic
def create_transaction(
    *,
    type: str,
    reason: str,
    lines: list[dict],
    user,
    site,
    supplier=None,
    user_reference: str | None = None,
    note: str | None = None,
) -> StockTransaction:
    """Write one header plus one movement per line, all or nothing.

    Every line shares the transaction's type and reason — a design decision,
    not an omission. Mixed-type transactions are out of scope.

    The header is written before the lines because a movement's foreign key
    needs it; its `total_quantity` is only knowable afterwards, since an
    ADJUSTMENT line records a derived delta rather than the counted target the
    client sent.

    Allocation, header, lines and stock levels all share this atomic block, so
    a line that fails validation rolls back the reference too and the sequence
    keeps no gap.
    """
    cleaned_reference = _clean(user_reference)
    cleaned_note = _clean(note)

    reference = next_reference("TR", shop_today().year)

    header = StockTransaction.objects.create(
        reference=reference,
        site=site,
        user_reference=cleaned_reference,
        type=type,
        reason=reason,
        supplier=supplier,
        supplier_name=supplier.name if supplier else None,
        note=cleaned_note,
        line_count=len(lines),
        total_quantity=0,
        user=user,
        user_name=user.full_name,
    )

    total_quantity = 0
    for index, line in enumerate(lines):
        movement = apply_movement(
            article=line["article"],
            site=site,
            type=type,
            reason=reason,
            quantity=line["quantity"],
            unit_cost=line.get("unit_cost"),
            # A line with no delivery-note number of its own is still
            # traceable to its transaction through the ledger's reference.
            reference=cleaned_reference or reference,
            note=cleaned_note,
            user=user,
            stock_transaction=header,
            field_prefix=f"lines.{index}.",
        )
        total_quantity += movement.quantity

    header.total_quantity = total_quantity
    header.save(update_fields=["total_quantity", "updated_at"])
    return header
