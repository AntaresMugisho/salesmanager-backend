# Sub-project 5 — Expenses & Finance

Design, 2026-08-08.

## Context

Sub-projects 1–4 built identity, the catalogue, the stock ledger, transactions
and sales. This sub-project adds expenses and the three finance reads, and in
doing so retires the last calculation modules the frontend owns:
`features/finance/lib/aggregate.ts` and `features/finance/lib/period.ts`.

That retirement was decided at the very start:

> **Finance & report arithmetic: server-side.** Endpoints return finished
> `FinanceSummary` / `SalesReport` shapes. The frontend's `features/*/lib/*.ts`
> calculation modules retire when sub-projects 5 and 6 land.

The contract is `Expense` in `types/domain.ts`; `ExpenseCreateDto`,
`ExpenseListParams`, `DateRange`, `FinanceSummary`, `FinanceBucket`,
`FinanceSeries`, `ExpenseBreakdownRow`, `TopArticleRow`, `UnpaidSaleRow` and
`FinanceBreakdown` in `types/dto.ts`; and the rules in `services/expenses.ts`,
`services/finance.ts`, `services/facts.ts` and the two `lib` modules.

Read sub-project 1's spec for the wire conventions, 2's for filters,
permissions and calendar dates, 3's for numbering, 4's for money arithmetic and
derived-not-stored figures. This document does not restate them.

## Decisions taken

| Question | Decision |
|---|---|
| Aggregation | **A pure Python module fed by narrow querysets.** Django-free, so it can be diffed against the frontend's own code in Node. |
| Bucket labels | **A hardcoded 12-entry table transcribed from `Intl`.** Django's French locale is wrong for two months. |
| Scope | **Expenses CRUD and all three finance reads together.** |

## The label problem

`FinanceBucket.label` is documented as "French, pre-formatted: « 12 juil. » or
« juil. 2026 »". The frontend produces it with
`Intl.DateTimeFormat("fr-FR", {day: "numeric", month: "short"})`.

Django's own French locale does **not** agree. Verified:

| month | Django `j N` | contract (`Intl`) |
|---|---|---|
| January | `12 jan.` | `12 janv.` |
| February | `12 fév.` | `12 févr.` |
| the other ten | — | identical |

Using Django's formatter would mislabel January and February on every chart —
silently, and visible only as a wrong tick on an axis.

The backend therefore carries a literal twelve-entry table taken from `Intl`:

```
janv.  févr.  mars  avr.  mai  juin  juil.  août  sept.  oct.  nov.  déc.
```

**Four of them take no trailing period** — `mars`, `mai`, `juin`, `août` — which
is CLDR's rule that an unabbreviated form gets no full stop. That irregularity
is the whole reason to transcribe rather than generate: a hand-rolled
`name[:4] + "."` would be wrong for six of the twelve.

A test asserts all twelve against Node, so the table cannot drift from the
contract without failing.

## Scope

**In:** the `Expense` model with full CRUD; `apps/finance/facts.py`,
`period.py` and `aggregate.py`; the summary, series and breakdown endpoints.

**Out, deliberately:** the four report documents, which are sub-project 6 and
reuse this module; period *presets* (`THIS_MONTH`, `LAST_30_DAYS`…), which
`resolvePreset` computes in the browser and sends as a resolved `from`/`to`;
and any write path for finance — the three reads are reads.

## Architecture

```
apps/
  finance/            # new app
    facts.py          # the only file that touches the ORM
    period.py         # granularity, buckets, labels — no Django
    aggregate.py      # summarise / bucketise / build_breakdown — no Django
    serializers.py
    views.py
    urls.py
  expenses/           # new app
    models.py         # Expense
    serializers.py
    filters.py
    views.py
    urls.py
```

Two apps rather than one. `apps.finance` reads from sales, stock and expenses;
`apps.expenses` owns a model and knows nothing about finance. Folding them
together would make the model app depend on the reporting app, and
sub-project 6 will import `apps.finance` without wanting expenses' viewset.

**`period.py` and `aggregate.py` import nothing from Django.** That is the same
shape as `apps/sales/totals.py`, and for the same reason: it is what makes a
line-by-line comparison against the frontend's implementation cheap enough to
keep as a test. These are the figures a shopkeeper files taxes from; "it looks
right" is not evidence.

`facts.py` is the seam. It projects five narrow shapes with `.values()` and
hands them to the pure modules as plain dicts:

| shape | source | fields |
|---|---|---|
| `SaleFact` | `Sale` | id, created_at, status, total, vat_total, reference, customer_name |
| `SaleLineFact` | `SaleLine` | sale_id, article_id, article_name, article_sku, quantity, line_total, discount_share, vat_amount, unit_cost |
| `PaymentFact` | `Payment` | sale_id, amount, paid_at |
| `ExpenseFact` | `Expense` | category, amount, spent_at |
| `PurchaseFact` | `StockMovement` where `type=IN, reason=PURCHASE` | quantity, unit_cost, created_at |

Every one is exactly what the arithmetic reads and nothing more, matching the
frontend's comment that these are "deliberately not the domain types".

`facts.py` scopes each queryset to `Site.objects.current()`, as every other
read in this codebase does. `SaleLine` and `Payment` carry no site of their
own, so they are narrowed through the sales that do — the same route
`services/facts.ts` takes.

Note that the three imports run one way and do not close a cycle:
`apps.expenses` imports `apps.sales` for `Payment.Method`; `apps.finance`
imports `apps.expenses`, `apps.sales` and `apps.stock`; neither of those
imports `apps.finance`.

## Data model

### `Expense`

| field | type | notes |
|---|---|---|
| `id` | UUID pk | |
| `site` | FK → `Site`, `PROTECT` | |
| `category` | `TextChoices` | `RENT / SALARY / UTILITIES / TRANSPORT / SUPPLIES / TAX / OTHER` |
| `label` | `CharField(120)` | 2–120 |
| `amount` | `PositiveIntegerField` | cents, strictly positive |
| `method` | `Payment.Method` | reused, not redeclared |
| `spent_at` | `DateTimeField` | a bare date widened to local noon |
| `reference` | `CharField(40, null, blank)` | |
| `note` | `CharField(500, null, blank)` | |
| `user` | FK → `User`, `PROTECT` | |
| `user_name` | `CharField(150)` | snapshot |
| `created_at` | auto | ordering `-spent_at, -id` |

`method` reuses `apps.sales.models.Payment.Method` rather than redeclaring five
identical choices. `apps.expenses` therefore imports `apps.sales`, one way.

**An expense is editable and deletable**, unlike a sale. `removeExpense` says
why: "Nothing references an expense, so unlike a customer this deletes
outright." It is a private record of money leaving, not a document issued to
anyone.

`spent_at` arrives as a bare calendar date and is widened to **local noon** via
the existing `at_local_noon`, for the reason the frontend gives: noon so that
neither a positive nor a negative offset can push the instant onto the adjacent
day — "the very boundary the reports slice at".

## Period handling

`apps/finance/period.py`:

```python
def days_in_range(start: date, end: date) -> int          # inclusive
def resolve_granularity(start, end) -> str                # "DAY" | "MONTH"
def bucket_key(moment: datetime, granularity: str) -> str # "2026-07-12" | "2026-07"
def enumerate_buckets(start, end, granularity) -> list[BucketSlot]
def in_range(moment: datetime, start: date, end: date) -> bool
```

Three rules carried over verbatim:

- **90 days is the daily/monthly threshold.** Beyond it a year would draw 365
  bars.
- **Every bucket in the range is emitted, empty ones included.** "A quiet week
  must render as zeros; dropping it would compress the x-axis and make the
  chart claim the shop traded on days it was shut."
- **Both bounds are inclusive, and membership is a calendar-day comparison**,
  not a timestamp comparison. The backend resolves each timestamp to its
  `SHOP_TIME_ZONE` calendar date — which is what `start_of_day` / `end_of_day`
  already do — because the range's bounds are days the shopkeeper picked.

## The arithmetic

`apps/finance/aggregate.py`, ported function for function.

### Summary

| field | rule |
|---|---|
| `revenue` | `Σ (total − vat_total)` over **completed** sales in range |
| `vatCollected` | `Σ vat_total` over the same |
| `cogs` | `Σ (quantity × unit_cost)` over their lines — the snapshot, never re-joined |
| `grossMargin` | `revenue − cogs` |
| `marginRate` | `margin / revenue × 100`, **0 when revenue ≤ 0** |
| `expenses` | `Σ amount` over expenses in range |
| `netResult` | `grossMargin − expenses` |
| `receipts` | `Σ amount` over payments in range |
| `purchaseDisbursements` | `Σ (quantity × (unit_cost or 0))` over purchases in range |
| `disbursements` | `purchaseDisbursements + expenses` |
| `cashBalance` | `receipts − disbursements` |
| `receivables` | **not period-scoped** — see below |
| `purchasesWithoutCost` | count of in-range purchases with a null `unit_cost` |

Three of these are easy to get subtly wrong and each gets its own test:

- **`receipts` includes payments on sales later cancelled.** The frontend says
  why: "the cash genuinely moved and there is no refund entity to undo it."
  Cancellation restores stock, not money.
- **`receivables` takes no range.** It is every completed sale's outstanding
  balance as of now, and the card that renders it says « à ce jour ». Each
  balance is floored at zero first, so an overpaid sale cannot lend its surplus
  to another's debt.
- **`purchaseDisbursements` counts `IN`/`PURCHASE` movements**, which includes
  the opening-stock movement written when an article is created. That is what
  the frontend counts, and it is defensible — opening stock was bought.

### Series

`bucketise` fills the enumerated buckets, then derives twice:

```
bucket.margin        = bucket.revenue - bucket.cogs
bucket.cumulativeCash = running total of (receipts - disbursements)
```

**`cumulativeCash` restarts at zero in the period's first bucket.** It answers
"what did this period do to my cash", not "what is in the till". Carried over
verbatim, and worth a test, because the other reading is the intuitive one.

A sale's COGS lands in the bucket of **its sale**, not of its line — the
frontend maps `saleId → bucket` first and then folds lines through that map, so
revenue and COGS can never fall in different buckets.

### Breakdown

- **`expenses`** — per category, with each one's share of the period's expense
  total as a percent, largest amount first. Share is `0` when the total is 0.
- **`topArticles`** — the **five** highest-margin articles, folded across every
  line of every completed sale in range. A line's HT revenue is
  `lineTotal − discountShare − vatAmount`, **not** `quantity × unitPrice`:
  the latter is TTC and ignores the discount allocation, so the per-article
  panel would disagree with the revenue card. Margin is that minus
  `quantity × unitCost`.
- **`unpaidSales`** — every completed sale with a positive balance, **whenever
  it happened**, largest balance first. Not range-scoped, for the same reason
  as `receivables`.

## Floats

`marginRate` and `share` are percentages, and the contract types them `number`
with no stated precision. The frontend does not round them:
`(margin / revenue) * 100`.

**The backend must not round them either.** Python and JavaScript both use
IEEE-754 doubles, so an unrounded division agrees bit-for-bit; introducing a
`round()` on either side is what would create a difference. This is the exact
opposite of the rule for money in sub-project 4 — money is integer cents and
never a float, percentages are floats and never rounded — and the two rules
sit one module apart, so both are stated explicitly where they apply.

Every other figure in this sub-project is integer cents.

## API surface

```
GET    /api/expenses/           ?search= &category= &dateFrom= &dateTo= &page= &pageSize=
POST   /api/expenses/
GET    /api/expenses/{id}/
PATCH  /api/expenses/{id}/
DELETE /api/expenses/{id}/

GET    /api/finance/summary/    ?from=YYYY-MM-DD &to=YYYY-MM-DD
GET    /api/finance/series/     ?from= &to=
GET    /api/finance/breakdown/  ?from= &to=
```

Expenses are ordered `-spentAt` and not otherwise sortable. Search covers
`label`, `reference` and `note`.

`from` and `to` are **required** on all three finance reads, and `from > to` is
a 400 — `isValidRange` in the frontend refuses it before sending, so a request
that arrives inverted is a bug worth reporting rather than silently swapping.

Per the README's role table, **expenses and finance are Manager and above**.
A cashier gets 403 on all eight routes.

## Validation

| condition | key | message |
|---|---|---|
| amount ≤ 0 | `amount` | Le montant doit être supérieur à zéro. |
| label under 2 chars | `label` | Le libellé doit contenir au moins 2 caractères. |
| label over 120 | `label` | Le libellé ne peut pas dépasser 120 caractères. |
| `spentAt` in the future | `spentAt` | La date ne peut pas être dans le futur. |
| `reference` over 40 | `reference` | La référence est trop longue. |
| `note` over 500 | `note` | La note ne peut pas dépasser 500 caractères. |
| `from` after `to` | `from` | La date de début doit précéder la date de fin. |

"In the future" is a **calendar-day** comparison in `SHOP_TIME_ZONE`, matching
the frontend's comment: "an expense dated today is fine at any hour."

## Testing

TDD. Three layers, because the modules have three different shapes.

- **`period.py`** — no database. Day counts across a month boundary, a leap
  day and a DST-free year; the 90-day threshold at 90 and 91; bucket
  enumeration including empty buckets and a range that starts mid-month;
  inclusive bounds at both ends; and **all twelve labels asserted against Node**.
- **`aggregate.py`** — no database, fed hand-built fact dicts. Every row of the
  summary table; a cancelled sale excluded from revenue but its payment
  included in receipts; receivables ignoring the range and flooring an
  overpayment; `marginRate` 0 rather than `NaN` at zero revenue;
  `cumulativeCash` restarting at zero; COGS landing in its sale's bucket; the
  five-article cap; HT revenue not being `quantity × unitPrice`. Plus a
  randomised comparison against the frontend's `aggregate.ts` in Node, skipped
  when node is absent.
- **`facts.py` and the endpoints** — API-level. The exact payload key sets; the
  Manager-and-above matrix; expense CRUD, filters and the future-date guard;
  `from > to` returning 400; and a query-count assertion on each finance read,
  since each one loads several tables.

No test count is predicted.

## Risks

**Memory grows with history, not with the period.** `receivables` and
`unpaidSales` need every completed sale ever, so a finance request reads the
whole sales table however narrow the range. At one shop's volume — a few
thousand sales a year — that is a few hundred kilobytes and well inside one
pass. It stops being fine somewhere around six figures of sales, and the fix is
known: replace the two unbounded folds with `aggregate()` calls and keep the
period-scoped folds as they are. Named here so the trigger is recognisable
rather than discovered.

**The pure modules can drift from the frontend.** The Node comparison is the
guard, and it only runs where `node` is installed. On a box without it the
suite still passes, so a CI environment that lacks node silently loses the
strongest test in this sub-project. Worth an explicit skip message rather than
a silent one.

**`marginRate` and `share` are unrounded floats by design.** Anyone "tidying"
them with `round()` breaks parity with the frontend. The docstring says so; a
test asserting a value with a long decimal expansion makes it fail loudly.

**Four float/integer boundaries now exist** — money cents, VAT decimals,
percentages, and quantities. Sub-project 6 adds report totals that must
reconcile with these exactly ("Must equal the compte de résultat's revenue,
COGS and gross margin"), so any drift introduced here surfaces there.

## Frontend type changes required

None. Sub-project 1's two changes — `User` gaining `role`, and
`Session.token` becoming `accessToken` + `refreshToken` — remain the only ones
outstanding, and are still due at cutover.
