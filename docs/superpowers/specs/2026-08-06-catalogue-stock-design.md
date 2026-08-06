# Sub-project 2 — Catalogue & Stock

Design, 2026-08-06.

## Context

Sub-project 1 shipped identity and the wire conventions. It shipped no business
domain. This is the first sub-project that does.

As before, **the contract is given, not designed.** `types/domain.ts` and
`types/dto.ts` in `stockmanager-frontend` fix every payload, and the mock
services fix every rule: `services/categories.ts`, `services/suppliers.ts`,
`services/articles.ts` and the non-transaction half of `services/stock.ts` are
the specification this document implements. Where a rule below looks arbitrary,
it is because the frontend already made the choice.

Read sub-project 1's spec first for the error envelope, camelCase translation,
pagination and permission conventions. This document does not restate them; it
extends them in exactly two places, both noted in §Conventions extended.

## Decisions taken

| Question | Decision |
|---|---|
| Scope | **Catalogue + single movements + dashboard.** Everything except the three transaction functions, which are sub-project 3. |
| Stock quantity | **A separate `StockLevel` model**, not columns on `Article`. Mirrors the frontend's `stockLevels` table and keeps `siteId` honest. |
| Permissions | **Read for any authenticated user, write for Manager and above, `DELETE` for Owner only.** |
| Invalid filter values | **400 with `fieldErrors`.** `?stockStatus=FOO` fails loudly rather than reading as "no filter". Sub-project 1's `?isActive=` is retrofitted onto this. |
| Filtering | **`django-filter` 26.1.** Its `raise_exception` default already produces the 400 above. |
| `salePrice >= purchasePrice` | **Enforced server-side**, mirroring the frontend's cross-field rule. |
| Decimal rendering | **`COERCE_DECIMAL_TO_STRING = False` globally**, so `vatRate` renders as a JSON number. |
| Calendar-date interpretation | **New `SHOP_TIME_ZONE` setting** — see §Calendar dates, the one genuinely new problem in this sub-project. |

## Scope

**In:** `Category`, `Supplier`, `Article`, `StockLevel`, `StockMovement`; full
CRUD for the first three; movement create and list; the low-stock list; the
dashboard statistics endpoint; `django-filter` adoption and the strict-filter
convention; the `?isActive=` retrofit on `UserViewSet`.

**Out, deliberately:** stock transactions and `TR-YYYY-NNNN` numbering
(sub-project 3); anything that reads or writes a sale (sub-project 4); article
image upload, which no frontend screen offers — `imageUrl` is modelled and
always serialises `null`.

## Architecture

```
apps/
  common/          # extended, not replaced
    filters.py     # + StrictBooleanFilter, AliasedOrderingFilter
    dates.py       # + SHOP_TIME_ZONE calendar-date bounds
    views.py       # + CatalogueViewSet base
  catalogue/
    models.py      # Category, Supplier, Article
    serializers.py # + ArticleRefSerializer, StockSummarySerializer
    filters.py     # ArticleFilterSet, and the simple search-only sets
    views.py       # CategoryViewSet, SupplierViewSet, ArticleViewSet
    urls.py
    tests/
  stock/
    models.py      # StockLevel, StockMovement
    services.py    # apply_movement — the single writer
    serializers.py # StockMovementSerializer, MovementCreateSerializer
    filters.py     # MovementFilterSet
    views.py       # MovementViewSet, LowStockView, DashboardView
    urls.py
    tests/
```

**The dependency runs one way: `apps.stock` imports from `apps.catalogue`, never
the reverse.** This is why `ArticleRefSerializer` and `StockSummarySerializer`
live in `catalogue` even though one of them describes a stock concept — the
movement serializer needs `ArticleRef`, and putting it in `stock` would close a
cycle. `StockLevel.status` is a model property, so the catalogue serializer
reads a derived status without importing the stock app at all.

Sub-project 3's `StockTransaction` extends `apps/stock/`. Sub-project 4's `Sale`
gets a new `apps/sales/`, which will import from both.

## Data model

### `Category`

| field | type | notes |
|---|---|---|
| `id` | UUID pk | |
| `name` | `CharField(60)` | unique, case-insensitive |
| `description` | `CharField(200, null, blank)` | serialised `null` when empty |

`articleCount` is annotated at read time (`Count("articles")`), never stored. It
counts **all** articles, active and archived — matching `withArticleCounts` in
`services/categories.ts`, which does not filter on `isActive`.

### `Supplier`

| field | type | notes |
|---|---|---|
| `id` | UUID pk | |
| `name` | `CharField(80)` | unique, case-insensitive |
| `contact_name` | `CharField(80, null, blank)` | |
| `email` | `EmailField(null, blank)` | |
| `phone` | `CharField(20, null, blank)` | |
| `address` | `CharField(200, null, blank)` | |
| `notes` | `CharField(500, null, blank)` | |
| `is_active` | `BooleanField(default=True)` | |
| `created_at` | `DateTimeField(auto_now_add)` | |

### `Article`

| field | type | notes |
|---|---|---|
| `id` | UUID pk | |
| `sku` | `CharField(32)` | unique, case-insensitive |
| `barcode` | `CharField(13, null)` | unique when present; 8 or 13 digits |
| `name` | `CharField(120)` | |
| `description` | `CharField(500, null, blank)` | |
| `category` | FK → `Category`, `PROTECT` | `related_name="articles"` |
| `supplier` | FK → `Supplier`, `PROTECT`, null | |
| `unit` | `TextChoices(5)` | `PIECE / KG / LITRE / PAQUET / CARTON` |
| `purchase_price` | `PositiveIntegerField` | cents |
| `sale_price` | `PositiveIntegerField` | cents |
| `vat_rate` | `DecimalField(5, 2)` | percent, 0–100 |
| `is_active` | `BooleanField(default=True)` | |
| `image_url` | `URLField(null)` | always `null` today |
| `created_at` / `updated_at` | auto | |

`PROTECT` rather than `CASCADE` on both FKs: the frontend's delete guards return
409 when a category or supplier is still referenced, and `PROTECT` makes the
database agree with that promise instead of silently deleting a shop's whole
catalogue when someone removes a category.

`vat_rate` is the sub-project's only decimal. The frontend's zod schema marks
`purchasePrice`, `salePrice`, `initialQuantity` and `reorderThreshold` `.int()`
and pointedly does not mark `vatRate`, whose form field normalises a decimal
comma — so `5,5` is a rate a user can enter and the model must store.

### `StockLevel`

| field | type | notes |
|---|---|---|
| `id` | UUID pk | |
| `article` | FK → `Article`, `CASCADE` | `related_name="levels"` |
| `site` | FK → `Site`, `PROTECT` | |
| `quantity` | `PositiveIntegerField(default=0)` | |
| `reorder_threshold` | `PositiveIntegerField(default=0)` | |

`UniqueConstraint(article, site)`. `CASCADE` here, unlike the catalogue FKs: a
level has no meaning without its article, and `removeArticle` deletes both
together.

`status` is a property, deriving exactly what `deriveStatus` derives:

```
quantity <= 0                  -> OUT_OF_STOCK
quantity <= reorder_threshold  -> LOW
otherwise                      -> IN_STOCK
```

### `StockMovement`

| field | type | notes |
|---|---|---|
| `id` | UUID pk | |
| `article` | FK → `Article`, `PROTECT` | |
| `site` | FK → `Site`, `PROTECT` | |
| `type` | `TextChoices` | `IN / OUT / ADJUSTMENT` |
| `reason` | `TextChoices` | seven values |
| `quantity` | `PositiveIntegerField` | always positive; `type` gives direction |
| `quantity_before` | `PositiveIntegerField` | frozen at write time |
| `quantity_after` | `PositiveIntegerField` | frozen at write time |
| `unit_cost` | `PositiveIntegerField(null)` | cents |
| `reference` | `CharField(40, null, blank)` | |
| `note` | `CharField(300, null, blank)` | |
| `user` | FK → `User`, `PROTECT` | |
| `user_name` | `CharField(150)` | denormalised at write time |
| `created_at` | `DateTimeField(auto_now_add)` | |

Movements are append-only. Nothing in this sub-project or any later one updates
or deletes one; a correction is a new compensating movement.

`user_name` is denormalised deliberately. The ledger must still read correctly
after a user is renamed, and `MovementJournalRow` in the reports sub-project
prints `userName` on a document. `PROTECT` on `user` is what makes sub-project
1's deactivate-never-delete policy load-bearing rather than decorative.

**`transactionId` and `saleId` have no columns yet.** The serializer emits a
constant `null` for both, satisfying the `StockMovement` type. Sub-projects 3
and 4 each add one nullable FK and swap one serializer line. The alternative —
unconstrained UUID columns sitting there for two sub-projects — buys nothing,
since nothing can write them until those models exist. The `?saleId=` movement
filter is deferred to sub-project 4 along with its column.

## The single writer

`apps/stock/services.py::apply_movement()` is the only code that changes a
quantity after article creation. It mirrors `applyMovementLine` in
`services/stock.ts`, including that function's central constraint: the read of
the current level and the write of the new one must be serialised, or two
concurrent movements both read the same stale `quantityBefore` and one
overwrites the other's result.

```python
def apply_movement(*, article, site, type, reason, quantity, unit_cost,
                   reference, note, user, field_prefix="") -> StockMovement:
```

It runs inside `transaction.atomic()` and takes `select_for_update()` on the
level row. It creates the level if absent.

| type | `quantity` means | result |
|---|---|---|
| `IN` | delta | `after = before + quantity` |
| `OUT` | delta | 400 if `quantity > before`, else `after = before − quantity` |
| `ADJUSTMENT` | counted target | `after = quantity`, recorded `= abs(quantity − before)`, 400 if that is 0 |

The two 400s carry the frontend's own messages, on the `quantity` field:

- `Stock insuffisant : {before} unité(s) disponible(s) actuellement.`
- `La quantité comptée est identique au stock actuel.`

`field_prefix` exists from day one so sub-project 3 can route a line's error to
`lines.2.quantity`. Sub-project 1's `flatten_errors` already produces dotted
paths, and the frontend's `lib/form-errors.ts` already consumes them; building
the parameter now costs one argument and saves reworking the signature under a
caller.

Sub-project 4 will post a sale's stock movements through this same function.
Neither a sale nor a transaction gets its own way to change a quantity.

## Article creation

`ArticleCreateDto` carries `initialQuantity` and `reorderThreshold`, which are
not `Article` fields. Creation therefore writes three rows in one transaction:
the article, its `StockLevel`, and — when `initialQuantity > 0` — an opening
movement, so a level can never exist without a matching ledger entry.

The opening movement is fixed, not client-supplied: type `IN`, reason
`PURCHASE`, `unit_cost` = the article's `purchasePrice`, note `Stock initial`.

`ArticleUpdateDto` omits `initialQuantity` by design — once an article exists,
stock changes only through movements. `reorderThreshold` remains editable and is
the only part of the level that `PATCH /api/articles/{id}/` touches.

**Consequence worth stating:** an article created with any opening stock can
never be hard-deleted, because its opening movement trips the
has-movements guard permanently. This is inherited from the frontend, which
behaves identically, and is why archiving exists.

## Article list queryset

`?stockStatus=` and `ordering=stock` both need the quantity in SQL, so the
queryset annotates it rather than walking the relation:

```python
levels = StockLevel.objects.filter(article=OuterRef("pk"), site=current_site)

Article.objects
    .select_related("category", "supplier")
    .annotate(
        stock_quantity=Coalesce(
            Subquery(levels.values("quantity")[:1]), 0,
            output_field=IntegerField(),
        ),
        stock_threshold=Coalesce(
            Subquery(levels.values("reorder_threshold")[:1]), 0,
            output_field=IntegerField(),
        ),
    )
```

The serializer builds `StockSummary` from those annotations, not from the
related object. `ordering=stock` maps to `stock_quantity` through
`OrderingFilter`'s field mapping — the annotation name and the public sort key
differ, and the mapping is where they meet. One queryset therefore serves the sort, the filter and the
payload without N+1 — a list of 500 articles must issue a constant number of
queries, and this is asserted in the tests rather than assumed.

`stockStatus` filters through the same three boundaries as the property, as
`Q` expressions over the annotations. The property and the filter deriving
status from one shared definition is the point; two definitions drift.

## Calendar dates

**This is the one genuinely new problem in this sub-project, and it is not
inherited from the frontend — it is created by moving the logic to a server.**

`MovementListParams.dateFrom` / `dateTo` are bare local calendar dates
(`"2026-07-01"`), and `DashboardStats.movementsToday` counts movements since
the start of today. In the browser both resolve against the user's local
timezone; `services/stock.ts` says so explicitly and parses without a `Z`
suffix on purpose.

Sub-project 1 set `TIME_ZONE = "UTC"`. Resolving these bounds in UTC would put
movements recorded in the first hours of a Kinshasa morning (UTC+1) into the
previous day, on both the movement list and the dashboard tile.

This spec adds `SHOP_TIME_ZONE`, read from `.env`, defaulting to
`Africa/Kinshasa`. Storage stays UTC and `TIME_ZONE` stays `UTC`; the new
setting is used **only** to convert a bare calendar date into an instant:

- `dateFrom` → local midnight, converted to UTC
- `dateTo` → local `23:59:59.999`, converted to UTC (inclusive, as the frontend has it)
- `movementsToday` → local start of today, converted to UTC

Sub-projects 5 and 6 need this more than this one does — every finance period
and every report range is a local calendar range — so establishing it here is
what stops four more sub-projects from each inventing a bound.

## API surface

All endpoints require authentication. `POST`, `PATCH` require Manager or above.
`DELETE` requires Owner.

### Categories

```
GET    /api/categories/       ?search= &page= &pageSize=
POST   /api/categories/
GET    /api/categories/{id}/
PATCH  /api/categories/{id}/
DELETE /api/categories/{id}/
```

Ordered by `name`. Search covers name and description. `DELETE` returns 409
when the category still has articles, with the frontend's message including the
count and its French plural: `Cette catégorie contient 3 articles et ne peut
pas être supprimée.`

### Suppliers

```
GET    /api/suppliers/        ?search= &page= &pageSize=
POST   /api/suppliers/
GET    /api/suppliers/{id}/
PATCH  /api/suppliers/{id}/
DELETE /api/suppliers/{id}/
```

Ordered by `name`. Search covers name, contact name, email and phone. `DELETE`
returns 409 when articles reference the supplier.

### Articles

```
GET    /api/articles/    ?search= &categoryId= &supplierId= &isActive=
                         &stockStatus= &ordering= &page= &pageSize=
POST   /api/articles/
GET    /api/articles/{id}/
PATCH  /api/articles/{id}/
DELETE /api/articles/{id}/
```

Default ordering `name`; also `sku`, `createdAt`, `salePrice`, `stock`, each
with the `-` descending form. Search covers name, SKU and barcode. `DELETE`
returns 409 when the article has any movement: `Cet article possède un
historique de mouvements et ne peut pas être supprimé. Vous pouvez l'archiver.`

There is no `archive` action. The frontend's `archiveArticle` is
`updateArticle(id, { isActive: false })`, which `PATCH` already serves.

### Stock

```
GET    /api/stock/movements/  ?search= &articleId= &type= &reason=
                              &dateFrom= &dateTo= &page= &pageSize=
POST   /api/stock/movements/
GET    /api/stock/low-stock/  ?search= &page= &pageSize=
GET    /api/stock/dashboard/
```

Movements are ordered `-createdAt` and are not otherwise sortable. Search covers
article name, article SKU and reference.

`low-stock` returns `Article` objects — the same payload as
`/api/articles/` — filtered to active articles whose status is `LOW` or
`OUT_OF_STOCK`, ordered ruptures first and then by ascending quantity. The
predicate is shared with the dashboard's `lowStockCount` so the tile and the
list it links to can never disagree.

`dashboard` returns `DashboardStats`, unpaginated:

| field | definition |
|---|---|
| `articleCount` | active articles |
| `stockValue` | `Σ quantity × article.purchasePrice`, in cents |
| `lowStockCount` | the shared low-stock predicate |
| `movementsToday` | movements since local start of today (see §Calendar dates) |

## Validation

Mirrored from the frontend's zod schemas, so the API cannot be used to create
data the forms would refuse to produce. Messages are the frontend's own, in
French.

| field | rule |
|---|---|
| `Category.name` | 2–60, unique case-insensitively — `Une catégorie porte déjà ce nom.` |
| `Category.description` | ≤ 200 |
| `Supplier.name` | 2–80, unique case-insensitively — `Un fournisseur porte déjà ce nom.` |
| `Supplier.phone` | `^$\|^[\d\s+().-]{6,20}$` |
| `Supplier.notes` | ≤ 500 |
| `Article.sku` | ≤ 32, unique case-insensitively — `Cette référence est déjà utilisée.` |
| `Article.barcode` | 8 or 13 digits, unique when present — `Ce code-barres est déjà utilisé.` |
| `Article.name` | 2–120 |
| `Article.vatRate` | 0–100 |
| `Article.salePrice` | `>= purchasePrice`, error on `salePrice` |
| movement `quantity` | integer ≥ 0; `> 0` unless `ADJUSTMENT` |
| movement `reference` | ≤ 40 |
| movement `note` | ≤ 300 |

Case-insensitive uniqueness is enforced by a functional index on `Lower(name)`
plus a serializer check, not by the serializer alone. The serializer produces
the French message; the index is what makes the guarantee true under
concurrency. This is a deliberate departure from sub-project 1's email
normalisation, which relied on `save()` and is recorded there as a follow-up.

Optional strings follow sub-project 1's `Site` convention exactly: the column is
`null=True, blank=True`, the serializer field is
`required=False, allow_blank=True, allow_null=True`, and a `validate()` pass
normalises `""` and whitespace to `None`. The frontend posts `""` from an
untouched optional input and its types promise `string | null` back.

This matters most for `Article.barcode`, which is also unique: `""` is a value
that collides with itself, so two articles without barcodes would clash, while
`NULL` never compares equal to `NULL`. The convention and the constraint agree
only because storage is `NULL`.

The `type` / `reason` pairing is **not** enforced. `REASONS_BY_TYPE` in
`types/domain.ts` populates the form's select; `services/stock.ts` never
validates against it, and neither does this API.

## Conventions extended

Sub-project 1's conventions carry over unchanged. Two additions:

### Strict filters

`apps/common/filters.py` gains `StrictBooleanFilter`. An unparseable value
returns 400 with `fieldErrors` keyed by the camelCase parameter, rather than
being silently dropped.

Choice filters need nothing new: `django-filter`'s `ChoiceFilter` already
rejects an unknown value, and Django ships the French message for it. Only
booleans are broken.

`django-filter`'s `DjangoFilterBackend.raise_exception` already defaults to
`True` and produces exactly that shape for choice fields. **Booleans need more
work:** `BooleanFilter` uses `django_filters.widgets.BooleanWidget`, whose
`value_from_datadict` maps any unrecognised value to `None` *before* validation
runs, so the field's `clean()` never sees it. `StrictBooleanFilter` must
override both the form field and the widget. Verified during design:
with only the field overridden, `?isActive=banana` still returns 200.

Accepted true values are `true` and `1`, false values `false` and `0`, all
case-insensitive; anything else is a 400. Absent means no filter.

Sub-project 1's hand-rolled `?isActive=` on `UserViewSet` is retrofitted onto
`StrictBooleanFilter`, closing the follow-up recorded in that plan and leaving
one convention rather than two.

`ordering` gets the same treatment, for the same reason. DRF's `OrderingFilter`
**silently drops** an unrecognised term and falls back to the default ordering —
verified by reading `remove_invalid_fields`, which filters the term list rather
than rejecting it. `AliasedOrderingFilter` in `apps/common/filters.py` raises
400 instead, and additionally maps a public sort key onto a different queryset
expression, which `ordering=stock` needs: the annotation is `stock_quantity`,
and DRF's valid-field check compares against queryset names directly.

### Shared viewset base

`apps/common/views.py` gains a base combining `CamelCaseQueryParamsMixin`, the
standard pagination, the search and ordering backends, `DjangoFilterBackend`,
and the read / Manager-writes / Owner-deletes permission map. The three
catalogue viewsets differ only in queryset, serializer and filterset.

This exists because the permission map would otherwise be copied into three
viewsets here and roughly a dozen across sub-projects 3–6, and a permission
rule that lives in twelve places is a permission rule that will eventually be
wrong in one of them.

## Testing

TDD throughout, API-level, using sub-project 1's `conftest.py` fixtures.
New factories: `CategoryFactory`, `SupplierFactory`, `ArticleFactory`,
`StockLevelFactory`, `StockMovementFactory`.

Coverage the plan must produce:

- **Models** — status derivation at every boundary (0, below, equal to, above
  threshold); the `(article, site)` unique constraint; `PROTECT` behaviour.
- **CRUD** — create, read, update, delete for all three catalogue resources,
  including the exact serialised payload against the frontend's type.
- **Permissions** — the full matrix: cashier reads and is refused every write;
  manager writes and is refused every delete; owner does everything. Refusals
  are 403 with `permission_denied`, never 404.
- **Delete guards** — 409 with the counted French message for all three.
- **Uniqueness** — case-insensitive clashes on category name, supplier name,
  article SKU and barcode, on create and on update, including that an object
  does not clash with itself.
- **Stock arithmetic** — `IN`, `OUT`, `OUT` past available, `ADJUSTMENT` up,
  down, and to an unchanged value; `quantityBefore` / `quantityAfter` correct
  on each; the level and the movement agreeing afterwards.
- **Article creation** — the level is written; the opening movement is written
  only when `initialQuantity > 0`; the movement's fixed fields are right.
- **Filters** — every filter matches, and every invalid value returns 400 with
  the camelCase key. Including `?isActive=banana` on `/api/users/`.
- **Ordering** — each of the five keys, both directions, `-createdAt` proving
  the camelCase translation still works through `django-filter`.
- **Query counts** — `/api/articles/` and `/api/stock/movements/` issue a
  constant number of queries regardless of page size.
- **Calendar dates** — `dateFrom` / `dateTo` bounds and `movementsToday`
  resolved in `SHOP_TIME_ZONE`, tested with a movement near local midnight,
  which is where a UTC implementation gives the wrong answer.

No test count is predicted. Sub-project 1's spec predicted one four times and
was wrong every time.

## Risks

**`select_for_update` is a silent no-op on SQLite.** Verified on Django 6.0.7:
`connection.features.has_select_for_update` is `False` and the call neither
locks nor raises. The serialisation in `apply_movement` is therefore aspirational
until the Postgres move — the same posture as sub-project 1's last-owner TOCTOU.
It is written now because it costs nothing, becomes correct on Postgres without
a code change, and SQLite's database-level write lock makes the window narrow
in the single-shop deployment this targets.

**Case-insensitive uniqueness needs a functional index that SQLite supports but
does not enforce identically to Postgres** on collation edge cases. The
serializer check is what users hit; the index is a backstop.

**`COERCE_DECIMAL_TO_STRING = False` is global.** No existing endpoint serialises
a decimal, so nothing changes today, but the setting is inherited by
sub-projects 5 and 6 where money aggregates live. Those are integer cents by
contract, so the exposure is small — but the setting must be revisited if any
later payload wants string decimals for precision.

**`SHOP_TIME_ZONE` is a new axis of configuration.** A deployment that leaves it
at the default while operating elsewhere gets subtly wrong day boundaries.
It is documented in `.env.example` and the README.

## Frontend type changes required

None. Every payload in this sub-project matches `types/domain.ts` as written.

Sub-project 1's two changes — `User` gaining `role`, and `Session.token`
becoming `accessToken` + `refreshToken` — remain the only ones outstanding, and
are still due at cutover.
