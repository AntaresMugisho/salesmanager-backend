# Sub-project 6 — Reports: design

**Date:** 2026-08-08
**Status:** approved
**Depends on:** sub-projects 1–5 (all merged to `master`)

## Goal

Serve the four printable reports the frontend already builds — compte de
résultat, ventes, rentabilité, stock et mouvements — as four read endpoints,
computing every shared figure with the arithmetic sub-project 5 already tested
rather than a second copy of it.

## The contract

The frontend is the authority, as in every previous sub-project. The payloads
are fixed by `types/dto.ts` lines 304–479 (`ReportMeta`, `ResultReport`,
`SalesReport*`, `Profitability*`, `StockReport*`, `MovementSummaryRow`,
`SupplierPurchaseRow`, `MovementJournalRow`) and the arithmetic by
`features/reports/lib/{result,sales,profitability,stock}-report.ts`.

Each of those four builders has a sibling `.test.ts`, and all four are pure
functions. That is what makes the Node cross-checks in this sub-project
possible for every report.

`features/reports/lib/csv.ts` and `download-csv.ts` are **out of scope**: CSV
export is generated in the browser from the payload. The backend serves JSON
only.

## Endpoints

All four are `GET`, all take the same inclusive range, all require manager or
above — the README role table puts « Dépenses, finances, rapports » out of a
cashier's reach entirely.

```
GET /api/reports/result/         ?from=YYYY-MM-DD&to=YYYY-MM-DD
GET /api/reports/sales/          ?from=YYYY-MM-DD&to=YYYY-MM-DD
GET /api/reports/profitability/  ?from=YYYY-MM-DD&to=YYYY-MM-DD
GET /api/reports/stock/          ?from=YYYY-MM-DD&to=YYYY-MM-DD
```

Range parsing reuses `apps.finance.serializers.parse_range` unchanged: both
bounds required, inclusive, `from` no later than `to`, and errors keyed
literally `from` and `to`.

Every payload carries `meta: {range, generatedAt}`. `generatedAt` is stamped in
the view from `timezone.now()`, so the printed « Édité le » belongs to the
response rather than to whenever the page last rendered, and a document can
never print a period its figures do not cover.

## Architecture

A new `apps/reports` whose builders are pure and import the shared arithmetic
from `apps.finance`. This mirrors the frontend's own split — `features/reports`
beside `features/finance` — and keeps each builder small enough to read in one
sitting.

| File | Responsibility | Imports Django |
|---|---|---|
| `apps/common/collation.py` | `collation_key(name)` — the fr-FR sort key | no |
| `apps/stock/status.py` | `derive_stock_status(quantity, threshold)` | no |
| `apps/reports/facts.py` | the app's only ORM seam | yes |
| `apps/reports/result.py` | assembles the compte de résultat | no |
| `apps/reports/sales.py` | totals, VAT rows, customer rows, invoice rows | no |
| `apps/reports/profitability.py` | margin by article and by category | no |
| `apps/reports/stock.py` | inventory, movement summary, purchases, journal | no |
| `apps/reports/views.py` / `urls.py` | four thin views on one base class | yes |

Modified:

- `apps/finance/facts.py` — widen the `sales` and `lines` projections by three
  fields (below).
- `apps/sales/totals.py` — gains `compute_balance` and `group_vat_by_rate`.
- `apps/sales/serializers.py` — `get_balance` delegates to `compute_balance`.
- `apps/stock/models.py` — `StockLevel.status` delegates to
  `derive_stock_status`.
- `apps/catalogue/models.py` — `name_sort` on `Category`, `Supplier`, `Article`.
- `apps/catalogue/views.py` — `ordering`/`ordering_aliases` for `name_sort`.
- `pytest.ini` — one fatal warning (below).

**Data flow:** view → `parse_range` → `load_facts(site)` +
`load_report_facts(site)` → pure builder → `Response`.

The two pure-module rules from sub-projects 4 and 5 carry over unchanged, and
both are enforced by tests: **no Django import** in any pure module, and **no
bare `round()`** anywhere in the arithmetic — money rounds through
`apps.common.money.round_half_up`, and percentages are not rounded at all.

## French collation

The stock report sorts category names, and article names within a category,
with `localeCompare(name, "fr-FR")`. Python's default sort gets this badly
wrong, because it compares code points:

```
SQLite / Python default : Fruits | Oignons | Zeste | Épicerie | Œufs
fr-FR                   : Épicerie | Fruits | Œufs | Oignons | Zeste
```

`Épicerie` and `Œufs` are not merely misplaced, they are pushed past `Zeste` to
the end of the list.

### The key

```
collation_key(s) = casefold(strip_combining(NFKD(expand_ligatures(s))))
```

with an explicit ligature table:

```python
LIGATURES = {"Œ": "OE", "œ": "oe", "Æ": "AE", "æ": "ae", "ß": "ss"}
```

The table is not redundant with NFKD. Unicode gives `Œ` **no compatibility
decomposition at all** — `unicodedata.normalize("NFKD", "Œ") == "Œ"` — so
without the table `Œufs` sorts after `Zeste` even with full normalisation.
`ç → c` and `ù → u` do come from NFKD.

Verified against `localeCompare(…, "fr-FR")` under Node over a 58-name French
corpus: **the sorted key sequence is identical.**

### Ties are broken by id, and this is a known limit

Names that collate equally — `Cafe`/`Café`, `Boeuf`/`Bœuf`, `eau`/`Eau`,
`Elan`/`élan`/`ÉLAN` — produce the same key. ICU then decides at a tertiary
level, preferring unaccented before accented, plain before ligature, lowercase
before uppercase. This design does **not** replicate those tertiary weights;
it sorts by `(collation_key, id)` so the output is deterministic.

The consequence, stated plainly: for two catalogue names differing only by
accent, case or ligature, this backend may order them differently from the
frontend's mock. Every distinct name is ordered identically. Replicating ICU's
tertiary level was considered and rejected as a hand-rolled collation
implementation with more surface to get subtly wrong than the defect it fixes.

### `name_sort` on the catalogue models

The same key fixes a **pre-existing, user-visible bug** outside the reports:
`Category`, `Supplier` and `Article` all declare `ordering = ["name"]`, which
on SQLite is byte order, and the frontend renders list responses in API order
without re-sorting. Accented names therefore appear last on the article,
category and supplier screens today.

Sorting in Python cannot fix it, because that would break pagination — the
sort has to stay in SQL. So each of the three models gains a `name_sort`
column, populated from `collation_key(self.name)` in `save()`, with
`Meta.ordering = ["name_sort"]`, and a data migration that backfills existing
rows. `name_sort` is never serialized; it is an ordering key, not part of the
contract.

**`max_length` must be double the source field, not equal to it.** Ligature
expansion lengthens the key — `Œ → OE`, `ß → ss` — so a name at the limit can
produce a key twice as long, and an equal `max_length` would raise a
`DataError` on a pathological name:

| Model | `name` | `name_sort` |
|---|---|---|
| `Category` | 60 | 120 |
| `Supplier` | 80 | 160 |
| `Article` | 120 | 240 |

Views keep `ordering_fields = ["name", ...]` so the query parameter the
frontend sends is unchanged, and `ordering_aliases = {"name": "name_sort"}`
maps it through the existing `AliasedOrderingFilter` already used for
`stock → stock_quantity`.

**The view's own `ordering` attribute must be `["name_sort"]`, not `["name"]`.**
DRF applies aliases only on the query-parameter path: `get_ordering` calls
`remove_invalid_fields` — where `AliasedOrderingFilter` resolves aliases — only
when `?ordering=` is present, and otherwise returns `get_default_ordering(view)`
untouched. Leaving `ordering = ["name"]` would therefore alias correctly when
the client sorts explicitly and silently fall back to byte order when it does
not, which is the common case. Verified by reading
`rest_framework.filters.OrderingFilter.get_ordering`.

## Facts

`apps.finance.facts.load_facts` is widened by exactly three fields, all of
which the reports read and finance does not:

- `sales.customer_id` — groups the sales report's customer rows
- `sales.discount` — the sales report's `discounts` total
- `lines.vat_rate` — groups the sales report's VAT rows

This mirrors the frontend, where the shared `loadFacts` already returns the
wider `ReportFacts` and the finance module simply reads a narrower view of it.
Adding keys to the projection cannot affect the finance folds, which name the
fields they read.

`apps/reports/facts.py` adds what only the reports need:

- **catalogue index** — every article resolved to `sku`, `name`, `unit`,
  `purchase_price`, `category_id`, `category_name`. Not site-scoped: articles
  and categories carry no site.
- **stock levels** for the site — `article_id`, `quantity`,
  `reorder_threshold`
- **movements** for the site — the journal's fields plus `unit_cost` and
  `transaction_id`
- **supplier by transaction**, and **supplier names** — a movement carries no
  supplier of its own; its transaction does, and an article's default supplier
  is not necessarily who a given purchase came from.

Like the finance seam, these are **not** range-filtered: inventory is as-of-now
and the period-scoped folds filter in Python through `in_range`, so the
inclusive-bounds rule lives in exactly one tested place.

## Shared helpers extracted to `apps/sales/totals.py`

Both are pure, both currently exist only on the frontend, and both are needed
by the sales report.

**`compute_balance(total, paid_amount, status)`** — zero on a cancelled sale
whatever was paid on it, floored at zero otherwise. The rule is presently
inline in `SaleSerializer.get_balance`; that method will call this function
instead, so the sale detail and the sales report cannot drift.

**`group_vat_by_rate(lines)`** — one row per rate, ascending, with
`base = total − vat_amount` and `total = Σ(line_total − discount_share)`.

`vat_rate` is a `DecimalField(max_digits=5, decimal_places=2)`. Grouping by
`Decimal` is safe — `Decimal("16.00") == Decimal("16.0")` and the two hash
alike — but the wire needs a number, and `REST_FRAMEWORK` already sets
`COERCE_DECIMAL_TO_STRING: False`, so rates serialize as JSON numbers to match
`vatRate: number`.

## The four reports

### Compte de résultat

```
{meta, summary: FinanceSummary, expenses: ExpenseBreakdownRow[]}
```

Deliberately thin — `summarise(facts, tz, start, end)` and
`build_expense_breakdown(...)`, both already tested in
`apps/finance/aggregate.py`. Recomputing any of it here would create a second
arithmetic that could drift from `/finances`.

### Rapport des ventes

```
{meta, totals: SalesReportTotals, vat: VatBreakdownRow[],
 customers: SalesReportCustomerRow[], invoices: SalesReportInvoiceRow[]}
```

- `revenueHT`, `vatCollected`, `receipts`, `receivables` come from
  `summarise`, not from a second fold.
- `receivables` is **as of today, not period-scoped** — the document says
  « à ce jour ».
- `receipts` includes payments on sales later cancelled: the cash moved.
- `invoices` is every sale in the period, cancelled included, oldest first.
  `balance` comes from `compute_balance`, so a cancelled sale shows what was
  paid and owes nothing.
- `customers` is completed sales only, largest total first, with all
  walk-in sales folded onto one row labelled `Client de passage`.
- `cancelledCount` is `len(in_period) − len(completed)`.
- `vat` groups the lines of completed sales only.

### Rapport de rentabilité

```
{meta, categories: ProfitabilityRow[], articles: ProfitabilityRow[],
 lowMargin: ProfitabilityRow[], totals: ProfitabilityTotals}
```

- Every figure starts from `line_revenue_ht` and `line_margin`, the same
  per-line functions `/finances` uses, so these rows roll up to the compte de
  résultat's totals by construction rather than by coincidence.
- `cogs` per row is `Σ quantity × unit_cost`.
- The article's **name and SKU come from the sale line's snapshot**, never from
  the catalogue: a renamed or repriced article must not rewrite what a past
  period says was sold. The catalogue is consulted for one thing only — which
  category the article belongs to.
- `categories` and `articles` are highest margin first; `lowMargin` is the
  rows with `margin <= 0`, **worst first**, because that is the actionable half
  of the document.
- `marginRate` is an unrounded float, 0 when revenue is 0, never NaN.

### Rapport de stock et mouvements

```
{meta, categories: StockReportCategoryGroup[], stockTotals,
 movementSummary: MovementSummaryRow[], supplierPurchases: SupplierPurchaseRow[],
 journal: MovementJournalRow[]}
```

**Two halves that do not share a date.** `categories` and `stockTotals`
describe stock as of `meta.generatedAt`; everything below describes
`meta.range`. The document states this in words.

- Inventory is valued at the article's **current** `purchase_price`
  (`value = quantity × purchase_price`), and the document says so.
- `status` comes from a new pure `apps/stock/status.py::derive_stock_status(
  quantity, threshold)` — `<= 0` is `OUT_OF_STOCK`, `<= threshold` is `LOW`,
  otherwise `IN_STOCK`, both comparisons inclusive. `StockLevel.status` is
  changed to delegate to it rather than repeat it, so this report adds the
  canonical encoding instead of a fifth ad-hoc copy. The two SQL encodings
  (`article_queryset`'s annotation and `ArticleFilterSet`) cannot call a Python
  function and stay as they are; see follow-ups.
- Category groups sort by `collation_key(category_name)`, articles within a
  group by `collation_key(name)`, ties by id.
- `movementSummary` sorts by a fixed type order `IN, OUT, ADJUSTMENT` then a
  fixed reason order `PURCHASE, SALE, RETURN, DAMAGE, LOSS, COUNT_CORRECTION,
  OTHER`, so the table reads the same way every time.
- `supplierPurchases` covers `IN`/`PURCHASE` movements only, largest cost
  first, with purchases whose transaction names no supplier folded onto a row
  labelled `Fournisseur non renseigné`.
- **A purchase with no unit cost contributes zero, never the article's current
  price** — valuing it at today's price would rewrite what the period actually
  cost. `withoutCostCount` keeps the omission visible.
- `journal` is every movement in the period, oldest first, unpaginated. The DTO
  has no pagination and a report is one document, so this follows the contract;
  see the follow-up on volume.

## Three fallbacks that are unreachable here

The frontend's builders defend against a sold article missing from the
catalogue (`Sans catégorie`), a moved article missing from it (`Article
supprimé`), and a stock level whose article is gone. It needs to: IndexedDB has
no foreign keys.

This backend does. `SaleLine.article`, `StockMovement.article` and
`Article.category` are all `PROTECT` and non-nullable, so the database refuses
the delete that would produce any of those states.

Those branches are therefore **not implemented**. Each is replaced by a test
asserting `ProtectedError` on the corresponding delete, which turns what would
be untestable dead code into a stated, verified invariant. If a future
migration relaxes one of those foreign keys, the test fails and points here.

## Errors

| Case | Response |
|---|---|
| `from` or `to` missing | 400, `{"from": [...], "to": [...]}` |
| either malformed | 400 on the offending key |
| `from` later than `to` | 400 on `from` |
| cashier | 403 |
| owner, manager | 200 |
| period with no data | 200, zeroed totals and empty arrays — never 404 |

An empty period is a valid answer, not an error: a shop that sold nothing in
July has a July compte de résultat, and it reads zero.

## Testing

1. **Node cross-checks for the two builders that fold and sort** — `sales` and
   `profitability` — over randomised facts, as in sub-project 5. Not all four,
   and the reasons matter:

   - `result` delegates entirely to `summarise` and `build_expense_breakdown`,
     which already carry this comparison in
     `apps/finance/tests/test_aggregate.py`. A second one would test the same
     code through an extra layer of indirection.
   - `stock` does grouping and fixed-order sorting; its one genuinely
     divergence-prone element is French collation, and that is checked against
     **real ICU** rather than a transcription — a stronger check than this one.

   What this compares, precisely: the JS is a **transcription** of
   `features/reports/lib/*.ts`, not an import of it, since running the real
   modules would need a TypeScript toolchain in the test path. It catches
   Python/JavaScript semantic divergence; it does not catch a transcription
   that is faithfully wrong in both languages.

   The comparison is mutation-tested. Four deliberate breakages must each be
   caught: `margin_rate` rounded, `lowMargin` narrowed from `<= 0` to `< 0`,
   the customer balance not floored per sale, and `cancelledCount` ignoring
   the range. The second of those **escaped** on the first attempt — purely
   random values essentially never produce a margin of exactly zero, so the
   boundary was untested until the generator was taught to emit zero-margin
   lines. A cross-check that cannot fail reads as coverage while providing
   none.
2. **Collation:** the 58-name corpus, asserting the sorted key sequence equals
   `localeCompare(…, "fr-FR")`; explicit cases for `Œ`, `Æ`, `ç`, `ù`; and
   tie-break determinism.
3. **Cross-report consistency**, the highest-value class:
   `result.summary.revenue == sales.totals.revenueHT ==
   profitability.totals.revenue`, and `profitability.totals.margin ==
   result.summary.grossMargin`. Three documents, one arithmetic.
4. **Referential invariants:** the three `ProtectedError` tests above.
5. **`name_sort`:** the backfill migration populates existing rows, and the
   list endpoints return accented names in fr-FR order.
6. **Purity:** no Django import in any pure module (AST-based, as in
   sub-project 5 — a docstring mentioning Django must not fail the test), and
   no bare `round()` in the arithmetic.
7. **Flat query counts** on each endpoint regardless of row volume.
8. **Permissions** on all four endpoints.

### Two test-infrastructure fixes

Both close follow-ups accumulated in earlier sub-projects.

**Make the pagination warning fatal.** `UnorderedObjectListWarning` flagged the
sub-project 4 pagination bug the whole time it existed and nobody looked,
because it is a warning:

```ini
filterwarnings =
    error::django.core.paginator.UnorderedObjectListWarning
```

The class lives in **`django.core.paginator`**, not in `rest_framework` — DRF's
paginator delegates to Django's `Paginator`, which is what emits it.
`rest_framework.pagination.UnorderedObjectListWarning` does not exist.

Measured rather than assumed: naming the DRF path does **not** produce a silent
no-op, as first supposed. pytest imports the category before Django is
configured, so the suite dies at collection with `ImproperlyConfigured` — loud,
immediate, and nothing to do with pagination.

(Note for the record: this warning was never suppressed by `pytest.ini`, whose
`addopts` is only `-q --strict-markers`. It was hidden by a `-p no:warnings`
flag passed by hand during development. The fix is to make it fatal and to
stop passing that flag.)

**One loud sentinel instead of three silent skips.** `apps/sales/tests/
test_totals.py`, `apps/finance/tests/test_period.py` and `test_aggregate.py`
each skip their Node comparison when `node` is absent. On a CI box without
Node the suite passes while testing none of the cross-language agreement.
Replace with a single test that **fails** when `node` is missing unless
`ALLOW_MISSING_NODE=1` is set, leaving the per-test skips in place for local
convenience.

## Follow-ups

New:

- The stock report's `journal` is unpaginated by contract. A busy shop over a
  90-day range could return thousands of rows in one response. If it becomes a
  problem the fix is a contract change, negotiated with the frontend, not a
  silent cap.
- Ties in `collation_key` are broken by id rather than ICU's tertiary weights,
  so names differing only by accent, case or ligature may order differently
  from the frontend.
- `name_sort` is maintained in `save()`, so a `bulk_create` or a
  `queryset.update(name=...)` bypasses it. No code path does either today.
  A `GeneratedField` would close this, but Django cannot express the key in SQL.

Carried forward, still open:

- The stock-status rule is down from five encodings to three:
  `derive_stock_status` (now canonical, used by `StockLevel.status` and the
  stock report), `article_queryset`'s SQL annotation, and `ArticleFilterSet`'s
  SQL buckets — plus the frontend's `deriveStatus`. Closing the last two needs
  a single SQL expression shared by both, which is worth doing but is not this
  sub-project's business.
- `DocumentSequence` is not scoped by site, so two sites share one reference
  counter.
- `UserViewSet` uses DRF's permissive `OrderingFilter` while the catalogue uses
  the strict one that 400s on an unknown field.
