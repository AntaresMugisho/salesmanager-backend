# Customers & Sales Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement customers, sales with snapshotted lines, `FA-YYYY-NNNN` invoice numbering, payments and cancellation — completing `services/customers.ts` and `services/sales.ts`.

**Architecture:** A new `apps/sales/` holding `Customer`, `Sale`, `SaleLine` and `Payment`, with the money arithmetic isolated in a Django-free `apps/sales/totals.py` so it can be tested against the frontend's own implementation. Every stock change still goes through `apply_movement`, which gains its third and final caller. `paidAmount`, `balance` and `paymentStatus` are annotated on every read and never stored.

**Tech Stack:** Django 6.0.7, DRF 3.17.1, django-filter 26.1, pytest 9.1.1 + pytest-django 4.12.0 + factory-boy 3.3.3. No new dependencies.

## Global Constraints

Every task's requirements implicitly include this section.

- **Read the spec first:** `docs/superpowers/specs/2026-08-06-customers-sales-design.md`. Sub-project 1's spec has the wire conventions, 2's the filter/permission/date ones, 3's the numbering and immutability patterns.
- **Python env:** pyenv's `stock`. Run as `~/.pyenv/versions/stock/bin/python` / `~/.pyenv/versions/stock/bin/pytest`. There is no `.venv`.
- **The suite takes ~5½ minutes.** Run the focused file while iterating; run everything before committing.
- **TDD, strictly.** Write the failing test, watch it fail for the right reason, then implement.
- **Never use Python's `round()` in this sub-project.** It is banker's rounding; the frontend is half-up. Use `apps.common.money.round_half_up`, which is exact integer arithmetic. `Math.round(2.5)` is 3 and `round(2.5)` is 2 — that one cent lands on an invoice.
- **Money is integer cents throughout.** No floats anywhere in `totals.py`.
- **Every user-facing string is French**, via `gettext_lazy as _`.
- **Field-error keys must match react-hook-form's names** — camelCase, dotted for array rows. `flatten_errors` + `camelize` already produce `lines.1.quantity` from DRF's nested shape; raise dotted string keys directly from `validate()` for cross-field cases.
- **`Site.objects.current()`** is how you get the site.
- **Models inherit `apps.common.models.UUIDModel`** — it supplies `id`, `created_at`, `updated_at`.
- **Optional strings:** column `null=True, blank=True`; serializer `required=False, allow_blank=True, allow_null=True`; normalise `""` to `None`.
- **Commit at the end of every task**, with the trailer:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01BVSaiKSTQQad3uwxNLsNPU
  ```
- **Never predict a test count.** Run the suite and report what it says.

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/common/permissions.py` | + `RoleScopedPermissionMixin` |
| `apps/common/views.py` | `CatalogueViewSet` re-expressed through the mixin |
| `apps/common/money.py` | **new** — `round_half_up`, `format_cents` |
| `apps/common/dates.py` | + `at_local_noon` |
| `apps/sales/totals.py` | **new** — the ported arithmetic, no Django imports |
| `apps/sales/models.py` | `Customer`, `Sale`, `SaleLine`, `Payment` |
| `apps/sales/querysets.py` | the annotated sale queryset |
| `apps/sales/services.py` | `create_sale`, `add_payment`, `cancel_sale` |
| `apps/sales/serializers.py` | customer, sale, line, payment shapes |
| `apps/sales/filters.py` | `SaleFilterSet` |
| `apps/sales/views.py` | `CustomerViewSet`, `SaleViewSet` |
| `apps/stock/models.py` | + `StockMovement.sale` |
| `apps/stock/services.py` | `apply_movement` gains `sale=` |

---

## Task 1: Extract the permission mixin

**Files:**
- Modify: `apps/common/permissions.py`, `apps/common/views.py`, `apps/stock/views.py`, `apps/accounts/views.py`
- Test: `apps/common/tests/test_permissions.py` (extend)

**Interfaces:**
- Consumes: `apps.common.permissions.IsOwner`, `IsManagerOrAbove`.
- Produces: `apps.common.permissions.RoleScopedPermissionMixin` with class attributes `permission_map: dict[str, type]` and `default_permission: type`, and a `get_permissions()` that resolves `self.action` against the map.

Three viewsets hand-roll the same map today and sales would add two more. Doing this first means the new viewsets are written against the mixin rather than retrofitted.

- [ ] **Step 1: Write the failing test**

Append to `apps/common/tests/test_permissions.py`:

```python
class TestRoleScopedPermissionMixin:
    """The map is keyed by DRF action name, which is also the method name for
    a custom @action — so `cancel` and `add_payment` work the same way."""

    def _view(self, action, permission_map=None, default=None):
        from rest_framework.permissions import IsAuthenticated

        from apps.common.permissions import RoleScopedPermissionMixin

        class Fixture(RoleScopedPermissionMixin):
            pass

        Fixture.permission_map = permission_map or {}
        if default is not None:
            Fixture.default_permission = default

        view = Fixture()
        view.action = action
        return view

    def test_an_unlisted_action_gets_the_default(self):
        from rest_framework.permissions import IsAuthenticated

        view = self._view("list")
        assert isinstance(view.get_permissions()[0], IsAuthenticated)

    def test_a_listed_action_gets_its_class(self):
        from apps.common.permissions import IsOwner

        view = self._view("destroy", {"destroy": IsOwner})
        assert isinstance(view.get_permissions()[0], IsOwner)

    def test_the_default_can_be_overridden(self):
        from apps.common.permissions import IsManagerOrAbove

        view = self._view("list", default=IsManagerOrAbove)
        assert isinstance(view.get_permissions()[0], IsManagerOrAbove)

    def test_it_returns_instances_not_classes(self):
        """DRF calls has_permission on an instance; returning the class would
        raise a TypeError at request time, not at import time."""
        view = self._view("list")
        permission = view.get_permissions()[0]
        assert not isinstance(permission, type)
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/common/tests/test_permissions.py -k RoleScoped -p no:warnings`
Expected: FAIL — `ImportError: cannot import name 'RoleScopedPermissionMixin'`.

- [ ] **Step 3: Implement the mixin**

Append to `apps/common/permissions.py`:

```python
class RoleScopedPermissionMixin:
    """Declarative per-action permissions.

    `permission_map` maps a DRF action name — `create`, `destroy`, or a custom
    `@action`'s method name — to a permission class. Anything unlisted falls
    back to `default_permission`.

    Exists because the same read/manager-writes/owner-deletes map was written
    out in three viewsets and sales would have made five. A permission rule
    living in five places is one that will eventually be wrong in one of them,
    and the failure — a cashier cancelling a sale — is silent until someone
    tries it.
    """

    permission_map: dict[str, type] = {}
    default_permission: type = IsAuthenticated

    def get_permissions(self):
        permission_class = self.permission_map.get(
            self.action, self.default_permission
        )
        return [permission_class()]
```

Add `from rest_framework.permissions import IsAuthenticated` to the imports —
the module currently imports only `SAFE_METHODS` and `BasePermission`.

- [ ] **Step 4: Re-express `CatalogueViewSet`**

In `apps/common/views.py`, replace the hand-rolled `get_permissions` with the
mixin. The action map is exactly equivalent for a `ModelViewSet`: `create`,
`update` and `partial_update` are the only actions reached by POST/PUT/PATCH.

```python
class CatalogueViewSet(
    RoleScopedPermissionMixin, CamelCaseQueryParamsMixin, viewsets.ModelViewSet
):
    """Read for anyone authenticated, write for manager and above, delete for
    the owner.

    Subclasses set `queryset` and `serializer_class`, and may set
    `search_fields`, `ordering_fields`, `ordering_aliases` and
    `filterset_class`. A subclass needing a different map overrides
    `permission_map` rather than `get_permissions`.
    """

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, AliasedOrderingFilter]

    permission_map = {
        "create": IsManagerOrAbove,
        "update": IsManagerOrAbove,
        "partial_update": IsManagerOrAbove,
        "destroy": IsOwner,
    }
```

Update the import line to bring in the mixin:

```python
from apps.common.permissions import IsManagerOrAbove, IsOwner, RoleScopedPermissionMixin
```

and delete the now-unused `from rest_framework.permissions import IsAuthenticated`
if nothing else in the module uses it.

- [ ] **Step 5: Convert `MovementViewSet` and `TransactionViewSet`**

In `apps/stock/views.py`, on both viewsets, delete the `get_permissions`
override and add the mixin plus a map.

`MovementViewSet` — add `RoleScopedPermissionMixin` as the first base class and:

```python
    permission_map = {"create": IsManagerOrAbove}
```

`TransactionViewSet` — same:

```python
    permission_map = {"create": IsManagerOrAbove}
```

Add `RoleScopedPermissionMixin` to the `apps.common.permissions` import. The
`IsAuthenticated` import stays only if `LowStockView` and `DashboardView` still
use it — they do, via `permission_classes`.

- [ ] **Step 6: Convert `UserViewSet`**

In `apps/accounts/views.py`, `UserViewSet` currently sets
`permission_classes = [IsAuthenticated, IsOwner]` — owner-only for every
action, including reads. That is not the catalogue map and must not become it.

Add the mixin and express the same rule:

```python
class UserViewSet(
    RoleScopedPermissionMixin, CamelCaseQueryParamsMixin, viewsets.ModelViewSet
):
    ...
    default_permission = IsOwner
```

and delete the `permission_classes` line. `IsOwner` already returns False for
an unauthenticated or inactive user — its `_active(request)` check runs first —
so dropping `IsAuthenticated` from the chain changes nothing.

- [ ] **Step 7: Run the whole suite**

Run: `~/.pyenv/versions/stock/bin/pytest -p no:warnings`

Expected: everything still passes. This task changes no behaviour; the existing
permission tests across accounts, catalogue and stock are the proof. If any
fail, the map is wrong — do not adjust the test.

- [ ] **Step 8: Commit**

```bash
git add apps/common apps/stock/views.py apps/accounts/views.py
git commit -m "Extract the role-scoped permission mixin"
```

---

## Task 2: Money primitives

**Files:**
- Create: `apps/common/money.py`
- Modify: `apps/common/dates.py`
- Test: `apps/common/tests/test_money.py`

**Interfaces:**
- Consumes: `apps.common.dates.shop_timezone`.
- Produces:
  - `apps.common.money.round_half_up(numerator: int, denominator: int) -> int`
  - `apps.common.money.format_cents(cents: int) -> str`
  - `apps.common.dates.at_local_noon(value: date) -> datetime`

- [ ] **Step 1: Write the failing test**

Create `apps/common/tests/test_money.py`:

```python
"""Money primitives.

`round_half_up` exists because Python's `round()` is banker's rounding and
JavaScript's `Math.round` is half-up. The frontend computes what a sale is
worth; a divergence here is a wrong number on an invoice.
"""

from datetime import date, datetime, timezone as dt_timezone

import pytest
from django.test import override_settings

from apps.common.dates import at_local_noon
from apps.common.money import format_cents, round_half_up


class TestRoundHalfUp:
    @pytest.mark.parametrize(
        ("numerator", "denominator", "expected"),
        [
            (1, 2, 1),      # 0.5  -> 1   (Python's round() gives 0)
            (3, 2, 2),      # 1.5  -> 2
            (5, 2, 3),      # 2.5  -> 3   (Python's round() gives 2)
            (7, 2, 4),      # 3.5  -> 4
            (1, 3, 0),      # 0.33 -> 0
            (2, 3, 1),      # 0.67 -> 1
            (0, 7, 0),
            (7, 7, 1),
        ],
    )
    def test_matches_javascript_math_round(self, numerator, denominator, expected):
        assert round_half_up(numerator, denominator) == expected

    def test_the_half_cases_are_where_python_round_would_disagree(self):
        """Guard the reason this function exists. If someone 'simplifies' it
        to round(n / d), these two flip."""
        assert round_half_up(1, 2) == 1 and round(1 / 2) == 0
        assert round_half_up(5, 2) == 3 and round(5 / 2) == 2

    def test_a_real_vat_extraction(self):
        # taxable 1050 cents at 16% TTC -> 1050 * 1600 / 11600
        assert round_half_up(1050 * 1600, 10000 + 1600) == 145

    def test_it_is_exact_at_magnitudes_that_would_lose_float_precision(self):
        huge = 10**18
        assert round_half_up(2 * huge + 1, 2) == huge + 1

    def test_a_zero_denominator_is_a_programming_error(self):
        with pytest.raises(ValueError):
            round_half_up(1, 0)


class TestFormatCents:
    @pytest.mark.parametrize(
        ("cents", "expected"),
        [
            (123450, "1 234,50 $US"),
            (500, "5,00 $US"),
            (0, "0,00 $US"),
            (1500, "15,00 $US"),
            (5, "0,05 $US"),
            (123456789, "1 234 567,89 $US"),
        ],
    )
    def test_matches_the_frontends_intl_output(self, cents, expected):
        """Verified against Intl.NumberFormat("fr-FR", {currency: "USD"}):
        U+202F narrow no-break space groups thousands, U+00A0 precedes $US."""
        assert format_cents(cents) == expected

    def test_the_separators_are_the_exact_unicode_the_frontend_emits(self):
        formatted = format_cents(123450)
        assert " " in formatted  # not a plain space
        assert " $US" in formatted


class TestAtLocalNoon:
    @override_settings(SHOP_TIME_ZONE="Africa/Kinshasa")
    def test_widens_a_bare_date_to_local_noon_in_utc(self):
        # Kinshasa is UTC+1, so local noon is 11:00 UTC.
        assert at_local_noon(date(2026, 7, 2)) == datetime(
            2026, 7, 2, 11, 0, tzinfo=dt_timezone.utc
        )

    @override_settings(SHOP_TIME_ZONE="Africa/Kinshasa")
    def test_noon_lands_on_the_picked_day_whatever_the_offset(self):
        """The whole point: midnight would be ambiguous across a timezone
        boundary, noon never is."""
        from apps.common.dates import end_of_day, start_of_day

        picked = date(2026, 7, 2)
        moment = at_local_noon(picked)
        assert start_of_day(picked) < moment < end_of_day(picked)

    @override_settings(SHOP_TIME_ZONE="UTC")
    def test_a_utc_shop_gets_utc_noon(self):
        assert at_local_noon(date(2026, 7, 2)) == datetime(
            2026, 7, 2, 12, 0, tzinfo=dt_timezone.utc
        )
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/common/tests/test_money.py -p no:warnings`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.common.money'`.

- [ ] **Step 3: Implement the money module**

Create `apps/common/money.py`:

```python
"""Money primitives shared by the sales and finance sub-projects.

Everything here is integer cents. No floats, anywhere.
"""


def round_half_up(numerator: int, denominator: int) -> int:
    """Round `numerator / denominator` half away from the lower value.

    This is JavaScript's `Math.round`, which the frontend's
    `features/sales/lib/totals.ts` uses for every rounded figure on a sale.
    Python's built-in `round()` is banker's rounding: `Math.round(2.5)` is 3
    while `round(2.5)` is 2, and integer-cent discount allocation lands on
    exact halves routinely. That one cent would appear on an invoice.

    Implemented as exact integer arithmetic rather than `round(n / d)` or
    `Decimal`, so there is no float in the path at all: adding half a unit
    before flooring is `(2n + d) // 2d`. Floor division on a negative operand
    rounds toward negative infinity, which is also what `Math.round(-2.5) ->
    -2` does, so the identity holds for negatives too — though every value in
    this codebase is non-negative.
    """
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return (2 * numerator + denominator) // (2 * denominator)


def format_cents(cents: int) -> str:
    """Cents to the frontend's money string: `1 234,50 $US`.

    Matches `formatMoney` in `lib/format.ts`, which is
    `Intl.NumberFormat("fr-FR", {style: "currency", currency: "USD"})`.
    Reproduced by hand rather than with `locale` or `babel`: the exact
    separators matter and process-wide locale state does not belong in a
    formatting helper.

    The two spacing characters are not ordinary spaces — U+202F (narrow
    no-break) groups thousands and U+00A0 (no-break) precedes the symbol.
    """
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    grouped = f"{whole:,}".replace(",", " ")
    return f"{sign}{grouped},{fraction:02d} $US"
```

- [ ] **Step 4: Add `at_local_noon`**

Append to `apps/common/dates.py`:

```python
def at_local_noon(value: date) -> datetime:
    """Local noon on `value`, as an aware UTC datetime.

    A payment's `paidAt` arrives as a bare calendar date from a picker. Noon
    rather than midnight because midnight sits on a day boundary: shifted by
    any timezone offset it lands on the adjacent day, while noon stays on the
    day the user picked whatever the offset.
    """
    local = datetime.combine(value, time(12, 0), tzinfo=shop_timezone())
    return local.astimezone(UTC)
```

`time` is already imported at the top of the module.

- [ ] **Step 5: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/common/tests/test_money.py -p no:warnings`
Expected: all PASS.

- [ ] **Step 6: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/common
git commit -m "Add money primitives and the local-noon date helper"
```

---

## Task 3: The sale arithmetic

**Files:**
- Create: `apps/sales/__init__.py`, `apps/sales/apps.py`, `apps/sales/totals.py`, `apps/sales/tests/__init__.py`
- Test: `apps/sales/tests/test_totals.py`

**Interfaces:**
- Consumes: `apps.common.money.round_half_up`.
- Produces:

```python
@dataclass(frozen=True)
class LineInput:
    quantity: int
    unit_price: int        # TTC cents
    vat_rate: Decimal      # percent, e.g. Decimal("16.00")

@dataclass(frozen=True)
class LineResult:
    line_total: int
    discount_share: int
    vat_amount: int

@dataclass(frozen=True)
class SaleTotals:
    subtotal: int
    discount: int
    total: int
    vat_total: int
    lines: list[LineResult]

def allocate_discount(discount: int, line_totals: list[int], subtotal: int) -> list[int]
def compute_sale_totals(lines: list[LineInput], discount: int) -> SaleTotals
```

**This module imports nothing from Django.** That isolation is what lets the
comparison test run the same inputs through Node and diff the results.

`compute_sale_totals` takes the discount already resolved to cents.
`SaleCreateDto` carries `discount` in cents — the form resolves the percentage
before sending — so `resolveDiscountAmount` has no backend counterpart.

- [ ] **Step 1: Write the failing test**

Create `apps/sales/tests/test_totals.py`:

```python
"""Sale arithmetic, ported from features/sales/lib/totals.ts.

Pure integers, no database, no Django. The last class in this file runs the
same random inputs through the frontend's actual implementation in Node and
diffs — which is the only way to be sure a port of money arithmetic is right.
"""

import json
import shutil
import subprocess
from decimal import Decimal

import pytest

from apps.sales.totals import (
    LineInput,
    allocate_discount,
    compute_sale_totals,
)


def line(quantity, unit_price, vat_rate="16.00"):
    return LineInput(
        quantity=quantity, unit_price=unit_price, vat_rate=Decimal(vat_rate)
    )


class TestSubtotalAndTotal:
    def test_a_single_line(self):
        totals = compute_sale_totals([line(3, 1000)], discount=0)
        assert totals.subtotal == 3000
        assert totals.discount == 0
        assert totals.total == 3000
        assert totals.lines[0].line_total == 3000
        assert totals.lines[0].discount_share == 0

    def test_several_lines_sum(self):
        totals = compute_sale_totals([line(2, 1500), line(1, 700)], discount=0)
        assert totals.subtotal == 3700
        assert totals.total == 3700

    def test_a_discount_reduces_the_total(self):
        totals = compute_sale_totals([line(1, 5000)], discount=500)
        assert totals.subtotal == 5000
        assert totals.discount == 500
        assert totals.total == 4500

    def test_a_discount_equal_to_the_subtotal_zeroes_the_total(self):
        totals = compute_sale_totals([line(1, 5000)], discount=5000)
        assert totals.total == 0

    def test_an_empty_sale_is_all_zeros(self):
        totals = compute_sale_totals([], discount=0)
        assert totals.subtotal == 0
        assert totals.total == 0
        assert totals.vat_total == 0
        assert totals.lines == []

    def test_a_discount_on_nothing_is_nothing(self):
        """'A discount can only be zero when there is nothing to discount,
        whatever the caller asked for.'"""
        totals = compute_sale_totals([line(1, 0)], discount=500)
        assert totals.subtotal == 0
        assert totals.discount == 0
        assert totals.total == 0


class TestVat:
    def test_tax_is_extracted_from_a_ttc_price_not_added(self):
        """Prices are tax-inclusive: base * rate / (100 + rate)."""
        totals = compute_sale_totals([line(1, 11600, "16.00")], discount=0)
        assert totals.total == 11600
        assert totals.vat_total == 1600  # 11600 * 16 / 116

    def test_a_zero_rate_yields_no_tax(self):
        totals = compute_sale_totals([line(1, 5000, "0.00")], discount=0)
        assert totals.vat_total == 0

    def test_a_decimal_rate(self):
        # 10550 TTC at 5.5% -> 10550 * 550 / 10550 = 550
        totals = compute_sale_totals([line(1, 10550, "5.50")], discount=0)
        assert totals.vat_total == 550

    def test_tax_is_computed_after_the_discount(self):
        """The taxable base is the discounted amount, not the gross."""
        undiscounted = compute_sale_totals([line(1, 11600, "16.00")], discount=0)
        discounted = compute_sale_totals([line(1, 11600, "16.00")], discount=1160)
        assert discounted.vat_total < undiscounted.vat_total
        assert discounted.vat_total == 1440  # 10440 * 16 / 116

    def test_mixed_rates_sum_independently(self):
        totals = compute_sale_totals(
            [line(1, 11600, "16.00"), line(1, 10550, "5.50")], discount=0
        )
        assert totals.vat_total == 1600 + 550


class TestDiscountAllocation:
    def test_an_even_split(self):
        shares = allocate_discount(300, [1000, 1000, 1000], 3000)
        assert shares == [100, 100, 100]

    def test_the_shares_always_sum_to_exactly_the_discount(self):
        """Rounding each share independently would lose a cent here: three
        equal lines of a 100-cent discount would come back 33+33+33."""
        shares = allocate_discount(100, [1000, 1000, 1000], 3000)
        assert sum(shares) == 100
        assert shares == [34, 33, 33]

    def test_leftovers_go_to_the_largest_fractional_parts(self):
        shares = allocate_discount(10, [500, 300, 200], 1000)
        assert sum(shares) == 10
        assert shares == [5, 3, 2]

    def test_ties_are_broken_by_ascending_index(self):
        shares = allocate_discount(1, [1000, 1000], 2000)
        assert shares == [1, 0]

    def test_a_zero_discount_allocates_nothing(self):
        assert allocate_discount(0, [1000, 2000], 3000) == [0, 0]

    def test_a_zero_subtotal_allocates_nothing(self):
        assert allocate_discount(500, [0, 0], 0) == [0, 0]

    def test_proportional_to_line_value(self):
        shares = allocate_discount(100, [900, 100], 1000)
        assert shares == [90, 10]


class TestHalfUpRounding:
    def test_an_allocation_landing_exactly_on_a_half(self):
        """discount * lineTotal / subtotal = 2.5 exactly.

        Half-up gives 3; banker's rounding would give 2 and the shares would
        no longer sum to the discount. This is the case that makes
        round_half_up necessary rather than merely tidy.
        """
        # 5 * 100 / 200 = 2.5
        shares = allocate_discount(5, [100, 100], 200)
        assert sum(shares) == 5
        assert shares == [3, 2]

    def test_a_vat_extraction_landing_exactly_on_a_half(self):
        # taxable 2 at 25% -> 2 * 2500 / 12500 = 0.4 ... choose one that halves:
        # taxable 5 at 100% -> 5 * 10000 / 20000 = 2.5 -> 3
        totals = compute_sale_totals([line(1, 5, "100.00")], discount=0)
        assert totals.vat_total == 3


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
class TestAgainstTheFrontendImplementation:
    """Runs the same random inputs through the frontend's own code.

    This is the strongest evidence available that the port is right, and it is
    kept as a test rather than a one-off spike because the arithmetic decides
    what money is stored. Skipped rather than failed when node is absent, so a
    CI box without it does not turn the suite red.
    """

    JS = """
    function allocate(discount, lineTotals, subtotal) {
      if (discount === 0 || subtotal <= 0) return lineTotals.map(() => 0);
      const exact = lineTotals.map((lt) => (discount * lt) / subtotal);
      const shares = exact.map((v) => Math.floor(v));
      let remainder = discount - shares.reduce((a, b) => a + b, 0);
      const order = exact
        .map((v, i) => ({ i, f: v - Math.floor(v) }))
        .sort((a, b) => b.f - a.f || a.i - b.i);
      for (const e of order) {
        if (remainder <= 0) break;
        shares[e.i] += 1;
        remainder -= 1;
      }
      return shares;
    }

    function computeSaleTotals(lines, discount) {
      const lineTotals = lines.map((l) => l.quantity * l.unitPrice);
      const subtotal = lineTotals.reduce((a, b) => a + b, 0);
      const shares = allocate(discount, lineTotals, subtotal);
      const resultLines = lines.map((line, index) => {
        const lineTotal = lineTotals[index];
        const discountShare = shares[index];
        const taxable = lineTotal - discountShare;
        const vatAmount =
          line.vatRate === 0
            ? 0
            : Math.round((taxable * line.vatRate) / (100 + line.vatRate));
        return { lineTotal, discountShare, vatAmount };
      });
      const effectiveDiscount = subtotal <= 0 ? 0 : discount;
      return {
        subtotal,
        discount: effectiveDiscount,
        total: subtotal - effectiveDiscount,
        vatTotal: resultLines.reduce((s, l) => s + l.vatAmount, 0),
        lines: resultLines,
      };
    }

    const cases = JSON.parse(process.argv[1]);
    console.log(JSON.stringify(cases.map(([lines, d]) => computeSaleTotals(lines, d))));
    """

    def test_matches_on_randomised_sales(self):
        import random

        random.seed(20260806)
        cases = []
        for _ in range(300):
            count = random.randint(1, 5)
            lines = [
                {
                    "quantity": random.randint(1, 40),
                    "unitPrice": random.randint(0, 250_00),
                    "vatRate": random.choice([0, 5.5, 10, 16, 20]),
                }
                for _ in range(count)
            ]
            subtotal = sum(row["quantity"] * row["unitPrice"] for row in lines)
            cases.append([lines, random.randint(0, subtotal)])

        result = subprocess.run(
            [NODE, "-e", self.JS, json.dumps(cases)],
            capture_output=True,
            text=True,
            check=True,
        )
        expected = json.loads(result.stdout)

        for (raw_lines, discount), want in zip(cases, expected):
            got = compute_sale_totals(
                [
                    LineInput(
                        quantity=row["quantity"],
                        unit_price=row["unitPrice"],
                        vat_rate=Decimal(str(row["vatRate"])),
                    )
                    for row in raw_lines
                ],
                discount,
            )
            assert got.subtotal == want["subtotal"]
            assert got.discount == want["discount"]
            assert got.total == want["total"]
            assert got.vat_total == want["vatTotal"]
            assert [row.line_total for row in got.lines] == [
                row["lineTotal"] for row in want["lines"]
            ]
            assert [row.discount_share for row in got.lines] == [
                row["discountShare"] for row in want["lines"]
            ]
            assert [row.vat_amount for row in got.lines] == [
                row["vatAmount"] for row in want["lines"]
            ]
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/sales/tests/test_totals.py -p no:warnings`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.sales'`.

- [ ] **Step 3: Create the app package**

```bash
mkdir -p apps/sales/migrations apps/sales/tests
touch apps/sales/__init__.py apps/sales/migrations/__init__.py apps/sales/tests/__init__.py
```

Create `apps/sales/apps.py`:

```python
from django.apps import AppConfig


class SalesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sales"
    label = "sales"
    verbose_name = "Ventes"
```

Add `"apps.sales"` to `INSTALLED_APPS` in `stockmanager/settings.py`, after
`"apps.stock"`.

- [ ] **Step 4: Implement the arithmetic**

Create `apps/sales/totals.py`:

```python
"""Sale money arithmetic, ported from features/sales/lib/totals.ts.

No Django imports, no database, no floats. Pure integer cents.

The frontend shares this logic between the sale form's live footer and the
service that persists the sale, precisely so the displayed total and the
stored total cannot differ. The backend now owns the persisting half, so this
module must agree with the frontend to the cent — see
`tests/test_totals.py::TestAgainstTheFrontendImplementation`, which checks
that against the frontend's actual code.
"""

from dataclasses import dataclass
from decimal import Decimal

from apps.common.money import round_half_up


@dataclass(frozen=True)
class LineInput:
    quantity: int
    #: Tax-inclusive (TTC), in cents.
    unit_price: int
    #: Percent, e.g. Decimal("16.00") — the rate embedded in `unit_price`.
    vat_rate: Decimal


@dataclass(frozen=True)
class LineResult:
    line_total: int
    discount_share: int
    vat_amount: int


@dataclass(frozen=True)
class SaleTotals:
    subtotal: int
    discount: int
    total: int
    #: Included in `total`, never added to it. Displayed as « dont TVA ».
    vat_total: int
    lines: list[LineResult]


def allocate_discount(
    discount: int, line_totals: list[int], subtotal: int
) -> list[int]:
    """Spread a global discount across lines in proportion to their value.

    Largest-remainder method: floor every exact share, then hand the leftover
    cents one at a time to the largest fractional parts, ties broken by
    ascending line index.

    The shares therefore sum to exactly `discount`. Rounding each share
    independently would not — three lines of a 100-cent discount would come
    back as 33+33+33 and quietly lose a cent, which then shows up as a VAT
    total that disagrees with the invoice.

    Every comparison is integer: the exact share is `discount * line / subtotal`,
    so its floor is integer division and its fractional part is ordered by the
    remainder. No float is constructed, so no two shares can compare equal by
    accident.
    """
    if discount == 0 or subtotal <= 0:
        return [0] * len(line_totals)

    shares = [(discount * line_total) // subtotal for line_total in line_totals]
    remainder = discount - sum(shares)

    # Each fractional part is < 1, so the remainder is always < the line count:
    # one pass over the ordering is enough, and no line is bumped twice.
    by_largest_fraction = sorted(
        range(len(line_totals)),
        key=lambda index: (-((discount * line_totals[index]) % subtotal), index),
    )

    for index in by_largest_fraction:
        if remainder <= 0:
            break
        shares[index] += 1
        remainder -= 1

    return shares


def compute_sale_totals(lines: list[LineInput], discount: int) -> SaleTotals:
    """`discount` is already resolved to cents by the caller.

    `SaleCreateDto` carries cents — the form resolves a percentage before
    sending — so the frontend's `resolveDiscountAmount` has no counterpart
    here.
    """
    line_totals = [line.quantity * line.unit_price for line in lines]
    subtotal = sum(line_totals)

    shares = allocate_discount(discount, line_totals, subtotal)

    result_lines: list[LineResult] = []
    for index, line in enumerate(lines):
        line_total = line_totals[index]
        discount_share = shares[index]
        taxable = line_total - discount_share

        # Prices are TTC, so the tax is extracted from the discounted amount
        # rather than added on top: base * rate / (100 + rate). The rate is
        # scaled by 100 to keep the arithmetic integral — the column is
        # DecimalField(5, 2), so 5.5 becomes 550 and
        # taxable*550/10550 is exactly taxable*5.5/105.5.
        rate_scaled = int(line.vat_rate * 100)
        vat_amount = (
            0
            if rate_scaled == 0
            else round_half_up(taxable * rate_scaled, 10000 + rate_scaled)
        )

        result_lines.append(
            LineResult(
                line_total=line_total,
                discount_share=discount_share,
                vat_amount=vat_amount,
            )
        )

    # A discount can only be zero when there is nothing to discount, whatever
    # the caller asked for.
    effective_discount = 0 if subtotal <= 0 else discount

    return SaleTotals(
        subtotal=subtotal,
        discount=effective_discount,
        total=subtotal - effective_discount,
        vat_total=sum(line.vat_amount for line in result_lines),
        lines=result_lines,
    )
```

- [ ] **Step 5: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/sales/tests/test_totals.py -p no:warnings -v`
Expected: all PASS, including the Node comparison. If Node is absent it skips —
check the output says `skipped`, not `passed`, so you know which happened.

- [ ] **Step 6: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/sales stockmanager/settings.py
git commit -m "Port the sale arithmetic with exact integer rounding"
```

---

## Task 4: The sales models

**Files:**
- Create: `apps/sales/models.py`, `apps/sales/tests/factories.py`
- Modify: `apps/stock/models.py`
- Test: `apps/sales/tests/test_models.py`

**Interfaces:**
- Consumes: `apps.catalogue.models.Article`, `apps.accounts.models.Site`.
- Produces: `apps.sales.models.Customer`, `Sale`, `Sale.Status`, `SaleLine`, `Payment`, `Payment.Method`; `StockMovement.sale`; factories `CustomerFactory`, `SaleFactory`, `SaleLineFactory`, `PaymentFactory`.

`StockMovement.sale` uses the lazy string `"sales.Sale"` — `apps.sales` imports
`apps.stock`, so a real import here would close the cycle.

- [ ] **Step 1: Write the failing test**

Create `apps/sales/tests/test_models.py`:

```python
"""Sales model invariants."""

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.catalogue.tests.factories import ArticleFactory
from apps.sales.models import Customer, Payment, Sale, SaleLine
from apps.sales.tests.factories import (
    CustomerFactory,
    PaymentFactory,
    SaleFactory,
    SaleLineFactory,
)
from apps.stock.tests.factories import StockMovementFactory

pytestmark = pytest.mark.django_db


class TestCustomer:
    def test_names_differing_only_in_case_collide(self):
        CustomerFactory(name="Kivu Market")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Customer.objects.create(name="KIVU MARKET")

    def test_default_ordering_is_by_name(self):
        CustomerFactory(name="Zeta")
        CustomerFactory(name="Alpha")
        assert [c.name for c in Customer.objects.all()] == ["Alpha", "Zeta"]

    def test_a_customer_with_sales_cannot_be_deleted(self, site, owner):
        customer = CustomerFactory()
        SaleFactory(customer=customer, user=owner, site=site)
        with pytest.raises(ProtectedError):
            customer.delete()


class TestSale:
    def test_references_are_unique(self, site, owner):
        SaleFactory(reference="FA-2026-0001", user=owner, site=site)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                SaleFactory(reference="FA-2026-0001", user=owner, site=site)

    def test_the_customer_is_optional(self, site, owner):
        """Null for a « client de passage »."""
        assert SaleFactory(customer=None, user=owner, site=site).customer is None

    def test_the_billing_block_is_snapshotted(self, site, owner):
        """An invoice is a legal document: a customer moving must not rewrite
        the address on last quarter's invoices."""
        customer = CustomerFactory(name="Kivu Market", address="10 av. du Lac")
        sale = SaleFactory(
            customer=customer,
            customer_name="Kivu Market",
            customer_address="10 av. du Lac",
            user=owner,
            site=site,
        )

        customer.name = "Kivu Market SARL"
        customer.address = "99 boulevard Neuf"
        customer.save()
        sale.refresh_from_db()

        assert sale.customer_name == "Kivu Market"
        assert sale.customer_address == "10 av. du Lac"

    def test_a_user_with_sales_cannot_be_deleted(self, site, owner):
        SaleFactory(user=owner, site=site)
        with pytest.raises(ProtectedError):
            owner.delete()

    def test_newest_first(self, site, owner):
        first = SaleFactory(reference="FA-2026-0001", user=owner, site=site)
        second = SaleFactory(reference="FA-2026-0002", user=owner, site=site)
        assert list(Sale.objects.all()) == [second, first]


class TestSaleLine:
    def test_deleting_a_sale_deletes_its_lines(self, site, owner):
        """CASCADE here, unlike everywhere else: a line is part of the
        document. Nothing deletes a sale, so this never fires in practice."""
        sale = SaleFactory(user=owner, site=site)
        SaleLineFactory(sale=sale)
        sale.delete()
        assert SaleLine.objects.count() == 0

    def test_an_article_with_sale_lines_cannot_be_deleted(self, site, owner):
        line = SaleLineFactory(sale=SaleFactory(user=owner, site=site))
        with pytest.raises(ProtectedError):
            line.article.delete()

    def test_the_article_snapshot_survives_a_rename_and_reprice(
        self, site, owner
    ):
        """unit_cost is the load-bearing one: sub-project 6 computes margin
        from it and never re-joins to the article."""
        article = ArticleFactory(name="Sucre", sku="EPI-1", purchase_price=800)
        line = SaleLineFactory(
            sale=SaleFactory(user=owner, site=site),
            article=article,
            article_name="Sucre",
            article_sku="EPI-1",
            unit_cost=800,
        )

        article.name = "Sucre roux"
        article.purchase_price = 1200
        article.save()
        line.refresh_from_db()

        assert line.article_name == "Sucre"
        assert line.unit_cost == 800


class TestPayment:
    def test_a_sale_with_payments_cannot_be_deleted(self, site, owner):
        """PROTECT, where SaleLine is CASCADE: a payment is a money record
        that should block a deletion rather than vanish inside one."""
        sale = SaleFactory(user=owner, site=site)
        PaymentFactory(sale=sale, user=owner)
        with pytest.raises(ProtectedError):
            sale.delete()

    def test_payments_reach_their_sale(self, site, owner):
        sale = SaleFactory(user=owner, site=site)
        first = PaymentFactory(sale=sale, user=owner)
        second = PaymentFactory(sale=sale, user=owner)
        assert set(sale.payments.all()) == {first, second}

    def test_the_user_name_is_denormalised(self, site, owner):
        payment = PaymentFactory(sale=SaleFactory(user=owner, site=site), user=owner)
        owner.full_name = "Nom Modifié"
        owner.save()
        payment.refresh_from_db()
        assert payment.user_name != "Nom Modifié"


class TestMovementLink:
    def test_a_movement_can_carry_a_sale(self, site, owner):
        sale = SaleFactory(user=owner, site=site)
        movement = StockMovementFactory(site=site, user=owner, sale=sale)
        assert list(sale.movements.all()) == [movement]

    def test_a_standalone_movement_has_no_sale(self, site, owner):
        assert StockMovementFactory(site=site, user=owner).sale is None

    def test_a_movement_carries_at_most_one_of_transaction_and_sale(
        self, site, owner
    ):
        """Not enforced by a constraint — the writers never set both — but
        asserted so the assumption is written down somewhere executable."""
        from apps.stock.tests.factories import StockTransactionFactory

        with_sale = StockMovementFactory(
            site=site, user=owner, sale=SaleFactory(user=owner, site=site)
        )
        with_transaction = StockMovementFactory(
            site=site, user=owner, transaction=StockTransactionFactory(user=owner)
        )

        assert with_sale.transaction is None
        assert with_transaction.sale is None
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/sales/tests/test_models.py -p no:warnings`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.sales.models'`.

- [ ] **Step 3: Add the movement's sale link**

In `apps/stock/models.py`, inside `StockMovement`, immediately after the
`transaction` field:

```python
    # Lazy string for the same reason as `transaction` above, one app further
    # out: apps.sales imports apps.stock, so a real import here would close
    # the cycle. A movement carries at most one of these two links.
    sale = models.ForeignKey(
        "sales.Sale",
        on_delete=models.PROTECT,
        related_name="movements",
        null=True,
        blank=True,
        verbose_name=_("vente"),
    )
```

- [ ] **Step 4: Write the models**

Create `apps/sales/models.py`:

```python
from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Site
from apps.catalogue.models import Article
from apps.common.models import UUIDModel


class Customer(UUIDModel):
    """Structurally a Supplier plus a tax number.

    `is_active` exists so an archived customer stops appearing in the sale
    form's picker. There is deliberately no `?isActive=` list filter: the
    contract's `listCustomers` takes SimpleListParams — search only.
    """

    name = models.CharField(_("nom"), max_length=80)
    contact_name = models.CharField(
        _("nom du contact"), max_length=80, null=True, blank=True
    )
    email = models.EmailField(_("adresse e-mail"), null=True, blank=True)
    phone = models.CharField(_("téléphone"), max_length=20, null=True, blank=True)
    address = models.CharField(_("adresse"), max_length=200, null=True, blank=True)
    tax_number = models.CharField(
        _("numéro d'identification fiscale"), max_length=30, null=True, blank=True
    )
    notes = models.CharField(_("notes"), max_length=500, null=True, blank=True)
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("client")
        verbose_name_plural = _("clients")
        constraints = [
            models.UniqueConstraint(Lower("name"), name="customer_name_unique_ci"),
        ]

    def __str__(self) -> str:
        return self.name


class Sale(UUIDModel):
    """The sale *is* the invoice — `reference` is its FA-YYYY-NNNN number.

    Immutable apart from cancellation. `paidAmount`, `balance` and
    `paymentStatus` are computed on every read and are deliberately not
    columns: a stored status can disagree with the payments it summarises.
    """

    class Status(models.TextChoices):
        COMPLETED = "COMPLETED", _("Finalisée")
        CANCELLED = "CANCELLED", _("Annulée")

    reference = models.CharField(_("référence"), max_length=20, unique=True)
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="sales")
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="sales",
        null=True,
        blank=True,
        verbose_name=_("client"),
    )
    # Snapshotted, not resolved at read time. The frontend resolves live and
    # argues it is safe because deletion is blocked — true for deletion, but a
    # rename or a move would rewrite every historical invoice.
    customer_name = models.CharField(_("client"), max_length=80, null=True, blank=True)
    customer_address = models.CharField(
        _("adresse"), max_length=200, null=True, blank=True
    )
    customer_tax_number = models.CharField(
        _("numéro d'identification fiscale"), max_length=30, null=True, blank=True
    )
    status = models.CharField(
        _("statut"), max_length=16, choices=Status.choices, default=Status.COMPLETED
    )
    subtotal = models.PositiveIntegerField(_("sous-total"), default=0)
    discount = models.PositiveIntegerField(_("remise"), default=0)
    # How the discount was entered, so the UI can redisplay "10 %" rather than
    # "1 500 FC". Never used in arithmetic — `discount` is authoritative.
    discount_rate = models.DecimalField(
        _("taux de remise"), max_digits=5, decimal_places=2, null=True, blank=True
    )
    total = models.PositiveIntegerField(_("total"), default=0)
    # Included in `total`, never added to it.
    vat_total = models.PositiveIntegerField(_("TVA"), default=0)
    note = models.CharField(_("note"), max_length=300, null=True, blank=True)
    cancelled_at = models.DateTimeField(_("annulée le"), null=True, blank=True)
    cancel_reason = models.CharField(
        _("motif d'annulation"), max_length=300, null=True, blank=True
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sales"
    )
    user_name = models.CharField(_("auteur"), max_length=150)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = _("vente")
        verbose_name_plural = _("ventes")

    def __str__(self) -> str:
        return self.reference


class SaleLine(UUIDModel):
    """One line of a sale, with everything about the article frozen.

    Nothing here is resolved back to the article afterwards: repricing an
    article must not rewrite an existing sale.
    """

    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, related_name="lines", verbose_name=_("vente")
    )
    article = models.ForeignKey(
        Article, on_delete=models.PROTECT, related_name="sale_lines"
    )
    article_name = models.CharField(_("article"), max_length=120)
    article_sku = models.CharField(_("référence"), max_length=32)
    unit = models.CharField(_("unité"), max_length=8, choices=Article.Unit.choices)
    quantity = models.PositiveIntegerField(_("quantité"))
    # TTC. Defaults to the article's sale price, but may be negotiated down.
    unit_price = models.PositiveIntegerField(_("prix unitaire"))
    # The article's purchase price at sale time. Sub-project 6 computes COGS
    # and margin from this and never re-joins to the article.
    unit_cost = models.PositiveIntegerField(_("coût unitaire"))
    vat_rate = models.DecimalField(_("taux de TVA"), max_digits=5, decimal_places=2)
    line_total = models.PositiveIntegerField(_("total ligne"))
    discount_share = models.PositiveIntegerField(_("part de remise"), default=0)
    vat_amount = models.PositiveIntegerField(_("TVA"), default=0)

    class Meta:
        verbose_name = _("ligne de vente")
        verbose_name_plural = _("lignes de vente")

    def __str__(self) -> str:
        return f"{self.article_sku} × {self.quantity}"


class Payment(UUIDModel):
    """Append-only: nothing updates or deletes a payment."""

    class Method(models.TextChoices):
        CASH = "CASH", _("Espèces")
        MOBILE_MONEY = "MOBILE_MONEY", _("Mobile money")
        BANK_TRANSFER = "BANK_TRANSFER", _("Virement bancaire")
        CARD = "CARD", _("Carte")
        OTHER = "OTHER", _("Autre")

    sale = models.ForeignKey(
        Sale, on_delete=models.PROTECT, related_name="payments", verbose_name=_("vente")
    )
    amount = models.PositiveIntegerField(_("montant"))
    method = models.CharField(_("moyen"), max_length=20, choices=Method.choices)
    paid_at = models.DateTimeField(_("payé le"))
    reference = models.CharField(_("référence"), max_length=40, null=True, blank=True)
    note = models.CharField(_("note"), max_length=300, null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments"
    )
    user_name = models.CharField(_("auteur"), max_length=150)

    class Meta:
        ordering = ["paid_at", "id"]
        verbose_name = _("paiement")
        verbose_name_plural = _("paiements")

    def __str__(self) -> str:
        return f"{self.amount} — {self.sale.reference}"
```

- [ ] **Step 5: Write the factories**

Create `apps/sales/tests/factories.py`:

```python
from decimal import Decimal

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import SiteFactory, UserFactory
from apps.catalogue.tests.factories import ArticleFactory
from apps.sales.models import Customer, Payment, Sale, SaleLine


class CustomerFactory(DjangoModelFactory):
    class Meta:
        model = Customer

    name = factory.Sequence(lambda n: f"Client {n}")
    contact_name = "Marie Kabeya"
    email = factory.Sequence(lambda n: f"client{n}@exemple.cd")
    phone = "+243 990 333 444"
    address = "22 avenue des Volcans, Goma"
    tax_number = None
    notes = None
    is_active = True


class SaleFactory(DjangoModelFactory):
    class Meta:
        model = Sale

    reference = factory.Sequence(lambda n: f"FA-2026-{n + 1:04d}")
    site = factory.SubFactory(SiteFactory)
    user = factory.SubFactory(UserFactory)
    user_name = factory.LazyAttribute(lambda obj: obj.user.full_name)
    customer = None
    customer_name = None
    customer_address = None
    customer_tax_number = None
    status = Sale.Status.COMPLETED
    subtotal = 10_000
    discount = 0
    discount_rate = None
    total = 10_000
    vat_total = 1_379
    note = None


class SaleLineFactory(DjangoModelFactory):
    class Meta:
        model = SaleLine

    sale = factory.SubFactory(SaleFactory)
    article = factory.SubFactory(ArticleFactory)
    article_name = factory.LazyAttribute(lambda obj: obj.article.name)
    article_sku = factory.LazyAttribute(lambda obj: obj.article.sku)
    unit = factory.LazyAttribute(lambda obj: obj.article.unit)
    quantity = 2
    unit_price = 5_000
    unit_cost = 3_000
    vat_rate = Decimal("16.00")
    line_total = 10_000
    discount_share = 0
    vat_amount = 1_379


class PaymentFactory(DjangoModelFactory):
    class Meta:
        model = Payment

    sale = factory.SubFactory(SaleFactory)
    user = factory.SubFactory(UserFactory)
    user_name = factory.LazyAttribute(lambda obj: obj.user.full_name)
    amount = 5_000
    method = Payment.Method.CASH
    paid_at = factory.LazyFunction(timezone.now)
    reference = None
    note = None
```

- [ ] **Step 6: Make `sale_id` a real serializer field**

`StockMovementSerializer` still returns a hardcoded `None` for `sale_id` — the
last placeholder left from sub-project 2. In `apps/stock/serializers.py`,
replace:

```python
    # No column yet. Sub-project 4 adds `sale` and swaps this line. The key
    # must be present now because the frontend's StockMovement type requires
    # it.
    sale_id = serializers.SerializerMethodField()
```

with:

```python
    sale_id = serializers.UUIDField(read_only=True)
```

and delete the method:

```python
    def get_sale_id(self, obj) -> None:
        return None
```

Then extend `apps/stock/tests/test_movements.py`, inside `TestCreate`, to prove
it carries a value — the mirror of the `transaction_id` test added in
sub-project 3:

```python
    def test_sale_id_carries_a_value_for_a_sale_line(
        self, auth_client, manager, site
    ):
        """The last hardcoded null is gone. A movement carries at most one of
        transactionId and saleId."""
        from apps.sales.services import create_sale
        from apps.stock.tests.factories import StockLevelFactory

        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=50)
        sale = create_sale(
            lines=[{"article": article, "quantity": 2, "unit_price": 5_000}],
            user=manager,
            site=site,
        )

        row = auth_client(manager).get(URL).json()["results"][0]

        assert row["saleId"] == str(sale.id)
        assert row["transactionId"] is None
```

> This test imports `create_sale`, which Task 6 writes. Add the serializer
> change and the existing `test_transaction_id_and_sale_id_are_null` check now;
> add this test at the end of Task 6, once `create_sale` exists.

- [ ] **Step 7: Migrate and run**

```bash
~/.pyenv/versions/stock/bin/python manage.py makemigrations sales stock
~/.pyenv/versions/stock/bin/pytest apps/sales/tests/test_models.py apps/stock -p no:warnings
```

Expected: all PASS. Two migrations are generated — `sales.0001_initial` and a
`stock.0003_*` adding the `sale` column. `test_transaction_id_and_sale_id_are_null`
must still pass: a standalone movement reports `null` for both.

- [ ] **Step 7: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/python manage.py makemigrations --check --dry-run
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/sales apps/stock
git commit -m "Add the Customer, Sale, SaleLine and Payment models"
```

---

## Task 5: Customer endpoints

**Files:**
- Create: `apps/sales/serializers.py`, `apps/sales/views.py`, `apps/sales/urls.py`
- Modify: `stockmanager/urls.py`
- Test: `apps/sales/tests/test_customers.py`

**Interfaces:**
- Consumes: `apps.common.views.CatalogueViewSet`, `apps.common.exceptions.Conflict`.
- Produces: `apps.sales.serializers.CustomerSerializer`; `apps.sales.views.CustomerViewSet`.

- [ ] **Step 1: Write the failing test**

Create `apps/sales/tests/test_customers.py`:

```python
"""Customer endpoints. Payload from the frontend's `Customer` type."""

import pytest

from apps.sales.models import Customer
from apps.sales.tests.factories import CustomerFactory, SaleFactory

pytestmark = pytest.mark.django_db

LIST_URL = "/api/customers/"


def detail_url(customer) -> str:
    return f"{LIST_URL}{customer.id}/"


class TestRead:
    def test_the_payload_matches_the_frontend_type(self, auth_client, cashier):
        CustomerFactory(name="Kivu Market")
        response = auth_client(cashier).get(LIST_URL)

        assert response.status_code == 200
        assert set(response.json()["results"][0]) == {
            "id",
            "name",
            "contactName",
            "email",
            "phone",
            "address",
            "taxNumber",
            "notes",
            "isActive",
            "createdAt",
        }

    def test_empty_optionals_serialise_as_null(self, auth_client, cashier):
        CustomerFactory(contact_name=None, email=None, phone=None, tax_number=None)
        row = auth_client(cashier).get(LIST_URL).json()["results"][0]
        assert row["contactName"] is None
        assert row["taxNumber"] is None

    def test_ordered_by_name(self, auth_client, cashier):
        CustomerFactory(name="Zeta")
        CustomerFactory(name="Alpha")
        response = auth_client(cashier).get(LIST_URL)
        assert [r["name"] for r in response.json()["results"]] == ["Alpha", "Zeta"]

    def test_search_covers_name_contact_email_and_phone(self, auth_client, cashier):
        CustomerFactory(
            name="Kivu Market",
            contact_name="Marie",
            email="marie@kivu.cd",
            phone="0990111222",
        )
        CustomerFactory(
            name="Goma Store",
            contact_name="Paul",
            email="paul@goma.cd",
            phone="0821333444",
        )
        client = auth_client(cashier)

        assert client.get(f"{LIST_URL}?search=kivu").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=paul").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=marie@kivu").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=0821").json()["count"] == 1

    def test_a_cashier_may_read(self, auth_client, cashier):
        CustomerFactory()
        assert auth_client(cashier).get(LIST_URL).status_code == 200


class TestWrite:
    def test_a_manager_can_create(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL,
            {
                "name": "Kivu Market",
                "contactName": "Marie Kabeya",
                "email": "marie@kivu.cd",
                "phone": "+243 990 111 222",
                "address": "10 avenue du Lac",
                "taxNumber": "A1234567B",
                "notes": "",
                "isActive": True,
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["taxNumber"] == "A1234567B"
        assert response.json()["notes"] is None

    def test_a_duplicate_name_is_rejected_case_insensitively(
        self, auth_client, manager
    ):
        CustomerFactory(name="Kivu Market")
        response = auth_client(manager).post(
            LIST_URL, {"name": "KIVU MARKET", "isActive": True}, format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["name"] == [
            "Un client porte déjà ce nom."
        ]

    def test_an_invalid_phone_is_rejected(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL,
            {"name": "Kivu Market", "phone": "pas-un-numéro!!", "isActive": True},
            format="json",
        )
        assert response.status_code == 400
        assert "phone" in response.json()["fieldErrors"]

    def test_an_over_long_tax_number_is_rejected(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL,
            {"name": "Kivu Market", "taxNumber": "X" * 31, "isActive": True},
            format="json",
        )
        assert response.status_code == 400
        assert "taxNumber" in response.json()["fieldErrors"]

    def test_a_customer_can_be_archived(self, auth_client, manager):
        customer = CustomerFactory(is_active=True)
        response = auth_client(manager).patch(
            detail_url(customer), {"isActive": False}, format="json"
        )
        assert response.status_code == 200
        customer.refresh_from_db()
        assert customer.is_active is False


class TestDelete:
    def test_an_owner_can_delete_an_unused_customer(self, auth_client, owner):
        customer = CustomerFactory()
        assert auth_client(owner).delete(detail_url(customer)).status_code == 204
        assert Customer.objects.count() == 0

    def test_a_customer_with_sales_is_409(self, auth_client, owner, site):
        customer = CustomerFactory()
        SaleFactory(customer=customer, user=owner, site=site)
        SaleFactory(customer=customer, user=owner, site=site)

        response = auth_client(owner).delete(detail_url(customer))

        assert response.status_code == 409
        assert response.json()["code"] == "conflict"
        assert response.json()["message"] == (
            "Ce client est lié à 2 ventes et ne peut pas être supprimé. "
            "Archivez-le à la place."
        )

    def test_the_message_is_singular_for_one_sale(self, auth_client, owner, site):
        customer = CustomerFactory()
        SaleFactory(customer=customer, user=owner, site=site)
        response = auth_client(owner).delete(detail_url(customer))
        assert response.json()["message"] == (
            "Ce client est lié à 1 vente et ne peut pas être supprimé. "
            "Archivez-le à la place."
        )


class TestPermissions:
    @pytest.mark.parametrize("method", ["post", "patch", "delete"])
    def test_a_cashier_may_not_write(self, auth_client, cashier, method):
        customer = CustomerFactory()
        client = auth_client(cashier)
        url = LIST_URL if method == "post" else detail_url(customer)
        response = getattr(client, method)(url, {"name": "X"}, format="json")
        assert response.status_code == 403

    def test_a_manager_may_not_delete(self, auth_client, manager):
        customer = CustomerFactory()
        assert auth_client(manager).delete(detail_url(customer)).status_code == 403
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/sales/tests/test_customers.py -p no:warnings`
Expected: FAIL — 404, no route registered.

- [ ] **Step 3: Write the serializer**

Create `apps/sales/serializers.py`:

```python
import re

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.sales.models import Customer

PHONE_PATTERN = re.compile(r"^[\d\s+().-]{6,20}$")


class CustomerSerializer(serializers.ModelSerializer):
    """The frontend's `Customer`. Validation mirrors
    `features/customers/schema.ts`."""

    contact_name = serializers.CharField(
        max_length=80, required=False, allow_blank=True, allow_null=True
    )
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    phone = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )
    address = serializers.CharField(
        max_length=200, required=False, allow_blank=True, allow_null=True
    )
    tax_number = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    notes = serializers.CharField(
        max_length=500, required=False, allow_blank=True, allow_null=True
    )

    OPTIONAL_FIELDS = (
        "contact_name",
        "email",
        "phone",
        "address",
        "tax_number",
        "notes",
    )

    class Meta:
        model = Customer
        fields = [
            "id",
            "name",
            "contact_name",
            "email",
            "phone",
            "address",
            "tax_number",
            "notes",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_name(self, value):
        name = value.strip()
        if len(name) < 2:
            raise serializers.ValidationError(
                _("Le nom doit contenir au moins 2 caractères.")
            )
        if len(name) > 80:
            raise serializers.ValidationError(
                _("Le nom ne peut pas dépasser 80 caractères.")
            )
        existing = Customer.objects.filter(name__iexact=name)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError(_("Un client porte déjà ce nom."))
        return name

    def validate_phone(self, value):
        if not value or not value.strip():
            return value
        if not PHONE_PATTERN.match(value.strip()):
            raise serializers.ValidationError(_("Numéro de téléphone invalide."))
        return value

    def validate(self, attrs):
        for field in self.OPTIONAL_FIELDS:
            if field in attrs:
                value = attrs[field]
                attrs[field] = value.strip() or None if value else None
        return attrs
```

- [ ] **Step 4: Write the viewset and URLs**

Create `apps/sales/views.py`:

```python
from django.utils.translation import gettext_lazy as _

from apps.common.exceptions import Conflict
from apps.common.views import CatalogueViewSet
from apps.sales.models import Customer
from apps.sales.serializers import CustomerSerializer


class CustomerViewSet(CatalogueViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    search_fields = ["name", "contact_name", "email", "phone"]
    ordering_fields = ["name", "created_at"]
    ordering = ["name"]

    def perform_destroy(self, instance):
        used = instance.sales.count()
        if used:
            raise Conflict(
                _(
                    "Ce client est lié à %(count)d vente%(plural)s et ne peut "
                    "pas être supprimé. Archivez-le à la place."
                )
                % {"count": used, "plural": "s" if used > 1 else ""}
            )
        instance.delete()
```

Create `apps/sales/urls.py`:

```python
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.sales.views import CustomerViewSet

router = DefaultRouter()
router.register("customers", CustomerViewSet, basename="customer")

urlpatterns = [path("", include(router.urls))]
```

Add to `stockmanager/urls.py`:

```python
    path("api/", include("apps.sales.urls")),
```

- [ ] **Step 5: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/sales/tests/test_customers.py -p no:warnings`
Expected: all PASS.

- [ ] **Step 6: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/sales stockmanager/urls.py
git commit -m "Add the customer endpoints"
```

---

## Task 6: The sale creation service

**Files:**
- Create: `apps/sales/services.py`
- Modify: `apps/stock/services.py`
- Test: `apps/sales/tests/test_create_sale.py`

**Interfaces:**
- Consumes: `apps.common.sequences.next_reference`, `apps.common.dates.shop_today`, `apps.sales.totals.compute_sale_totals`, `apps.stock.services.apply_movement`.
- Produces:

```python
def create_sale(
    *,
    lines: list[dict],   # each {"article": Article, "quantity": int, "unit_price": int}
    user,
    site,
    customer=None,
    discount: int = 0,
    discount_rate=None,   # Decimal | None
    note: str | None = None,
) -> Sale
```

Raises `rest_framework.serializers.ValidationError` keyed `discount` or
`lines.N.quantity`. All-or-nothing.

`apply_movement` gains `sale=None` — its third and final caller.

- [ ] **Step 1: Write the failing test**

Create `apps/sales/tests/test_create_sale.py`:

```python
"""Sale creation: snapshots, totals, stock, numbering, atomicity."""

from decimal import Decimal

import pytest
from rest_framework.serializers import ValidationError

from apps.catalogue.tests.factories import ArticleFactory
from apps.common.models import DocumentSequence
from apps.sales.models import Sale, SaleLine
from apps.sales.services import create_sale
from apps.sales.tests.factories import CustomerFactory
from apps.stock.models import StockLevel, StockMovement
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db


def stocked(site, quantity=100, **kwargs):
    article = ArticleFactory(**kwargs)
    StockLevelFactory(article=article, site=site, quantity=quantity)
    return article


def line(article, quantity=2, unit_price=5_000):
    return {"article": article, "quantity": quantity, "unit_price": unit_price}


def build(site, user, lines, **kwargs):
    return create_sale(lines=lines, user=user, site=site, **kwargs)


class TestHeader:
    def test_the_reference_is_allocated(self, site, owner):
        sale = build(site, owner, [line(stocked(site))])
        assert sale.reference.startswith("FA-")
        assert sale.reference.endswith("-0001")

    def test_consecutive_sales_increment(self, site, owner):
        first = build(site, owner, [line(stocked(site))])
        second = build(site, owner, [line(stocked(site))])
        assert (
            int(second.reference.split("-")[-1])
            == int(first.reference.split("-")[-1]) + 1
        )

    def test_the_invoice_sequence_is_separate_from_transactions(self, site, owner):
        build(site, owner, [line(stocked(site))])
        assert DocumentSequence.objects.get(prefix="FA").last_number == 1
        assert not DocumentSequence.objects.filter(prefix="TR").exists()

    def test_a_new_sale_is_completed(self, site, owner):
        assert build(site, owner, [line(stocked(site))]).status == "COMPLETED"

    def test_the_user_name_is_snapshotted(self, site, owner):
        assert build(site, owner, [line(stocked(site))]).user_name == owner.full_name


class TestBillingSnapshot:
    def test_the_customer_block_is_captured(self, site, owner):
        customer = CustomerFactory(
            name="Kivu Market", address="10 av. du Lac", tax_number="A123"
        )
        sale = build(site, owner, [line(stocked(site))], customer=customer)

        assert sale.customer == customer
        assert sale.customer_name == "Kivu Market"
        assert sale.customer_address == "10 av. du Lac"
        assert sale.customer_tax_number == "A123"

    def test_a_walk_in_sale_has_no_customer(self, site, owner):
        sale = build(site, owner, [line(stocked(site))])
        assert sale.customer is None
        assert sale.customer_name is None


class TestLineSnapshots:
    def test_every_field_is_frozen_at_sale_time(self, site, owner):
        article = stocked(
            site, name="Sucre", sku="EPI-1", purchase_price=800, vat_rate=Decimal("16.00")
        )
        sale = build(site, owner, [line(article, quantity=3, unit_price=1_200)])

        row = sale.lines.get()
        assert row.article_name == "Sucre"
        assert row.article_sku == "EPI-1"
        assert row.unit == article.unit
        assert row.quantity == 3
        assert row.unit_price == 1_200
        assert row.unit_cost == 800
        assert row.vat_rate == Decimal("16.00")

    def test_the_snapshot_survives_a_later_reprice(self, site, owner):
        article = stocked(site, purchase_price=800)
        sale = build(site, owner, [line(article)])

        article.purchase_price = 9_999
        article.save()

        assert sale.lines.get().unit_cost == 800

    def test_the_unit_price_may_be_negotiated_below_the_article_price(
        self, site, owner
    ):
        article = stocked(site, sale_price=5_000)
        sale = build(site, owner, [line(article, unit_price=4_000)])
        assert sale.lines.get().unit_price == 4_000


class TestTotals:
    def test_they_match_the_arithmetic_module(self, site, owner):
        from apps.sales.totals import LineInput, compute_sale_totals

        first = stocked(site, vat_rate=Decimal("16.00"))
        second = stocked(site, vat_rate=Decimal("5.50"))

        sale = build(
            site,
            owner,
            [line(first, 3, 1_200), line(second, 1, 4_000)],
            discount=500,
        )

        expected = compute_sale_totals(
            [
                LineInput(quantity=3, unit_price=1_200, vat_rate=Decimal("16.00")),
                LineInput(quantity=1, unit_price=4_000, vat_rate=Decimal("5.50")),
            ],
            discount=500,
        )

        assert sale.subtotal == expected.subtotal
        assert sale.discount == expected.discount
        assert sale.total == expected.total
        assert sale.vat_total == expected.vat_total

    def test_the_discount_shares_are_persisted_per_line(self, site, owner):
        sale = build(
            site,
            owner,
            [line(stocked(site), 1, 1_000), line(stocked(site), 1, 1_000)],
            discount=100,
        )
        shares = sorted(row.discount_share for row in sale.lines.all())
        assert sum(shares) == 100

    def test_the_discount_rate_is_recorded_but_not_used(self, site, owner):
        """It exists so the UI can redisplay '10 %'. `discount` is
        authoritative."""
        sale = build(
            site,
            owner,
            [line(stocked(site), 1, 10_000)],
            discount=1_000,
            discount_rate=Decimal("10.00"),
        )
        assert sale.discount == 1_000
        assert sale.discount_rate == Decimal("10.00")
        assert sale.total == 9_000


class TestStock:
    def test_one_out_sale_movement_per_line(self, site, owner):
        first, second = stocked(site), stocked(site)
        sale = build(site, owner, [line(first, 2), line(second, 3)])

        movements = list(sale.movements.all())
        assert len(movements) == 2
        assert {m.type for m in movements} == {"OUT"}
        assert {m.reason for m in movements} == {"SALE"}

    def test_stock_falls_by_the_sold_quantity(self, site, owner):
        article = stocked(site, quantity=50)
        build(site, owner, [line(article, quantity=8)])
        assert StockLevel.objects.get(article=article).quantity == 42

    def test_the_movement_carries_the_sale_reference(self, site, owner):
        sale = build(site, owner, [line(stocked(site))])
        assert sale.movements.get().reference == sale.reference

    def test_the_movement_carries_no_unit_cost(self, site, owner):
        """`createSale` passes unitCost: null — a sale's cost is on the line
        snapshot, not the movement."""
        sale = build(site, owner, [line(stocked(site))])
        assert sale.movements.get().unit_cost is None


class TestValidation:
    def test_a_line_exceeding_stock_names_its_row(self, site, owner):
        good, bad = stocked(site, quantity=100), stocked(site, quantity=1)

        with pytest.raises(ValidationError) as exc:
            build(site, owner, [line(good, 2), line(bad, 99)])

        assert "lines.1.quantity" in exc.value.detail

    def test_a_failed_sale_writes_nothing(self, site, owner):
        good, bad = stocked(site, quantity=100), stocked(site, quantity=1)

        with pytest.raises(ValidationError):
            build(site, owner, [line(good, 2), line(bad, 99)])

        assert Sale.objects.count() == 0
        assert SaleLine.objects.count() == 0
        assert StockMovement.objects.count() == 0
        assert StockLevel.objects.get(article=good).quantity == 100

    def test_a_failed_sale_leaves_no_gap_in_the_invoice_sequence(self, site, owner):
        build(site, owner, [line(stocked(site))])
        bad = stocked(site, quantity=1)

        with pytest.raises(ValidationError):
            build(site, owner, [line(bad, 99)])

        assert build(site, owner, [line(stocked(site))]).reference.endswith("-0002")

    def test_a_discount_over_the_subtotal_is_rejected(self, site, owner):
        with pytest.raises(ValidationError) as exc:
            build(site, owner, [line(stocked(site), 1, 1_000)], discount=1_001)

        assert exc.value.detail["discount"][0] == (
            "La remise ne peut pas dépasser le total de la vente."
        )

    def test_a_discount_equal_to_the_subtotal_is_allowed(self, site, owner):
        sale = build(site, owner, [line(stocked(site), 1, 1_000)], discount=1_000)
        assert sale.total == 0
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/sales/tests/test_create_sale.py -p no:warnings`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.sales.services'`.

- [ ] **Step 3: Extend `apply_movement`**

In `apps/stock/services.py`, add `sale=None` to the signature immediately after
`stock_transaction=None`, extend the docstring:

```python
    `sale` links this movement to the sale it is a line of, the same way
    `stock_transaction` does for a transaction. A movement carries at most one
    of the two.
```

and pass it through in the `StockMovement.objects.create(...)` call, after
`transaction=stock_transaction,`:

```python
        sale=sale,
```

- [ ] **Step 4: Implement `create_sale`**

Create `apps/sales/services.py`:

```python
"""Sale writers.

Every stock change still goes through `apply_movement`. A sale does not get
its own way to change a quantity.
"""

from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.common.dates import shop_today
from apps.common.sequences import next_reference
from apps.sales.models import Sale, SaleLine
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

    reference = next_reference("FA", shop_today().year)

    sale = Sale.objects.create(
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
```

- [ ] **Step 5: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/sales/tests/test_create_sale.py -p no:warnings`
Expected: all PASS.

If `test_a_failed_sale_leaves_no_gap_in_the_invoice_sequence` fails, check that
`next_reference` is called inside `create_sale` rather than by a caller — the
rollback property depends on it sharing this atomic block.

- [ ] **Step 6: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/sales apps/stock
git commit -m "Add create_sale with snapshotted lines and FA numbering"
```

---

## Task 7: The sale queryset and read serializers

**Files:**
- Create: `apps/sales/querysets.py`
- Modify: `apps/sales/serializers.py`
- Test: `apps/sales/tests/test_sale_reads.py`

**Interfaces:**
- Consumes: `apps.sales.models.Sale`, `Payment`.
- Produces:
  - `apps.sales.querysets.sale_queryset() -> QuerySet[Sale]`, annotating `paid_amount` and `line_count`.
  - `apps.sales.serializers.CustomerRefSerializer`, `SaleCustomerDetailSerializer`, `SaleLineSerializer`, `PaymentSerializer`, `SaleSerializer`, `SaleDetailSerializer`.

**The annotation must be a correlated subquery, not a second join aggregate.**
`Count("lines")` and `Sum("payments__amount")` in one queryset multiply each
other's rows: a sale with 3 lines and 2 payments would report 6× its paid
amount. This is the classic Django multi-join aggregate bug and it has its own
test below.

- [ ] **Step 1: Write the failing test**

Create `apps/sales/tests/test_sale_reads.py`:

```python
"""Derived figures: paidAmount, balance, paymentStatus, lineCount."""

import pytest

from apps.sales.querysets import sale_queryset
from apps.sales.tests.factories import PaymentFactory, SaleFactory, SaleLineFactory

pytestmark = pytest.mark.django_db


class TestAnnotations:
    def test_paid_amount_sums_the_payments(self, site, owner):
        sale = SaleFactory(user=owner, site=site, total=10_000)
        PaymentFactory(sale=sale, user=owner, amount=3_000)
        PaymentFactory(sale=sale, user=owner, amount=2_000)

        assert sale_queryset().get(pk=sale.pk).paid_amount == 5_000

    def test_paid_amount_is_zero_with_no_payments(self, site, owner):
        sale = SaleFactory(user=owner, site=site)
        assert sale_queryset().get(pk=sale.pk).paid_amount == 0

    def test_line_count_counts_the_lines(self, site, owner):
        sale = SaleFactory(user=owner, site=site)
        SaleLineFactory(sale=sale)
        SaleLineFactory(sale=sale)
        SaleLineFactory(sale=sale)

        assert sale_queryset().get(pk=sale.pk).line_count == 3

    def test_lines_and_payments_do_not_multiply_each_other(self, site, owner):
        """The bug this queryset is shaped to avoid.

        Annotating Count("lines") and Sum("payments__amount") together joins
        both tables, giving 3 x 2 = 6 rows: line_count would read 6 and
        paid_amount would read 3x its true value.
        """
        sale = SaleFactory(user=owner, site=site, total=10_000)
        for _ in range(3):
            SaleLineFactory(sale=sale)
        PaymentFactory(sale=sale, user=owner, amount=1_000)
        PaymentFactory(sale=sale, user=owner, amount=2_000)

        annotated = sale_queryset().get(pk=sale.pk)

        assert annotated.line_count == 3
        assert annotated.paid_amount == 3_000

    def test_annotations_are_per_sale_not_global(self, site, owner):
        first = SaleFactory(user=owner, site=site)
        second = SaleFactory(user=owner, site=site)
        PaymentFactory(sale=first, user=owner, amount=1_000)
        PaymentFactory(sale=second, user=owner, amount=7_000)

        by_id = {row.id: row for row in sale_queryset()}
        assert by_id[first.id].paid_amount == 1_000
        assert by_id[second.id].paid_amount == 7_000
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/sales/tests/test_sale_reads.py -p no:warnings`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.sales.querysets'`.

- [ ] **Step 3: Write the queryset**

Create `apps/sales/querysets.py`:

```python
"""The annotated sale queryset.

`paidAmount`, `balance` and `paymentStatus` are derived on every read and
never stored. A status column would be a second source of truth, free to
disagree with the payments it claims to summarise.
"""

from django.db.models import Count, IntegerField, OuterRef, QuerySet, Subquery, Sum
from django.db.models.functions import Coalesce

from apps.sales.models import Payment, Sale


def sale_queryset() -> QuerySet[Sale]:
    """Annotate `paid_amount` and `line_count`.

    `paid_amount` is a correlated subquery rather than `Sum("payments__amount")`
    on purpose. Two join aggregates in one queryset multiply each other's rows:
    a sale with three lines and two payments would report a line count of six
    and three times its true paid amount. The subquery form cannot do that
    because it never joins.
    """
    paid = (
        Payment.objects.filter(sale=OuterRef("pk"))
        .values("sale")
        .annotate(total=Sum("amount"))
        .values("total")
    )

    return (
        Sale.objects.select_related("customer", "site", "user")
        .annotate(
            paid_amount=Coalesce(
                Subquery(paid, output_field=IntegerField()),
                0,
                output_field=IntegerField(),
            ),
            line_count=Count("lines", distinct=True),
        )
    )
```

- [ ] **Step 4: Run the annotation tests**

Run: `~/.pyenv/versions/stock/bin/pytest apps/sales/tests/test_sale_reads.py -p no:warnings`
Expected: all PASS. `test_lines_and_payments_do_not_multiply_each_other` is the
one that matters — if it fails, the annotation reverted to a join aggregate.

- [ ] **Step 5: Write the read serializers**

Add `import unicodedata` to the **top** of `apps/sales/serializers.py`, beside
the existing `import re`, and extend the models import to
`from apps.sales.models import Customer, Payment, Sale, SaleLine`. Then append:

```python
def french_sort_key(value: str) -> str:
    """Approximate `localeCompare(fr-FR)` for sorting article names.

    Python's default sort is by code point, which puts « Épicerie » after
    « Zzz » because É is U+00C9. Stripping accents via NFKD puts it back
    beside « E », which is what a French reader expects.

    An approximation, deliberately: it does not implement CLDR tailoring, and
    names differing only by accent fall back to their original form. Full
    collation would mean PyICU, which is not worth a dependency for invoice
    line order.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return (stripped.casefold(), value)


class CustomerRefSerializer(serializers.ModelSerializer):
    """The frontend's `CustomerRef`, built from the sale's own snapshot."""

    id = serializers.UUIDField(source="customer_id", read_only=True)
    name = serializers.CharField(source="customer_name", read_only=True)

    class Meta:
        model = Sale
        fields = ["id", "name"]


class SaleCustomerDetailSerializer(CustomerRefSerializer):
    """The frontend's `SaleCustomerDetail` — the billing block on an invoice."""

    address = serializers.CharField(source="customer_address", read_only=True)
    tax_number = serializers.CharField(
        source="customer_tax_number", read_only=True
    )

    class Meta(CustomerRefSerializer.Meta):
        fields = CustomerRefSerializer.Meta.fields + ["address", "tax_number"]


class SaleLineSerializer(serializers.ModelSerializer):
    """The frontend's `SaleLine`. Every field is the snapshot."""

    class Meta:
        model = SaleLine
        fields = [
            "id",
            "article_id",
            "article_name",
            "article_sku",
            "unit",
            "quantity",
            "unit_price",
            "unit_cost",
            "vat_rate",
            "line_total",
            "discount_share",
            "vat_amount",
        ]


class PaymentSerializer(serializers.ModelSerializer):
    """The frontend's `Payment`."""

    sale_id = serializers.UUIDField(read_only=True)
    user_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "sale_id",
            "amount",
            "method",
            "paid_at",
            "reference",
            "note",
            "user_id",
            "user_name",
            "created_at",
        ]


class SaleSerializer(serializers.ModelSerializer):
    """The frontend's `Sale`.

    `paidAmount` comes from the queryset annotation; `balance` and
    `paymentStatus` are derived from it here. None of the three is a column.
    """

    site_id = serializers.UUIDField(read_only=True)
    customer_id = serializers.UUIDField(read_only=True)
    user_id = serializers.UUIDField(read_only=True)
    customer = serializers.SerializerMethodField()
    line_count = serializers.IntegerField(read_only=True)
    paid_amount = serializers.IntegerField(read_only=True)
    balance = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = [
            "id",
            "reference",
            "site_id",
            "customer_id",
            "customer",
            "status",
            "subtotal",
            "discount",
            "discount_rate",
            "total",
            "vat_total",
            "note",
            "cancelled_at",
            "cancel_reason",
            "line_count",
            "paid_amount",
            "balance",
            "payment_status",
            "user_id",
            "user_name",
            "created_at",
        ]

    def get_customer(self, obj):
        if obj.customer_id is None:
            return None
        return CustomerRefSerializer(obj).data

    def get_balance(self, obj) -> int:
        # Zero on a cancelled sale, whatever was paid before: nothing is owed
        # on one, and money already received is a refund rather than a debt.
        # Floored at zero otherwise, so an overpayment never reads as negative.
        if obj.status == Sale.Status.CANCELLED:
            return 0
        return max(obj.total - obj.paid_amount, 0)

    def get_payment_status(self, obj) -> str:
        if obj.paid_amount <= 0:
            return "UNPAID"
        if obj.paid_amount >= obj.total:
            return "PAID"
        return "PARTIAL"


class SaleDetailSerializer(SaleSerializer):
    """The frontend's `SaleDetail` — the list shape plus lines and payments,
    with the customer widened to the invoice billing block."""

    customer = serializers.SerializerMethodField()
    lines = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()

    class Meta(SaleSerializer.Meta):
        fields = SaleSerializer.Meta.fields + ["lines", "payments"]

    def get_customer(self, obj):
        if obj.customer_id is None:
            return None
        return SaleCustomerDetailSerializer(obj).data

    def get_lines(self, obj):
        rows = sorted(obj.lines.all(), key=lambda row: french_sort_key(row.article_name))
        return SaleLineSerializer(rows, many=True).data

    def get_payments(self, obj):
        # Model ordering is already (paid_at, id); this reads from the
        # prefetched cache rather than issuing a second query.
        return PaymentSerializer(obj.payments.all(), many=True).data
```

- [ ] **Step 6: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/sales
git commit -m "Add the annotated sale queryset and read serializers"
```

---

## Task 8: Sale create, list and detail endpoints

**Files:**
- Modify: `apps/sales/serializers.py`, `apps/sales/views.py`, `apps/sales/urls.py`
- Create: `apps/sales/filters.py`
- Test: `apps/sales/tests/test_sales_api.py`

**Interfaces:**
- Consumes: `create_sale`, `sale_queryset`, `SaleSerializer`, `SaleDetailSerializer`, `apps.common.permissions.RoleScopedPermissionMixin`.
- Produces: `apps.sales.serializers.SaleCreateSerializer`, `SaleLineInputSerializer`; `apps.sales.filters.SaleFilterSet`; `apps.sales.views.SaleViewSet`.

`lines` keeps DRF's default `allow_empty=True` and rejects an empty list in
`validate_lines`. `allow_empty=False` produces
`{"lines": {"non_field_errors": [...]}}`, which reaches the client as
`lines.nonFieldErrors` — a key no form field is mounted on, so the user would
see nothing at all.

- [ ] **Step 1: Write the failing test**

Create `apps/sales/tests/test_sales_api.py`:

```python
"""Sale endpoints: create, list, detail."""

import uuid
from datetime import datetime, timezone as dt_timezone

import pytest

from apps.catalogue.tests.factories import ArticleFactory
from apps.sales.models import Sale
from apps.sales.services import create_sale
from apps.sales.tests.factories import CustomerFactory, PaymentFactory
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db

URL = "/api/sales/"


def stocked(site, quantity=100, **kwargs):
    article = ArticleFactory(**kwargs)
    StockLevelFactory(article=article, site=site, quantity=quantity)
    return article


def body(lines, **overrides):
    payload = {
        "customerId": None,
        "discount": 0,
        "discountRate": None,
        "note": None,
        "lines": lines,
    }
    payload.update(overrides)
    return payload


def line(article, quantity=2, unit_price=5_000):
    return {
        "articleId": str(article.id),
        "quantity": quantity,
        "unitPrice": unit_price,
    }


def make(site, user, quantities=(2,), **kwargs):
    lines = [
        {"article": stocked(site), "quantity": q, "unit_price": 5_000}
        for q in quantities
    ]
    return create_sale(lines=lines, user=user, site=site, **kwargs)


class TestCreate:
    def test_a_cashier_can_create_a_sale(self, auth_client, cashier, site):
        """The till. Cashiers create sales and payments; they do not cancel."""
        response = auth_client(cashier).post(
            URL, body([line(stocked(site))]), format="json"
        )
        assert response.status_code == 201
        assert response.json()["reference"].startswith("FA-")

    def test_the_payload_matches_the_frontend_sale_type(
        self, auth_client, cashier, site
    ):
        response = auth_client(cashier).post(
            URL, body([line(stocked(site))]), format="json"
        )

        assert set(response.json()) == {
            "id",
            "reference",
            "siteId",
            "customerId",
            "customer",
            "status",
            "subtotal",
            "discount",
            "discountRate",
            "total",
            "vatTotal",
            "note",
            "cancelledAt",
            "cancelReason",
            "lineCount",
            "paidAmount",
            "balance",
            "paymentStatus",
            "userId",
            "userName",
            "createdAt",
        }

    def test_a_new_sale_is_unpaid_with_the_full_balance(
        self, auth_client, cashier, site
    ):
        response = auth_client(cashier).post(
            URL, body([line(stocked(site), 2, 5_000)]), format="json"
        )
        payload = response.json()
        assert payload["paidAmount"] == 0
        assert payload["balance"] == payload["total"] == 10_000
        assert payload["paymentStatus"] == "UNPAID"

    def test_a_customer_is_recorded_by_id_and_ref(self, auth_client, cashier, site):
        customer = CustomerFactory(name="Kivu Market")
        response = auth_client(cashier).post(
            URL,
            body([line(stocked(site))], customerId=str(customer.id)),
            format="json",
        )
        assert response.json()["customerId"] == str(customer.id)
        assert response.json()["customer"] == {
            "id": str(customer.id),
            "name": "Kivu Market",
        }

    def test_a_walk_in_sale_has_a_null_customer(self, auth_client, cashier, site):
        response = auth_client(cashier).post(
            URL, body([line(stocked(site))]), format="json"
        )
        assert response.json()["customerId"] is None
        assert response.json()["customer"] is None

    def test_line_count_reflects_the_lines(self, auth_client, cashier, site):
        response = auth_client(cashier).post(
            URL, body([line(stocked(site)), line(stocked(site))]), format="json"
        )
        assert response.json()["lineCount"] == 2


class TestCreateValidation:
    def test_no_lines_is_rejected(self, auth_client, cashier, site):
        response = auth_client(cashier).post(URL, body([]), format="json")
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines"] == [
            "Ajoutez au moins un article à la vente."
        ]

    def test_a_duplicate_article_is_rejected(self, auth_client, cashier, site):
        article = stocked(site)
        response = auth_client(cashier).post(
            URL, body([line(article), line(article)]), format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.1.articleId"] == [
            "Cet article est déjà présent dans la vente."
        ]

    def test_an_unknown_article_is_rejected_on_its_row(
        self, auth_client, cashier, site
    ):
        response = auth_client(cashier).post(
            URL,
            body(
                [
                    line(stocked(site)),
                    {"articleId": str(uuid.uuid4()), "quantity": 1, "unitPrice": 100},
                ]
            ),
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.1.articleId"] == [
            "Cet article n'existe plus."
        ]

    def test_a_zero_quantity_is_rejected(self, auth_client, cashier, site):
        """Unlike a stock ADJUSTMENT, a sale line of zero is never meaningful."""
        response = auth_client(cashier).post(
            URL, body([line(stocked(site), quantity=0)]), format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.0.quantity"] == [
            "La quantité doit être supérieure à zéro."
        ]

    def test_a_negative_unit_price_is_rejected(self, auth_client, cashier, site):
        response = auth_client(cashier).post(
            URL, body([line(stocked(site), unit_price=-1)]), format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.0.unitPrice"] == [
            "Le prix unitaire est invalide."
        ]

    def test_a_negative_discount_is_rejected(self, auth_client, cashier, site):
        response = auth_client(cashier).post(
            URL, body([line(stocked(site))], discount=-5), format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["discount"] == [
            "La remise ne peut pas être négative."
        ]

    def test_a_discount_over_the_subtotal_is_rejected(
        self, auth_client, cashier, site
    ):
        response = auth_client(cashier).post(
            URL, body([line(stocked(site), 1, 1_000)], discount=1_001), format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["discount"] == [
            "La remise ne peut pas dépasser le total de la vente."
        ]

    def test_insufficient_stock_names_the_offending_row(
        self, auth_client, cashier, site
    ):
        good = stocked(site, quantity=100)
        bad = stocked(site, quantity=1)

        response = auth_client(cashier).post(
            URL, body([line(good, 2), line(bad, 99)]), format="json"
        )

        assert response.status_code == 400
        assert "lines.1.quantity" in response.json()["fieldErrors"]
        assert Sale.objects.count() == 0

    def test_an_unknown_customer_is_rejected(self, auth_client, cashier, site):
        response = auth_client(cashier).post(
            URL, body([line(stocked(site))], customerId=str(uuid.uuid4())),
            format="json",
        )
        assert response.status_code == 400
        assert "customerId" in response.json()["fieldErrors"]


class TestList:
    def test_newest_first(self, auth_client, cashier, site, owner):
        first = make(site, owner)
        second = make(site, owner)
        response = auth_client(cashier).get(URL)
        assert [r["id"] for r in response.json()["results"]] == [
            str(second.id),
            str(first.id),
        ]

    def test_the_list_never_includes_lines_or_payments(
        self, auth_client, cashier, site, owner
    ):
        make(site, owner, quantities=(1, 2))
        row = auth_client(cashier).get(URL).json()["results"][0]
        assert "lines" not in row
        assert "payments" not in row

    def test_filter_by_customer(self, auth_client, cashier, site, owner):
        customer = CustomerFactory()
        make(site, owner, customer=customer)
        make(site, owner)
        response = auth_client(cashier).get(f"{URL}?customerId={customer.id}")
        assert response.json()["count"] == 1

    def test_filter_by_status(self, auth_client, cashier, site, owner):
        sale = make(site, owner)
        make(site, owner)
        Sale.objects.filter(pk=sale.pk).update(status="CANCELLED")

        client = auth_client(cashier)
        assert client.get(f"{URL}?status=CANCELLED").json()["count"] == 1
        assert client.get(f"{URL}?status=COMPLETED").json()["count"] == 1

    def test_filter_by_payment_status(self, auth_client, cashier, site, owner):
        unpaid = make(site, owner, quantities=(2,))       # total 10 000
        partial = make(site, owner, quantities=(2,))
        paid = make(site, owner, quantities=(2,))
        PaymentFactory(sale=partial, user=owner, amount=3_000)
        PaymentFactory(sale=paid, user=owner, amount=paid.total)

        client = auth_client(cashier)
        assert [r["id"] for r in client.get(f"{URL}?paymentStatus=UNPAID").json()["results"]] == [
            str(unpaid.id)
        ]
        assert [r["id"] for r in client.get(f"{URL}?paymentStatus=PARTIAL").json()["results"]] == [
            str(partial.id)
        ]
        assert [r["id"] for r in client.get(f"{URL}?paymentStatus=PAID").json()["results"]] == [
            str(paid.id)
        ]

    def test_a_cancelled_sale_never_matches_a_payment_status_filter(
        self, auth_client, cashier, site, owner
    ):
        """Otherwise « Impayée » would list sales nobody owes for."""
        sale = make(site, owner)
        Sale.objects.filter(pk=sale.pk).update(status="CANCELLED")

        client = auth_client(cashier)
        for value in ("UNPAID", "PARTIAL", "PAID"):
            assert client.get(f"{URL}?paymentStatus={value}").json()["count"] == 0

    @pytest.mark.parametrize(
        ("param", "value"),
        [("status", "PENDING"), ("paymentStatus", "MAYBE")],
    )
    def test_an_invalid_filter_value_is_400(
        self, auth_client, cashier, site, param, value
    ):
        response = auth_client(cashier).get(f"{URL}?{param}={value}")
        assert response.status_code == 400
        assert param in response.json()["fieldErrors"]

    def test_search_covers_reference_customer_name_and_note(
        self, auth_client, cashier, site, owner
    ):
        customer = CustomerFactory(name="Kivu Market")
        target = make(site, owner, customer=customer, note="Livraison spéciale")
        make(site, owner)

        client = auth_client(cashier)
        assert client.get(f"{URL}?search={target.reference}").json()["count"] == 1
        assert client.get(f"{URL}?search=kivu").json()["count"] == 1
        assert client.get(f"{URL}?search=spéciale").json()["count"] == 1

    def test_the_query_count_is_flat(
        self, auth_client, cashier, site, owner, django_assert_num_queries
    ):
        for _ in range(10):
            make(site, owner)

        client = auth_client(cashier)
        client.get(URL)

        with django_assert_num_queries(3):
            response = client.get(f"{URL}?pageSize=10")

        assert len(response.json()["results"]) == 10


class TestDateBounds:
    @pytest.fixture(autouse=True)
    def _kinshasa(self, settings):
        settings.SHOP_TIME_ZONE = "Africa/Kinshasa"

    def _at(self, instant, site, owner):
        sale = make(site, owner)
        Sale.objects.filter(pk=sale.pk).update(created_at=instant)
        return sale

    def test_date_from_includes_the_early_local_morning(
        self, auth_client, cashier, site, owner
    ):
        self._at(datetime(2026, 7, 1, 23, 30, tzinfo=dt_timezone.utc), site, owner)
        assert auth_client(cashier).get(f"{URL}?dateFrom=2026-07-02").json()["count"] == 1

    def test_date_to_is_inclusive_of_the_whole_local_day(
        self, auth_client, cashier, site, owner
    ):
        self._at(datetime(2026, 7, 2, 22, 30, tzinfo=dt_timezone.utc), site, owner)
        assert auth_client(cashier).get(f"{URL}?dateTo=2026-07-02").json()["count"] == 1


class TestDetail:
    def test_the_payload_adds_lines_and_payments(
        self, auth_client, cashier, site, owner
    ):
        sale = make(site, owner, quantities=(1, 2))
        PaymentFactory(sale=sale, user=owner, amount=1_000)

        payload = auth_client(cashier).get(f"{URL}{sale.id}/").json()

        assert len(payload["lines"]) == 2
        assert len(payload["payments"]) == 1
        assert set(payload["lines"][0]) == {
            "id",
            "articleId",
            "articleName",
            "articleSku",
            "unit",
            "quantity",
            "unitPrice",
            "unitCost",
            "vatRate",
            "lineTotal",
            "discountShare",
            "vatAmount",
        }
        assert set(payload["payments"][0]) == {
            "id",
            "saleId",
            "amount",
            "method",
            "paidAt",
            "reference",
            "note",
            "userId",
            "userName",
            "createdAt",
        }

    def test_the_detail_customer_carries_the_billing_block(
        self, auth_client, cashier, site, owner
    ):
        customer = CustomerFactory(
            name="Kivu Market", address="10 av. du Lac", tax_number="A123"
        )
        sale = make(site, owner, customer=customer)

        payload = auth_client(cashier).get(f"{URL}{sale.id}/").json()

        assert payload["customer"] == {
            "id": str(customer.id),
            "name": "Kivu Market",
            "address": "10 av. du Lac",
            "taxNumber": "A123",
        }

    def test_lines_are_sorted_by_article_name_in_french(
        self, auth_client, cashier, site, owner
    ):
        """Python's default sort puts « Épicerie » after « Zzz » because É is
        U+00C9. French collation puts it beside E."""
        lines = [
            {"article": stocked(site, name="Zèbre"), "quantity": 1, "unit_price": 100},
            {"article": stocked(site, name="Épicerie"), "quantity": 1, "unit_price": 100},
            {"article": stocked(site, name="Avocat"), "quantity": 1, "unit_price": 100},
        ]
        sale = create_sale(lines=lines, user=owner, site=site)

        payload = auth_client(cashier).get(f"{URL}{sale.id}/").json()

        assert [row["articleName"] for row in payload["lines"]] == [
            "Avocat",
            "Épicerie",
            "Zèbre",
        ]

    def test_unknown_id_is_404_with_the_envelope(self, auth_client, cashier, site):
        response = auth_client(cashier).get(f"{URL}{uuid.uuid4()}/")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/sales/tests/test_sales_api.py -p no:warnings`
Expected: FAIL — 404, no route.

- [ ] **Step 3: Add the write serializers**

Add `from apps.catalogue.models import Article` to the **top** of
`apps/sales/serializers.py`, then append:

```python
class SaleLineInputSerializer(serializers.Serializer):
    """One row of `SaleCreateDto.lines`."""

    article_id = serializers.PrimaryKeyRelatedField(
        source="article",
        queryset=Article.objects.all(),
        error_messages={"does_not_exist": _("Cet article n'existe plus.")},
    )
    quantity = serializers.IntegerField(
        min_value=1,
        error_messages={
            "min_value": _("La quantité doit être supérieure à zéro."),
            "invalid": _("La quantité doit être supérieure à zéro."),
        },
    )
    unit_price = serializers.IntegerField(
        min_value=0,
        error_messages={
            "min_value": _("Le prix unitaire est invalide."),
            "invalid": _("Le prix unitaire est invalide."),
        },
    )


class SaleCreateSerializer(serializers.Serializer):
    """The frontend's `SaleCreateDto`.

    `discount` arrives already resolved to cents — the form turns a percentage
    into an amount before sending, and `discountRate` records which it was.
    """

    customer_id = serializers.PrimaryKeyRelatedField(
        source="customer",
        queryset=Customer.objects.all(),
        required=False,
        allow_null=True,
        default=None,
        error_messages={"does_not_exist": _("Ce client n'existe plus.")},
    )
    discount = serializers.IntegerField(
        min_value=0,
        required=False,
        default=0,
        error_messages={
            "min_value": _("La remise ne peut pas être négative."),
            "invalid": _("La remise ne peut pas être négative."),
        },
    )
    discount_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=0,
        max_value=100,
        required=False,
        allow_null=True,
        default=None,
    )
    note = serializers.CharField(
        max_length=300, required=False, allow_blank=True, allow_null=True, default=None
    )
    lines = SaleLineInputSerializer(many=True)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError(
                _("Ajoutez au moins un article à la vente.")
            )
        return value

    def validate(self, attrs):
        seen = set()
        for index, row in enumerate(attrs["lines"]):
            article = row["article"]
            if article.id in seen:
                raise serializers.ValidationError(
                    {
                        f"lines.{index}.article_id": [
                            _("Cet article est déjà présent dans la vente.")
                        ]
                    }
                )
            seen.add(article.id)
        return attrs
```

- [ ] **Step 4: Add the filterset**

Create `apps/sales/filters.py`:

```python
from django.db.models import F
from django_filters import rest_framework as drf_filters

from apps.common.dates import end_of_day, start_of_day
from apps.sales.models import Sale

PAYMENT_STATUS_CHOICES = [
    ("UNPAID", "UNPAID"),
    ("PARTIAL", "PARTIAL"),
    ("PAID", "PAID"),
]


class SaleFilterSet(drf_filters.FilterSet):
    customer_id = drf_filters.UUIDFilter(field_name="customer_id")
    status = drf_filters.ChoiceFilter(choices=Sale.Status.choices)
    payment_status = drf_filters.ChoiceFilter(
        choices=PAYMENT_STATUS_CHOICES, method="filter_payment_status"
    )
    date_from = drf_filters.DateFilter(method="filter_date_from")
    date_to = drf_filters.DateFilter(method="filter_date_to")

    class Meta:
        model = Sale
        fields = ["customer_id", "status", "payment_status", "date_from", "date_to"]

    def filter_payment_status(self, queryset, name, value):
        # A cancelled sale is not a receivable, so it never matches a payment
        # status filter — otherwise « Impayée » would list sales nobody owes
        # for. Requires the `paid_amount` annotation from sale_queryset().
        queryset = queryset.exclude(status=Sale.Status.CANCELLED)
        if value == "UNPAID":
            return queryset.filter(paid_amount__lte=0)
        if value == "PAID":
            return queryset.filter(paid_amount__gte=F("total"))
        return queryset.filter(paid_amount__gt=0, paid_amount__lt=F("total"))

    def filter_date_from(self, queryset, name, value):
        return queryset.filter(created_at__gte=start_of_day(value))

    def filter_date_to(self, queryset, name, value):
        return queryset.filter(created_at__lte=end_of_day(value))
```

- [ ] **Step 5: Add the viewset**

Append to `apps/sales/views.py`:

```python
class SaleViewSet(
    RoleScopedPermissionMixin,
    CamelCaseQueryParamsMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Create, list and retrieve. A sale's only mutation is cancellation,
    which is its own action — there is no update and no destroy."""

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_class = SaleFilterSet
    search_fields = ["reference", "customer_name", "note"]

    # Cashiers work the till: they create sales and take payments. They do not
    # cancel — that is the manager's call.
    permission_map = {"cancel": IsManagerOrAbove}

    def get_queryset(self):
        queryset = sale_queryset()
        if self.action == "retrieve":
            return queryset.prefetch_related("lines", "payments")
        return queryset

    def get_serializer_class(self):
        if self.action == "create":
            return SaleCreateSerializer
        if self.action == "retrieve":
            return SaleDetailSerializer
        return SaleSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        sale = create_sale(
            lines=data["lines"],
            user=request.user,
            site=Site.objects.current(),
            customer=data.get("customer"),
            discount=data.get("discount", 0),
            discount_rate=data.get("discount_rate"),
            note=data.get("note"),
        )

        # Re-read through the annotated queryset: a bare Sale has no
        # paid_amount or line_count, and the response serializer needs both.
        annotated = sale_queryset().get(pk=sale.pk)
        return Response(
            SaleSerializer(annotated, context=self.get_serializer_context()).data,
            status=201,
        )
```

Extend the imports at the top of `apps/sales/views.py`:

```python
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, mixins, viewsets
from rest_framework.response import Response

from apps.accounts.models import Site
from apps.common.filters import CamelCaseQueryParamsMixin
from apps.common.pagination import StandardPagination
from apps.common.permissions import IsManagerOrAbove, RoleScopedPermissionMixin
from apps.sales.filters import SaleFilterSet
from apps.sales.querysets import sale_queryset
from apps.sales.serializers import (
    CustomerSerializer,
    SaleCreateSerializer,
    SaleDetailSerializer,
    SaleSerializer,
)
from apps.sales.services import create_sale
```

Register in `apps/sales/urls.py`:

```python
from apps.sales.views import CustomerViewSet, SaleViewSet

router.register("sales", SaleViewSet, basename="sale")
```

- [ ] **Step 6: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/sales/tests/test_sales_api.py -p no:warnings`

Adjust the `django_assert_num_queries(3)` bound only after confirming it does
not grow with page size — add ten more sales and check it is unchanged.
Growth means a missing `select_related` on the queryset.

- [ ] **Step 7: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/sales
git commit -m "Add the sale create, list and detail endpoints"
```

---

## Task 9: Payments

**Files:**
- Modify: `apps/sales/services.py`, `apps/sales/serializers.py`, `apps/sales/views.py`
- Test: `apps/sales/tests/test_payments.py`

**Interfaces:**
- Consumes: `apps.common.money.format_cents`, `apps.common.dates.at_local_noon`.
- Produces: `apps.sales.services.add_payment(*, sale, amount, method, paid_at, user, reference=None, note=None) -> Payment` where `paid_at` is a `datetime.date`; `apps.sales.serializers.PaymentCreateSerializer`; a `payments` action on `SaleViewSet`.

- [ ] **Step 1: Write the failing test**

Create `apps/sales/tests/test_payments.py`:

```python
"""POST /api/sales/{id}/payments/."""

from datetime import datetime, timezone as dt_timezone

import pytest

from apps.catalogue.tests.factories import ArticleFactory
from apps.sales.models import Payment, Sale
from apps.sales.services import create_sale
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db


def stocked(site, quantity=100):
    article = ArticleFactory()
    StockLevelFactory(article=article, site=site, quantity=quantity)
    return article


def make(site, user, unit_price=5_000, quantity=2):
    return create_sale(
        lines=[{"article": stocked(site), "quantity": quantity, "unit_price": unit_price}],
        user=user,
        site=site,
    )


def url(sale):
    return f"/api/sales/{sale.id}/payments/"


def body(**overrides):
    payload = {
        "amount": 3_000,
        "method": "CASH",
        "paidAt": "2026-07-02",
        "reference": None,
        "note": None,
    }
    payload.update(overrides)
    return payload


class TestCreate:
    def test_a_cashier_can_record_a_payment(self, auth_client, cashier, site, owner):
        sale = make(site, owner)
        response = auth_client(cashier).post(url(sale), body(), format="json")

        assert response.status_code == 201
        assert response.json()["amount"] == 3_000
        assert Payment.objects.count() == 1

    def test_the_payload_matches_the_frontend_payment_type(
        self, auth_client, cashier, site, owner
    ):
        sale = make(site, owner)
        response = auth_client(cashier).post(url(sale), body(), format="json")

        assert set(response.json()) == {
            "id",
            "saleId",
            "amount",
            "method",
            "paidAt",
            "reference",
            "note",
            "userId",
            "userName",
            "createdAt",
        }

    def test_paid_at_is_widened_to_local_noon(
        self, auth_client, cashier, site, owner, settings
    ):
        """The picker gives a bare date. Noon, not midnight, so the stored
        instant lands on the day the user picked whatever the offset."""
        settings.SHOP_TIME_ZONE = "Africa/Kinshasa"
        sale = make(site, owner)

        auth_client(cashier).post(url(sale), body(paidAt="2026-07-02"), format="json")

        # Kinshasa is UTC+1, so local noon is 11:00 UTC.
        assert Payment.objects.get().paid_at == datetime(
            2026, 7, 2, 11, 0, tzinfo=dt_timezone.utc
        )

    def test_the_sale_reflects_the_payment(self, auth_client, cashier, site, owner):
        sale = make(site, owner)  # total 10 000
        auth_client(cashier).post(url(sale), body(amount=3_000), format="json")

        payload = auth_client(cashier).get(f"/api/sales/{sale.id}/").json()
        assert payload["paidAmount"] == 3_000
        assert payload["balance"] == 7_000
        assert payload["paymentStatus"] == "PARTIAL"

    def test_paying_the_balance_marks_it_paid(self, auth_client, cashier, site, owner):
        sale = make(site, owner)
        auth_client(cashier).post(url(sale), body(amount=sale.total), format="json")

        payload = auth_client(cashier).get(f"/api/sales/{sale.id}/").json()
        assert payload["balance"] == 0
        assert payload["paymentStatus"] == "PAID"

    def test_the_user_name_is_snapshotted(self, auth_client, cashier, site, owner):
        sale = make(site, owner)
        auth_client(cashier).post(url(sale), body(), format="json")
        assert Payment.objects.get().user_name == cashier.full_name


class TestValidation:
    def test_a_zero_amount_is_rejected(self, auth_client, cashier, site, owner):
        sale = make(site, owner)
        response = auth_client(cashier).post(url(sale), body(amount=0), format="json")
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["amount"] == [
            "Le montant doit être supérieur à zéro."
        ]

    def test_overpayment_is_refused_with_the_balance_in_the_message(
        self, auth_client, cashier, site, owner
    ):
        """Cheaper to refuse than to explain a negative balance afterwards."""
        sale = make(site, owner)  # total 10 000
        auth_client(cashier).post(url(sale), body(amount=4_000), format="json")

        response = auth_client(cashier).post(
            url(sale), body(amount=6_001), format="json"
        )

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["amount"] == [
            "Le montant dépasse le solde restant dû (60,00 $US)."
        ]
        assert Payment.objects.count() == 1

    def test_paying_exactly_the_balance_is_allowed(
        self, auth_client, cashier, site, owner
    ):
        sale = make(site, owner)
        auth_client(cashier).post(url(sale), body(amount=4_000), format="json")
        response = auth_client(cashier).post(
            url(sale), body(amount=6_000), format="json"
        )
        assert response.status_code == 201

    def test_a_payment_on_a_cancelled_sale_is_refused(
        self, auth_client, cashier, site, owner
    ):
        sale = make(site, owner)
        Sale.objects.filter(pk=sale.pk).update(status="CANCELLED")

        response = auth_client(cashier).post(url(sale), body(), format="json")

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["amount"] == [
            "Cette vente est annulée : aucun paiement ne peut être ajouté."
        ]

    def test_an_invalid_method_is_rejected(self, auth_client, cashier, site, owner):
        sale = make(site, owner)
        response = auth_client(cashier).post(
            url(sale), body(method="BITCOIN"), format="json"
        )
        assert response.status_code == 400
        assert "method" in response.json()["fieldErrors"]

    def test_an_unknown_sale_is_404(self, auth_client, cashier, site):
        import uuid

        response = auth_client(cashier).post(
            f"/api/sales/{uuid.uuid4()}/payments/", body(), format="json"
        )
        assert response.status_code == 404
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/sales/tests/test_payments.py -p no:warnings`
Expected: FAIL — 404, the action is not registered.

- [ ] **Step 3: Implement `add_payment`**

Append to `apps/sales/services.py`:

```python
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
        sale=sale,
        amount=amount,
        method=method,
        paid_at=at_local_noon(paid_at),
        reference=_clean(reference),
        note=_clean(note),
        user=user,
        user_name=user.full_name,
    )
```

Extend the module imports:

```python
from django.db.models import Sum

from apps.common.dates import at_local_noon, shop_today
from apps.common.money import format_cents
from apps.sales.models import Payment, Sale, SaleLine
```

- [ ] **Step 4: Add the write serializer**

Append to `apps/sales/serializers.py`:

```python
class PaymentCreateSerializer(serializers.Serializer):
    """The frontend's `PaymentCreateDto`."""

    amount = serializers.IntegerField(
        min_value=1,
        error_messages={
            "min_value": _("Le montant doit être supérieur à zéro."),
            "invalid": _("Le montant doit être supérieur à zéro."),
        },
    )
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    #: A bare calendar date from a picker; the service widens it to local noon.
    paid_at = serializers.DateField()
    reference = serializers.CharField(
        max_length=40, required=False, allow_blank=True, allow_null=True, default=None
    )
    note = serializers.CharField(
        max_length=300, required=False, allow_blank=True, allow_null=True, default=None
    )
```

- [ ] **Step 5: Add the action**

Append to `SaleViewSet` in `apps/sales/views.py`:

```python
    @action(detail=True, methods=["post"], url_path="payments")
    def payments(self, request, pk=None):
        sale = self.get_object()
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        payment = add_payment(
            sale=sale,
            amount=data["amount"],
            method=data["method"],
            paid_at=data["paid_at"],
            user=request.user,
            reference=data.get("reference"),
            note=data.get("note"),
        )

        return Response(PaymentSerializer(payment).data, status=201)
```

Extend the imports:

```python
from rest_framework.decorators import action

from apps.sales.serializers import (
    CustomerSerializer,
    PaymentCreateSerializer,
    PaymentSerializer,
    SaleCreateSerializer,
    SaleDetailSerializer,
    SaleSerializer,
)
from apps.sales.services import add_payment, create_sale
```

> `payments` is not in `permission_map`, so it falls to `default_permission`
> — `IsAuthenticated`. That is correct: cashiers take payments.

- [ ] **Step 6: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/sales/tests/test_payments.py -p no:warnings`
Expected: all PASS.

If the overpayment message fails on whitespace, check `format_cents` is
emitting U+00A0 before `$US` — the test asserts the exact character.

- [ ] **Step 7: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/sales
git commit -m "Add payment recording with overpayment refused"
```

---

## Task 10: Cancellation

**Files:**
- Modify: `apps/sales/services.py`, `apps/sales/serializers.py`, `apps/sales/views.py`
- Test: `apps/sales/tests/test_cancel_sale.py`

**Interfaces:**
- Consumes: `apply_movement`.
- Produces: `apps.sales.services.cancel_sale(*, sale, reason=None, user) -> Sale`; `apps.sales.serializers.SaleCancelSerializer`; a `cancel` action on `SaleViewSet`.

- [ ] **Step 1: Write the failing test**

Create `apps/sales/tests/test_cancel_sale.py`:

```python
"""POST /api/sales/{id}/cancel/."""

import pytest

from apps.catalogue.tests.factories import ArticleFactory
from apps.sales.models import Sale
from apps.sales.services import create_sale
from apps.sales.tests.factories import PaymentFactory
from apps.stock.models import StockLevel, StockMovement
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db


def stocked(site, quantity=100):
    article = ArticleFactory()
    StockLevelFactory(article=article, site=site, quantity=quantity)
    return article


def make(site, user, articles=None, quantity=2):
    articles = articles or [stocked(site)]
    return create_sale(
        lines=[
            {"article": a, "quantity": quantity, "unit_price": 5_000} for a in articles
        ],
        user=user,
        site=site,
    )


def url(sale):
    return f"/api/sales/{sale.id}/cancel/"


class TestCancel:
    def test_a_manager_can_cancel(self, auth_client, manager, site, owner):
        sale = make(site, owner)
        response = auth_client(manager).post(url(sale), {"reason": None}, format="json")

        assert response.status_code == 200
        assert response.json()["status"] == "CANCELLED"
        assert response.json()["cancelledAt"] is not None

    def test_the_reason_is_recorded(self, auth_client, manager, site, owner):
        sale = make(site, owner)
        response = auth_client(manager).post(
            url(sale), {"reason": "Erreur de saisie"}, format="json"
        )
        assert response.json()["cancelReason"] == "Erreur de saisie"

    def test_a_blank_reason_becomes_null(self, auth_client, manager, site, owner):
        sale = make(site, owner)
        response = auth_client(manager).post(url(sale), {"reason": "  "}, format="json")
        assert response.json()["cancelReason"] is None


class TestStockRestoration:
    def test_each_line_gets_a_compensating_in_return(
        self, auth_client, manager, site, owner
    ):
        """Movements are append-only, so cancelling never deletes them."""
        first, second = stocked(site), stocked(site)
        sale = make(site, owner, [first, second])

        auth_client(manager).post(url(sale), {"reason": None}, format="json")

        movements = sale.movements.all()
        assert movements.filter(type="OUT", reason="SALE").count() == 2
        assert movements.filter(type="IN", reason="RETURN").count() == 2

    def test_the_original_movements_are_untouched(
        self, auth_client, manager, site, owner
    ):
        sale = make(site, owner)
        original = sale.movements.get()

        auth_client(manager).post(url(sale), {"reason": None}, format="json")
        original.refresh_from_db()

        assert original.type == "OUT"
        assert original.reason == "SALE"

    def test_stock_returns_to_its_pre_sale_level(
        self, auth_client, manager, site, owner
    ):
        article = stocked(site, quantity=50)
        sale = make(site, owner, [article], quantity=8)
        assert StockLevel.objects.get(article=article).quantity == 42

        auth_client(manager).post(url(sale), {"reason": None}, format="json")

        assert StockLevel.objects.get(article=article).quantity == 50

    def test_the_compensating_movement_carries_the_same_sale(
        self, auth_client, manager, site, owner
    ):
        """Which is why the movement journal can link both halves to one
        document."""
        sale = make(site, owner)
        auth_client(manager).post(url(sale), {"reason": None}, format="json")

        assert sale.movements.count() == 2
        assert all(m.sale_id == sale.id for m in sale.movements.all())

    def test_the_compensating_note_defaults_to_naming_the_sale(
        self, auth_client, manager, site, owner
    ):
        sale = make(site, owner)
        auth_client(manager).post(url(sale), {"reason": None}, format="json")

        compensating = sale.movements.get(type="IN")
        assert compensating.note == f"Annulation de la vente {sale.reference}"

    def test_a_supplied_reason_becomes_the_note(
        self, auth_client, manager, site, owner
    ):
        sale = make(site, owner)
        auth_client(manager).post(url(sale), {"reason": "Client parti"}, format="json")

        assert sale.movements.get(type="IN").note == "Client parti"


class TestBalance:
    def test_a_cancelled_sale_owes_nothing(self, auth_client, manager, site, owner):
        sale = make(site, owner)
        auth_client(manager).post(url(sale), {"reason": None}, format="json")

        payload = auth_client(manager).get(f"/api/sales/{sale.id}/").json()
        assert payload["balance"] == 0

    def test_money_already_received_is_not_refunded(
        self, auth_client, manager, site, owner
    ):
        """This sub-project does not move money out. The frontend reports it
        as « Remboursement dû »."""
        sale = make(site, owner)
        PaymentFactory(sale=sale, user=owner, amount=4_000)

        auth_client(manager).post(url(sale), {"reason": None}, format="json")

        payload = auth_client(manager).get(f"/api/sales/{sale.id}/").json()
        assert payload["paidAmount"] == 4_000
        assert payload["balance"] == 0
        assert len(payload["payments"]) == 1


class TestGuards:
    def test_cancelling_twice_is_rejected(self, auth_client, manager, site, owner):
        sale = make(site, owner)
        auth_client(manager).post(url(sale), {"reason": None}, format="json")

        response = auth_client(manager).post(url(sale), {"reason": None}, format="json")

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["reason"] == [
            "Cette vente est déjà annulée."
        ]

    def test_a_second_cancellation_posts_no_extra_movements(
        self, auth_client, manager, site, owner
    ):
        sale = make(site, owner)
        auth_client(manager).post(url(sale), {"reason": None}, format="json")
        before = StockMovement.objects.count()

        auth_client(manager).post(url(sale), {"reason": None}, format="json")

        assert StockMovement.objects.count() == before

    def test_a_cashier_may_not_cancel(self, auth_client, cashier, site, owner):
        sale = make(site, owner)
        response = auth_client(cashier).post(url(sale), {"reason": None}, format="json")
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/sales/tests/test_cancel_sale.py -p no:warnings`
Expected: FAIL — 404, the action is not registered.

- [ ] **Step 3: Implement `cancel_sale`**

Append to `apps/sales/services.py`:

```python
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
    note = cleaned_reason or _("Annulation de la vente %(reference)s") % {
        "reference": sale.reference
    }

    for line in sale.lines.select_related("article"):
        apply_movement(
            article=line.article,
            site=sale.site,
            type="IN",
            reason="RETURN",
            quantity=line.quantity,
            unit_cost=None,
            reference=sale.reference,
            note=str(note),
            user=user,
            sale=sale,
        )

    sale.status = Sale.Status.CANCELLED
    sale.cancelled_at = timezone.now()
    sale.cancel_reason = cleaned_reason
    sale.save(update_fields=["status", "cancelled_at", "cancel_reason", "updated_at"])
    return sale
```

Add `from django.utils import timezone` to the module imports.

- [ ] **Step 4: Add the serializer and action**

Append to `apps/sales/serializers.py`:

```python
class SaleCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(
        max_length=300, required=False, allow_blank=True, allow_null=True, default=None
    )
```

Append to `SaleViewSet`:

```python
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        sale = self.get_object()
        serializer = SaleCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cancel_sale(
            sale=sale, reason=serializer.validated_data.get("reason"), user=request.user
        )

        annotated = sale_queryset().get(pk=sale.pk)
        return Response(
            SaleSerializer(annotated, context=self.get_serializer_context()).data
        )
```

Extend the imports with `SaleCancelSerializer` and `cancel_sale`.

- [ ] **Step 5: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/sales/tests/test_cancel_sale.py -p no:warnings`
Expected: all PASS.

`test_a_cashier_may_not_cancel` proves the `permission_map` entry from Task 8
is wired — if it returns 201, `cancel` is not in the map or the mixin is not on
the viewset.

- [ ] **Step 6: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/sales
git commit -m "Add sale cancellation with compensating movements"
```

---

## Task 11: Admin, README and the wire check

**Files:**
- Create: `apps/sales/admin.py`
- Modify: `README.md`
- Test: manual wire verification, then the full suite

- [ ] **Step 1: Register the admin**

Create `apps/sales/admin.py`:

```python
from django.contrib import admin

from apps.sales.models import Customer, Payment, Sale, SaleLine


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["name", "contact_name", "phone", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "contact_name", "email"]


class SaleLineInline(admin.TabularInline):
    model = SaleLine
    extra = 0
    readonly_fields = [f.name for f in SaleLine._meta.fields]
    can_delete = False


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = [
        "reference",
        "created_at",
        "customer_name",
        "status",
        "total",
        "user_name",
    ]
    list_filter = ["status"]
    search_fields = ["reference", "customer_name", "note"]
    inlines = [SaleLineInline]
    # An issued invoice is not editable from the admin. Cancellation is an
    # API action with stock consequences; doing it here would change a status
    # without giving the stock back.
    readonly_fields = [f.name for f in Sale._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["sale", "paid_at", "amount", "method", "user_name"]
    list_filter = ["method"]
    search_fields = ["sale__reference", "reference"]
    readonly_fields = [f.name for f in Payment._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

- [ ] **Step 2: Update the README**

Add to the endpoints table:

```
| `/api/customers/` `…/{id}/` | GET POST PATCH DELETE | gérant · DELETE propriétaire |
| `/api/sales/` | GET, POST | tous (caissier compris) |
| `/api/sales/{id}/` | GET | — |
| `/api/sales/{id}/cancel/` | POST | gérant |
| `/api/sales/{id}/payments/` | POST | tous (caissier compris) |
```

Add a short French section covering: that a sale is an invoice and its
`reference` is `FA-YYYY-NNNN` from the same year-scoped sequence as `TR-`;
that a sale is immutable apart from cancellation, which posts compensating
`IN`/`RETURN` movements rather than deleting anything and does **not** refund
money already received; that `paidAmount`, `balance` and `paymentStatus` are
derived on every read and never stored; and that line prices, names, VAT rates
and costs are snapshotted so repricing an article never rewrites an existing
sale.

- [ ] **Step 3: Verify the wire format**

Start the server against a scratch database as sub-project 3's Task 7 did, then
check each payload's exact key set against `types/domain.ts`:

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8393/api/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"email":"...","password":"..."}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["accessToken"])')

curl -s http://127.0.0.1:8393/api/sales/ -H "Authorization: Bearer $TOKEN" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(sorted(d)); print(sorted(d["results"][0]))'
```

Confirm, key by key:

- a sale row carries `paidAmount`, `balance` and `paymentStatus`, and `customer`
  is `{id, name}` or `null`
- the detail route adds `lines` and `payments`, and widens `customer` to
  `{id, name, address, taxNumber}`
- `vatRate` on a line is a JSON **number**, not a quoted string
- a movement created by a sale reports a non-null `saleId` and a null
  `transactionId`
- posting a sale then over-paying it returns 400 with the balance formatted as
  `… $US` in `fieldErrors.amount`
- cancelling returns `status: "CANCELLED"` and a later `GET` shows
  `balance: 0` with the payments still listed

- [ ] **Step 4: Final checks**

```bash
~/.pyenv/versions/stock/bin/python manage.py check
~/.pyenv/versions/stock/bin/python manage.py makemigrations --check --dry-run
~/.pyenv/versions/stock/bin/pytest -p no:warnings
```

All three must be clean. Report the actual test count; do not estimate it.

- [ ] **Step 5: Commit**

```bash
git add apps/sales/admin.py README.md
git commit -m "Register the sales admin and document the endpoints"
```

---

## Notes for the reviewer

Things a passing suite does not prove:

- **No `round()` anywhere.** `grep -rn "round(" apps/sales apps/common --include="*.py"`
  should return only `round_half_up`'s definition and its call sites. Python's
  `round` is banker's rounding and would be a silent one-cent error on
  invoices.
- **`paid_amount` is a subquery.** If someone "simplifies" it to
  `Sum("payments__amount")`, `test_lines_and_payments_do_not_multiply_each_other`
  fails — but only because that test exists. Check it is still there.
- **The import direction.** `grep -n "from apps.sales" apps/stock apps/catalogue -r`
  should return nothing. `StockMovement.sale` uses the lazy string form.
- **`create_sale` owns its atomic block**, not the view. The no-gap invoice
  numbering depends on `next_reference` sharing it.
- **Cashier permissions are inverted from the catalogue.** Cashiers *can*
  create sales and payments and *cannot* cancel. If `permission_map` grew a
  `create` entry, the till stops working and only one test catches it.
- **Query-count bounds.** If either was raised, confirm it does not grow with
  the row count.
