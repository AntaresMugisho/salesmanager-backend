# Sub-project 3 — Stock Transactions

Design, 2026-08-06.

## Context

Sub-project 2 implemented every function in the frontend's `services/stock.ts`
except three: `createTransaction`, `listTransactions` and `getTransaction`.
This sub-project implements those three, and nothing else in that module
remains unimplemented afterwards.

As before, the contract is given rather than designed. `StockTransaction`,
`StockTransactionLine` and `StockTransactionDetail` in
`stockmanager-frontend/types/domain.ts` fix the payloads;
`TransactionCreateDto`, `TransactionLineDto` and `TransactionListParams` in
`types/dto.ts` fix the inputs; and `createTransaction` in `services/stock.ts`
fixes the rules.

One thing the frontend explicitly does **not** solve, and says so:

> Sequence resolved inside the transaction so two concurrent creates cannot
> claim the same number. Counting rows is adequate for a single-tab mock
> ONLY — **the real backend owns numbering.**

That is the centre of this sub-project.

Read sub-project 1's spec for the wire conventions (error envelope, camelCase,
pagination) and sub-project 2's for the filter, permission and calendar-date
conventions. This document does not restate them.

## Decisions taken

| Question | Decision |
|---|---|
| `TR-YYYY-NNNN` allocation | **A locked counter row per prefix and year.** `DocumentSequence` in `apps/common/`, reused unchanged by sub-project 4's `FA-YYYY-NNNN`. |
| Supplier deletion | **`PROTECT` the FK *and* snapshot `supplier_name`**, exactly as `StockMovement` treats `user` / `user_name`. |
| Scope | **Transactions only.** The sub-project 2 follow-ups stay recorded, not bundled. |
| Mutability | **Immutable.** No `PATCH`, no `DELETE`; a correction is a new compensating transaction. |

## Scope

**In:** `DocumentSequence` and the allocation service; `StockTransaction`; the
`transaction` foreign key on `StockMovement` and the serializer swap it
enables; transaction create, list and detail.

**Out, deliberately:** mixed-type transactions — one `type` and one `reason`
apply to every line, which `services/stock.ts` calls "a design decision, not an
omission". Also out: editing or voiding a transaction, and any sale-related
field. Sub-project 4 adds `Sale` and the `sale` FK beside `transaction`.

## Numbering

`apps/common/models.py` gains:

| field | type | notes |
|---|---|---|
| `prefix` | `CharField(8)` | `"TR"` here, `"FA"` in sub-project 4 |
| `year` | `PositiveIntegerField` | the sequence resets each year |
| `last_number` | `PositiveIntegerField(default=0)` | |

with `UniqueConstraint(prefix, year)`.

`apps/common/sequences.py`:

```python
def next_reference(prefix: str, year: int) -> str:
    """Allocate the next `PREFIX-YYYY-NNNN`. Caller must be inside atomic()."""
```

It calls `get_or_create(prefix=..., year=...)` — whose documented
`IntegrityError`-and-re-get path handles two requests racing to create the
first row of a year — then re-reads that row `select_for_update()`, increments,
and formats `f"{prefix}-{year}-{number:04d}"`.

**Allocation happens inside the caller's atomic block.** Two consequences,
both wanted:

- A create that fails validation on line 3 rolls the counter back with
  everything else, so a rejected transaction leaves **no gap** in the
  sequence. This matters more in sub-project 4, where the number is an
  invoice number rather than a delivery-note number.
- The row lock is held until commit, so transaction creation is serialised.
  At one shop's write volume that is free; it is the price of gapless
  numbering, and worth restating if this backend ever serves many sites.

`select_for_update` remains a silent no-op on SQLite — verified in
sub-project 2, `connection.features.has_select_for_update` is `False` and the
call neither locks nor raises. The guarantee is real only after the Postgres
move. SQLite's database-level write lock makes the window narrow meanwhile.

## Data model

### `StockTransaction`

| field | type | notes |
|---|---|---|
| `id` | UUID pk | from `UUIDModel` |
| `reference` | `CharField(20)` | unique; the generated `TR-YYYY-NNNN` |
| `site` | FK → `Site`, `PROTECT` | |
| `user_reference` | `CharField(40, null, blank)` | the user's own delivery-note number |
| `type` | `StockMovement.Type` | one type for every line |
| `reason` | `StockMovement.Reason` | one reason for every line |
| `supplier` | FK → `Supplier`, `PROTECT`, null | |
| `supplier_name` | `CharField(80, null, blank)` | snapshot at write time |
| `note` | `CharField(300, null, blank)` | |
| `line_count` | `PositiveIntegerField` | denormalised so the list need not read the lines |
| `total_quantity` | `PositiveIntegerField` | denormalised |
| `user` | FK → `User`, `PROTECT` | |
| `user_name` | `CharField(150)` | snapshot at write time |
| `created_at` | auto | ordering `-created_at, -id` |

`type` and `reason` reuse `StockMovement.Type` and `StockMovement.Reason`
rather than redeclaring them. A transaction whose choices could drift from its
own lines' choices is a bug waiting to happen.

`supplier` is `PROTECT` **and** `supplier_name` is snapshotted, matching how
`StockMovement` treats `user`. The `PROTECT` means supplier deletion is
refused; the snapshot means a supplier *rename* does not rewrite what last
year's delivery note says. The frontend's `composeTransactions` resolves the
name at read time, so this is a deliberate improvement on the mock, invisible
in the payload.

**Consequence:** `SupplierViewSet.perform_destroy` currently counts only
articles. It gains a second guard for transactions, with its own French
message. Without it, `PROTECT` would surface as an unhandled `ProtectedError`
— a 500 rather than the 409 the frontend expects.

### `StockMovement.transaction`

A nullable FK to `StockTransaction`, `related_name="lines"`, `on_delete=PROTECT`.

`PROTECT` never fires today, because nothing deletes a transaction. It is the
honest declaration of that fact rather than a `CASCADE` that would quietly
delete ledger rows if a delete path ever appeared.

**Declaration order matters, and it points both ways.** `StockTransaction.type`
needs `StockMovement.Type`, while `StockMovement.transaction` needs
`StockTransaction`. So `StockMovement` stays first in the module and its new
foreign key uses the lazy string form `"stock.StockTransaction"`. Reversing the
order would require the choices to be duplicated, which is exactly what reusing
them avoids.

`StockMovementSerializer.get_transaction_id` — the method that returns a
hardcoded `None` today — is replaced by a real field. The payload key does not
change; it starts carrying a value.

`sale_id` keeps its hardcoded `None` until sub-project 4.

## Creation

One atomic block, in this order:

1. **Validate the whole payload** — lines non-empty, no duplicate article,
   every quantity an integer and within its type's rules, every article
   still present.
2. **Allocate** the reference via `next_reference("TR", year)`.
3. **Write the header** with `line_count = len(lines)` and
   `total_quantity = 0`, against `Site.objects.current()` and the requesting
   user, whose `full_name` is snapshotted into `user_name`.
4. **Post each line** through `apply_movement`, passing the header and
   `field_prefix=f"lines.{index}."`, accumulating the recorded quantities.
5. **Save `total_quantity`** on the header.

The header is written before the lines because a movement's FK needs it. Its
`total_quantity` is only knowable afterwards, since an `ADJUSTMENT` line
records a derived delta rather than the number the client sent.

All-or-nothing: any line failing rolls back the header, the earlier lines,
their stock levels and the sequence increment.

### `apply_movement` gains one argument

```python
def apply_movement(*, article, site, type, reason, quantity, user,
                   unit_cost=None, reference=None, note=None,
                   stock_transaction=None, field_prefix="") -> StockMovement:
```

Named `stock_transaction`, **not** `transaction` — that name is already bound
to `django.db.transaction` in the module, and shadowing it inside the function
that opens the atomic block is how a subtle bug gets written.

This is the extension `field_prefix` was built for in sub-project 2. Sales
will add `sale=` the same way.

### The three-way `reference` split

Subtle enough to write down, because two of the three are called `reference`:

| where | value |
|---|---|
| `transaction.reference` | always the generated `TR-YYYY-NNNN` |
| `transaction.userReference` | what the user typed, or `null` |
| each `movement.reference` | what the user typed, **or the TR number** when blank |

The last row is the surprising one, and it comes straight from
`services/stock.ts`: a movement with no delivery-note number of its own is
still traceable to its transaction through the ledger's `reference` column.

## API surface

```
GET  /api/stock/transactions/       ?search= &type= &reason=
                                    &dateFrom= &dateTo= &page= &pageSize=
POST /api/stock/transactions/
GET  /api/stock/transactions/{id}/
```

No `PATCH` and no `DELETE`. Read for any authenticated user; create for
Manager and above — the same split as movements.

Ordered `-createdAt` and not otherwise sortable, matching `listTransactions`.
Search covers `reference`, `user_reference`, `supplier_name` and `note`.
`dateFrom` / `dateTo` resolve through `apps/common/dates.py` in
`SHOP_TIME_ZONE`, exactly as the movement list does.

The **detail** read returns `StockTransactionDetail` — the list shape plus
`lines`, each line being `{movementId, article, quantity, quantityBefore,
quantityAfter, unitCost}` resolved back from its movement row. The list read
never includes lines; that is what `lineCount` and `totalQuantity` are
denormalised for.

## Validation

Messages are the frontend's own, in French.

| condition | key | message |
|---|---|---|
| no lines | `lines` | Ajoutez au moins un article à la transaction. |
| duplicate article | `lines.N.articleId` | Cet article est déjà présent dans la transaction. |
| article deleted | `lines.N.articleId` | Cet article n'existe plus. |
| non-integer or negative quantity | `lines.N.quantity` | La quantité doit être un nombre entier positif. |
| zero quantity, type ≠ ADJUSTMENT | `lines.N.quantity` | La quantité doit être supérieure à zéro. |
| `OUT` past available | `lines.N.quantity` | Stock insuffisant : … (from `apply_movement`) |
| unchanged `ADJUSTMENT` count | `lines.N.quantity` | La quantité comptée est identique au stock actuel. |
| `reference` over 40 chars | `reference` | La référence est trop longue. |
| `note` over 300 chars | `note` | La note ne peut pas dépasser 300 caractères. |

Duplicate articles are rejected rather than summed: summing makes the ledger
ambiguous and raises an ordering question with no good answer.

The dotted keys are why `flatten_errors` produces dotted paths and why
`apply_movement` took a `field_prefix` from the start. `lib/form-errors.ts`
feeds them to `setError` verbatim, and react-hook-form resolves
`lines.2.quantity` to the third row of the line editor.

## Testing

TDD, API-level, using the existing fixtures and factories. New factories:
`StockTransactionFactory`, `DocumentSequenceFactory`.

- **Numbering** — the first reference of a year is `TR-2026-0001`; the next is
  `0002`; a new year restarts at `0001` while the old year's counter is
  untouched; the format is zero-padded to four digits; a failed create leaves
  **no gap**; two prefixes (`TR`, `FA`) count independently.
- **All-or-nothing** — a transaction whose third line has insufficient stock
  writes no header, no movements, and leaves every stock level and the counter
  exactly as they were.
- **Line errors** — each row of the validation table, asserting the exact
  dotted key so a mismatch with react-hook-form's field names fails here.
- **Creation side effects** — one movement per line, each carrying the header;
  `lineCount` and `totalQuantity` correct, including an `ADJUSTMENT`
  transaction where `totalQuantity` sums derived deltas rather than the
  submitted targets.
- **The `reference` split** — a blank user reference puts the TR number on
  every movement; a supplied one puts that on the movements and leaves
  `reference` as the TR number.
- **Movement payload** — `transactionId` now carries a value for a
  transaction's lines and stays `null` for a standalone movement.
- **Supplier guard** — deleting a supplier with transactions returns 409, not
  a 500 from `ProtectedError`; `supplierName` survives a supplier rename.
- **Detail payload** — exact key set against `StockTransactionDetail`, lines
  in a stable order.
- **List** — filters, `SHOP_TIME_ZONE` date bounds, search across all four
  fields, `-createdAt` ordering, and a flat query count.
- **Permissions** — cashier reads and cannot create; manager creates; `PATCH`
  and `DELETE` return 405 on both the list and detail routes.

No test count is predicted.

## Risks

**`select_for_update` is a silent no-op on SQLite.** Gapless, collision-free
numbering is therefore aspirational until Postgres. This is the third
sub-project to record the same caveat; it is the strongest single argument for
doing the Postgres move before the shop goes live.

**Serialised creation.** Holding the counter lock until commit means
concurrent transaction creates queue behind one another. Correct, and free at
one shop's volume, but it is a design choice rather than an accident.

**`line_count` and `total_quantity` are denormalised.** Nothing updates a
transaction, so they cannot drift today — but that guarantee rests entirely on
immutability. If a later sub-project adds an edit path, these must be
recomputed there or they become the lie the frontend reads.

## Frontend type changes required

None. Sub-project 1's two changes — `User` gaining `role`, and
`Session.token` becoming `accessToken` + `refreshToken` — remain the only ones
outstanding, and are still due at cutover.
