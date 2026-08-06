# Sub-project 4 — Customers & Sales

Design, 2026-08-06.

## Context

Sub-projects 1–3 built identity, the catalogue, the stock ledger and
multi-line transactions. `services/stock.ts` is fully implemented. This
sub-project implements `services/customers.ts` and `services/sales.ts`, and it
is the largest remaining slice.

The contract is given, not designed: `Customer`, `Sale`, `SaleLine`,
`SaleDetail`, `SaleCustomerDetail` and `Payment` in `types/domain.ts`;
`CustomerCreateDto`, `SaleCreateDto`, `SaleLineDto`, `PaymentCreateDto` and
`SaleListParams` in `types/dto.ts`; and the rules in `services/sales.ts`.

Unlike earlier sub-projects, one piece of *arithmetic* moves server-side here
rather than only being reimplemented: `features/sales/lib/totals.ts` computes
what gets persisted, so the backend must reproduce it to the cent.

Read sub-project 1's spec for the wire conventions, 2's for filters,
permissions and calendar dates, 3's for the numbering and immutability
patterns. This document does not restate them.

## Decisions taken

| Question | Decision |
|---|---|
| Scope | **One sub-project.** Customers, sales, cancellation and payments together. |
| Billing block | **Snapshotted on the sale**, not resolved at read time. An invoice is a legal document. |
| Permission duplication | **Extracted first**, as task one, before sales adds two more copies. |
| Rounding | **Exact integer arithmetic**, avoiding both Python's banker's rounding and float drift. |

## The rounding problem

`computeSaleTotals` rounds with JavaScript's `Math.round`, which is **half-up**.
Python's built-in `round()` is **banker's rounding**. Verified:

| value | `Math.round` | Python `round` |
|---|---|---|
| 0.5 | 1 | 0 |
| 2.5 | 3 | 2 |

Integer-cent discount allocation lands on exact halves routinely, so a naive
port would put the backend one cent off the invoice the user was shown — on
the document that matters most.

**The backend avoids the question by never using floats.** Every rounded value
in this arithmetic is a rational with integer numerator and denominator, so
half-up rounding is exact integer math:

```
round_half_up(numerator, denominator) = (2·numerator + denominator) // (2·denominator)
```

Two applications, both in `apps/sales/totals.py`:

| frontend | backend |
|---|---|
| `Math.round(discount * lineTotal / subtotal)` | `round_half_up(discount·lineTotal, subtotal)` |
| `Math.round(taxable * vatRate / (100 + vatRate))` | `round_half_up(taxable·r, 10000 + r)` where `r = vatRate × 100` |

Scaling `vatRate` by 100 keeps it integral — the column is
`DecimalField(5, 2)`, so a rate like `5.5` becomes `550` and the identity
`taxable·550/10550 ≡ taxable·5.5/105.5` holds exactly.

**Verified during design**, not assumed: 400 randomised cases of both formulas
and 300 randomised cases of the discount allocation, each run against the real
`Math.round` in Node. Zero mismatches, including exact half-way values.

This is *stricter* than the frontend, which uses IEEE doubles. At realistic
cent magnitudes the products stay well under 2⁵³ so the frontend is exact too
and the two agree; on absurd values the backend would be right and the
frontend would drift. That asymmetry is acceptable — the contract is the
frontend's *intent*, and its own comment says every rounding is "applied
exactly once to an unrounded value".

## Scope

**In:** `Customer` with full CRUD; `Sale`, `SaleLine`, `Payment`; sale create,
list, detail and cancel; payment create; `FA-YYYY-NNNN` numbering reusing
`next_reference`; the `sale` foreign key on `StockMovement` and the serializer
swap; the shared permission mixin.

**Out, deliberately:** editing a sale — the only mutation is cancellation;
refunds, which `cancelSale` explicitly does not perform; credit notes; and any
finance aggregation, which is sub-project 5.

## Architecture

```
apps/
  common/
    money.py       # new — round_half_up
    permissions.py # + RoleScopedPermissionMixin
  sales/           # new app
    models.py      # Customer, Sale, SaleLine, Payment
    totals.py      # the ported arithmetic — no Django imports
    querysets.py   # the annotated sale queryset
    services.py    # create_sale, add_payment, cancel_sale
    serializers.py
    filters.py
    views.py
    urls.py
  stock/
    models.py      # + StockMovement.sale
```

**The dependency runs one way: `apps.sales` imports `apps.stock` and
`apps.catalogue`, never the reverse.** `StockMovement.sale` uses the lazy
string `"sales.Sale"`, which is precisely the tool for a foreign key pointing
at an app that imports you.

`apps/sales/totals.py` imports nothing from Django. It is pure arithmetic over
integers, testable without a database, and that isolation is what makes the
randomised comparison against the frontend cheap to run.

### The permission mixin

`MovementViewSet`, `TransactionViewSet` and `UserViewSet` each hand-roll the
same read / manager-writes map because none can subclass `CatalogueViewSet` —
they use different mixin sets. Sales and payments would make five copies.

`apps/common/permissions.py` gains:

```python
class RoleScopedPermissionMixin:
    """Declarative per-action permissions.

    `permission_map` maps an action name to a permission class; anything
    unlisted falls back to `default_permission`.
    """
    permission_map: dict[str, type] = {}
    default_permission = IsAuthenticated
```

Applied to all five viewsets. `CatalogueViewSet` keeps its existing behaviour,
expressed through the same mixin so there is one mechanism rather than two.

## Data model

### `Customer`

Structurally a `Supplier` plus `tax_number`. Same conventions: `name` unique
case-insensitively via a functional index, optional strings `null=True`,
`is_active` for archiving.

`listCustomers` takes `SimpleListParams` — page, pageSize and search only.
There is deliberately **no `?isActive=` filter**, unlike articles: the contract
does not have one, and `is_active` exists so an archived customer stops
appearing in the sale form's picker, not so the customer list can be filtered.

| field | type |
|---|---|
| `id` | UUID pk |
| `name` | `CharField(80)`, unique case-insensitively |
| `contact_name`, `email`, `phone`, `address`, `tax_number`, `notes` | optional |
| `is_active` | `BooleanField(default=True)` |
| `created_at` | auto |

### `Sale`

| field | type | notes |
|---|---|---|
| `reference` | `CharField(20)` | unique; `FA-YYYY-NNNN` |
| `site` | FK → `Site`, `PROTECT` | |
| `customer` | FK → `Customer`, `PROTECT`, null | null for « client de passage » |
| `customer_name` | `CharField(80, null)` | snapshot |
| `customer_address` | `CharField(200, null)` | snapshot |
| `customer_tax_number` | `CharField(100, null)` | snapshot |
| `status` | `TextChoices` | `COMPLETED` / `CANCELLED` |
| `subtotal`, `discount`, `total`, `vat_total` | `PositiveIntegerField` | cents |
| `discount_rate` | `DecimalField(5,2), null` | how it was entered; never used in arithmetic |
| `note` | `CharField(300, null)` | |
| `cancelled_at` | `DateTimeField(null)` | |
| `cancel_reason` | `CharField(300, null)` | |
| `user` | FK → `User`, `PROTECT` | |
| `user_name` | `CharField(150)` | snapshot |

The three billing snapshots are the departure from the frontend, which
resolves them live. Its comment argues that is safe because `removeCustomer`
refuses to delete a customer with sales — true for *deletion*, but a rename or
a move still rewrites every historical invoice. Snapshotting costs three
columns and makes an issued invoice immutable, which is what an invoice is.

**`discount_rate` is recorded and never read.** `SaleCreateDto` carries both
`discount` (already resolved to cents by the form) and `discountRate` (the
percentage, when that is how the user entered it). The backend validates and
allocates from `discount` alone; `discountRate` exists so the UI can redisplay
"10 %" rather than "1 500 FC".

### `SaleLine`

| field | type | notes |
|---|---|---|
| `sale` | FK → `Sale`, `CASCADE` | `related_name="lines"` |
| `article` | FK → `Article`, `PROTECT` | |
| `article_name`, `article_sku`, `unit` | snapshot | |
| `quantity` | `PositiveIntegerField` | |
| `unit_price` | `PositiveIntegerField` | TTC, possibly negotiated below the article's price |
| `unit_cost` | `PositiveIntegerField` | the article's `purchase_price` at sale time |
| `vat_rate` | `DecimalField(5,2)` | snapshot |
| `line_total`, `discount_share`, `vat_amount` | `PositiveIntegerField` | computed at write time |

`CASCADE` here, unlike everywhere else: a line has no meaning without its
sale, and nothing ever deletes a sale.

**`unit_cost` is the load-bearing snapshot.** Sub-project 6 computes COGS and
margin from it and never re-joins to the article. Repricing an article must
not rewrite last quarter's margin.

### `Payment`

| field | type | notes |
|---|---|---|
| `sale` | FK → `Sale`, `PROTECT` | `related_name="payments"` |
| `amount` | `PositiveIntegerField` | cents |
| `method` | `TextChoices` | five values |
| `paid_at` | `DateTimeField` | see below |
| `reference`, `note` | optional | |
| `user` | FK → `User`, `PROTECT` | |
| `user_name` | `CharField(150)` | snapshot |

Append-only: no update, no delete.

`PROTECT` on `sale`, where `SaleLine` uses `CASCADE`. Neither ever fires —
nothing deletes a sale — so the difference is a statement of intent: a line is
part of the document and would go with it, whereas a payment is a money record
that should block a deletion rather than vanish inside one.

`paidAt` arrives as a bare calendar date from a picker. The frontend widens it
to **local noon** so the stored instant lands on the day the user picked in
every timezone. `apps/common/dates.py` gains `at_local_noon(date) -> datetime`
alongside the existing bounds helpers, resolved in `SHOP_TIME_ZONE`.

### `StockMovement.sale`

Nullable FK to `"sales.Sale"`, `related_name="movements"`, `on_delete=PROTECT`.
`StockMovementSerializer.get_sale_id` — the last hardcoded `None` — becomes a
real field. A movement carries at most one of `transaction` and `sale`.

## Derived figures

`paidAmount`, `balance` and `paymentStatus` are computed on every read and
**never stored**. A status column would be a second source of truth, free to
disagree with the payments it claims to summarise.

`apps/sales/querysets.py::sale_queryset()` annotates:

```python
paid = (
    Payment.objects.filter(sale=OuterRef("pk"))
    .values("sale")
    .annotate(total=Sum("amount"))
    .values("total")
)

Sale.objects.annotate(
    paid_amount=Coalesce(Subquery(paid), 0, output_field=IntegerField()),
    line_count=Count("lines", distinct=True),
)
```

`paid_amount` is a correlated subquery rather than a second join aggregate:
`Count("lines")` and `Sum("payments__amount")` in one queryset would multiply
each other's rows, giving a sale with three lines and two payments a paid
amount of six times its true value. That is the classic Django multi-join
aggregate bug, and the subquery form is immune to it.

The serializer derives the rest:

| field | rule |
|---|---|
| `balance` | `0` when `CANCELLED`, else `max(total − paidAmount, 0)` |
| `paymentStatus` | `UNPAID` when `paid ≤ 0`; `PAID` when `paid ≥ total`; else `PARTIAL` |

`?paymentStatus=` filters over the same three buckets in SQL, **and excludes
cancelled sales entirely** — otherwise "Impayée" would list sales nobody owes
for. That exclusion is in `services/sales.ts` and is easy to lose in
translation, so it gets its own test.

## Sale creation

One atomic block:

1. **Validate** — lines non-empty, no duplicate article, quantity ≥ 1,
   unit price ≥ 0, discount ≥ 0, customer still present.
2. **Snapshot** every line's article: name, SKU, unit, `vat_rate`, and
   `purchase_price` into `unit_cost`.
3. **Compute totals** with `apps/sales/totals.py`, then reject a discount
   exceeding the subtotal. The arithmetic reports faithfully and leaves the
   ruling to its caller, exactly as the frontend splits it.
4. **Allocate** `FA-YYYY-NNNN` via `next_reference("FA", shop_today().year)`.
5. **Write** the header and its lines.
6. **Post one `OUT` / `SALE` movement per line** through `apply_movement`,
   with `sale=` and `field_prefix=f"lines.{index}."`.

All-or-nothing. A line that exceeds available stock rolls back the header, the
lines, the earlier movements, the stock levels and the sequence increment — so
a rejected sale leaves no gap in the invoice numbering, which is the property
sub-project 3 built the allocator for.

The frontend writes its header *last* ("so a failure anywhere above leaves no
sale"). That is a Dexie-specific concern; under a real transaction the order
is irrelevant, and the header must come first because the lines and movements
carry foreign keys to it.

### `apply_movement` gains one more argument

```python
def apply_movement(*, article, site, type, reason, quantity, user,
                   unit_cost=None, reference=None, note=None,
                   stock_transaction=None, sale=None, field_prefix="") -> StockMovement
```

Third and final caller of the single writer. Neither sales nor transactions
grow their own way to change a quantity.

## Payments

`POST /api/sales/{id}/payments/`.

- **Overpayment is refused**, not accepted and netted off later: a payment
  taking the total received above the sale total is a mistake at the moment it
  is typed. The message carries the remaining balance, formatted in French.
- **A cancelled sale accepts no payment.**
- `amount` must be a positive integer.

Money formatting for that one message needs a French cent formatter —
`apps/common/money.py::format_cents` — matching `lib/format.ts`.

## Cancellation

`POST /api/sales/{id}/cancel/` with an optional `reason`.

Movements are append-only, so cancellation never deletes them. Each line's
`OUT` is compensated by an `IN` / `RETURN` carrying the **same sale**, which
is why the sale detail can show both halves and why the movement journal links
them to one document. The compensating movement's note defaults to
`Annulation de la vente {reference}`.

Cancelling an already-cancelled sale is a 400 on `reason`.

**Money already received is not refunded.** This sub-project does not move
money out; the frontend reports it as « Remboursement dû ».

## API surface

```
GET    /api/customers/            ?search= &page= &pageSize=
POST   /api/customers/
GET    /api/customers/{id}/
PATCH  /api/customers/{id}/
DELETE /api/customers/{id}/

GET    /api/sales/                ?search= &customerId= &status= &paymentStatus=
                                  &dateFrom= &dateTo= &page= &pageSize=
POST   /api/sales/
GET    /api/sales/{id}/           → adds `lines` and `payments`
POST   /api/sales/{id}/cancel/
POST   /api/sales/{id}/payments/
```

Sales are ordered `-createdAt` and not otherwise sortable. Search covers
`reference`, `customer_name` and `note` — the snapshot, not a join, which is a
small bonus of snapshotting.

Permissions, from the README's role table:

| action | Owner | Manager | Cashier |
|---|---|---|---|
| read sales and customers | yes | yes | yes |
| create a sale, add a payment | yes | yes | **yes** |
| cancel a sale | yes | yes | — |
| write customers | yes | yes | — |
| delete a customer | yes | — | — |

Cashiers create sales and payments because that is the till. They do not
cancel, and they do not maintain the customer list — the sale form picks from
existing customers and offers no inline creation, so nothing in the till
workflow needs write access.

`DELETE /api/customers/{id}/` returns 409 when the customer has sales:
`Ce client est lié à N ventes et ne peut pas être supprimé. Archivez-le à la
place.`

## Validation

| condition | key | message |
|---|---|---|
| no lines | `lines` | Ajoutez au moins un article à la vente. |
| duplicate article | `lines.N.articleId` | Cet article est déjà présent dans la vente. |
| article deleted | `lines.N.articleId` | Cet article n'existe plus. |
| quantity ≤ 0 | `lines.N.quantity` | La quantité doit être supérieure à zéro. |
| unit price invalid | `lines.N.unitPrice` | Le prix unitaire est invalide. |
| insufficient stock | `lines.N.quantity` | Stock insuffisant : … (from `apply_movement`) |
| negative discount | `discount` | La remise ne peut pas être négative. |
| discount > subtotal | `discount` | La remise ne peut pas dépasser le total de la vente. |
| unknown customer | `customerId` | Ce client n'existe plus. |
| payment ≤ 0 | `amount` | Le montant doit être supérieur à zéro. |
| payment > balance | `amount` | Le montant dépasse le solde restant dû (…). |
| payment on cancelled | `amount` | Cette vente est annulée : aucun paiement ne peut être ajouté. |
| already cancelled | `reason` | Cette vente est déjà annulée. |

## Line ordering on the invoice

`getSale` sorts lines by `articleName.localeCompare(b, "fr-FR")`. Python's
default string sort orders by code point, which puts « Épicerie » *after*
« Zzz » because `É` is U+00C9.

Lines are therefore sorted on an accent-stripped NFKD key. That matches French
collation for article names without pulling in PyICU. It is an approximation:
it does not implement full CLDR tailoring, and two names differing only by
accent sort by their original form as a tiebreak. Named here so nobody later
mistakes it for a complete collation.

Payments sort by `paid_at` ascending, which needs no such care.

## Testing

TDD, API-level, plus one pure-arithmetic module tested without a database.

- **Totals** — `apps/sales/totals.py` against a table of hand-computed cases,
  including: a single line; several lines with different VAT rates; a discount
  that divides evenly; one that does not, asserting the shares sum to exactly
  the discount; a discount equal to the subtotal; a zero subtotal; a zero VAT
  rate; and a decimal VAT rate. Plus the exact half-way cases that distinguish
  half-up from banker's rounding, which is the whole reason the module exists.
- **Sale creation** — snapshots taken and independent of later article edits;
  one `OUT`/`SALE` movement per line carrying the sale; totals persisted
  matching the module; `FA-` numbering; all-or-nothing on an insufficient
  line, including no gap in the sequence.
- **Derived figures** — `paidAmount`, `balance` and `paymentStatus` across
  unpaid, partial, paid, overpaid-impossible and cancelled; the cancelled
  exclusion from `?paymentStatus=`.
- **Payments** — happy path; overpayment refused with the balance in the
  message; a payment on a cancelled sale refused; `paidAt` widened to local
  noon and landing on the picked day.
- **Cancellation** — compensating `IN`/`RETURN` per line carrying the same
  sale; stock restored; original movements untouched; `balance` 0 afterwards;
  double cancellation refused; a cashier refused.
- **Customers** — CRUD, case-insensitive name clash, the 409 delete guard.
- **Permissions** — the full matrix from the table above, and that the
  extracted mixin did not change any existing viewset's behaviour.
- **Query counts** — flat on `/api/sales/` and on the detail route.

No test count is predicted.

## Risks

**The arithmetic is the contract.** Every other sub-project could be checked
by eye against a payload; this one produces money. The randomised comparison
against Node is the strongest available evidence and it should be kept as a
test, not just a design-time spike — but it needs `node` on the path, so it
is marked and skipped when absent rather than failing the suite.

**Snapshotting diverges from the frontend's read-time resolution.** Payload
shapes are identical, so no frontend change is needed, but an existing mock
database and a real backend would disagree about a renamed customer's old
invoices. That only matters during cutover, and the backend's answer is the
correct one.

**`select_for_update` remains a no-op on SQLite.** Fourth sub-project to
record it. Invoice numbering is now the thing it protects, which raises the
stakes of the Postgres move.

**`line_count` is annotated, not stored** — unlike `StockTransaction`, where it
is denormalised. The two differ because a transaction is immutable while a
sale's payments change; annotating avoids a second thing to keep in step. The
inconsistency is deliberate and worth remembering.

## Frontend type changes required

None. Sub-project 1's two changes — `User` gaining `role`, and `Session.token`
becoming `accessToken` + `refreshToken` — remain the only ones outstanding.
