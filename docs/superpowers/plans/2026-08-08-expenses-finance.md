# Expenses & Finance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement expenses with full CRUD and the three finance reads — summary, series and breakdown — retiring the frontend's `features/finance/lib/aggregate.ts` and `period.ts`.

**Architecture:** Two new apps. `apps/expenses/` owns a model. `apps/finance/` owns three files with a deliberate split: `facts.py` is the only one that touches the ORM, while `period.py` and `aggregate.py` import nothing from Django — the same shape as `apps/sales/totals.py`, and for the same reason: it lets both be diffed against the frontend's own implementation in Node.

**Tech Stack:** Django 6.0.7, DRF 3.17.1, django-filter 26.1, pytest 9.1.1 + pytest-django 4.12.0 + factory-boy 3.3.3. No new dependencies.

## Global Constraints

Every task's requirements implicitly include this section.

- **Read the spec first:** `docs/superpowers/specs/2026-08-08-expenses-finance-design.md`. Sub-project 1's spec has the wire conventions, 2's the filter/permission/date ones, 4's the money rules.
- **Python env:** pyenv's `stock`. Run as `~/.pyenv/versions/stock/bin/python` / `~/.pyenv/versions/stock/bin/pytest`.
- **The suite takes ~8 minutes.** Run the focused file while iterating; run everything before committing.
- **TDD, strictly.** Write the failing test, watch it fail for the right reason, then implement. Do not write a view that references a function from a later task — that leaves the module unimportable and forces the implementation in ahead of its test, which is how sub-project 4 lost its red-green cycle on three tasks.
- **Two opposite float rules, one module apart:**
  - **Money is integer cents.** Never a float. If a division is needed, use `apps.common.money.round_half_up` — Python's `round()` is banker's rounding and the frontend is half-up.
  - **Percentages are unrounded floats.** `marginRate` and `share` are `(a / b) * 100` with **no rounding**. Verified: Python and JS agree bit-for-bit on the unrounded value and through JSON (`(7/11)*100` is `63.63636363636363` in both). Adding a `round()` is what would create a difference.
- **`period.py` and `aggregate.py` must not import Django.** A test asserts this.
- **Every user-facing string is French**, via `gettext_lazy as _`.
- **`Site.objects.current()`** is how you get the site.
- **Models inherit `apps.common.models.UUIDModel`** — it supplies `id`, `created_at`, `updated_at`.
- **Optional strings:** column `null=True, blank=True`; serializer `required=False, allow_blank=True, allow_null=True`; normalise `""` to `None`.
- **Any annotated list queryset needs an explicit `.order_by()`.** Django drops `Meta.ordering` from any query with a `GROUP BY`; the sale list shipped unordered in sub-project 4 because of it.
- **Commit at the end of every task**, with the trailer:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01BVSaiKSTQQad3uwxNLsNPU
  ```
- **Never predict a test count.**

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/expenses/models.py` | `Expense` |
| `apps/expenses/serializers.py` | the read/write shape |
| `apps/expenses/filters.py` | `ExpenseFilterSet` |
| `apps/expenses/views.py` | `ExpenseViewSet` |
| `apps/finance/period.py` | **no Django** — granularity, buckets, French labels |
| `apps/finance/aggregate.py` | **no Django** — summarise, bucketise, build_breakdown |
| `apps/finance/facts.py` | the only ORM seam: five `.values()` projections |
| `apps/finance/serializers.py` | the range query params |
| `apps/finance/views.py` | three read endpoints |

Dependency direction, one way: `apps.expenses` → `apps.sales` (for
`Payment.Method`); `apps.finance` → `apps.expenses`, `apps.sales`, `apps.stock`.
Nothing imports `apps.finance`.

---

## Task 1: The Expense model and endpoints

**Files:**
- Create: `apps/expenses/{__init__,apps,models,serializers,filters,views,urls}.py`, `apps/expenses/migrations/__init__.py`, `apps/expenses/tests/{__init__,factories}.py`
- Modify: `stockmanager/settings.py`, `stockmanager/urls.py`
- Test: `apps/expenses/tests/test_expenses.py`

**Interfaces:**
- Consumes: `apps.sales.models.Payment.Method`, `apps.common.dates.at_local_noon`, `apps.common.dates.shop_today`, `apps.common.views.CatalogueViewSet`, `apps.common.permissions.IsManagerOrAbove`.
- Produces: `apps.expenses.models.Expense`, `Expense.Category`; `apps.expenses.tests.factories.ExpenseFactory`.

Expenses are **Manager and above for every action, reads included** — a cashier
gets 403 on the list too. That is not the catalogue map, so `ExpenseViewSet`
overrides `default_permission` rather than inheriting the read-for-anyone rule.

- [ ] **Step 1: Write the failing test**

Create `apps/expenses/tests/test_expenses.py`:

```python
"""Expense endpoints. Payload from the frontend's `Expense` type."""

import uuid
from datetime import datetime, timezone as dt_timezone

import pytest

from apps.expenses.models import Expense
from apps.expenses.tests.factories import ExpenseFactory

pytestmark = pytest.mark.django_db

LIST_URL = "/api/expenses/"


def detail_url(expense) -> str:
    return f"{LIST_URL}{expense.id}/"


def body(**overrides):
    payload = {
        "category": "RENT",
        "label": "Loyer du mois",
        "amount": 250_000,
        "method": "CASH",
        "spentAt": "2026-07-02",
        "reference": None,
        "note": None,
    }
    payload.update(overrides)
    return payload


class TestRead:
    def test_the_payload_matches_the_frontend_type(self, auth_client, manager, site):
        ExpenseFactory(site=site, user=manager, user_name=manager.full_name)

        response = auth_client(manager).get(LIST_URL)

        assert response.status_code == 200
        assert set(response.json()["results"][0]) == {
            "id",
            "siteId",
            "category",
            "label",
            "amount",
            "method",
            "spentAt",
            "reference",
            "note",
            "userId",
            "userName",
            "createdAt",
        }

    def test_newest_spend_first(self, auth_client, manager, site):
        older = ExpenseFactory(site=site, user=manager, label="Ancienne")
        newer = ExpenseFactory(site=site, user=manager, label="Récente")
        Expense.objects.filter(pk=older.pk).update(
            spent_at=datetime(2026, 7, 1, 12, tzinfo=dt_timezone.utc)
        )
        Expense.objects.filter(pk=newer.pk).update(
            spent_at=datetime(2026, 7, 5, 12, tzinfo=dt_timezone.utc)
        )

        response = auth_client(manager).get(LIST_URL)

        assert [r["label"] for r in response.json()["results"]] == [
            "Récente",
            "Ancienne",
        ]

    def test_filter_by_category(self, auth_client, manager, site):
        ExpenseFactory(site=site, user=manager, category="RENT")
        ExpenseFactory(site=site, user=manager, category="SALARY")

        response = auth_client(manager).get(f"{LIST_URL}?category=SALARY")

        assert response.json()["count"] == 1

    def test_an_invalid_category_is_400(self, auth_client, manager, site):
        response = auth_client(manager).get(f"{LIST_URL}?category=CAVIAR")
        assert response.status_code == 400
        assert "category" in response.json()["fieldErrors"]

    def test_search_covers_label_reference_and_note(self, auth_client, manager, site):
        ExpenseFactory(
            site=site, user=manager, label="Loyer", reference="REF-1", note="Juillet"
        )
        ExpenseFactory(site=site, user=manager, label="Salaires")
        client = auth_client(manager)

        assert client.get(f"{LIST_URL}?search=loyer").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=REF-1").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=juillet").json()["count"] == 1

    def test_date_bounds_use_the_shop_timezone(
        self, auth_client, manager, site, settings
    ):
        """Kinshasa is UTC+1, so 23:30 UTC is already the next local day."""
        settings.SHOP_TIME_ZONE = "Africa/Kinshasa"
        expense = ExpenseFactory(site=site, user=manager)
        Expense.objects.filter(pk=expense.pk).update(
            spent_at=datetime(2026, 7, 1, 23, 30, tzinfo=dt_timezone.utc)
        )

        client = auth_client(manager)
        assert client.get(f"{LIST_URL}?dateFrom=2026-07-02").json()["count"] == 1
        assert client.get(f"{LIST_URL}?dateTo=2026-07-01").json()["count"] == 0


class TestWrite:
    def test_a_manager_can_create(self, auth_client, manager, site):
        response = auth_client(manager).post(LIST_URL, body(), format="json")

        assert response.status_code == 201
        assert response.json()["label"] == "Loyer du mois"
        assert response.json()["amount"] == 250_000
        assert response.json()["userName"] == manager.full_name

    def test_spent_at_is_widened_to_local_noon(
        self, auth_client, manager, site, settings
    ):
        """Noon so that neither a positive nor a negative offset can push the
        instant onto the adjacent day — the very boundary reports slice at."""
        settings.SHOP_TIME_ZONE = "Africa/Kinshasa"

        auth_client(manager).post(LIST_URL, body(spentAt="2026-07-02"), format="json")

        assert Expense.objects.get().spent_at == datetime(
            2026, 7, 2, 11, 0, tzinfo=dt_timezone.utc
        )

    def test_blank_optionals_become_null(self, auth_client, manager, site):
        response = auth_client(manager).post(
            LIST_URL, body(reference="", note="  "), format="json"
        )
        assert response.json()["reference"] is None
        assert response.json()["note"] is None

    def test_an_expense_can_be_edited(self, auth_client, manager, site):
        """Unlike a sale. An expense is a private record, not a document
        issued to anyone."""
        expense = ExpenseFactory(site=site, user=manager, amount=1_000)

        response = auth_client(manager).patch(
            detail_url(expense), {"amount": 2_000}, format="json"
        )

        assert response.status_code == 200
        expense.refresh_from_db()
        assert expense.amount == 2_000

    def test_an_expense_can_be_deleted(self, auth_client, manager, site):
        """`removeExpense`: nothing references an expense, so unlike a
        customer this deletes outright."""
        expense = ExpenseFactory(site=site, user=manager)

        assert auth_client(manager).delete(detail_url(expense)).status_code == 204
        assert Expense.objects.count() == 0

    def test_unknown_id_is_404_with_the_envelope(self, auth_client, manager, site):
        response = auth_client(manager).get(f"{LIST_URL}{uuid.uuid4()}/")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"


class TestValidation:
    @pytest.mark.parametrize("amount", [0, -1])
    def test_a_non_positive_amount_is_rejected(
        self, auth_client, manager, site, amount
    ):
        response = auth_client(manager).post(
            LIST_URL, body(amount=amount), format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["amount"] == [
            "Le montant doit être supérieur à zéro."
        ]

    def test_a_short_label_is_rejected(self, auth_client, manager, site):
        response = auth_client(manager).post(LIST_URL, body(label="X"), format="json")
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["label"] == [
            "Le libellé doit contenir au moins 2 caractères."
        ]

    def test_an_over_long_label_is_rejected(self, auth_client, manager, site):
        response = auth_client(manager).post(
            LIST_URL, body(label="X" * 121), format="json"
        )
        assert response.status_code == 400
        assert "label" in response.json()["fieldErrors"]

    def test_a_future_date_is_rejected(self, auth_client, manager, site):
        from datetime import timedelta

        from apps.common.dates import shop_today

        tomorrow = shop_today() + timedelta(days=1)
        response = auth_client(manager).post(
            LIST_URL, body(spentAt=tomorrow.isoformat()), format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["spentAt"] == [
            "La date ne peut pas être dans le futur."
        ]

    def test_today_is_accepted_at_any_hour(self, auth_client, manager, site):
        """'An expense dated today is fine at any hour' — the comparison is on
        calendar days, not instants."""
        from apps.common.dates import shop_today

        response = auth_client(manager).post(
            LIST_URL, body(spentAt=shop_today().isoformat()), format="json"
        )
        assert response.status_code == 201

    def test_an_invalid_method_is_rejected(self, auth_client, manager, site):
        response = auth_client(manager).post(
            LIST_URL, body(method="BITCOIN"), format="json"
        )
        assert response.status_code == 400
        assert "method" in response.json()["fieldErrors"]


class TestPermissions:
    @pytest.mark.parametrize("method", ["get", "post", "patch", "delete"])
    def test_a_cashier_is_refused_everything(
        self, auth_client, cashier, manager, site, method
    ):
        """Expenses are manager-and-above for reads too — not the catalogue
        map, where a cashier may read."""
        expense = ExpenseFactory(site=site, user=manager)
        client = auth_client(cashier)
        url = LIST_URL if method in ("get", "post") else detail_url(expense)

        response = getattr(client, method)(url, {}, format="json")

        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"

    def test_an_owner_may_do_everything(self, auth_client, owner, site):
        assert auth_client(owner).post(LIST_URL, body(), format="json").status_code == 201
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/expenses -p no:warnings`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.expenses'`.

- [ ] **Step 3: Create the app package**

```bash
mkdir -p apps/expenses/migrations apps/expenses/tests
touch apps/expenses/__init__.py apps/expenses/migrations/__init__.py apps/expenses/tests/__init__.py
```

`apps/expenses/apps.py`:

```python
from django.apps import AppConfig


class ExpensesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.expenses"
    label = "expenses"
    verbose_name = "Charges"
```

Add `"apps.expenses"` to `INSTALLED_APPS` in `stockmanager/settings.py`, after
`"apps.sales"`.

- [ ] **Step 4: Write the model**

Create `apps/expenses/models.py`:

```python
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Site
from apps.common.models import UUIDModel
from apps.sales.models import Payment


class Expense(UUIDModel):
    """Money leaving the shop that is not a stock purchase.

    Editable and deletable, unlike a sale: nothing references an expense, and
    it is a private record rather than a document issued to anyone.
    """

    class Category(models.TextChoices):
        RENT = "RENT", _("Loyer")
        SALARY = "SALARY", _("Salaires")
        UTILITIES = "UTILITIES", _("Eau et électricité")
        TRANSPORT = "TRANSPORT", _("Transport")
        SUPPLIES = "SUPPLIES", _("Fournitures")
        TAX = "TAX", _("Taxes et impôts")
        OTHER = "OTHER", _("Autre")

    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="expenses")
    category = models.CharField(
        _("catégorie"), max_length=16, choices=Category.choices
    )
    label = models.CharField(_("libellé"), max_length=120)
    amount = models.PositiveIntegerField(_("montant"))
    # Reused, not redeclared: an expense is paid the same five ways a sale is.
    method = models.CharField(_("moyen"), max_length=20, choices=Payment.Method.choices)
    spent_at = models.DateTimeField(_("dépensé le"))
    reference = models.CharField(_("référence"), max_length=40, null=True, blank=True)
    note = models.CharField(_("note"), max_length=500, null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expenses"
    )
    user_name = models.CharField(_("auteur"), max_length=150)

    class Meta:
        ordering = ["-spent_at", "-id"]
        verbose_name = _("charge")
        verbose_name_plural = _("charges")

    def __str__(self) -> str:
        return f"{self.label} — {self.amount}"
```

- [ ] **Step 5: Write the factory**

Create `apps/expenses/tests/factories.py`:

```python
import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import SiteFactory, UserFactory
from apps.expenses.models import Expense


class ExpenseFactory(DjangoModelFactory):
    class Meta:
        model = Expense

    site = factory.SubFactory(SiteFactory)
    user = factory.SubFactory(UserFactory)
    user_name = factory.LazyAttribute(lambda obj: obj.user.full_name)
    category = Expense.Category.RENT
    label = factory.Sequence(lambda n: f"Charge {n}")
    amount = 50_000
    method = "CASH"
    spent_at = factory.LazyFunction(timezone.now)
    reference = None
    note = None
```

- [ ] **Step 6: Write the serializer**

Create `apps/expenses/serializers.py`:

```python
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.common.dates import at_local_noon, shop_today
from apps.expenses.models import Expense
from apps.sales.models import Payment


class SpentAtField(serializers.DateTimeField):
    """Reads as an ISO instant, writes as a bare calendar date.

    The contract is asymmetric on purpose: `Expense.spentAt` is an
    `ISODateTime`, but `ExpenseCreateDto.spentAt` is "2026-07-30" from a date
    picker. Reading the input through a DateField rather than a DateTimeField
    is not a style choice — `DateTimeField("2026-07-02")` yields midnight UTC,
    and `.astimezone(shop).date()` on that is the *previous* day for any shop
    west of Greenwich. Parsing a date involves no timezone at all, and
    `at_local_noon` then puts it on the right instant for any offset.
    """

    def to_internal_value(self, data):
        day = serializers.DateField().to_internal_value(data)
        # Calendar-day comparison: an expense dated today is fine at any hour.
        if day > shop_today():
            raise serializers.ValidationError(
                _("La date ne peut pas être dans le futur.")
            )
        return at_local_noon(day)


class ExpenseSerializer(serializers.ModelSerializer):
    """The frontend's `Expense`."""

    site_id = serializers.UUIDField(read_only=True)
    user_id = serializers.UUIDField(read_only=True)
    spent_at = SpentAtField()
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    reference = serializers.CharField(
        max_length=40, required=False, allow_blank=True, allow_null=True
    )
    note = serializers.CharField(
        max_length=500, required=False, allow_blank=True, allow_null=True
    )
    amount = serializers.IntegerField(
        min_value=1,
        error_messages={
            "min_value": _("Le montant doit être supérieur à zéro."),
            "invalid": _("Le montant doit être supérieur à zéro."),
        },
    )

    OPTIONAL_FIELDS = ("reference", "note")

    class Meta:
        model = Expense
        fields = [
            "id",
            "site_id",
            "category",
            "label",
            "amount",
            "method",
            "spent_at",
            "reference",
            "note",
            "user_id",
            "user_name",
            "created_at",
        ]
        read_only_fields = ["id", "site_id", "user_id", "user_name", "created_at"]

    def validate_label(self, value):
        label = value.strip()
        if len(label) < 2:
            raise serializers.ValidationError(
                _("Le libellé doit contenir au moins 2 caractères.")
            )
        if len(label) > 120:
            raise serializers.ValidationError(
                _("Le libellé ne peut pas dépasser 120 caractères.")
            )
        return label

    def validate(self, attrs):
        for field in self.OPTIONAL_FIELDS:
            if field in attrs:
                value = attrs[field]
                attrs[field] = value.strip() or None if value else None
        return attrs
```

- [ ] **Step 7: Write the filterset, viewset and URLs**

Create `apps/expenses/filters.py`:

```python
from django_filters import rest_framework as drf_filters

from apps.common.dates import end_of_day, start_of_day
from apps.expenses.models import Expense


class ExpenseFilterSet(drf_filters.FilterSet):
    category = drf_filters.ChoiceFilter(choices=Expense.Category.choices)
    date_from = drf_filters.DateFilter(method="filter_date_from")
    date_to = drf_filters.DateFilter(method="filter_date_to")

    class Meta:
        model = Expense
        fields = ["category", "date_from", "date_to"]

    def filter_date_from(self, queryset, name, value):
        return queryset.filter(spent_at__gte=start_of_day(value))

    def filter_date_to(self, queryset, name, value):
        return queryset.filter(spent_at__lte=end_of_day(value))
```

Create `apps/expenses/views.py`:

```python
from apps.accounts.models import Site
from apps.common.permissions import IsManagerOrAbove
from apps.common.views import CatalogueViewSet
from apps.expenses.filters import ExpenseFilterSet
from apps.expenses.models import Expense
from apps.expenses.serializers import ExpenseSerializer


class ExpenseViewSet(CatalogueViewSet):
    """Manager and above for *every* action, reads included.

    Not the catalogue map, where a cashier may read: the README's role table
    puts « Dépenses, finances, rapports » at manager and above outright, so
    `default_permission` is overridden rather than only the write actions.
    """

    queryset = Expense.objects.all()
    serializer_class = ExpenseSerializer
    filterset_class = ExpenseFilterSet
    search_fields = ["label", "reference", "note"]
    ordering_fields = ["spent_at", "amount", "created_at"]
    ordering = ["-spent_at"]

    default_permission = IsManagerOrAbove
    # Every action falls to the default; nothing is owner-only here. An
    # expense is deletable by any manager because nothing references it.
    permission_map = {}

    def perform_create(self, serializer):
        serializer.save(
            site=Site.objects.current(),
            user=self.request.user,
            user_name=self.request.user.full_name,
        )
```

Create `apps/expenses/urls.py`:

```python
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.expenses.views import ExpenseViewSet

router = DefaultRouter()
router.register("expenses", ExpenseViewSet, basename="expense")

urlpatterns = [path("", include(router.urls))]
```

Add to `stockmanager/urls.py`:

```python
    path("api/", include("apps.expenses.urls")),
```

- [ ] **Step 8: Migrate and run**

```bash
~/.pyenv/versions/stock/bin/python manage.py makemigrations expenses
~/.pyenv/versions/stock/bin/pytest apps/expenses -p no:warnings
```

Expected: all PASS.

If `test_a_cashier_is_refused_everything[get]` returns 200, the
`default_permission` override did not take — check that `CatalogueViewSet`
resolves `self.permission_map.get(self.action, self.default_permission)` and
that `permission_map` was emptied rather than inherited.

- [ ] **Step 9: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/python manage.py makemigrations --check --dry-run
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/expenses stockmanager/settings.py stockmanager/urls.py
git commit -m "Add the Expense model and endpoints"
```

---

## Task 2: Period arithmetic

**Files:**
- Create: `apps/finance/{__init__,apps}.py`, `apps/finance/period.py`, `apps/finance/tests/{__init__}.py`
- Modify: `stockmanager/settings.py`
- Test: `apps/finance/tests/test_period.py`

**Interfaces:**
- Consumes: nothing. **This module imports nothing from Django.**
- Produces:

```python
MONTH_ABBREVIATIONS: tuple[str, ...]        # 12 entries, index 0 = January
DAILY_BUCKET_LIMIT: int                      # 90

@dataclass(frozen=True)
class BucketSlot:
    key: str
    label: str

def days_in_range(start: date, end: date) -> int
def resolve_granularity(start: date, end: date) -> str      # "DAY" | "MONTH"
def bucket_key(moment: datetime, tz: tzinfo, granularity: str) -> str
def day_label(value: date) -> str                            # "12 juil."
def month_label(value: date) -> str                          # "juil. 2026"
def enumerate_buckets(start, end, granularity) -> list[BucketSlot]
def in_range(moment: datetime, tz: tzinfo, start: date, end: date) -> bool
```

`bucket_key` and `in_range` take an explicit `tzinfo` rather than reading
`settings.SHOP_TIME_ZONE`, which is what keeps this module Django-free. The
caller passes `apps.common.dates.shop_timezone()`.

- [ ] **Step 1: Write the failing test**

Create `apps/finance/tests/test_period.py`:

```python
"""Period arithmetic, ported from features/finance/lib/period.ts.

No Django, no database. The label test runs the frontend's own Intl call in
Node and diffs, because Django's French locale disagrees with it for two
months and the difference is invisible until it reaches a chart axis.
"""

import json
import shutil
import subprocess
from datetime import date, datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

import pytest

from apps.finance.period import (
    DAILY_BUCKET_LIMIT,
    MONTH_ABBREVIATIONS,
    bucket_key,
    day_label,
    days_in_range,
    enumerate_buckets,
    in_range,
    month_label,
    resolve_granularity,
)

KINSHASA = ZoneInfo("Africa/Kinshasa")


class TestNoDjangoImport:
    def test_the_module_does_not_import_django(self):
        """The isolation is the point: it is what lets this be diffed against
        the frontend's implementation without a database."""
        import inspect

        import apps.finance.period as module

        source = inspect.getsource(module)
        assert "django" not in source.lower()


class TestDaysInRange:
    @pytest.mark.parametrize(
        ("start", "end", "expected"),
        [
            (date(2026, 7, 1), date(2026, 7, 1), 1),
            (date(2026, 7, 1), date(2026, 7, 2), 2),
            (date(2026, 7, 1), date(2026, 7, 31), 31),
            (date(2026, 1, 1), date(2026, 12, 31), 365),
            (date(2024, 1, 1), date(2024, 12, 31), 366),  # leap year
            (date(2026, 1, 31), date(2026, 2, 1), 2),  # month boundary
        ],
    )
    def test_the_count_is_inclusive(self, start, end, expected):
        assert days_in_range(start, end) == expected


class TestGranularity:
    def test_ninety_days_is_still_daily(self):
        """Verified against the frontend: 2026-01-01..2026-03-31 is 90 days."""
        assert days_in_range(date(2026, 1, 1), date(2026, 3, 31)) == 90
        assert resolve_granularity(date(2026, 1, 1), date(2026, 3, 31)) == "DAY"

    def test_ninety_one_days_switches_to_monthly(self):
        assert days_in_range(date(2026, 1, 1), date(2026, 4, 1)) == 91
        assert resolve_granularity(date(2026, 1, 1), date(2026, 4, 1)) == "MONTH"

    def test_the_limit_is_ninety(self):
        assert DAILY_BUCKET_LIMIT == 90

    def test_a_single_day_is_daily(self):
        assert resolve_granularity(date(2026, 7, 1), date(2026, 7, 1)) == "DAY"


class TestLabels:
    def test_there_are_twelve_abbreviations(self):
        assert len(MONTH_ABBREVIATIONS) == 12

    def test_four_months_take_no_trailing_period(self):
        """CLDR gives a full stop only to an actually-abbreviated form. mars,
        mai, juin and août are written out, so they get none — which is why
        this table is transcribed rather than generated from a prefix."""
        without = [m for m in MONTH_ABBREVIATIONS if not m.endswith(".")]
        assert without == ["mars", "mai", "juin", "août"]

    def test_a_day_label(self):
        assert day_label(date(2026, 7, 12)) == "12 juil."

    def test_a_day_label_is_not_zero_padded(self):
        """Intl uses day: "numeric", not "2-digit"."""
        assert day_label(date(2026, 7, 2)) == "2 juil."

    def test_a_month_label(self):
        assert month_label(date(2026, 7, 12)) == "juil. 2026"

    def test_january_and_february_are_the_ones_django_gets_wrong(self):
        """Django's French locale gives 'jan.' and 'fév.'. The contract needs
        'janv.' and 'févr.'."""
        assert day_label(date(2026, 1, 12)) == "12 janv."
        assert day_label(date(2026, 2, 12)) == "12 févr."


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
class TestLabelsAgainstIntl:
    """The table is a transcription, so a test that only restates it proves
    nothing. This one asks the frontend's own formatter."""

    JS = """
    const day = new Intl.DateTimeFormat("fr-FR", {day: "numeric", month: "short"});
    const mon = new Intl.DateTimeFormat("fr-FR", {month: "short", year: "numeric"});
    const out = [];
    for (let m = 0; m < 12; m++) {
      const d = new Date(2026, m, 12);
      out.push([day.format(d), mon.format(d)]);
    }
    console.log(JSON.stringify(out));
    """

    def test_all_twelve_match_the_frontends_intl_output(self):
        result = subprocess.run(
            [NODE, "-e", self.JS], capture_output=True, text=True, check=True
        )
        expected = json.loads(result.stdout)

        for index, (want_day, want_month) in enumerate(expected):
            value = date(2026, index + 1, 12)
            assert day_label(value) == want_day
            assert month_label(value) == want_month


class TestBucketKey:
    def test_a_day_key_is_the_local_calendar_date(self):
        # 23:30 UTC on 1 July is 00:30 on 2 July in Kinshasa (UTC+1).
        moment = datetime(2026, 7, 1, 23, 30, tzinfo=dt_timezone.utc)
        assert bucket_key(moment, KINSHASA, "DAY") == "2026-07-02"

    def test_a_month_key_truncates_the_day(self):
        moment = datetime(2026, 7, 12, 10, 0, tzinfo=dt_timezone.utc)
        assert bucket_key(moment, KINSHASA, "MONTH") == "2026-07"

    def test_the_timezone_can_move_a_key_across_a_month_boundary(self):
        """23:30 UTC on 31 July is 1 August locally."""
        moment = datetime(2026, 7, 31, 23, 30, tzinfo=dt_timezone.utc)
        assert bucket_key(moment, KINSHASA, "MONTH") == "2026-08"


class TestEnumerateBuckets:
    def test_daily_buckets_cover_every_day_inclusive(self):
        slots = enumerate_buckets(date(2026, 7, 1), date(2026, 7, 3), "DAY")
        assert [s.key for s in slots] == ["2026-07-01", "2026-07-02", "2026-07-03"]
        assert [s.label for s in slots] == ["1 juil.", "2 juil.", "3 juil."]

    def test_empty_buckets_are_emitted(self):
        """'A quiet week must render as zeros; dropping it would compress the
        x-axis and make the chart claim the shop traded on days it was shut.'
        Enumeration does not know what has data — that is the point."""
        assert len(enumerate_buckets(date(2026, 7, 1), date(2026, 7, 31), "DAY")) == 31

    def test_monthly_buckets_start_at_the_months_of_the_bounds(self):
        slots = enumerate_buckets(date(2026, 7, 15), date(2026, 9, 3), "MONTH")
        assert [s.key for s in slots] == ["2026-07", "2026-08", "2026-09"]
        assert [s.label for s in slots] == ["juil. 2026", "août 2026", "sept. 2026"]

    def test_monthly_buckets_cross_a_year_boundary(self):
        slots = enumerate_buckets(date(2026, 11, 1), date(2027, 1, 31), "MONTH")
        assert [s.key for s in slots] == ["2026-11", "2026-12", "2027-01"]

    def test_a_single_day_yields_one_bucket(self):
        assert len(enumerate_buckets(date(2026, 7, 1), date(2026, 7, 1), "DAY")) == 1


class TestInRange:
    def test_both_bounds_are_inclusive(self):
        start, end = date(2026, 7, 1), date(2026, 7, 31)
        first = datetime(2026, 7, 1, 6, 0, tzinfo=dt_timezone.utc)
        last = datetime(2026, 7, 31, 20, 0, tzinfo=dt_timezone.utc)

        assert in_range(first, KINSHASA, start, end)
        assert in_range(last, KINSHASA, start, end)

    def test_membership_is_a_calendar_day_comparison(self):
        """23:30 UTC on 30 June is already 1 July in Kinshasa, so it is in a
        July range even though its UTC date is not."""
        moment = datetime(2026, 6, 30, 23, 30, tzinfo=dt_timezone.utc)
        assert in_range(moment, KINSHASA, date(2026, 7, 1), date(2026, 7, 31))

    def test_outside_is_outside(self):
        moment = datetime(2026, 8, 1, 12, 0, tzinfo=dt_timezone.utc)
        assert not in_range(moment, KINSHASA, date(2026, 7, 1), date(2026, 7, 31))
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/finance -p no:warnings`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.finance'`.

- [ ] **Step 3: Create the app package**

```bash
mkdir -p apps/finance/tests
touch apps/finance/__init__.py apps/finance/tests/__init__.py
```

`apps/finance/apps.py`:

```python
from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.finance"
    label = "finance"
    verbose_name = "Finances"
```

`apps/finance` owns no models, so it needs no `migrations` package. Add
`"apps.finance"` to `INSTALLED_APPS` after `"apps.expenses"`.

- [ ] **Step 4: Implement the module**

Create `apps/finance/period.py`:

```python
"""Period arithmetic, ported from features/finance/lib/period.ts.

Imports nothing from Django — deliberately. That isolation is what lets this
be compared against the frontend's own implementation without a database, and
a test asserts it.

Timezone-dependent functions take an explicit `tzinfo` rather than reading
settings, for the same reason. The caller passes
`apps.common.dates.shop_timezone()`.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo

#: Transcribed from `Intl.DateTimeFormat("fr-FR", {month: "short"})`, which is
#: what `features/finance/lib/period.ts` uses.
#:
#: Django's own French locale is NOT equivalent: it gives "jan." and "fév."
#: where CLDR gives "janv." and "févr.", so using `date_filter(d, "N")` would
#: mislabel two months on every chart.
#:
#: Note that four entries carry no trailing full stop — mars, mai, juin and
#: août are not abbreviated, and CLDR marks only abbreviations. Generating
#: these from a prefix would be wrong for half the year.
MONTH_ABBREVIATIONS: tuple[str, ...] = (
    "janv.",
    "févr.",
    "mars",
    "avr.",
    "mai",
    "juin",
    "juil.",
    "août",
    "sept.",
    "oct.",
    "nov.",
    "déc.",
)

#: Longest range still bucketed by day. Beyond it a year would draw 365 bars.
DAILY_BUCKET_LIMIT = 90


@dataclass(frozen=True)
class BucketSlot:
    key: str
    label: str


def days_in_range(start: date, end: date) -> int:
    """Inclusive day count.

    `date` arithmetic is calendar arithmetic, so unlike the frontend — which
    has to route through `Date.UTC` to stop a daylight-saving transition making
    a day 23 hours long — this needs no special handling.
    """
    return (end - start).days + 1


def resolve_granularity(start: date, end: date) -> str:
    return "DAY" if days_in_range(start, end) <= DAILY_BUCKET_LIMIT else "MONTH"


def day_label(value: date) -> str:
    """« 12 juil. » — the day is not zero-padded (`Intl` uses "numeric")."""
    return f"{value.day} {MONTH_ABBREVIATIONS[value.month - 1]}"


def month_label(value: date) -> str:
    """« juil. 2026 »."""
    return f"{MONTH_ABBREVIATIONS[value.month - 1]} {value.year}"


def local_date(moment: datetime, tz: tzinfo) -> date:
    """The calendar day this instant falls on, where the shop is.

    Every boundary in this module is a local calendar boundary, because that
    is the one the shopkeeper picked in the date input.
    """
    return moment.astimezone(tz).date()


def bucket_key(moment: datetime, tz: tzinfo, granularity: str) -> str:
    day = local_date(moment, tz)
    return day.isoformat() if granularity == "DAY" else day.strftime("%Y-%m")


def enumerate_buckets(start: date, end: date, granularity: str) -> list[BucketSlot]:
    """Every bucket in the range, empty ones included.

    A quiet week must render as zeros; dropping it would compress the x-axis
    and make the chart claim the shop traded on days it was shut.
    """
    slots: list[BucketSlot] = []

    if granularity == "DAY":
        cursor = start
        while cursor <= end:
            slots.append(BucketSlot(key=cursor.isoformat(), label=day_label(cursor)))
            cursor += timedelta(days=1)
        return slots

    cursor = start.replace(day=1)
    last = end.replace(day=1)
    while cursor <= last:
        slots.append(
            BucketSlot(key=cursor.strftime("%Y-%m"), label=month_label(cursor))
        )
        # `replace` cannot add a month, and adding 31 days can skip February.
        # Going to the 28th of next month and snapping back to the 1st is
        # exact for every month length.
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return slots


def in_range(moment: datetime, tz: tzinfo, start: date, end: date) -> bool:
    """Both bounds inclusive.

    Compares calendar days rather than instants: the range's bounds are days,
    so "is this instant before the end" is the wrong question — the right one
    is "is this instant's local day within the span of days", which has no time
    component to get wrong.
    """
    return start <= local_date(moment, tz) <= end
```

- [ ] **Step 5: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/finance/tests/test_period.py -p no:warnings -v`
Expected: all PASS, with `TestLabelsAgainstIntl` **passing rather than
skipping** — check the output says so, since a skip here removes the only
check that the table is right.

- [ ] **Step 6: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/finance stockmanager/settings.py
git commit -m "Add Django-free period arithmetic with transcribed French labels"
```

---

## Task 3: The aggregation module

**Files:**
- Create: `apps/finance/aggregate.py`
- Test: `apps/finance/tests/test_aggregate.py`

**Interfaces:**
- Consumes: `apps.finance.period` (`resolve_granularity`, `enumerate_buckets`, `bucket_key`, `in_range`).
- Produces:

```python
TOP_ARTICLE_COUNT: int   # 5

def line_revenue_ht(line: dict) -> int
def line_margin(line: dict) -> int
def margin_rate(revenue: int, margin: int) -> float
def paid_by_sale(payments: list[dict]) -> dict[str, int]
def summarise(facts: dict, tz, start: date, end: date) -> dict
def bucketise(facts: dict, tz, start: date, end: date) -> dict
def build_breakdown(facts: dict, tz, start: date, end: date) -> dict
```

`facts` is a dict with keys `sales`, `lines`, `payments`, `expenses`,
`purchases`, each a list of plain dicts. The returned dicts use **snake_case**
keys; the serializer and the camelCase renderer convert them.

**This module imports nothing from Django either.** A test asserts it.

- [ ] **Step 1: Write the failing test**

Create `apps/finance/tests/test_aggregate.py`:

```python
"""Finance aggregation, ported from features/finance/lib/aggregate.ts.

No Django, no database — the facts are hand-built dicts. The last class runs
the frontend's own implementation in Node over randomised facts and diffs.
"""

import json
import shutil
import subprocess
from datetime import date, datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

import pytest

from apps.finance.aggregate import (
    TOP_ARTICLE_COUNT,
    build_breakdown,
    bucketise,
    line_margin,
    line_revenue_ht,
    margin_rate,
    paid_by_sale,
    summarise,
)

KINSHASA = ZoneInfo("Africa/Kinshasa")
JULY = (date(2026, 7, 1), date(2026, 7, 31))


def at(day, hour=12):
    return datetime(2026, 7, day, hour, tzinfo=dt_timezone.utc)


def sale(id="s1", day=15, status="COMPLETED", total=11_600, vat_total=1_600, **kw):
    row = {
        "id": id,
        "created_at": at(day),
        "status": status,
        "total": total,
        "vat_total": vat_total,
        "reference": f"FA-2026-{id}",
        "customer_name": None,
    }
    row.update(kw)
    return row


def line(sale_id="s1", article_id="a1", quantity=2, line_total=11_600,
         discount_share=0, vat_amount=1_600, unit_cost=3_000, **kw):
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


class TestNoDjangoImport:
    def test_the_module_does_not_import_django(self):
        import inspect

        import apps.finance.aggregate as module

        assert "django" not in inspect.getsource(module).lower()


class TestLineHelpers:
    def test_line_revenue_is_ht_after_discount(self):
        """Not quantity x unitPrice: that is TTC and ignores the discount
        allocation, so the per-article panel would disagree with the CA card."""
        row = line(line_total=11_600, discount_share=600, vat_amount=1_517)
        assert line_revenue_ht(row) == 11_600 - 600 - 1_517

    def test_line_margin_subtracts_the_cost_snapshot(self):
        row = line(quantity=2, line_total=10_000, discount_share=0,
                   vat_amount=1_379, unit_cost=3_000)
        assert line_margin(row) == (10_000 - 0 - 1_379) - (2 * 3_000)

    def test_margin_rate_is_an_unrounded_percent(self):
        """Verified bit-identical to JS: (1/3)*100 is 33.33333333333333 in
        both. Rounding here is what would create a difference."""
        assert margin_rate(3, 1) == (1 / 3) * 100
        assert margin_rate(3, 1) == 33.33333333333333

    def test_margin_rate_is_zero_at_zero_revenue(self):
        """Never NaN, never Infinity."""
        assert margin_rate(0, 5) == 0
        assert margin_rate(-10, 5) == 0

    def test_paid_by_sale_folds_once(self):
        totals = paid_by_sale([payment("s1", 100), payment("s2", 50), payment("s1", 25)])
        assert totals == {"s1": 125, "s2": 50}


class TestSummary:
    def test_revenue_is_ht(self, ):
        result = summarise(facts(sales=[sale(total=11_600, vat_total=1_600)]),
                           KINSHASA, *JULY)
        assert result["revenue"] == 10_000
        assert result["vat_collected"] == 1_600

    def test_cancelled_sales_are_excluded_from_revenue(self):
        result = summarise(
            facts(sales=[sale(id="s1"), sale(id="s2", status="CANCELLED")]),
            KINSHASA, *JULY,
        )
        assert result["revenue"] == 10_000  # only s1

    def test_a_payment_on_a_cancelled_sale_still_counts_as_a_receipt(self):
        """'The cash genuinely moved and there is no refund entity to undo
        it.' Cancellation restores stock, not money."""
        result = summarise(
            facts(
                sales=[sale(id="s1", status="CANCELLED")],
                payments=[payment("s1", 4_000)],
            ),
            KINSHASA, *JULY,
        )
        assert result["revenue"] == 0
        assert result["receipts"] == 4_000

    def test_cogs_uses_the_line_cost_snapshot(self):
        result = summarise(
            facts(sales=[sale()], lines=[line(quantity=2, unit_cost=3_000)]),
            KINSHASA, *JULY,
        )
        assert result["cogs"] == 6_000
        assert result["gross_margin"] == 10_000 - 6_000

    def test_lines_of_a_cancelled_sale_do_not_contribute_cogs(self):
        result = summarise(
            facts(
                sales=[sale(id="s1", status="CANCELLED")],
                lines=[line(sale_id="s1", quantity=2, unit_cost=3_000)],
            ),
            KINSHASA, *JULY,
        )
        assert result["cogs"] == 0

    def test_expenses_and_net_result(self):
        result = summarise(
            facts(sales=[sale()], lines=[line()], expenses=[expense(2_000)]),
            KINSHASA, *JULY,
        )
        assert result["expenses"] == 2_000
        assert result["net_result"] == result["gross_margin"] - 2_000

    def test_purchase_disbursements_and_the_missing_cost_count(self):
        result = summarise(
            facts(purchases=[purchase(10, 800), purchase(5, None)]),
            KINSHASA, *JULY,
        )
        assert result["purchase_disbursements"] == 8_000  # the null contributes 0
        assert result["purchases_without_cost"] == 1

    def test_disbursements_and_cash_balance(self):
        result = summarise(
            facts(
                payments=[payment(amount=9_000)],
                expenses=[expense(2_000)],
                purchases=[purchase(10, 800)],
            ),
            KINSHASA, *JULY,
        )
        assert result["disbursements"] == 8_000 + 2_000
        assert result["cash_balance"] == 9_000 - 10_000

    def test_out_of_range_rows_are_ignored(self):
        june = {"created_at": datetime(2026, 6, 15, 12, tzinfo=dt_timezone.utc)}
        result = summarise(facts(sales=[sale(**june)]), KINSHASA, *JULY)
        assert result["revenue"] == 0

    def test_range_membership_uses_the_shop_calendar_day(self):
        """23:30 UTC on 30 June is already 1 July in Kinshasa."""
        edge = {"created_at": datetime(2026, 6, 30, 23, 30, tzinfo=dt_timezone.utc)}
        result = summarise(facts(sales=[sale(**edge)]), KINSHASA, *JULY)
        assert result["revenue"] == 10_000


class TestReceivables:
    def test_receivables_ignore_the_range(self):
        """A figure as of now, not for the period — the card says « à ce
        jour »."""
        january = {"created_at": datetime(2026, 1, 15, 12, tzinfo=dt_timezone.utc)}
        result = summarise(facts(sales=[sale(total=10_000, **january)]),
                           KINSHASA, *JULY)
        assert result["revenue"] == 0
        assert result["receivables"] == 10_000

    def test_payments_reduce_the_balance(self):
        result = summarise(
            facts(sales=[sale(total=10_000)], payments=[payment(amount=4_000)]),
            KINSHASA, *JULY,
        )
        assert result["receivables"] == 6_000

    def test_an_overpaid_sale_cannot_lend_its_surplus_to_another(self):
        """Balances are floored at zero before summing."""
        result = summarise(
            facts(
                sales=[sale(id="s1", total=1_000), sale(id="s2", total=5_000)],
                payments=[payment("s1", 3_000)],
            ),
            KINSHASA, *JULY,
        )
        # s1's 2 000 overpayment must not offset s2's 5 000 debt.
        assert result["receivables"] == 5_000

    def test_cancelled_sales_are_not_receivable(self):
        result = summarise(
            facts(sales=[sale(status="CANCELLED", total=10_000)]), KINSHASA, *JULY
        )
        assert result["receivables"] == 0


class TestSeries:
    def test_every_bucket_in_the_range_is_present(self):
        result = bucketise(facts(), KINSHASA, date(2026, 7, 1), date(2026, 7, 3))
        assert result["granularity"] == "DAY"
        assert [b["key"] for b in result["buckets"]] == [
            "2026-07-01", "2026-07-02", "2026-07-03",
        ]

    def test_a_long_range_switches_to_months(self):
        result = bucketise(facts(), KINSHASA, date(2026, 1, 1), date(2026, 12, 31))
        assert result["granularity"] == "MONTH"
        assert len(result["buckets"]) == 12

    def test_revenue_lands_in_its_days_bucket(self):
        result = bucketise(
            facts(sales=[sale(day=2)]), KINSHASA, date(2026, 7, 1), date(2026, 7, 3)
        )
        by_key = {b["key"]: b for b in result["buckets"]}
        assert by_key["2026-07-02"]["revenue"] == 10_000
        assert by_key["2026-07-01"]["revenue"] == 0

    def test_cogs_lands_in_the_bucket_of_its_sale_not_its_line(self):
        """The frontend maps saleId -> bucket first, so revenue and COGS can
        never fall in different buckets."""
        result = bucketise(
            facts(sales=[sale(id="s1", day=2)],
                  lines=[line(sale_id="s1", quantity=2, unit_cost=3_000)]),
            KINSHASA, date(2026, 7, 1), date(2026, 7, 3),
        )
        by_key = {b["key"]: b for b in result["buckets"]}
        assert by_key["2026-07-02"]["cogs"] == 6_000
        assert by_key["2026-07-02"]["margin"] == 10_000 - 6_000

    def test_receipts_and_disbursements_bucket_separately(self):
        result = bucketise(
            facts(payments=[payment(day=1, amount=5_000)],
                  expenses=[expense(day=2, amount=1_000)],
                  purchases=[purchase(day=3, quantity=2, unit_cost=500)]),
            KINSHASA, date(2026, 7, 1), date(2026, 7, 3),
        )
        by_key = {b["key"]: b for b in result["buckets"]}
        assert by_key["2026-07-01"]["receipts"] == 5_000
        assert by_key["2026-07-02"]["disbursements"] == 1_000
        assert by_key["2026-07-03"]["disbursements"] == 1_000

    def test_cumulative_cash_restarts_at_zero_in_the_first_bucket(self):
        """It answers 'what did this period do to my cash', not 'what is in
        the till'."""
        result = bucketise(
            facts(payments=[payment(day=1, amount=5_000),
                            payment(day=3, amount=2_000)],
                  expenses=[expense(day=2, amount=1_000)]),
            KINSHASA, date(2026, 7, 1), date(2026, 7, 3),
        )
        assert [b["cumulative_cash"] for b in result["buckets"]] == [
            5_000, 4_000, 6_000,
        ]

    def test_a_cancelled_sale_contributes_no_revenue_to_any_bucket(self):
        result = bucketise(
            facts(sales=[sale(day=2, status="CANCELLED")]),
            KINSHASA, date(2026, 7, 1), date(2026, 7, 3),
        )
        assert all(b["revenue"] == 0 for b in result["buckets"])


class TestBreakdown:
    def test_expense_rows_are_largest_first_with_shares(self):
        result = build_breakdown(
            facts(expenses=[expense(3_000, "RENT"), expense(1_000, "TRANSPORT")]),
            KINSHASA, *JULY,
        )
        rows = result["expenses"]
        assert [r["category"] for r in rows] == ["RENT", "TRANSPORT"]
        assert rows[0]["share"] == 75.0
        assert rows[1]["share"] == 25.0

    def test_shares_are_unrounded(self):
        result = build_breakdown(
            facts(expenses=[expense(1_000, "RENT"), expense(1_000, "TAX"),
                            expense(1_000, "SALARY")]),
            KINSHASA, *JULY,
        )
        assert result["expenses"][0]["share"] == (1 / 3) * 100

    def test_categories_are_folded(self):
        result = build_breakdown(
            facts(expenses=[expense(1_000, "RENT"), expense(2_000, "RENT")]),
            KINSHASA, *JULY,
        )
        assert len(result["expenses"]) == 1
        assert result["expenses"][0]["amount"] == 3_000

    def test_a_zero_total_yields_zero_shares_not_a_division_error(self):
        result = build_breakdown(facts(expenses=[expense(0, "RENT")]), KINSHASA, *JULY)
        assert result["expenses"][0]["share"] == 0

    def test_top_articles_are_capped_at_five(self):
        assert TOP_ARTICLE_COUNT == 5
        rows = [line(article_id=f"a{i}", quantity=1, line_total=1_000 * (i + 1),
                     vat_amount=0, unit_cost=0) for i in range(8)]
        result = build_breakdown(facts(sales=[sale()], lines=rows), KINSHASA, *JULY)
        assert len(result["top_articles"]) == 5

    def test_top_articles_are_ranked_by_margin(self):
        rows = [
            line(article_id="low", line_total=2_000, vat_amount=0, quantity=1,
                 unit_cost=1_900),
            line(article_id="high", line_total=2_000, vat_amount=0, quantity=1,
                 unit_cost=100),
        ]
        result = build_breakdown(facts(sales=[sale()], lines=rows), KINSHASA, *JULY)
        assert [r["article_id"] for r in result["top_articles"]] == ["high", "low"]

    def test_the_same_article_across_lines_is_folded(self):
        rows = [
            line(article_id="a1", quantity=1, line_total=1_000, vat_amount=0,
                 unit_cost=0),
            line(article_id="a1", quantity=2, line_total=2_000, vat_amount=0,
                 unit_cost=0),
        ]
        result = build_breakdown(facts(sales=[sale()], lines=rows), KINSHASA, *JULY)
        assert len(result["top_articles"]) == 1
        assert result["top_articles"][0]["quantity"] == 3
        assert result["top_articles"][0]["revenue"] == 3_000

    def test_unpaid_sales_ignore_the_range(self):
        january = {"created_at": datetime(2026, 1, 15, 12, tzinfo=dt_timezone.utc)}
        result = build_breakdown(
            facts(sales=[sale(total=10_000, **january)]), KINSHASA, *JULY
        )
        assert len(result["unpaid_sales"]) == 1

    def test_a_fully_paid_sale_is_not_listed(self):
        result = build_breakdown(
            facts(sales=[sale(total=10_000)], payments=[payment(amount=10_000)]),
            KINSHASA, *JULY,
        )
        assert result["unpaid_sales"] == []

    def test_unpaid_sales_are_largest_balance_first(self):
        result = build_breakdown(
            facts(sales=[sale(id="small", total=1_000),
                         sale(id="big", total=9_000)]),
            KINSHASA, *JULY,
        )
        assert [r["id"] for r in result["unpaid_sales"]] == ["big", "small"]

    def test_cancelled_sales_are_not_unpaid(self):
        result = build_breakdown(
            facts(sales=[sale(status="CANCELLED", total=10_000)]), KINSHASA, *JULY
        )
        assert result["unpaid_sales"] == []


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
class TestAgainstTheFrontendImplementation:
    """Randomised facts through the frontend's own aggregate.ts, diffed.

    The port is long enough that hand-written cases cannot cover the
    interactions between range filtering, cancellation and the two unbounded
    folds. This can.
    """

    JS = """
    const inRange = (iso, r) => { const d = iso.slice(0, 10); return d >= r.from && d <= r.to; };
    const sumBy = (xs, f) => xs.reduce((t, x) => t + f(x), 0);
    const paidBySale = (ps) => { const m = new Map();
      for (const p of ps) m.set(p.saleId, (m.get(p.saleId) ?? 0) + p.amount); return m; };
    const completed = (f, r) => f.sales.filter(s => s.status === "COMPLETED" && inRange(s.createdAt, r));
    const linesOf = (f, sales) => { const ids = new Set(sales.map(s => s.id));
      return f.lines.filter(l => ids.has(l.saleId)); };

    function summarise(f, r) {
      const sales = completed(f, r), lines = linesOf(f, sales);
      const revenue = sumBy(sales, s => s.total - s.vatTotal);
      const cogs = sumBy(lines, l => l.quantity * l.unitCost);
      const grossMargin = revenue - cogs;
      const expenses = sumBy(f.expenses.filter(e => inRange(e.spentAt, r)), e => e.amount);
      const receipts = sumBy(f.payments.filter(p => inRange(p.paidAt, r)), p => p.amount);
      const purchases = f.purchases.filter(p => inRange(p.createdAt, r));
      const purchaseDisbursements = sumBy(purchases, p => p.quantity * (p.unitCost ?? 0));
      const paid = paidBySale(f.payments);
      const receivables = f.sales.filter(s => s.status === "COMPLETED")
        .reduce((t, s) => t + Math.max(s.total - (paid.get(s.id) ?? 0), 0), 0);
      const disbursements = purchaseDisbursements + expenses;
      return { revenue, cogs, grossMargin,
        marginRate: revenue <= 0 ? 0 : (grossMargin / revenue) * 100,
        expenses, netResult: grossMargin - expenses,
        vatCollected: sumBy(sales, s => s.vatTotal), receipts,
        purchaseDisbursements, disbursements, cashBalance: receipts - disbursements,
        receivables, purchasesWithoutCost: purchases.filter(p => p.unitCost === null).length };
    }

    const [factsIn, range] = JSON.parse(process.argv[1]);
    console.log(JSON.stringify(summarise(factsIn, range)));
    """

    def test_the_summary_matches_on_randomised_facts(self):
        import random

        random.seed(20260808)

        for _ in range(60):
            js_facts = {"sales": [], "lines": [], "payments": [],
                        "expenses": [], "purchases": []}
            py_facts = facts()

            for index in range(random.randint(0, 6)):
                sale_id = f"s{index}"
                day = random.randint(1, 28)
                month = random.choice([6, 7, 8])
                status = random.choice(["COMPLETED", "COMPLETED", "CANCELLED"])
                total = random.randint(0, 50_000)
                vat = random.randint(0, total) if total else 0
                moment = datetime(2026, month, day, 12, tzinfo=dt_timezone.utc)

                js_facts["sales"].append({
                    "id": sale_id, "createdAt": moment.isoformat().replace("+00:00", "Z"),
                    "status": status, "total": total, "vatTotal": vat,
                })
                py_facts["sales"].append({
                    "id": sale_id, "created_at": moment, "status": status,
                    "total": total, "vat_total": vat,
                    "reference": "", "customer_name": None,
                })

                for _line in range(random.randint(0, 3)):
                    quantity = random.randint(1, 5)
                    unit_cost = random.randint(0, 2_000)
                    js_facts["lines"].append({
                        "saleId": sale_id, "articleId": "a", "articleName": "A",
                        "articleSku": "A", "quantity": quantity, "lineTotal": 0,
                        "discountShare": 0, "vatAmount": 0, "unitCost": unit_cost,
                    })
                    py_facts["lines"].append({
                        "sale_id": sale_id, "article_id": "a", "article_name": "A",
                        "article_sku": "A", "quantity": quantity, "line_total": 0,
                        "discount_share": 0, "vat_amount": 0, "unit_cost": unit_cost,
                    })

                if random.random() < 0.7:
                    amount = random.randint(0, total + 5_000)
                    pay_moment = datetime(2026, month, day, 12, tzinfo=dt_timezone.utc)
                    js_facts["payments"].append({
                        "saleId": sale_id,
                        "paidAt": pay_moment.isoformat().replace("+00:00", "Z"),
                        "amount": amount,
                    })
                    py_facts["payments"].append({
                        "sale_id": sale_id, "paid_at": pay_moment, "amount": amount,
                    })

            for _ in range(random.randint(0, 4)):
                moment = datetime(2026, random.choice([6, 7, 8]),
                                  random.randint(1, 28), 12, tzinfo=dt_timezone.utc)
                amount = random.randint(0, 20_000)
                category = random.choice(["RENT", "TAX", "OTHER"])
                js_facts["expenses"].append({
                    "category": category, "amount": amount,
                    "spentAt": moment.isoformat().replace("+00:00", "Z"),
                })
                py_facts["expenses"].append({
                    "category": category, "amount": amount, "spent_at": moment,
                })

            for _ in range(random.randint(0, 4)):
                moment = datetime(2026, random.choice([6, 7, 8]),
                                  random.randint(1, 28), 12, tzinfo=dt_timezone.utc)
                quantity = random.randint(1, 20)
                unit_cost = random.choice([None, random.randint(0, 3_000)])
                js_facts["purchases"].append({
                    "quantity": quantity, "unitCost": unit_cost,
                    "createdAt": moment.isoformat().replace("+00:00", "Z"),
                })
                py_facts["purchases"].append({
                    "quantity": quantity, "unit_cost": unit_cost, "created_at": moment,
                })

            payload = json.dumps([js_facts, {"from": "2026-07-01", "to": "2026-07-31"}])
            result = subprocess.run([NODE, "-e", self.JS, payload],
                                    capture_output=True, text=True, check=True)
            want = json.loads(result.stdout)

            # UTC noon and Kinshasa share a calendar day, so the JS string
            # comparison and the Python tz-aware one agree by construction.
            got = summarise(py_facts, dt_timezone.utc, *JULY)

            for js_key, py_key in [
                ("revenue", "revenue"), ("cogs", "cogs"),
                ("grossMargin", "gross_margin"), ("marginRate", "margin_rate"),
                ("expenses", "expenses"), ("netResult", "net_result"),
                ("vatCollected", "vat_collected"), ("receipts", "receipts"),
                ("purchaseDisbursements", "purchase_disbursements"),
                ("disbursements", "disbursements"),
                ("cashBalance", "cash_balance"), ("receivables", "receivables"),
                ("purchasesWithoutCost", "purchases_without_cost"),
            ]:
                assert got[py_key] == want[js_key], f"{py_key} differs"
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/finance/tests/test_aggregate.py -p no:warnings`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.finance.aggregate'`.

- [ ] **Step 3: Implement the module**

Create `apps/finance/aggregate.py`:

```python
"""Finance aggregation, ported from features/finance/lib/aggregate.ts.

Imports nothing from Django. The facts arrive as plain dicts from
`apps.finance.facts`, which is the only file here that touches the ORM.

Money is integer cents throughout. The two percentages — `margin_rate` and a
breakdown row's `share` — are **unrounded floats**, exactly as the frontend
computes them. Python and JavaScript agree bit-for-bit on an unrounded IEEE-754
division; rounding either side is what would make them differ.
"""

from datetime import date, tzinfo

from apps.finance.period import (
    bucket_key,
    enumerate_buckets,
    in_range,
    resolve_granularity,
)

TOP_ARTICLE_COUNT = 5


def line_revenue_ht(line: dict) -> int:
    """A line's share of the sale's HT revenue.

    Not `quantity × unit_price`: that is TTC and ignores the sale's discount
    allocation, so the per-article panel would disagree with the revenue card.
    These roll up exactly — Σ line_total = subtotal, Σ discount_share =
    discount, Σ vat_amount = vat_total.
    """
    return line["line_total"] - line["discount_share"] - line["vat_amount"]


def line_margin(line: dict) -> int:
    return line_revenue_ht(line) - line["quantity"] * line["unit_cost"]


def margin_rate(revenue: int, margin: int) -> float:
    """Percent. Zero revenue yields 0, never NaN or a division error."""
    if revenue <= 0:
        return 0
    return (margin / revenue) * 100


def paid_by_sale(payments: list[dict]) -> dict:
    """Total paid per sale, folded once.

    Three callers depend on this agreeing with itself: receivables, the
    unpaid-sales panel, and sub-project 6's « réglé » column.
    """
    totals: dict = {}
    for row in payments:
        totals[row["sale_id"]] = totals.get(row["sale_id"], 0) + row["amount"]
    return totals


def _completed_in_range(facts, tz, start, end) -> list[dict]:
    return [
        row
        for row in facts["sales"]
        if row["status"] == "COMPLETED" and in_range(row["created_at"], tz, start, end)
    ]


def _lines_of(facts, sales) -> list[dict]:
    sale_ids = {row["id"] for row in sales}
    return [row for row in facts["lines"] if row["sale_id"] in sale_ids]


def _receivables(facts) -> int:
    """Outstanding across every completed sale, whenever it happened.

    A figure as of now, not for the period, which is why it takes no range.
    Each balance is floored at zero first: a sale paid past its total must not
    lend its overpayment to another's balance.
    """
    paid = paid_by_sale(facts["payments"])
    return sum(
        max(row["total"] - paid.get(row["id"], 0), 0)
        for row in facts["sales"]
        if row["status"] == "COMPLETED"
    )


def summarise(facts: dict, tz: tzinfo, start: date, end: date) -> dict:
    sales = _completed_in_range(facts, tz, start, end)
    lines = _lines_of(facts, sales)

    revenue = sum(row["total"] - row["vat_total"] for row in sales)
    vat_collected = sum(row["vat_total"] for row in sales)
    cogs = sum(row["quantity"] * row["unit_cost"] for row in lines)
    gross_margin = revenue - cogs

    expenses = sum(
        row["amount"]
        for row in facts["expenses"]
        if in_range(row["spent_at"], tz, start, end)
    )

    # Every payment in the window, including those on sales later cancelled:
    # the cash genuinely moved and there is no refund entity to undo it.
    receipts = sum(
        row["amount"]
        for row in facts["payments"]
        if in_range(row["paid_at"], tz, start, end)
    )

    purchases = [
        row
        for row in facts["purchases"]
        if in_range(row["created_at"], tz, start, end)
    ]
    purchase_disbursements = sum(
        row["quantity"] * (row["unit_cost"] or 0) for row in purchases
    )
    purchases_without_cost = sum(1 for row in purchases if row["unit_cost"] is None)

    disbursements = purchase_disbursements + expenses

    return {
        "revenue": revenue,
        "cogs": cogs,
        "gross_margin": gross_margin,
        "margin_rate": margin_rate(revenue, gross_margin),
        "expenses": expenses,
        "net_result": gross_margin - expenses,
        "vat_collected": vat_collected,
        "receipts": receipts,
        "purchase_disbursements": purchase_disbursements,
        "disbursements": disbursements,
        "cash_balance": receipts - disbursements,
        "receivables": _receivables(facts),
        "purchases_without_cost": purchases_without_cost,
    }


def bucketise(facts: dict, tz: tzinfo, start: date, end: date) -> dict:
    granularity = resolve_granularity(start, end)

    buckets: list[dict] = []
    by_key: dict = {}
    for slot in enumerate_buckets(start, end, granularity):
        bucket = {
            "key": slot.key,
            "label": slot.label,
            "revenue": 0,
            "cogs": 0,
            "margin": 0,
            "receipts": 0,
            "disbursements": 0,
            "cumulative_cash": 0,
        }
        buckets.append(bucket)
        by_key[slot.key] = bucket

    sales = _completed_in_range(facts, tz, start, end)

    # A sale's bucket is resolved once and its lines follow it, so revenue and
    # COGS can never fall in different buckets.
    bucket_by_sale: dict = {}
    for row in sales:
        bucket = by_key.get(bucket_key(row["created_at"], tz, granularity))
        bucket_by_sale[row["id"]] = bucket
        if bucket:
            bucket["revenue"] += row["total"] - row["vat_total"]

    for row in _lines_of(facts, sales):
        bucket = bucket_by_sale.get(row["sale_id"])
        if bucket:
            bucket["cogs"] += row["quantity"] * row["unit_cost"]

    for row in facts["payments"]:
        if not in_range(row["paid_at"], tz, start, end):
            continue
        bucket = by_key.get(bucket_key(row["paid_at"], tz, granularity))
        if bucket:
            bucket["receipts"] += row["amount"]

    for row in facts["expenses"]:
        if not in_range(row["spent_at"], tz, start, end):
            continue
        bucket = by_key.get(bucket_key(row["spent_at"], tz, granularity))
        if bucket:
            bucket["disbursements"] += row["amount"]

    for row in facts["purchases"]:
        if not in_range(row["created_at"], tz, start, end):
            continue
        bucket = by_key.get(bucket_key(row["created_at"], tz, granularity))
        if bucket:
            bucket["disbursements"] += row["quantity"] * (row["unit_cost"] or 0)

    # Margin and the running balance are derived once the buckets are filled.
    # The cumulative line starts at zero at the period's first bucket: it
    # answers "what did this period do to my cash", not "what is in the till".
    running = 0
    for bucket in buckets:
        bucket["margin"] = bucket["revenue"] - bucket["cogs"]
        running += bucket["receipts"] - bucket["disbursements"]
        bucket["cumulative_cash"] = running

    return {"granularity": granularity, "buckets": buckets}


def build_expense_breakdown(facts, tz, start, end) -> list[dict]:
    totals: dict = {}
    for row in facts["expenses"]:
        if not in_range(row["spent_at"], tz, start, end):
            continue
        totals[row["category"]] = totals.get(row["category"], 0) + row["amount"]

    total = sum(totals.values())

    rows = [
        {
            "category": category,
            "amount": amount,
            "share": (amount / total) * 100 if total > 0 else 0,
        }
        for category, amount in totals.items()
    ]
    rows.sort(key=lambda row: -row["amount"])
    return rows


def build_top_articles(facts, tz, start, end) -> list[dict]:
    sales = _completed_in_range(facts, tz, start, end)
    by_article: dict = {}

    for row in _lines_of(facts, sales):
        existing = by_article.get(row["article_id"])
        if existing:
            existing["quantity"] += row["quantity"]
            existing["revenue"] += line_revenue_ht(row)
            existing["margin"] += line_margin(row)
            continue
        by_article[row["article_id"]] = {
            "article_id": row["article_id"],
            "article_name": row["article_name"],
            "article_sku": row["article_sku"],
            "quantity": row["quantity"],
            "revenue": line_revenue_ht(row),
            "margin": line_margin(row),
        }

    rows = sorted(by_article.values(), key=lambda row: -row["margin"])
    return rows[:TOP_ARTICLE_COUNT]


def build_unpaid_sales(facts) -> list[dict]:
    """Not range-scoped, for the same reason as receivables."""
    paid = paid_by_sale(facts["payments"])

    rows = [
        {
            "id": row["id"],
            "reference": row.get("reference") or "",
            "customer_name": row.get("customer_name"),
            "created_at": row["created_at"],
            "total": row["total"],
            "balance": row["total"] - paid.get(row["id"], 0),
        }
        for row in facts["sales"]
        if row["status"] == "COMPLETED"
    ]
    rows = [row for row in rows if row["balance"] > 0]
    rows.sort(key=lambda row: -row["balance"])
    return rows


def build_breakdown(facts: dict, tz: tzinfo, start: date, end: date) -> dict:
    return {
        "expenses": build_expense_breakdown(facts, tz, start, end),
        "top_articles": build_top_articles(facts, tz, start, end),
        "unpaid_sales": build_unpaid_sales(facts),
    }
```

- [ ] **Step 4: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/finance/tests/test_aggregate.py -p no:warnings -v`
Expected: all PASS, with `TestAgainstTheFrontendImplementation` **passing, not
skipping**.

- [ ] **Step 5: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/finance
git commit -m "Add the Django-free finance aggregation module"
```

---

## Task 4: The facts seam and the three endpoints

**Files:**
- Create: `apps/finance/facts.py`, `apps/finance/serializers.py`, `apps/finance/views.py`, `apps/finance/urls.py`
- Modify: `stockmanager/urls.py`
- Test: `apps/finance/tests/test_finance_api.py`

**Interfaces:**
- Consumes: `summarise`, `bucketise`, `build_breakdown`; `apps.common.dates.shop_timezone`; `apps.common.permissions.RoleScopedPermissionMixin`, `IsManagerOrAbove`.
- Produces: `apps.finance.facts.load_facts(site) -> dict`; `apps.finance.serializers.parse_range(query_params) -> tuple[date, date]`.

- [ ] **Step 1: Write the failing test**

Create `apps/finance/tests/test_finance_api.py`:

```python
"""The three finance reads, end to end."""

from datetime import date, datetime, timezone as dt_timezone

import pytest

from apps.catalogue.tests.factories import ArticleFactory
from apps.expenses.tests.factories import ExpenseFactory
from apps.sales.models import Sale
from apps.sales.services import create_sale
from apps.sales.tests.factories import PaymentFactory
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db

SUMMARY = "/api/finance/summary/"
SERIES = "/api/finance/series/"
BREAKDOWN = "/api/finance/breakdown/"
JULY = "?from=2026-07-01&to=2026-07-31"


def stocked(site, quantity=1000, **kwargs):
    article = ArticleFactory(**kwargs)
    StockLevelFactory(article=article, site=site, quantity=quantity)
    return article


def sold(site, user, unit_price=11_600, quantity=1, day=15, **kwargs):
    sale = create_sale(
        lines=[{"article": stocked(site), "quantity": quantity,
                "unit_price": unit_price}],
        user=user, site=site, **kwargs,
    )
    Sale.objects.filter(pk=sale.pk).update(
        created_at=datetime(2026, 7, day, 12, tzinfo=dt_timezone.utc)
    )
    sale.refresh_from_db()
    return sale


class TestSummary:
    def test_the_payload_matches_the_frontend_type(self, auth_client, manager, site):
        response = auth_client(manager).get(f"{SUMMARY}{JULY}")

        assert response.status_code == 200
        assert set(response.json()) == {
            "revenue",
            "cogs",
            "grossMargin",
            "marginRate",
            "expenses",
            "netResult",
            "vatCollected",
            "receipts",
            "purchaseDisbursements",
            "disbursements",
            "cashBalance",
            "receivables",
            "purchasesWithoutCost",
        }

    def test_an_empty_period_is_all_zeros(self, auth_client, manager, site):
        payload = auth_client(manager).get(f"{SUMMARY}{JULY}").json()
        assert payload["revenue"] == 0
        assert payload["marginRate"] == 0
        assert payload["receivables"] == 0

    def test_a_sale_reaches_the_summary(self, auth_client, manager, site):
        sold(site, manager, unit_price=11_600, quantity=1)

        payload = auth_client(manager).get(f"{SUMMARY}{JULY}").json()

        # 11 600 TTC at the factory's 16% -> 1 600 VAT, 10 000 HT.
        assert payload["revenue"] == 10_000
        assert payload["vatCollected"] == 1_600

    def test_an_expense_reaches_the_summary(self, auth_client, manager, site):
        expense = ExpenseFactory(site=site, user=manager, amount=2_500)
        from apps.expenses.models import Expense

        Expense.objects.filter(pk=expense.pk).update(
            spent_at=datetime(2026, 7, 10, 12, tzinfo=dt_timezone.utc)
        )

        payload = auth_client(manager).get(f"{SUMMARY}{JULY}").json()

        assert payload["expenses"] == 2_500

    def test_the_opening_stock_movement_counts_as_a_purchase(
        self, auth_client, manager, site
    ):
        """An IN/PURCHASE movement is a purchase whether it came from a
        transaction or from an article's opening balance."""
        from apps.stock.models import StockMovement
        from apps.stock.services import apply_movement

        article = ArticleFactory()
        movement = apply_movement(
            article=article, site=site, type="IN", reason="PURCHASE",
            quantity=10, unit_cost=800, user=manager,
        )
        StockMovement.objects.filter(pk=movement.pk).update(
            created_at=datetime(2026, 7, 5, 12, tzinfo=dt_timezone.utc)
        )

        payload = auth_client(manager).get(f"{SUMMARY}{JULY}").json()

        assert payload["purchaseDisbursements"] == 8_000
        assert payload["purchasesWithoutCost"] == 0

    def test_margin_rate_is_a_float_not_a_string(self, auth_client, manager, site):
        sold(site, manager)
        payload = auth_client(manager).get(f"{SUMMARY}{JULY}").json()
        assert isinstance(payload["marginRate"], float)


class TestSeries:
    def test_the_payload_matches_the_frontend_type(self, auth_client, manager, site):
        response = auth_client(manager).get(f"{SERIES}{JULY}")

        assert response.status_code == 200
        assert set(response.json()) == {"granularity", "buckets"}
        assert set(response.json()["buckets"][0]) == {
            "key",
            "label",
            "revenue",
            "cogs",
            "margin",
            "receipts",
            "disbursements",
            "cumulativeCash",
        }

    def test_july_yields_thirty_one_daily_buckets(self, auth_client, manager, site):
        payload = auth_client(manager).get(f"{SERIES}{JULY}").json()
        assert payload["granularity"] == "DAY"
        assert len(payload["buckets"]) == 31

    def test_a_year_yields_twelve_monthly_buckets(self, auth_client, manager, site):
        payload = auth_client(manager).get(
            f"{SERIES}?from=2026-01-01&to=2026-12-31"
        ).json()
        assert payload["granularity"] == "MONTH"
        assert len(payload["buckets"]) == 12
        assert payload["buckets"][0]["label"] == "janv. 2026"

    def test_the_labels_are_french(self, auth_client, manager, site):
        payload = auth_client(manager).get(f"{SERIES}{JULY}").json()
        assert payload["buckets"][0]["label"] == "1 juil."
        assert payload["buckets"][30]["label"] == "31 juil."


class TestBreakdown:
    def test_the_payload_matches_the_frontend_type(self, auth_client, manager, site):
        response = auth_client(manager).get(f"{BREAKDOWN}{JULY}")

        assert response.status_code == 200
        assert set(response.json()) == {"expenses", "topArticles", "unpaidSales"}

    def test_an_unpaid_sale_is_listed_with_camel_case_keys(
        self, auth_client, manager, site
    ):
        sale = sold(site, manager, unit_price=10_000)

        rows = auth_client(manager).get(f"{BREAKDOWN}{JULY}").json()["unpaidSales"]

        assert len(rows) == 1
        assert set(rows[0]) == {
            "id", "reference", "customerName", "createdAt", "total", "balance",
        }
        assert rows[0]["balance"] == sale.total

    def test_a_paid_sale_drops_off_the_unpaid_list(self, auth_client, manager, site):
        sale = sold(site, manager)
        PaymentFactory(sale=sale, user=manager, amount=sale.total)

        rows = auth_client(manager).get(f"{BREAKDOWN}{JULY}").json()["unpaidSales"]

        assert rows == []

    def test_top_article_rows_carry_the_expected_keys(
        self, auth_client, manager, site
    ):
        sold(site, manager)

        rows = auth_client(manager).get(f"{BREAKDOWN}{JULY}").json()["topArticles"]

        assert set(rows[0]) == {
            "articleId", "articleName", "articleSku", "quantity", "revenue", "margin",
        }


class TestRangeValidation:
    @pytest.mark.parametrize("url", [SUMMARY, SERIES, BREAKDOWN])
    def test_a_missing_range_is_400(self, auth_client, manager, site, url):
        response = auth_client(manager).get(url)
        assert response.status_code == 400
        assert "from" in response.json()["fieldErrors"]

    @pytest.mark.parametrize("url", [SUMMARY, SERIES, BREAKDOWN])
    def test_an_inverted_range_is_400(self, auth_client, manager, site, url):
        response = auth_client(manager).get(f"{url}?from=2026-07-31&to=2026-07-01")
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["from"] == [
            "La date de début doit précéder la date de fin."
        ]

    @pytest.mark.parametrize("url", [SUMMARY, SERIES, BREAKDOWN])
    def test_a_malformed_date_is_400(self, auth_client, manager, site, url):
        response = auth_client(manager).get(f"{url}?from=juillet&to=2026-07-31")
        assert response.status_code == 400
        assert "from" in response.json()["fieldErrors"]

    def test_a_single_day_range_is_valid(self, auth_client, manager, site):
        response = auth_client(manager).get(
            f"{SUMMARY}?from=2026-07-01&to=2026-07-01"
        )
        assert response.status_code == 200


class TestPermissions:
    @pytest.mark.parametrize("url", [SUMMARY, SERIES, BREAKDOWN])
    def test_a_cashier_is_refused(self, auth_client, cashier, site, url):
        response = auth_client(cashier).get(f"{url}{JULY}")
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"

    @pytest.mark.parametrize("url", [SUMMARY, SERIES, BREAKDOWN])
    def test_an_owner_may_read(self, auth_client, owner, site, url):
        assert auth_client(owner).get(f"{url}{JULY}").status_code == 200

    @pytest.mark.parametrize("url", [SUMMARY, SERIES, BREAKDOWN])
    def test_anonymous_is_401(self, api_client, site, url):
        response = api_client.get(f"{url}{JULY}")
        assert response.status_code == 401


class TestQueryCount:
    def test_the_summary_reads_a_fixed_number_of_tables(
        self, auth_client, manager, site, django_assert_num_queries
    ):
        for day in range(1, 6):
            sold(site, manager, day=day)

        client = auth_client(manager)
        client.get(f"{SUMMARY}{JULY}")

        # 1 user, 1 site, then one read per fact table: sales, lines,
        # payments, expenses, purchases.
        with django_assert_num_queries(7):
            response = client.get(f"{SUMMARY}{JULY}")

        assert response.status_code == 200
```

> The `django_assert_num_queries(7)` bound is an estimate. Run it, read the
> real number, and adjust **only** after confirming it does not grow with the
> number of sales — add five more and check it is unchanged. Growth means a
> fact projection is iterating rather than reading once.

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/finance/tests/test_finance_api.py -p no:warnings`
Expected: FAIL — 404, no routes registered.

- [ ] **Step 3: Write the facts seam**

Create `apps/finance/facts.py`:

```python
"""The ORM seam.

The only file in `apps.finance` that touches the database. It projects five
narrow shapes with `.values()` and hands them to the pure modules as plain
dicts — deliberately not the domain types, because every field named here is
one the arithmetic actually reads.
"""

from apps.expenses.models import Expense
from apps.sales.models import Payment, Sale, SaleLine
from apps.stock.models import StockMovement


def load_facts(site) -> dict:
    """Read every row the three finance endpoints fold, once.

    Not range-filtered: `receivables` and `unpaid_sales` need every completed
    sale whenever it happened, and the period-scoped folds filter in Python
    through `in_range`, so the inclusive-bounds rule lives in one tested place.

    `SaleLine` and `Payment` carry no site of their own, so they are narrowed
    through the sales that do.
    """
    sales = list(
        Sale.objects.filter(site=site).values(
            "id", "created_at", "status", "total", "vat_total",
            "reference", "customer_name",
        )
    )
    sale_ids = [row["id"] for row in sales]

    return {
        "sales": sales,
        "lines": list(
            SaleLine.objects.filter(sale_id__in=sale_ids).values(
                "sale_id", "article_id", "article_name", "article_sku",
                "quantity", "line_total", "discount_share", "vat_amount",
                "unit_cost",
            )
        ),
        "payments": list(
            Payment.objects.filter(sale_id__in=sale_ids).values(
                "sale_id", "amount", "paid_at",
            )
        ),
        "expenses": list(
            Expense.objects.filter(site=site).values(
                "category", "amount", "spent_at",
            )
        ),
        "purchases": list(
            StockMovement.objects.filter(
                site=site,
                type=StockMovement.Type.IN,
                reason=StockMovement.Reason.PURCHASE,
            ).values("quantity", "unit_cost", "created_at")
        ),
    }
```

- [ ] **Step 4: Write the range serializer**

Create `apps/finance/serializers.py`:

```python
"""Range parsing for the three finance reads.

A plain function rather than a Serializer, and deliberately so. The wire keys
are `from` and `to`; `from` is a Python keyword, so it cannot be a field name,
and every rename trick (`source="from"` plus a `to_internal_value` shuffle)
puts the *declared* name in `serializer.errors` — the client would receive
`fieldErrors.start` where the form has a field called `from`, and see nothing.
Verified during planning; this shape produces the right keys by construction.
"""

from datetime import date

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers


def parse_range(query_params) -> tuple[date, date]:
    """Both bounds required and inclusive, `from` no later than `to`.

    `isValidRange` refuses an inverted range in the browser before sending, so
    one that arrives inverted is a bug worth reporting rather than silently
    swapping.
    """
    errors: dict = {}
    values: dict = {}

    for key in ("from", "to"):
        raw = query_params.get(key)
        if not raw:
            errors[key] = [_("Ce champ est obligatoire.")]
            continue
        try:
            values[key] = date.fromisoformat(raw)
        except ValueError:
            errors[key] = [_("Date invalide : format attendu AAAA-MM-JJ.")]

    if errors:
        raise serializers.ValidationError(errors)

    if values["from"] > values["to"]:
        raise serializers.ValidationError(
            {"from": [_("La date de début doit précéder la date de fin.")]}
        )

    return values["from"], values["to"]
```

- [ ] **Step 5: Write the views and URLs**

Create `apps/finance/views.py`:

```python
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Site
from apps.common.dates import shop_timezone
from apps.common.permissions import IsManagerOrAbove
from apps.finance.aggregate import build_breakdown, bucketise, summarise
from apps.finance.facts import load_facts
from apps.finance.serializers import parse_range


class FinanceReadView(APIView):
    """Shared shape for the three reads.

    Manager and above: the README's role table puts « Dépenses, finances,
    rapports » out of a cashier's reach entirely.
    """

    permission_classes = [IsManagerOrAbove]

    #: Set by each subclass to one of the three aggregate functions.
    aggregate = None

    def get(self, request):
        start, end = parse_range(request.query_params)

        facts = load_facts(Site.objects.current())
        result = type(self).aggregate(facts, shop_timezone(), start, end)

        return Response(result)


class FinanceSummaryView(FinanceReadView):
    aggregate = staticmethod(summarise)


class FinanceSeriesView(FinanceReadView):
    aggregate = staticmethod(bucketise)


class FinanceBreakdownView(FinanceReadView):
    aggregate = staticmethod(build_breakdown)
```

> `staticmethod` is not decoration for its own sake: assigning a plain function
> to a class attribute makes it an instance method, so `self` would be passed
> as the first argument. `type(self).aggregate(...)` plus `staticmethod` keeps
> the call signature honest.

Create `apps/finance/urls.py`:

```python
from django.urls import path

from apps.finance.views import (
    FinanceBreakdownView,
    FinanceSeriesView,
    FinanceSummaryView,
)

urlpatterns = [
    path("finance/summary/", FinanceSummaryView.as_view(), name="finance-summary"),
    path("finance/series/", FinanceSeriesView.as_view(), name="finance-series"),
    path(
        "finance/breakdown/",
        FinanceBreakdownView.as_view(),
        name="finance-breakdown",
    ),
]
```

Add to `stockmanager/urls.py`:

```python
    path("api/", include("apps.finance.urls")),
```

- [ ] **Step 6: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/finance/tests/test_finance_api.py -p no:warnings`

One failure to expect: the query-count bound, per the note in Step 1.
Confirm it is flat before adjusting it.

- [ ] **Step 7: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/finance stockmanager/urls.py
git commit -m "Add the finance facts seam and the three read endpoints"
```

---

## Task 5: Admin, README and the wire check

**Files:**
- Create: `apps/expenses/admin.py`
- Modify: `README.md`
- Test: manual wire verification, then the full suite

- [ ] **Step 1: Register the admin**

Create `apps/expenses/admin.py`:

```python
from django.contrib import admin

from apps.expenses.models import Expense


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ["spent_at", "category", "label", "amount", "method", "user_name"]
    list_filter = ["category", "method"]
    search_fields = ["label", "reference", "note"]
    date_hierarchy = "spent_at"
```

Editable, unlike the sales and movement admins: an expense is a private record
that nothing references, and the API allows the same.

- [ ] **Step 2: Update the README**

Add to the endpoints table:

```
| `/api/expenses/` `…/{id}/` | GET POST PATCH DELETE | gérant |
| `/api/finance/summary/` `series/` `breakdown/` | GET | gérant |
```

Add a short French section covering: that the three finance reads take a
required `from`/`to` and return finished figures — the frontend does no
arithmetic; that `receivables` and the unpaid-sales list are « à ce jour » and
ignore the period; that a payment on a later-cancelled sale still counts as an
encaissement, because the cash moved; and that the cumulative cash line starts
at zero at the beginning of the period rather than showing the till balance.

- [ ] **Step 3: Verify the wire format**

Start the server against a scratch database, as sub-project 4's Task 11 did,
then check each payload's exact key set against `types/dto.ts`:

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8395/api/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"email":"...","password":"..."}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["accessToken"])')

for path in summary series breakdown; do
  echo "== $path"
  curl -s "http://127.0.0.1:8395/api/finance/$path/?from=2026-01-01&to=2026-12-31" \
    -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | head -30
done
```

Confirm, key by key:

- the summary carries all thirteen `FinanceSummary` keys in camelCase
- `marginRate` is a JSON **number** with decimals, not a string and not an
  integer
- a monthly series labels its first bucket `janv. 2026` — the month Django's
  own locale would have called `jan.`
- a daily series labels a July bucket `1 juil.` with no zero padding
- the breakdown's `unpaidSales` rows carry `customerName`, and `topArticles`
  rows carry `articleSku`
- an expense round-trips: POST one with `spentAt: "2026-07-02"` and confirm the
  response's `spentAt` is that day at local noon in UTC

- [ ] **Step 4: Final checks**

```bash
~/.pyenv/versions/stock/bin/python manage.py check
~/.pyenv/versions/stock/bin/python manage.py makemigrations --check --dry-run
~/.pyenv/versions/stock/bin/pytest -p no:warnings
```

All three must be clean. Report the actual test count; do not estimate it.

- [ ] **Step 5: Commit**

```bash
git add apps/expenses/admin.py README.md
git commit -m "Register the expense admin and document the finance reads"
```

---

## Notes for the reviewer

Things a passing suite does not prove:

- **The two Node comparisons must run, not skip.** They are the only checks
  that the label table and the aggregation match the frontend. `pytest -v`
  should show them passing; if the output says `skipped`, node is missing and
  this sub-project has lost its strongest evidence.
- **No `round()` on the percentages.** `grep -n "round" apps/finance/*.py`
  should return nothing. `marginRate` and `share` are unrounded floats by
  design, which is the opposite of the money rule one app away.
- **`period.py` and `aggregate.py` import no Django.** Two tests assert it;
  check they are still there, because the isolation is what makes the Node
  comparison possible.
- **The three unbounded folds.** `receivables`, `unpaid_sales` and
  `paid_by_sale` deliberately ignore the date range. If someone "optimises"
  `load_facts` by range-filtering the sales queryset, all three silently start
  reporting period figures instead of as-of-now figures, and no key set
  changes.
- **Query-count bound.** If it was raised, confirm it does not grow with the
  number of sales.

---

## Follow-ups

Recorded during execution. None blocks merge.

- **`aggregate.py` was written before its test file.** The same slip as
  sub-project 4's tasks 8–10: the red-green cycle was not observed. Rather
  than leave that as a claim, the implementation was mutated four ways and
  each mutation confirmed to fail a test — `round()` on `margin_rate`,
  dropping the `max(...,0)` floor on receivables, letting receipts ignore the
  range, and dropping the top-5 cap. The third was caught **only** by the Node
  comparison, which is the strongest single argument for keeping that test.
  Task 4 was done test-first and its 36 tests were seen red.
- **The `-p no:warnings` habit is now a known hazard.** It hid
  `UnorderedObjectListWarning` through all of sub-project 4. Nothing in this
  sub-project paginates an annotated queryset, so there was nothing to hide —
  but the flag is still on every focused run. Worth a `filterwarnings = error`
  entry in `pytest.ini` for the specific DRF warnings that indicate bugs,
  rather than suppressing the lot.
- **`load_facts` reads the whole sales table on every finance request.** Named
  in the spec as the known scale limit; repeating it here because the fix is
  easy to get wrong. Range-filtering that queryset is the *obvious* change and
  the *wrong* one: `receivables` and `unpaid_sales` would silently become
  period figures with no payload key changing. The correct fix is to replace
  those two folds with `aggregate()` calls and leave the queryset unbounded.
- **The two Node comparisons are the load-bearing tests** and they skip
  silently where `node` is absent. A CI box without it keeps a green suite
  while losing the only check that the labels and the arithmetic match the
  frontend. Worth failing rather than skipping in CI specifically.
- **`facts.py` has no test of its own.** It is covered only through the three
  endpoints. That is adequate — its whole job is projection — but a direct
  test of the five shapes would catch a renamed field faster than an endpoint
  test does.
- **Carried over and still open:** the stock-status rule has four encodings;
  `DocumentSequence` is not scoped by site; `UserViewSet` uses DRF's
  `OrderingFilter` while articles use the strict one.
