# Catalogue & Stock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the catalogue (categories, suppliers, articles) and single stock movements, plus the low-stock and dashboard reads, exactly as the frontend's mock services already specify them.

**Architecture:** Two new Django apps — `apps/catalogue` (Category, Supplier, Article) and `apps/stock` (StockLevel, StockMovement) — with a strict one-way dependency: `apps.stock` imports from `apps.catalogue`, never the reverse. All stock quantity changes funnel through one function, `apps/stock/services.py::apply_movement`. Shared machinery from sub-project 1 in `apps/common/` is extended, not replaced.

**Tech Stack:** Django 6.0.7, DRF 3.17.1, django-filter 26.1 (new), djangorestframework-camel-case 1.4.2, pytest 9.1.1 + pytest-django 4.12.0 + factory-boy 3.3.3.

## Global Constraints

Every task's requirements implicitly include this section.

- **Read the spec first:** `docs/superpowers/specs/2026-08-06-catalogue-stock-design.md`, and sub-project 1's spec `docs/superpowers/specs/2026-08-03-foundation-auth-design.md` for the conventions this one inherits.
- **Python env:** the virtualenv is pyenv's `stock`. Run everything as `~/.pyenv/versions/stock/bin/python` / `~/.pyenv/versions/stock/bin/pytest`. There is no `.venv` in the project.
- **TDD, strictly.** Write the failing test, watch it fail for the right reason, then implement. A test that has never been seen to fail proves nothing.
- **Every user-facing string is French.** The frontend renders `error.message` straight into a toast. Use `gettext_lazy as _`.
- **Field-error keys must match the frontend's react-hook-form field names**, which are camelCase. Serializers are snake_case; the camelCase renderer converts error bodies too. A key matching no mounted field renders nothing anywhere — a silent failure.
- **Every list view must use `CamelCaseQueryParamsMixin`** (via the base viewset in Task 5). Without it, `?categoryId=` and `ordering=-createdAt` are silently ignored rather than erroring.
- **`Site.objects.current()`** is how you get the site. Never thread a `site_id` through a signature. A `siteId` arriving from a client is accepted and ignored.
- **Models inherit `apps.common.models.UUIDModel`**, which already supplies `id`, `created_at` and `updated_at`. Do not redeclare them.
- **Optional strings:** column is `null=True, blank=True`; serializer field is `required=False, allow_blank=True, allow_null=True`; a `validate()` pass normalises `""` and whitespace to `None`. Copy the pattern from `SiteSerializer` in `apps/accounts/serializers.py`.
- **Money is integer cents** (`PositiveIntegerField`). Quantities are whole units. `vat_rate` is the only decimal in this sub-project.
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
| `stockmanager/settings.py` | + `django_filters`, the two new apps, `SHOP_TIME_ZONE`, `COERCE_DECIMAL_TO_STRING` |
| `apps/common/dates.py` | **new** — turn a local calendar date into a UTC instant |
| `apps/common/filters.py` | + `StrictBooleanFilter`, `AliasedOrderingFilter` |
| `apps/common/views.py` | **new** — the shared catalogue viewset base |
| `apps/catalogue/models.py` | `Category`, `Supplier`, `Article` |
| `apps/catalogue/serializers.py` | the four read shapes + the two write shapes |
| `apps/catalogue/filters.py` | `ArticleFilterSet` |
| `apps/catalogue/views.py` | three viewsets |
| `apps/catalogue/querysets.py` | the annotated article queryset, shared by three views |
| `apps/stock/models.py` | `StockLevel`, `StockMovement` |
| `apps/stock/services.py` | `apply_movement` — the only writer of a quantity |
| `apps/stock/serializers.py` | movement read + write |
| `apps/stock/filters.py` | `MovementFilterSet` |
| `apps/stock/views.py` | movements, low-stock, dashboard |

---

## Task 1: Configuration and calendar dates

**Files:**
- Modify: `requirements.txt`
- Modify: `stockmanager/settings.py`
- Modify: `.env.example`
- Create: `apps/common/dates.py`
- Test: `apps/common/tests/test_dates.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `apps.common.dates.start_of_day(value: date) -> datetime`, `end_of_day(value: date) -> datetime`, `today_start() -> datetime`. All return timezone-aware UTC datetimes. `settings.SHOP_TIME_ZONE: str`.

Why this exists: `dateFrom` / `dateTo` and `movementsToday` are **local calendar** concepts. In the browser they resolved against the user's timezone. Sub-project 1 pinned `TIME_ZONE = "UTC"`, so resolving them in UTC would file a movement recorded at 00:30 Kinshasa time under the previous day.

- [ ] **Step 1: Write the failing test**

Create `apps/common/tests/test_dates.py`:

```python
"""Calendar-date bounds.

Africa/Kinshasa is UTC+1 with no DST, so local midnight is 23:00 UTC on the
previous day. Every assertion below turns on that one hour: a UTC
implementation passes none of them.
"""

from datetime import date, datetime, timezone as dt_timezone

import pytest
from django.test import override_settings

from apps.common.dates import end_of_day, start_of_day, today_start


@override_settings(SHOP_TIME_ZONE="Africa/Kinshasa")
def test_start_of_day_is_local_midnight_expressed_in_utc():
    assert start_of_day(date(2026, 7, 1)) == datetime(
        2026, 6, 30, 23, 0, 0, tzinfo=dt_timezone.utc
    )


@override_settings(SHOP_TIME_ZONE="Africa/Kinshasa")
def test_end_of_day_is_the_last_local_instant_expressed_in_utc():
    assert end_of_day(date(2026, 7, 31)) == datetime(
        2026, 7, 31, 22, 59, 59, 999999, tzinfo=dt_timezone.utc
    )


@override_settings(SHOP_TIME_ZONE="Africa/Kinshasa")
def test_the_bounds_of_one_day_do_not_overlap_the_next():
    assert end_of_day(date(2026, 7, 1)) < start_of_day(date(2026, 7, 2))


@override_settings(SHOP_TIME_ZONE="UTC")
def test_a_utc_shop_gets_utc_midnight():
    assert start_of_day(date(2026, 7, 1)) == datetime(
        2026, 7, 1, 0, 0, 0, tzinfo=dt_timezone.utc
    )


@override_settings(SHOP_TIME_ZONE="Africa/Kinshasa")
def test_today_start_uses_the_shop_day_not_the_utc_day(settings):
    """At 23:30 UTC it is already tomorrow in Kinshasa.

    A UTC implementation returns today's UTC midnight and would count a
    movement made two minutes ago as belonging to a day that, locally, ended
    half an hour earlier.
    """
    from unittest import mock

    from django.utils import timezone as dj_timezone

    late = datetime(2026, 7, 1, 23, 30, tzinfo=dt_timezone.utc)
    with mock.patch.object(dj_timezone, "now", return_value=late):
        # Local date is 2026-07-02, whose midnight is 2026-07-01T23:00Z.
        assert today_start() == datetime(
            2026, 7, 1, 23, 0, 0, tzinfo=dt_timezone.utc
        )


def test_shop_time_zone_is_configured(settings):
    from zoneinfo import ZoneInfo

    assert ZoneInfo(settings.SHOP_TIME_ZONE) is not None
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/common/tests/test_dates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.common.dates'`.

- [ ] **Step 3: Add the dependency**

Add to `requirements.txt`, in the alphabetical block with the other Django packages:

```
django-filter==26.1
```

Install it: `~/.pyenv/versions/stock/bin/pip install django-filter==26.1`

- [ ] **Step 4: Wire the settings**

In `stockmanager/settings.py`, add `"django_filters"` to `INSTALLED_APPS` immediately after `"corsheaders"`, and the two new apps at the end:

```python
INSTALLED_APPS = [
    # ... unchanged ...
    "corsheaders",
    "django_filters",
    "apps.common",
    "apps.accounts",
    "apps.catalogue",
    "apps.stock",
]
```

> The two app packages do not exist yet, so `manage.py check` will fail until Tasks 3 and 4 create them. Add them now anyway — splitting the settings edit across three tasks is worse. Task 3's first step creates the package.

Add to the `REST_FRAMEWORK` dict, after `"PAGE_SIZE": 20,`:

```python
    # DRF renders DecimalField as a JSON *string* by default. The frontend's
    # `vatRate` is typed `number`, and a string there renders NaN in the
    # article form. Set globally so every future decimal is right by default
    # rather than needing a per-field flag someone will forget.
    "COERCE_DECIMAL_TO_STRING": False,
```

Add after the `TIME_ZONE` / `USE_TZ` block:

```python
# Storage stays UTC. This is used *only* to turn a bare calendar date from the
# client — `dateFrom=2026-07-01`, or "today" on the dashboard — into an
# instant. Those are local-calendar concepts: the frontend resolved them
# against the browser's timezone, and a server that resolves them in UTC files
# a movement made at 00:30 Kinshasa time under the previous day.
SHOP_TIME_ZONE = str(env("SHOP_TIME_ZONE", "Africa/Kinshasa"))
```

- [ ] **Step 5: Document the setting**

Add to `.env.example`, with a comment:

```
# IANA timezone of the shop. Used only to interpret calendar dates and
# "today"; all timestamps are stored in UTC.
SHOP_TIME_ZONE=Africa/Kinshasa
```

- [ ] **Step 6: Implement the date helpers**

Create `apps/common/dates.py`:

```python
"""Local calendar dates.

`MovementListParams.dateFrom` / `dateTo` and `DashboardStats.movementsToday`
are local-calendar concepts. `services/stock.ts` says so explicitly: it parses
`"2026-07-01"` without a `Z` suffix precisely so the browser reads it as local
midnight.

Storage is UTC and `TIME_ZONE` is UTC. These three functions are the only
place `SHOP_TIME_ZONE` is used, so there is exactly one definition of where a
day begins.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone


def shop_timezone() -> ZoneInfo:
    return ZoneInfo(settings.SHOP_TIME_ZONE)


def start_of_day(value: date) -> datetime:
    """Local midnight on `value`, as an aware UTC datetime."""
    local = datetime.combine(value, time.min, tzinfo=shop_timezone())
    return local.astimezone(timezone.utc)


def end_of_day(value: date) -> datetime:
    """The last local instant of `value`, as an aware UTC datetime.

    23:59:59.999999 rather than the next midnight, because the frontend's
    `dateTo` is inclusive and a half-open upper bound would silently include
    the first microsecond of the following day.
    """
    local = datetime.combine(value, time.max, tzinfo=shop_timezone())
    return local.astimezone(timezone.utc)


def today_start() -> datetime:
    """Local midnight of the shop's current day, as an aware UTC datetime."""
    return start_of_day(timezone.now().astimezone(shop_timezone()).date())
```

- [ ] **Step 7: Run the tests**

Run: `~/.pyenv/versions/stock/bin/pytest apps/common/tests/test_dates.py -v`
Expected: all PASS.

Then confirm nothing else broke — the decimal setting is global:
Run: `~/.pyenv/versions/stock/bin/pytest apps/common apps/accounts -q`
Expected: all PASS. (`apps.catalogue` / `apps.stock` in `INSTALLED_APPS` will fail here; if so, create the two empty packages now — `apps/catalogue/__init__.py`, `apps/catalogue/apps.py`, and the same for `stock` — using `apps/common/apps.py` as the template for the `AppConfig`.)

- [ ] **Step 8: Commit**

```bash
git add requirements.txt stockmanager/settings.py .env.example apps/common/dates.py apps/common/tests/test_dates.py apps/catalogue apps/stock
git commit -m "Add django-filter, SHOP_TIME_ZONE and the calendar-date helpers"
```

---

## Task 2: Strict filters and the `?isActive=` retrofit

**Files:**
- Modify: `apps/common/filters.py`
- Modify: `apps/accounts/views.py` (`UserViewSet`)
- Create: `apps/accounts/filters.py`
- Test: `apps/common/tests/test_filters.py` (extend), `apps/accounts/tests/test_users_endpoint.py` (extend)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `apps.common.filters.StrictBooleanFilter` (a `django_filters.BooleanFilter` subclass), `apps.common.filters.AliasedOrderingFilter` (a `rest_framework.filters.OrderingFilter` subclass reading `ordering_aliases: dict[str, str]` from the view).

Two silent-failure modes are being closed here.

**Booleans.** `django_filters.BooleanFilter` uses `django_filters.widgets.BooleanWidget`, whose `value_from_datadict` maps any unrecognised value to `None` *before* validation runs — so overriding only the form field is not enough and `?isActive=banana` still returns 200. This was verified during design. The widget must be overridden too.

**Ordering.** DRF's `OrderingFilter.remove_invalid_fields` *filters* the term list rather than rejecting it, so an unknown `ordering` value silently falls back to the default. It also compares terms against queryset names directly, so a public sort key cannot differ from the annotation it sorts by — which `ordering=stock` needs, since the annotation is `stock_quantity`.

- [ ] **Step 1: Write the failing tests for the filters themselves**

Append to `apps/common/tests/test_filters.py`:

```python
class TestStrictBooleanFilter:
    """`?isActive=banana` must 400, not read as "no filter".

    The dangerous case is not the typo — it is that a silently-dropped filter
    returns *more* rows than asked for, looking exactly like a correct
    unfiltered response.
    """

    def _filterset(self, value):
        from django_filters import rest_framework as drf_filters

        from apps.accounts.models import User
        from apps.common.filters import StrictBooleanFilter

        class Fixture(drf_filters.FilterSet):
            is_active = StrictBooleanFilter()

            class Meta:
                model = User
                fields = ["is_active"]

        return Fixture(data={"is_active": value}, queryset=User.objects.all())

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("true", True),
            ("TRUE", True),
            ("True", True),
            ("1", True),
            ("false", False),
            ("FALSE", False),
            ("0", False),
        ],
    )
    def test_accepts_both_cases_and_both_spellings(self, db, raw, expected):
        fs = self._filterset(raw)
        assert fs.is_valid(), fs.errors
        assert fs.form.cleaned_data["is_active"] is expected

    @pytest.mark.parametrize("raw", ["banana", "yes", "2", "-1", "oui"])
    def test_rejects_anything_else(self, db, raw):
        fs = self._filterset(raw)
        assert not fs.is_valid()
        assert "is_active" in fs.errors

    def test_an_absent_value_is_not_a_filter(self, db):
        from apps.accounts.models import User
        from django_filters import rest_framework as drf_filters

        from apps.common.filters import StrictBooleanFilter

        class Fixture(drf_filters.FilterSet):
            is_active = StrictBooleanFilter()

            class Meta:
                model = User
                fields = ["is_active"]

        fs = Fixture(data={}, queryset=User.objects.all())
        assert fs.is_valid(), fs.errors
        assert fs.form.cleaned_data["is_active"] is None

    def test_the_widget_is_overridden_not_just_the_field(self, db):
        """Regression guard for the exact bug this class exists to avoid.

        `BooleanWidget.value_from_datadict` maps an unknown value to None
        before `clean()` runs, so a `field_class` override alone silently
        passes. If someone drops the widget override, this fails.
        """
        from django import forms
        from django_filters.widgets import BooleanWidget

        from apps.common.filters import StrictBooleanFilter

        widget = StrictBooleanFilter().field.widget
        assert not isinstance(widget, BooleanWidget)
        assert isinstance(widget, forms.TextInput)

    def test_the_message_is_french(self, db):
        fs = self._filterset("banana")
        fs.is_valid()
        assert "true" in str(fs.errors["is_active"][0])
        assert "attendu" in str(fs.errors["is_active"][0])
```

Add `import pytest` at the top of the file if it is not already there.

- [ ] **Step 2: Run them and watch them fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/common/tests/test_filters.py -v`
Expected: FAIL — `ImportError: cannot import name 'StrictBooleanFilter'`.

- [ ] **Step 3: Implement both filters**

Append to `apps/common/filters.py` (keep the existing module docstring and `CamelCaseQueryParamsMixin`):

```python
from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django_filters import rest_framework as drf_filters
from rest_framework import serializers
from rest_framework.filters import OrderingFilter

_TRUE = {"true", "1"}
_FALSE = {"false", "0"}


class StrictBooleanField(forms.Field):
    # A plain text widget, because django-filter's BooleanWidget maps an
    # unrecognised value to None inside `value_from_datadict` — before any
    # field validation runs. With that widget in place `clean()` below never
    # sees "banana" and the filter silently does nothing.
    widget = forms.TextInput

    def clean(self, value):
        if value in self.empty_values:
            return None
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ValidationError(
            _("Valeur invalide : « true » ou « false » attendu."), code="invalid"
        )


class StrictBooleanFilter(drf_filters.BooleanFilter):
    """A boolean filter that rejects what it cannot parse.

    An unparseable value returns 400 rather than being dropped. A dropped
    filter returns *more* rows than the caller asked for while looking like a
    correct response, which is the worst failure mode a filter has.
    """

    field_class = StrictBooleanField

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", forms.TextInput)
        super().__init__(*args, **kwargs)


class AliasedOrderingFilter(OrderingFilter):
    """`OrderingFilter` that rejects unknown terms and maps public sort keys.

    Two departures from DRF:

    1. `remove_invalid_fields` silently *drops* an unrecognised term and falls
       back to the default ordering. Here an unknown term is a 400, matching
       how every other query parameter behaves.
    2. A view may declare `ordering_aliases = {"stock": "stock_quantity"}`, so
       the public sort key and the queryset expression can differ. DRF
       compares terms against queryset names directly and has no way to
       express this.
    """

    def remove_invalid_fields(self, queryset, fields, view, request):
        aliases = getattr(view, "ordering_aliases", {}) or {}
        valid = {item[0] for item in self.get_valid_fields(queryset, view, {"request": request})}
        valid |= set(aliases)

        resolved = []
        for term in fields:
            descending = term.startswith("-")
            name = term[1:] if descending else term
            if name not in valid:
                raise serializers.ValidationError(
                    {
                        self.ordering_param: [
                            _("Tri invalide : « %(field)s » n'est pas un tri autorisé.")
                            % {"field": name}
                        ]
                    }
                )
            target = aliases.get(name, name)
            resolved.append(f"-{target}" if descending else target)
        return resolved
```

- [ ] **Step 4: Run the filter tests**

Run: `~/.pyenv/versions/stock/bin/pytest apps/common/tests/test_filters.py -v`
Expected: all PASS.

- [ ] **Step 5: Write the failing API test for the retrofit**

Append to `apps/accounts/tests/test_users_endpoint.py`:

```python
def test_is_active_filter_still_works(auth_client, owner, db):
    from apps.accounts.tests.factories import CashierFactory

    CashierFactory(is_active=False)
    client = auth_client(owner)

    active = client.get("/api/users/?isActive=true")
    assert active.status_code == 200
    assert all(row["isActive"] for row in active.json()["results"])

    inactive = client.get("/api/users/?isActive=false")
    assert inactive.status_code == 200
    assert inactive.json()["count"] == 1
    assert not inactive.json()["results"][0]["isActive"]


def test_an_unparseable_is_active_is_rejected(auth_client, owner, db):
    """Closes the follow-up recorded in sub-project 1's plan.

    Before this, `?isActive=banana` returned 200 and every user — a typo read
    as "no filter", which is indistinguishable from a correct response.
    """
    response = auth_client(owner).get("/api/users/?isActive=banana")

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
    assert "isActive" in response.json()["fieldErrors"]
```

- [ ] **Step 6: Run it and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/accounts/tests/test_users_endpoint.py -k is_active -v`
Expected: `test_an_unparseable_is_active_is_rejected` FAILS with 200 != 400. The other test passes already — that is the point of writing it, to prove the retrofit does not regress what worked.

- [ ] **Step 7: Retrofit `UserViewSet`**

Create `apps/accounts/filters.py`:

```python
from django_filters import rest_framework as drf_filters

from apps.accounts.models import User
from apps.common.filters import StrictBooleanFilter


class UserFilterSet(drf_filters.FilterSet):
    is_active = StrictBooleanFilter()

    class Meta:
        model = User
        fields = ["is_active"]
```

In `apps/accounts/views.py`: add the imports

```python
from django_filters.rest_framework import DjangoFilterBackend

from apps.accounts.filters import UserFilterSet
```

then on `UserViewSet`, replace the `filter_backends` line and **delete the whole `get_queryset` override** with its manual `is_active` handling:

```python
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = UserFilterSet
```

- [ ] **Step 8: Run the accounts suite**

Run: `~/.pyenv/versions/stock/bin/pytest apps/accounts -q`
Expected: all PASS. If `get_queryset` did anything besides the `is_active` filter, restore that part — check the diff before assuming.

- [ ] **Step 9: Commit**

```bash
git add apps/common/filters.py apps/common/tests/test_filters.py apps/accounts/filters.py apps/accounts/views.py apps/accounts/tests/test_users_endpoint.py
git commit -m "Add strict boolean and ordering filters, retrofit ?isActive="
```

---

## Task 3: Catalogue models

**Files:**
- Create: `apps/catalogue/__init__.py`, `apps/catalogue/apps.py`, `apps/catalogue/models.py`, `apps/catalogue/migrations/__init__.py`
- Create: `apps/catalogue/tests/__init__.py`, `apps/catalogue/tests/factories.py`
- Test: `apps/catalogue/tests/test_models.py`

**Interfaces:**
- Consumes: `apps.common.models.UUIDModel`.
- Produces: `apps.catalogue.models.Category`, `Supplier`, `Article`, `Article.Unit` (TextChoices). Factories `CategoryFactory`, `SupplierFactory`, `ArticleFactory` in `apps.catalogue.tests.factories` — later tasks and sub-projects import these.

- [ ] **Step 1: Write the failing model tests**

Create `apps/catalogue/tests/test_models.py`:

```python
"""Catalogue model invariants.

Case-insensitive uniqueness is enforced by a functional index, not only by a
serializer. The serializer produces the French message a user reads; the index
is what makes the guarantee true when two requests race.
"""

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.catalogue.models import Article, Category, Supplier
from apps.catalogue.tests.factories import (
    ArticleFactory,
    CategoryFactory,
    SupplierFactory,
)

pytestmark = pytest.mark.django_db


class TestCategory:
    def test_names_differing_only_in_case_collide(self):
        CategoryFactory(name="Boissons")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Category.objects.create(name="BOISSONS")

    def test_distinct_names_coexist(self):
        CategoryFactory(name="Boissons")
        CategoryFactory(name="Épicerie")
        assert Category.objects.count() == 2

    def test_default_ordering_is_by_name(self):
        CategoryFactory(name="Épicerie")
        CategoryFactory(name="Boissons")
        assert [c.name for c in Category.objects.all()] == ["Boissons", "Épicerie"]

    def test_a_category_with_articles_cannot_be_deleted(self):
        article = ArticleFactory()
        with pytest.raises(ProtectedError):
            article.category.delete()


class TestSupplier:
    def test_names_differing_only_in_case_collide(self):
        SupplierFactory(name="Brasimba")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Supplier.objects.create(name="BRASIMBA")

    def test_a_supplier_with_articles_cannot_be_deleted(self):
        article = ArticleFactory(supplier=SupplierFactory())
        with pytest.raises(ProtectedError):
            article.supplier.delete()


class TestArticle:
    def test_skus_differing_only_in_case_collide(self):
        category = CategoryFactory()
        ArticleFactory(sku="BOI-001", category=category)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ArticleFactory(sku="boi-001", category=category)

    def test_barcodes_collide(self):
        ArticleFactory(barcode="1234567890123")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ArticleFactory(barcode="1234567890123")

    def test_many_articles_may_have_no_barcode(self):
        """NULL, not "".

        An empty string is a value that collides with itself, so a second
        barcode-less article would violate the unique constraint. NULL never
        compares equal to NULL.
        """
        ArticleFactory(barcode=None)
        ArticleFactory(barcode=None)
        assert Article.objects.filter(barcode__isnull=True).count() == 2

    def test_supplier_is_optional(self):
        article = ArticleFactory(supplier=None)
        assert article.supplier is None

    def test_vat_rate_keeps_two_decimal_places(self):
        from decimal import Decimal

        article = ArticleFactory(vat_rate=Decimal("5.50"))
        article.refresh_from_db()
        assert article.vat_rate == Decimal("5.50")

    def test_default_ordering_is_by_name(self):
        ArticleFactory(name="Sucre")
        ArticleFactory(name="Farine")
        assert [a.name for a in Article.objects.all()] == ["Farine", "Sucre"]
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/catalogue -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.catalogue.models'`.

- [ ] **Step 3: Create the app package**

```bash
mkdir -p apps/catalogue/migrations apps/catalogue/tests
touch apps/catalogue/__init__.py apps/catalogue/migrations/__init__.py apps/catalogue/tests/__init__.py
```

Create `apps/catalogue/apps.py`:

```python
from django.apps import AppConfig


class CatalogueConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalogue"
    verbose_name = "Catalogue"
```

- [ ] **Step 4: Write the models**

Create `apps/catalogue/models.py`:

```python
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from apps.common.models import UUIDModel


class Category(UUIDModel):
    name = models.CharField(_("nom"), max_length=60)
    description = models.CharField(
        _("description"), max_length=200, null=True, blank=True
    )

    class Meta:
        ordering = ["name"]
        verbose_name = _("catégorie")
        verbose_name_plural = _("catégories")
        constraints = [
            # A functional index, not `unique=True`: the frontend compares
            # names with `toLocaleLowerCase("fr-FR")`, so "Boissons" and
            # "BOISSONS" are the same category to a user. The serializer
            # produces the French message; this is what holds under a race.
            models.UniqueConstraint(Lower("name"), name="category_name_unique_ci"),
        ]

    def __str__(self) -> str:
        return self.name


class Supplier(UUIDModel):
    name = models.CharField(_("nom"), max_length=80)
    contact_name = models.CharField(
        _("nom du contact"), max_length=80, null=True, blank=True
    )
    email = models.EmailField(_("adresse e-mail"), null=True, blank=True)
    phone = models.CharField(_("téléphone"), max_length=20, null=True, blank=True)
    address = models.CharField(_("adresse"), max_length=200, null=True, blank=True)
    notes = models.CharField(_("notes"), max_length=500, null=True, blank=True)
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("fournisseur")
        verbose_name_plural = _("fournisseurs")
        constraints = [
            models.UniqueConstraint(Lower("name"), name="supplier_name_unique_ci"),
        ]

    def __str__(self) -> str:
        return self.name


class Article(UUIDModel):
    class Unit(models.TextChoices):
        PIECE = "PIECE", _("Pièce")
        KG = "KG", _("Kilogramme")
        LITRE = "LITRE", _("Litre")
        PAQUET = "PAQUET", _("Paquet")
        CARTON = "CARTON", _("Carton")

    sku = models.CharField(_("référence"), max_length=32)
    # NULL rather than "" — the column is unique, and "" collides with itself,
    # so a second barcode-less article would be rejected.
    barcode = models.CharField(
        _("code-barres"), max_length=13, null=True, blank=True
    )
    name = models.CharField(_("nom"), max_length=120)
    description = models.CharField(
        _("description"), max_length=500, null=True, blank=True
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="articles",
        verbose_name=_("catégorie"),
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="articles",
        null=True,
        blank=True,
        verbose_name=_("fournisseur"),
    )
    unit = models.CharField(
        _("unité"), max_length=8, choices=Unit.choices, default=Unit.PIECE
    )
    # Cents. The frontend's `Cents` type is an integer and every price input
    # is `.int()`; storing a float here would reintroduce rounding error into
    # figures the reports sub-project has to reconcile exactly.
    purchase_price = models.PositiveIntegerField(_("prix d'achat"), default=0)
    sale_price = models.PositiveIntegerField(_("prix de vente"), default=0)
    # The only decimal in this sub-project: the article form normalises a
    # decimal comma, so "5,5" is a rate a user can enter.
    vat_rate = models.DecimalField(
        _("taux de TVA"), max_digits=5, decimal_places=2, default=0
    )
    is_active = models.BooleanField(_("actif"), default=True)
    image_url = models.URLField(_("image"), null=True, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("article")
        verbose_name_plural = _("articles")
        constraints = [
            models.UniqueConstraint(Lower("sku"), name="article_sku_unique_ci"),
            models.UniqueConstraint(
                "barcode",
                name="article_barcode_unique",
                condition=models.Q(barcode__isnull=False),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.sku} — {self.name}"
```

- [ ] **Step 5: Write the factories**

Create `apps/catalogue/tests/factories.py`:

```python
"""Catalogue factories.

Imported by later tasks and by sub-projects 3–6, so the signatures are
effectively public. Keep the defaults realistic — a Goma corner shop.
"""

from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

from apps.catalogue.models import Article, Category, Supplier


class CategoryFactory(DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f"Catégorie {n}")
    description = "Produits de première nécessité."


class SupplierFactory(DjangoModelFactory):
    class Meta:
        model = Supplier

    name = factory.Sequence(lambda n: f"Fournisseur {n}")
    contact_name = "Jean Kabila"
    email = factory.Sequence(lambda n: f"contact{n}@fournisseur.cd")
    phone = "+243 990 111 222"
    address = "18 avenue du Lac, Goma"
    notes = None
    is_active = True


class ArticleFactory(DjangoModelFactory):
    class Meta:
        model = Article

    sku = factory.Sequence(lambda n: f"ART-{n:04d}")
    barcode = None
    name = factory.Sequence(lambda n: f"Article {n}")
    description = None
    category = factory.SubFactory(CategoryFactory)
    supplier = None
    unit = Article.Unit.PIECE
    purchase_price = 1000
    sale_price = 1500
    vat_rate = Decimal("16.00")
    is_active = True
```

- [ ] **Step 6: Make and run the migration**

```bash
~/.pyenv/versions/stock/bin/python manage.py makemigrations catalogue
~/.pyenv/versions/stock/bin/pytest apps/catalogue -v
```

Expected: all PASS.

- [ ] **Step 7: Verify nothing else broke and the migration is complete**

```bash
~/.pyenv/versions/stock/bin/python manage.py makemigrations --check --dry-run
~/.pyenv/versions/stock/bin/pytest -q
```

Expected: "No changes detected", and the whole suite green.

- [ ] **Step 8: Commit**

```bash
git add apps/catalogue
git commit -m "Add the Category, Supplier and Article models"
```

---

## Task 4: Stock models

**Files:**
- Create: `apps/stock/__init__.py`, `apps/stock/apps.py`, `apps/stock/models.py`, `apps/stock/migrations/__init__.py`
- Create: `apps/stock/tests/__init__.py`, `apps/stock/tests/factories.py`
- Test: `apps/stock/tests/test_models.py`

**Interfaces:**
- Consumes: `apps.catalogue.models.Article`, `apps.accounts.models.Site`, `Site.objects.current()`, `apps.catalogue.tests.factories.ArticleFactory`.
- Produces: `apps.stock.models.StockLevel` (with a `status` property returning one of `"IN_STOCK" | "LOW" | "OUT_OF_STOCK"`), `StockMovement`, `StockMovement.Type`, `StockMovement.Reason`. Factories `StockLevelFactory`, `StockMovementFactory`.

- [ ] **Step 1: Write the failing tests**

Create `apps/stock/tests/test_models.py`:

```python
"""Stock model invariants.

The status boundaries are the important part. `deriveStatus` in the
frontend's `lib/service-utils.ts` is three lines, and every one of them is an
inclusive comparison — a strict `<` anywhere here puts an article on the
wrong side of the low-stock alert.
"""

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.catalogue.tests.factories import ArticleFactory
from apps.stock.models import StockLevel, StockMovement
from apps.stock.tests.factories import StockLevelFactory, StockMovementFactory

pytestmark = pytest.mark.django_db


class TestStockLevelStatus:
    @pytest.mark.parametrize(
        ("quantity", "threshold", "expected"),
        [
            (0, 10, "OUT_OF_STOCK"),
            (0, 0, "OUT_OF_STOCK"),
            (1, 10, "LOW"),
            (9, 10, "LOW"),
            (10, 10, "LOW"),      # inclusive: quantity <= threshold
            (11, 10, "IN_STOCK"),
            (1, 0, "IN_STOCK"),   # no threshold set, any stock is fine
            (500, 10, "IN_STOCK"),
        ],
    )
    def test_boundaries_match_derive_status(self, site, quantity, threshold, expected):
        level = StockLevelFactory(quantity=quantity, reorder_threshold=threshold)
        assert level.status == expected


class TestStockLevel:
    def test_one_level_per_article_and_site(self, site):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                StockLevel.objects.create(article=article, site=site, quantity=5)

    def test_deleting_an_article_deletes_its_level(self, site):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site)
        article.delete()
        assert StockLevel.objects.count() == 0


class TestStockMovement:
    def test_an_article_with_movements_cannot_be_deleted(self, site, owner):
        movement = StockMovementFactory(user=owner)
        with pytest.raises(ProtectedError):
            movement.article.delete()

    def test_a_user_with_movements_cannot_be_deleted(self, site, owner):
        """Which is what makes sub-project 1's deactivate-never-delete policy
        load-bearing rather than decorative."""
        StockMovementFactory(user=owner)
        with pytest.raises(ProtectedError):
            owner.delete()

    def test_user_name_is_denormalised(self, site, owner):
        movement = StockMovementFactory(user=owner, user_name=owner.full_name)
        owner.full_name = "Nom Modifié"
        owner.save()
        movement.refresh_from_db()
        assert movement.user_name != "Nom Modifié"

    def test_default_ordering_is_newest_first(self, site, owner):
        first = StockMovementFactory(user=owner)
        second = StockMovementFactory(user=owner)
        assert list(StockMovement.objects.all()) == [second, first]
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/stock -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.stock.models'`.

- [ ] **Step 3: Create the package and models**

```bash
mkdir -p apps/stock/migrations apps/stock/tests
touch apps/stock/__init__.py apps/stock/migrations/__init__.py apps/stock/tests/__init__.py
```

`apps/stock/apps.py`:

```python
from django.apps import AppConfig


class StockConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.stock"
    verbose_name = "Stock"
```

`apps/stock/models.py`:

```python
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Site
from apps.catalogue.models import Article
from apps.common.models import UUIDModel


class StockLevel(UUIDModel):
    """The current quantity of one article at one site.

    Written only by `apps.stock.services.apply_movement`, with one exception:
    article creation writes the opening row alongside the article itself, and
    article update may change `reorder_threshold`. Quantity has exactly one
    writer.
    """

    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name="levels",
        verbose_name=_("article"),
    )
    site = models.ForeignKey(
        Site, on_delete=models.PROTECT, related_name="stock_levels"
    )
    quantity = models.PositiveIntegerField(_("quantité"), default=0)
    reorder_threshold = models.PositiveIntegerField(
        _("seuil de réapprovisionnement"), default=0
    )

    class Meta:
        verbose_name = _("niveau de stock")
        verbose_name_plural = _("niveaux de stock")
        constraints = [
            models.UniqueConstraint(
                fields=["article", "site"], name="one_stock_level_per_article_and_site"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.article.sku}: {self.quantity}"

    @property
    def status(self) -> str:
        """Mirrors `deriveStatus` in the frontend's `lib/service-utils.ts`.

        Both comparisons are inclusive. `ArticleFilterSet` derives the same
        three buckets in SQL; if you change one, change both, or the
        low-stock list and the article filter start disagreeing.
        """
        if self.quantity <= 0:
            return "OUT_OF_STOCK"
        if self.quantity <= self.reorder_threshold:
            return "LOW"
        return "IN_STOCK"


class StockMovement(UUIDModel):
    """One append-only ledger entry.

    Nothing updates or deletes a movement, in this sub-project or any later
    one. A correction is a new, compensating movement.
    """

    class Type(models.TextChoices):
        IN = "IN", _("Entrée")
        OUT = "OUT", _("Sortie")
        ADJUSTMENT = "ADJUSTMENT", _("Ajustement")

    class Reason(models.TextChoices):
        PURCHASE = "PURCHASE", _("Achat fournisseur")
        SALE = "SALE", _("Vente")
        RETURN = "RETURN", _("Retour")
        DAMAGE = "DAMAGE", _("Casse")
        LOSS = "LOSS", _("Perte")
        COUNT_CORRECTION = "COUNT_CORRECTION", _("Correction d'inventaire")
        OTHER = "OTHER", _("Autre")

    article = models.ForeignKey(
        Article, on_delete=models.PROTECT, related_name="movements"
    )
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="movements")
    type = models.CharField(_("type"), max_length=16, choices=Type.choices)
    reason = models.CharField(_("motif"), max_length=20, choices=Reason.choices)
    # Always positive; `type` carries the direction. For an ADJUSTMENT this is
    # the delta that was applied, not the counted target the client sent.
    quantity = models.PositiveIntegerField(_("quantité"))
    quantity_before = models.PositiveIntegerField(_("quantité avant"))
    quantity_after = models.PositiveIntegerField(_("quantité après"))
    unit_cost = models.PositiveIntegerField(_("coût unitaire"), null=True, blank=True)
    reference = models.CharField(
        _("référence"), max_length=40, null=True, blank=True
    )
    note = models.CharField(_("note"), max_length=300, null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="movements"
    )
    # Denormalised so the ledger still reads correctly after a rename, and so
    # the reports sub-project can print `userName` on a document without a join.
    user_name = models.CharField(_("auteur"), max_length=150)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = _("mouvement de stock")
        verbose_name_plural = _("mouvements de stock")

    def __str__(self) -> str:
        return f"{self.type} {self.quantity} × {self.article.sku}"
```

> `ordering` includes `-id` as a tiebreaker: two movements created in the same
> transaction can share a timestamp to the microsecond on SQLite, and an
> unstable sort makes pagination drop or repeat rows.

- [ ] **Step 4: Write the factories**

Create `apps/stock/tests/factories.py`:

```python
import factory
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import SiteFactory, UserFactory
from apps.catalogue.tests.factories import ArticleFactory
from apps.stock.models import StockLevel, StockMovement


class StockLevelFactory(DjangoModelFactory):
    class Meta:
        model = StockLevel

    article = factory.SubFactory(ArticleFactory)
    site = factory.SubFactory(SiteFactory)
    quantity = 0
    reorder_threshold = 0


class StockMovementFactory(DjangoModelFactory):
    class Meta:
        model = StockMovement

    article = factory.SubFactory(ArticleFactory)
    site = factory.SubFactory(SiteFactory)
    user = factory.SubFactory(UserFactory)
    user_name = factory.LazyAttribute(lambda obj: obj.user.full_name)
    type = StockMovement.Type.IN
    reason = StockMovement.Reason.PURCHASE
    quantity = 10
    quantity_before = 0
    quantity_after = 10
    unit_cost = 1000
    reference = None
    note = None
```

- [ ] **Step 5: Migrate and run**

```bash
~/.pyenv/versions/stock/bin/python manage.py makemigrations stock
~/.pyenv/versions/stock/bin/pytest apps/stock -v
```

Expected: all PASS.

- [ ] **Step 6: Full suite and migration check**

```bash
~/.pyenv/versions/stock/bin/python manage.py makemigrations --check --dry-run
~/.pyenv/versions/stock/bin/pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add apps/stock
git commit -m "Add the StockLevel and StockMovement models"
```

---

## Task 5: The shared viewset base and the Category endpoints

**Files:**
- Create: `apps/common/views.py`
- Create: `apps/catalogue/serializers.py`, `apps/catalogue/views.py`, `apps/catalogue/urls.py`
- Modify: `stockmanager/urls.py`
- Test: `apps/catalogue/tests/test_categories.py`

**Interfaces:**
- Consumes: `apps.common.filters.CamelCaseQueryParamsMixin`, `AliasedOrderingFilter`; `apps.common.pagination.StandardPagination`; `apps.common.permissions.IsManagerOrAbove`, `IsOwner`; `apps.common.exceptions.Conflict`.
- Produces: `apps.common.views.CatalogueViewSet` — a `ModelViewSet` subclass that later tasks and sub-projects subclass. Subclasses set `queryset`, `serializer_class`, and optionally `search_fields`, `ordering_fields`, `ordering_aliases`, `filterset_class`. `apps.catalogue.serializers.CategorySerializer`.

The base exists because the permission map would otherwise be copied into three viewsets here and roughly a dozen across sub-projects 3–6. A permission rule living in twelve places is one that will eventually be wrong in one of them.

- [ ] **Step 1: Write the failing endpoint tests**

Create `apps/catalogue/tests/test_categories.py`:

```python
"""Category endpoints.

Payload assertions are against the frontend's `Category` type in
`types/domain.ts`: exactly `id`, `name`, `description`, `articleCount`.
"""

import pytest

from apps.catalogue.models import Category
from apps.catalogue.tests.factories import ArticleFactory, CategoryFactory

pytestmark = pytest.mark.django_db

LIST_URL = "/api/categories/"


def detail_url(category) -> str:
    return f"{LIST_URL}{category.id}/"


class TestRead:
    def test_the_payload_matches_the_frontend_type(self, auth_client, cashier):
        category = CategoryFactory(name="Boissons", description="Sodas et eaux.")
        ArticleFactory(category=category)
        ArticleFactory(category=category)

        response = auth_client(cashier).get(LIST_URL)

        assert response.status_code == 200
        assert set(response.json()["results"][0]) == {
            "id",
            "name",
            "description",
            "articleCount",
        }
        row = response.json()["results"][0]
        assert row["name"] == "Boissons"
        assert row["description"] == "Sodas et eaux."
        assert row["articleCount"] == 2

    def test_article_count_includes_archived_articles(self, auth_client, cashier):
        """`withArticleCounts` in services/categories.ts does not filter on
        isActive, and the delete guard counts the same population."""
        category = CategoryFactory()
        ArticleFactory(category=category, is_active=True)
        ArticleFactory(category=category, is_active=False)

        response = auth_client(cashier).get(LIST_URL)

        assert response.json()["results"][0]["articleCount"] == 2

    def test_an_empty_description_serialises_as_null(self, auth_client, cashier):
        CategoryFactory(description=None)
        response = auth_client(cashier).get(LIST_URL)
        assert response.json()["results"][0]["description"] is None

    def test_the_envelope_is_the_frontend_paginated_shape(self, auth_client, cashier):
        CategoryFactory()
        response = auth_client(cashier).get(LIST_URL)
        assert set(response.json()) == {"count", "next", "previous", "results"}

    def test_ordered_by_name(self, auth_client, cashier):
        CategoryFactory(name="Épicerie")
        CategoryFactory(name="Boissons")
        response = auth_client(cashier).get(LIST_URL)
        assert [r["name"] for r in response.json()["results"]] == ["Boissons", "Épicerie"]

    def test_search_covers_name_and_description(self, auth_client, cashier):
        CategoryFactory(name="Boissons", description="Sodas.")
        CategoryFactory(name="Épicerie", description="Farine et sucre.")

        by_name = auth_client(cashier).get(f"{LIST_URL}?search=boiss")
        assert by_name.json()["count"] == 1

        by_description = auth_client(cashier).get(f"{LIST_URL}?search=farine")
        assert by_description.json()["count"] == 1

    def test_retrieve(self, auth_client, cashier):
        category = CategoryFactory(name="Boissons")
        response = auth_client(cashier).get(detail_url(category))
        assert response.status_code == 200
        assert response.json()["name"] == "Boissons"

    def test_unknown_id_is_404_with_the_envelope(self, auth_client, cashier):
        import uuid

        response = auth_client(cashier).get(f"{LIST_URL}{uuid.uuid4()}/")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"

    def test_anonymous_is_rejected(self, api_client):
        response = api_client.get(LIST_URL)
        assert response.status_code == 401
        assert response.json()["code"] == "authentication_failed"


class TestWrite:
    def test_a_manager_can_create(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL, {"name": "Boissons", "description": "Sodas."}, format="json"
        )
        assert response.status_code == 201
        assert response.json()["articleCount"] == 0
        assert Category.objects.count() == 1

    def test_an_empty_description_is_stored_as_null(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL, {"name": "Boissons", "description": ""}, format="json"
        )
        assert response.status_code == 201
        assert Category.objects.get().description is None

    def test_a_manager_can_update(self, auth_client, manager):
        category = CategoryFactory(name="Boissons")
        response = auth_client(manager).patch(
            detail_url(category), {"name": "Boissons fraîches"}, format="json"
        )
        assert response.status_code == 200
        category.refresh_from_db()
        assert category.name == "Boissons fraîches"

    def test_a_duplicate_name_is_rejected_case_insensitively(
        self, auth_client, manager
    ):
        CategoryFactory(name="Boissons")
        response = auth_client(manager).post(
            LIST_URL, {"name": "BOISSONS", "description": ""}, format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["name"] == [
            "Une catégorie porte déjà ce nom."
        ]

    def test_a_category_does_not_clash_with_itself_on_update(
        self, auth_client, manager
    ):
        category = CategoryFactory(name="Boissons")
        response = auth_client(manager).patch(
            detail_url(category), {"description": "Mis à jour."}, format="json"
        )
        assert response.status_code == 200

    def test_a_short_name_is_rejected(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL, {"name": "B", "description": ""}, format="json"
        )
        assert response.status_code == 400
        assert "name" in response.json()["fieldErrors"]


class TestDelete:
    def test_an_owner_can_delete_an_empty_category(self, auth_client, owner):
        category = CategoryFactory()
        response = auth_client(owner).delete(detail_url(category))
        assert response.status_code == 204
        assert Category.objects.count() == 0

    def test_a_category_with_articles_is_409(self, auth_client, owner):
        category = CategoryFactory()
        ArticleFactory(category=category)
        ArticleFactory(category=category)
        ArticleFactory(category=category)

        response = auth_client(owner).delete(detail_url(category))

        assert response.status_code == 409
        assert response.json()["code"] == "conflict"
        assert response.json()["message"] == (
            "Cette catégorie contient 3 articles et ne peut pas être supprimée."
        )

    def test_the_message_is_singular_for_one_article(self, auth_client, owner):
        category = CategoryFactory()
        ArticleFactory(category=category)
        response = auth_client(owner).delete(detail_url(category))
        assert response.json()["message"] == (
            "Cette catégorie contient 1 article et ne peut pas être supprimée."
        )


class TestPermissions:
    def test_a_cashier_may_read(self, auth_client, cashier):
        CategoryFactory()
        assert auth_client(cashier).get(LIST_URL).status_code == 200

    @pytest.mark.parametrize("method", ["post", "patch", "delete"])
    def test_a_cashier_may_not_write(self, auth_client, cashier, method):
        category = CategoryFactory()
        client = auth_client(cashier)
        url = LIST_URL if method == "post" else detail_url(category)
        response = getattr(client, method)(url, {"name": "X"}, format="json")

        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"

    def test_a_manager_may_not_delete(self, auth_client, manager):
        category = CategoryFactory()
        response = auth_client(manager).delete(detail_url(category))
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"

    def test_an_owner_may_do_everything(self, auth_client, owner):
        response = auth_client(owner).post(
            LIST_URL, {"name": "Boissons", "description": ""}, format="json"
        )
        assert response.status_code == 201
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/catalogue/tests/test_categories.py -v`
Expected: FAIL — 404 on every request, because no URL is registered.

- [ ] **Step 3: Write the shared base**

Create `apps/common/views.py`:

```python
"""The shared catalogue viewset.

Every list endpoint in sub-projects 2–6 subclasses this. It exists so the
permission map, the camelCase query translation and the pagination class are
declared once: a rule copied into a dozen viewsets is a rule that will
eventually be wrong in one of them, and the failure — a cashier able to delete
an article — is silent until someone tries it.
"""

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.permissions import IsAuthenticated

from apps.common.filters import AliasedOrderingFilter, CamelCaseQueryParamsMixin
from apps.common.pagination import StandardPagination
from apps.common.permissions import IsManagerOrAbove, IsOwner


class CatalogueViewSet(CamelCaseQueryParamsMixin, viewsets.ModelViewSet):
    """Read for anyone authenticated, write for manager and above, delete for
    the owner.

    Subclasses set `queryset` and `serializer_class`, and may set
    `search_fields`, `ordering_fields`, `ordering_aliases` and
    `filterset_class`.
    """

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, AliasedOrderingFilter]

    def get_permissions(self):
        if self.action == "destroy":
            classes = [IsOwner]
        elif self.request.method in ("POST", "PUT", "PATCH"):
            classes = [IsManagerOrAbove]
        else:
            classes = [IsAuthenticated]
        return [permission() for permission in classes]
```

- [ ] **Step 4: Write the Category serializer**

Create `apps/catalogue/serializers.py`:

```python
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.catalogue.models import Category


class CategorySerializer(serializers.ModelSerializer):
    """The frontend's `Category`.

    `articleCount` is annotated by the queryset, never stored — see
    `CategoryViewSet.get_queryset`.
    """

    description = serializers.CharField(
        max_length=200, required=False, allow_blank=True, allow_null=True
    )
    article_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = ["id", "name", "description", "article_count"]
        read_only_fields = ["id"]

    def validate_name(self, value):
        name = value.strip()
        if len(name) < 2:
            raise serializers.ValidationError(
                _("Le nom doit contenir au moins 2 caractères.")
            )
        if len(name) > 60:
            raise serializers.ValidationError(
                _("Le nom ne peut pas dépasser 60 caractères.")
            )
        # Case-insensitive, matching the frontend's
        # `toLocaleLowerCase("fr-FR")` comparison. A functional unique index
        # backs this up under a race; this is what produces the message.
        existing = Category.objects.filter(name__iexact=name)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError(_("Une catégorie porte déjà ce nom."))
        return name

    def validate(self, attrs):
        if "description" in attrs:
            value = attrs["description"]
            attrs["description"] = value.strip() or None if value else None
        return attrs
```

- [ ] **Step 5: Write the viewset and URLs**

Create `apps/catalogue/views.py`:

```python
from django.db.models import Count
from django.utils.translation import gettext_lazy as _

from apps.catalogue.models import Category
from apps.catalogue.serializers import CategorySerializer
from apps.common.exceptions import Conflict
from apps.common.views import CatalogueViewSet


class CategoryViewSet(CatalogueViewSet):
    serializer_class = CategorySerializer
    search_fields = ["name", "description"]
    ordering_fields = ["name", "article_count"]
    ordering = ["name"]

    def get_queryset(self):
        # Annotated rather than counted per row: a page of 20 categories would
        # otherwise issue 20 extra queries.
        return Category.objects.annotate(article_count=Count("articles"))

    def perform_destroy(self, instance):
        used = instance.articles.count()
        if used:
            raise Conflict(
                _(
                    "Cette catégorie contient %(count)d article%(plural)s "
                    "et ne peut pas être supprimée."
                )
                % {"count": used, "plural": "s" if used > 1 else ""}
            )
        instance.delete()
```

Create `apps/catalogue/urls.py`:

```python
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.catalogue.views import CategoryViewSet

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")

urlpatterns = [path("", include(router.urls))]
```

In `stockmanager/urls.py`, add the include:

```python
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.accounts.urls")),
    path("api/", include("apps.catalogue.urls")),
]
```

- [ ] **Step 6: Run the tests**

Run: `~/.pyenv/versions/stock/bin/pytest apps/catalogue/tests/test_categories.py -v`
Expected: all PASS.

If `test_a_cashier_may_not_write` returns 401 instead of 403, the permission class is being consulted before authentication — check that `IsAuthenticated` is in the chain and that `_active()` is short-circuiting correctly. If it returns 404, the router basename is wrong.

- [ ] **Step 7: Full suite**

Run: `~/.pyenv/versions/stock/bin/pytest -q`

- [ ] **Step 8: Commit**

```bash
git add apps/common/views.py apps/catalogue stockmanager/urls.py
git commit -m "Add the shared catalogue viewset and the category endpoints"
```

---

## Task 6: Supplier endpoints

**Files:**
- Modify: `apps/catalogue/serializers.py`, `apps/catalogue/views.py`, `apps/catalogue/urls.py`
- Test: `apps/catalogue/tests/test_suppliers.py`

**Interfaces:**
- Consumes: `apps.common.views.CatalogueViewSet`, `apps.catalogue.models.Supplier`.
- Produces: `apps.catalogue.serializers.SupplierSerializer`.

- [ ] **Step 1: Write the failing tests**

Create `apps/catalogue/tests/test_suppliers.py`:

```python
"""Supplier endpoints. Payload from the frontend's `Supplier` type."""

import pytest

from apps.catalogue.models import Supplier
from apps.catalogue.tests.factories import ArticleFactory, SupplierFactory

pytestmark = pytest.mark.django_db

LIST_URL = "/api/suppliers/"


def detail_url(supplier) -> str:
    return f"{LIST_URL}{supplier.id}/"


class TestRead:
    def test_the_payload_matches_the_frontend_type(self, auth_client, cashier):
        SupplierFactory(name="Brasimba")
        response = auth_client(cashier).get(LIST_URL)

        assert response.status_code == 200
        assert set(response.json()["results"][0]) == {
            "id",
            "name",
            "contactName",
            "email",
            "phone",
            "address",
            "notes",
            "isActive",
            "createdAt",
        }

    def test_empty_optionals_serialise_as_null(self, auth_client, cashier):
        SupplierFactory(contact_name=None, email=None, phone=None, address=None)
        row = auth_client(cashier).get(LIST_URL).json()["results"][0]
        assert row["contactName"] is None
        assert row["email"] is None
        assert row["phone"] is None
        assert row["address"] is None

    def test_ordered_by_name(self, auth_client, cashier):
        SupplierFactory(name="Zeta")
        SupplierFactory(name="Alpha")
        response = auth_client(cashier).get(LIST_URL)
        assert [r["name"] for r in response.json()["results"]] == ["Alpha", "Zeta"]

    def test_search_covers_name_contact_email_and_phone(self, auth_client, cashier):
        SupplierFactory(
            name="Brasimba", contact_name="Jean", email="jean@bra.cd", phone="0990111222"
        )
        SupplierFactory(
            name="Bralima", contact_name="Marie", email="marie@bra.cd", phone="0821333444"
        )
        client = auth_client(cashier)

        assert client.get(f"{LIST_URL}?search=brasimba").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=marie").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=jean@bra").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=0821").json()["count"] == 1


class TestWrite:
    def test_a_manager_can_create(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL,
            {
                "name": "Brasimba",
                "contactName": "Jean Kabila",
                "email": "jean@brasimba.cd",
                "phone": "+243 990 111 222",
                "address": "18 avenue du Lac",
                "notes": "",
                "isActive": True,
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["contactName"] == "Jean Kabila"
        assert response.json()["notes"] is None

    def test_a_duplicate_name_is_rejected_case_insensitively(
        self, auth_client, manager
    ):
        SupplierFactory(name="Brasimba")
        response = auth_client(manager).post(
            LIST_URL, {"name": "BRASIMBA", "isActive": True}, format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["name"] == [
            "Un fournisseur porte déjà ce nom."
        ]

    def test_an_invalid_phone_is_rejected(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL,
            {"name": "Brasimba", "phone": "pas-un-numéro!!", "isActive": True},
            format="json",
        )
        assert response.status_code == 400
        assert "phone" in response.json()["fieldErrors"]

    def test_an_invalid_email_is_rejected(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL,
            {"name": "Brasimba", "email": "pas-une-adresse", "isActive": True},
            format="json",
        )
        assert response.status_code == 400
        assert "email" in response.json()["fieldErrors"]

    def test_a_supplier_can_be_deactivated(self, auth_client, manager):
        supplier = SupplierFactory(is_active=True)
        response = auth_client(manager).patch(
            detail_url(supplier), {"isActive": False}, format="json"
        )
        assert response.status_code == 200
        supplier.refresh_from_db()
        assert supplier.is_active is False


class TestDelete:
    def test_an_owner_can_delete_an_unused_supplier(self, auth_client, owner):
        supplier = SupplierFactory()
        assert auth_client(owner).delete(detail_url(supplier)).status_code == 204
        assert Supplier.objects.count() == 0

    def test_a_supplier_with_articles_is_409(self, auth_client, owner):
        supplier = SupplierFactory()
        ArticleFactory(supplier=supplier)
        ArticleFactory(supplier=supplier)

        response = auth_client(owner).delete(detail_url(supplier))

        assert response.status_code == 409
        assert response.json()["code"] == "conflict"
        assert response.json()["message"] == (
            "Ce fournisseur est lié à 2 articles et ne peut pas être supprimé."
        )

    def test_the_message_is_singular_for_one_article(self, auth_client, owner):
        supplier = SupplierFactory()
        ArticleFactory(supplier=supplier)
        response = auth_client(owner).delete(detail_url(supplier))
        assert response.json()["message"] == (
            "Ce fournisseur est lié à 1 article et ne peut pas être supprimé."
        )


class TestPermissions:
    @pytest.mark.parametrize("method", ["post", "patch", "delete"])
    def test_a_cashier_may_not_write(self, auth_client, cashier, method):
        supplier = SupplierFactory()
        client = auth_client(cashier)
        url = LIST_URL if method == "post" else detail_url(supplier)
        response = getattr(client, method)(url, {"name": "X"}, format="json")
        assert response.status_code == 403

    def test_a_manager_may_not_delete(self, auth_client, manager):
        supplier = SupplierFactory()
        assert auth_client(manager).delete(detail_url(supplier)).status_code == 403
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/catalogue/tests/test_suppliers.py -v`
Expected: FAIL — 404, no route registered.

- [ ] **Step 3: Add the serializer**

Append to `apps/catalogue/serializers.py`:

```python
import re

from apps.catalogue.models import Supplier

PHONE_PATTERN = re.compile(r"^[\d\s+().-]{6,20}$")


class SupplierSerializer(serializers.ModelSerializer):
    """The frontend's `Supplier`. Validation mirrors
    `features/suppliers/schema.ts`."""

    contact_name = serializers.CharField(
        max_length=80, required=False, allow_blank=True, allow_null=True
    )
    email = serializers.EmailField(
        required=False, allow_blank=True, allow_null=True
    )
    phone = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )
    address = serializers.CharField(
        max_length=200, required=False, allow_blank=True, allow_null=True
    )
    notes = serializers.CharField(
        max_length=500, required=False, allow_blank=True, allow_null=True
    )

    OPTIONAL_FIELDS = ("contact_name", "email", "phone", "address", "notes")

    class Meta:
        model = Supplier
        fields = [
            "id",
            "name",
            "contact_name",
            "email",
            "phone",
            "address",
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
        existing = Supplier.objects.filter(name__iexact=name)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError(_("Un fournisseur porte déjà ce nom."))
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

- [ ] **Step 4: Add the viewset**

Append to `apps/catalogue/views.py`:

```python
from apps.catalogue.models import Supplier
from apps.catalogue.serializers import SupplierSerializer


class SupplierViewSet(CatalogueViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    search_fields = ["name", "contact_name", "email", "phone"]
    ordering_fields = ["name", "created_at"]
    ordering = ["name"]

    def perform_destroy(self, instance):
        used = instance.articles.count()
        if used:
            raise Conflict(
                _(
                    "Ce fournisseur est lié à %(count)d article%(plural)s "
                    "et ne peut pas être supprimé."
                )
                % {"count": used, "plural": "s" if used > 1 else ""}
            )
        instance.delete()
```

Register it in `apps/catalogue/urls.py`:

```python
router.register("suppliers", SupplierViewSet, basename="supplier")
```

(and add `SupplierViewSet` to the import.)

- [ ] **Step 5: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/catalogue/tests/test_suppliers.py -v`
Expected: all PASS.

- [ ] **Step 6: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -q
git add apps/catalogue
git commit -m "Add the supplier endpoints"
```

---

## Task 7: The article read path

**Files:**
- Create: `apps/catalogue/querysets.py`, `apps/catalogue/filters.py`
- Modify: `apps/catalogue/serializers.py`, `apps/catalogue/views.py`, `apps/catalogue/urls.py`
- Test: `apps/catalogue/tests/test_articles_read.py`

**Interfaces:**
- Consumes: `apps.stock.models.StockLevel`, `apps.accounts.models.Site.objects.current()`, `apps.common.filters.StrictBooleanFilter`, `AliasedOrderingFilter`.
- Produces:
  - `apps.catalogue.querysets.article_queryset() -> QuerySet[Article]` — select_related + `stock_quantity` / `stock_threshold` annotations. Task 11 reuses it.
  - `apps.catalogue.serializers.ArticleRefSerializer` (`id`, `sku`, `name`, `unit`) — Task 10 imports this.
  - `apps.catalogue.serializers.StockSummarySerializer`, `ArticleSerializer`.
  - `apps.catalogue.filters.ArticleFilterSet`.

**This task is where `apps.catalogue` imports `apps.stock`.** That is the one direction the spec forbids — so `article_queryset()` imports `StockLevel` *inside the function body*, not at module scope. Django resolves it fine either way at runtime, but a module-level import here makes the cycle real the moment `apps.stock.serializers` imports `ArticleRefSerializer` in Task 10.

- [ ] **Step 1: Write the failing tests**

Create `apps/catalogue/tests/test_articles_read.py`:

```python
"""Article reads: payload, filters, ordering, and query counts."""

import pytest

from apps.catalogue.tests.factories import (
    ArticleFactory,
    CategoryFactory,
    SupplierFactory,
)
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db

LIST_URL = "/api/articles/"


def detail_url(article) -> str:
    return f"{LIST_URL}{article.id}/"


class TestPayload:
    def test_matches_the_frontend_article_type(self, auth_client, cashier, site):
        category = CategoryFactory(name="Boissons")
        supplier = SupplierFactory(name="Brasimba")
        article = ArticleFactory(category=category, supplier=supplier)
        StockLevelFactory(article=article, site=site, quantity=5, reorder_threshold=10)

        response = auth_client(cashier).get(LIST_URL)

        assert response.status_code == 200
        row = response.json()["results"][0]
        assert set(row) == {
            "id", "sku", "barcode", "name", "description",
            "categoryId", "category", "supplierId", "supplier",
            "unit", "purchasePrice", "salePrice", "vatRate",
            "isActive", "imageUrl", "stock", "createdAt", "updatedAt",
        }
        assert set(row["category"]) == {"id", "name"}
        assert set(row["supplier"]) == {"id", "name"}
        assert set(row["stock"]) == {
            "siteId", "quantity", "reorderThreshold", "status"
        }
        assert row["category"]["name"] == "Boissons"
        assert row["supplier"]["name"] == "Brasimba"
        assert row["stock"]["quantity"] == 5
        assert row["stock"]["reorderThreshold"] == 10
        assert row["stock"]["status"] == "LOW"

    def test_vat_rate_is_a_number_not_a_string(self, auth_client, cashier, site):
        """`COERCE_DECIMAL_TO_STRING = False`.

        DRF's default renders a DecimalField as "16.00", and the frontend's
        `vatRate: number` then renders NaN in the article form.
        """
        from decimal import Decimal

        ArticleFactory(vat_rate=Decimal("16.00"))
        row = auth_client(cashier).get(LIST_URL).json()["results"][0]
        assert isinstance(row["vatRate"], float)
        assert row["vatRate"] == 16.0

    def test_a_null_supplier_serialises_as_null(self, auth_client, cashier, site):
        ArticleFactory(supplier=None)
        row = auth_client(cashier).get(LIST_URL).json()["results"][0]
        assert row["supplier"] is None
        assert row["supplierId"] is None

    def test_an_article_with_no_level_reads_as_zero(self, auth_client, cashier, site):
        """Coalesced to 0, not omitted. The frontend's `composeArticles` does
        the same with `level?.quantity ?? 0`."""
        ArticleFactory()
        row = auth_client(cashier).get(LIST_URL).json()["results"][0]
        assert row["stock"]["quantity"] == 0
        assert row["stock"]["status"] == "OUT_OF_STOCK"

    def test_site_id_is_the_current_site(self, auth_client, cashier, site):
        ArticleFactory()
        row = auth_client(cashier).get(LIST_URL).json()["results"][0]
        assert row["stock"]["siteId"] == str(site.id)


class TestFilters:
    def test_by_category(self, auth_client, cashier, site):
        wanted = CategoryFactory()
        ArticleFactory(category=wanted)
        ArticleFactory(category=CategoryFactory())

        response = auth_client(cashier).get(f"{LIST_URL}?categoryId={wanted.id}")
        assert response.json()["count"] == 1

    def test_by_supplier(self, auth_client, cashier, site):
        wanted = SupplierFactory()
        ArticleFactory(supplier=wanted)
        ArticleFactory(supplier=None)

        response = auth_client(cashier).get(f"{LIST_URL}?supplierId={wanted.id}")
        assert response.json()["count"] == 1

    def test_by_is_active(self, auth_client, cashier, site):
        ArticleFactory(is_active=True)
        ArticleFactory(is_active=False)
        client = auth_client(cashier)

        assert client.get(f"{LIST_URL}?isActive=true").json()["count"] == 1
        assert client.get(f"{LIST_URL}?isActive=false").json()["count"] == 1

    @pytest.mark.parametrize(
        ("quantity", "threshold", "status"),
        [(0, 10, "OUT_OF_STOCK"), (5, 10, "LOW"), (50, 10, "IN_STOCK")],
    )
    def test_by_stock_status(self, auth_client, cashier, site, quantity, threshold, status):
        for q, t in [(0, 10), (5, 10), (50, 10)]:
            article = ArticleFactory()
            StockLevelFactory(
                article=article, site=site, quantity=q, reorder_threshold=t
            )

        response = auth_client(cashier).get(f"{LIST_URL}?stockStatus={status}")

        assert response.json()["count"] == 1
        assert response.json()["results"][0]["stock"]["status"] == status

    def test_search_covers_name_sku_and_barcode(self, auth_client, cashier, site):
        ArticleFactory(name="Sucre blanc", sku="EPI-001", barcode="1234567890123")
        ArticleFactory(name="Farine", sku="EPI-002", barcode="9876543210987")
        client = auth_client(cashier)

        assert client.get(f"{LIST_URL}?search=sucre").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=EPI-002").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=1234567890123").json()["count"] == 1

    @pytest.mark.parametrize(
        ("param", "value"),
        [
            ("isActive", "banana"),
            ("stockStatus", "LOW_ISH"),
            ("categoryId", "not-a-uuid"),
        ],
    )
    def test_an_invalid_filter_value_is_400(self, auth_client, cashier, site, param, value):
        """A dropped filter returns *more* rows than asked for while looking
        like a correct response. That is why these must error."""
        response = auth_client(cashier).get(f"{LIST_URL}?{param}={value}")

        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"
        assert param in response.json()["fieldErrors"]


class TestOrdering:
    def test_default_is_by_name(self, auth_client, cashier, site):
        ArticleFactory(name="Sucre")
        ArticleFactory(name="Farine")
        response = auth_client(cashier).get(LIST_URL)
        assert [r["name"] for r in response.json()["results"]] == ["Farine", "Sucre"]

    @pytest.mark.parametrize("key", ["name", "sku", "createdAt", "salePrice"])
    def test_each_key_sorts_both_ways(self, auth_client, cashier, site, key):
        ArticleFactory(name="Aaa", sku="AAA-1", sale_price=100)
        ArticleFactory(name="Zzz", sku="ZZZ-9", sale_price=900)
        client = auth_client(cashier)

        ascending = client.get(f"{LIST_URL}?ordering={key}").json()["results"]
        descending = client.get(f"{LIST_URL}?ordering=-{key}").json()["results"]

        assert [r["id"] for r in ascending] == [r["id"] for r in descending][::-1]

    def test_ordering_by_stock_uses_the_annotation(self, auth_client, cashier, site):
        """`stock` is the public sort key; `stock_quantity` is the annotation.
        DRF cannot express that mapping, which is why AliasedOrderingFilter
        exists."""
        low = ArticleFactory(name="Peu")
        high = ArticleFactory(name="Beaucoup")
        StockLevelFactory(article=low, site=site, quantity=1)
        StockLevelFactory(article=high, site=site, quantity=99)

        response = auth_client(cashier).get(f"{LIST_URL}?ordering=stock")

        assert [r["name"] for r in response.json()["results"]] == ["Peu", "Beaucoup"]

    def test_camel_case_ordering_is_translated(self, auth_client, cashier, site):
        ArticleFactory(name="Aaa")
        ArticleFactory(name="Zzz")
        response = auth_client(cashier).get(f"{LIST_URL}?ordering=-createdAt")
        assert response.status_code == 200
        assert [r["name"] for r in response.json()["results"]] == ["Zzz", "Aaa"]

    def test_an_unknown_ordering_key_is_400(self, auth_client, cashier, site):
        """DRF drops it silently and falls back to the default. We do not."""
        response = auth_client(cashier).get(f"{LIST_URL}?ordering=couleur")
        assert response.status_code == 400
        assert "ordering" in response.json()["fieldErrors"]


class TestQueryCount:
    def test_the_list_does_not_scale_with_page_size(
        self, auth_client, cashier, site, django_assert_num_queries
    ):
        """Guards the annotation approach. Composing `stock` from the related
        object instead would issue one extra query per row, and nothing else
        in the suite would notice."""
        for _ in range(10):
            article = ArticleFactory(supplier=SupplierFactory())
            StockLevelFactory(article=article, site=site, quantity=5)

        client = auth_client(cashier)
        client.get(LIST_URL)  # warm any lazily-cached state

        with django_assert_num_queries(4):
            # 1 session/user, 1 site, 1 count, 1 page
            response = client.get(f"{LIST_URL}?pageSize=10")

        assert len(response.json()["results"]) == 10
```

> The `django_assert_num_queries(4)` bound is a starting estimate. Run it,
> read the actual number, and if it differs but does **not** grow when you
> change `pageSize=10` to `pageSize=20` with 20 articles, update the constant
> to the observed value. If it *does* grow with page size, the annotation is
> not being used — fix that, do not raise the bound.

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/catalogue/tests/test_articles_read.py -v`
Expected: FAIL — 404, no route registered.

- [ ] **Step 3: Write the queryset**

Create `apps/catalogue/querysets.py`:

```python
"""The annotated article queryset.

`?stockStatus=` and `ordering=stock` both need the quantity in SQL, and the
serializer needs it in the payload. Doing it once as an annotation serves all
three and keeps the query count flat; composing `stock` from the related
object instead costs one query per row.
"""

from django.db.models import IntegerField, OuterRef, QuerySet, Subquery
from django.db.models.functions import Coalesce

from apps.accounts.models import Site
from apps.catalogue.models import Article


def article_queryset() -> QuerySet[Article]:
    # Imported inside the function on purpose. `apps.stock` imports from
    # `apps.catalogue` — a module-level import here would close that cycle
    # the moment apps/stock/serializers.py imports ArticleRefSerializer.
    from apps.stock.models import StockLevel

    site = Site.objects.current()
    levels = StockLevel.objects.filter(article=OuterRef("pk"), site=site)

    return (
        Article.objects.select_related("category", "supplier")
        .annotate(
            stock_quantity=Coalesce(
                Subquery(levels.values("quantity")[:1]),
                0,
                output_field=IntegerField(),
            ),
            stock_threshold=Coalesce(
                Subquery(levels.values("reorder_threshold")[:1]),
                0,
                output_field=IntegerField(),
            ),
        )
    )
```

- [ ] **Step 4: Write the serializers**

Append to `apps/catalogue/serializers.py`:

```python
from apps.accounts.models import Site
from apps.catalogue.models import Article


class CategoryRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]


class SupplierRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name"]


class ArticleRefSerializer(serializers.ModelSerializer):
    """The frontend's `ArticleRef`.

    Lives here rather than in `apps.stock` so the movement serializer can
    import it without closing an import cycle.
    """

    class Meta:
        model = Article
        fields = ["id", "sku", "name", "unit"]


class StockSummarySerializer(serializers.Serializer):
    """The frontend's `StockSummary`, built from the queryset annotations
    rather than from the related StockLevel row."""

    site_id = serializers.SerializerMethodField()
    quantity = serializers.IntegerField(source="stock_quantity", read_only=True)
    reorder_threshold = serializers.IntegerField(
        source="stock_threshold", read_only=True
    )
    status = serializers.SerializerMethodField()

    def get_site_id(self, obj) -> str:
        return str(self.context["site"].id)

    def get_status(self, obj) -> str:
        # The same three inclusive comparisons as StockLevel.status and as
        # ArticleFilterSet's SQL. Three copies is two too many; they are kept
        # in step by the tests, which assert the same boundaries in each.
        if obj.stock_quantity <= 0:
            return "OUT_OF_STOCK"
        if obj.stock_quantity <= obj.stock_threshold:
            return "LOW"
        return "IN_STOCK"


class ArticleSerializer(serializers.ModelSerializer):
    """The frontend's `Article`."""

    category = CategoryRefSerializer(read_only=True)
    supplier = SupplierRefSerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        source="category", queryset=Category.objects.all(), write_only=False
    )
    supplier_id = serializers.PrimaryKeyRelatedField(
        source="supplier",
        queryset=Supplier.objects.all(),
        allow_null=True,
        required=False,
    )
    stock = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = [
            "id", "sku", "barcode", "name", "description",
            "category_id", "category", "supplier_id", "supplier",
            "unit", "purchase_price", "sale_price", "vat_rate",
            "is_active", "image_url", "stock", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "image_url", "created_at", "updated_at"]

    def get_stock(self, obj):
        return StockSummarySerializer(obj, context=self.context).data
```

> `category_id` / `supplier_id` use `PrimaryKeyRelatedField(source=...)` so the
> wire name is the frontend's `categoryId` while the model attribute stays
> `category`. Verify in Step 6 that the **read** payload emits `categoryId` as a
> plain UUID string and `category` as the nested ref — if `categoryId` comes
> back as an object, the `source` wiring is wrong.

- [ ] **Step 5: Write the filterset and viewset**

Create `apps/catalogue/filters.py`:

```python
from django.db.models import F, Q
from django_filters import rest_framework as drf_filters

from apps.catalogue.models import Article
from apps.common.filters import StrictBooleanFilter

STOCK_STATUS_CHOICES = [
    ("IN_STOCK", "IN_STOCK"),
    ("LOW", "LOW"),
    ("OUT_OF_STOCK", "OUT_OF_STOCK"),
]


class ArticleFilterSet(drf_filters.FilterSet):
    category_id = drf_filters.UUIDFilter(field_name="category_id")
    supplier_id = drf_filters.UUIDFilter(field_name="supplier_id")
    is_active = StrictBooleanFilter()
    stock_status = drf_filters.ChoiceFilter(
        choices=STOCK_STATUS_CHOICES, method="filter_stock_status"
    )

    class Meta:
        model = Article
        fields = ["category_id", "supplier_id", "is_active", "stock_status"]

    def filter_stock_status(self, queryset, name, value):
        # The same three inclusive boundaries as StockLevel.status, in SQL.
        if value == "OUT_OF_STOCK":
            return queryset.filter(stock_quantity__lte=0)
        if value == "LOW":
            return queryset.filter(
                stock_quantity__gt=0, stock_quantity__lte=F("stock_threshold")
            )
        return queryset.filter(
            Q(stock_quantity__gt=0) & Q(stock_quantity__gt=F("stock_threshold"))
        )
```

Append to `apps/catalogue/views.py`:

```python
from apps.accounts.models import Site
from apps.catalogue.filters import ArticleFilterSet
from apps.catalogue.querysets import article_queryset
from apps.catalogue.serializers import ArticleSerializer


class ArticleViewSet(CatalogueViewSet):
    serializer_class = ArticleSerializer
    filterset_class = ArticleFilterSet
    search_fields = ["name", "sku", "barcode"]
    ordering_fields = ["name", "sku", "created_at", "sale_price"]
    ordering_aliases = {"stock": "stock_quantity"}
    ordering = ["name"]

    def get_queryset(self):
        return article_queryset()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["site"] = Site.objects.current()
        return context
```

Register it in `apps/catalogue/urls.py`:

```python
router.register("articles", ArticleViewSet, basename="article")
```

- [ ] **Step 6: Run the read tests**

Run: `~/.pyenv/versions/stock/bin/pytest apps/catalogue/tests/test_articles_read.py -v`

Work through the failures one at a time. The likely ones:
- `categoryId` rendering as an object → the `source=` wiring in Step 4.
- `vatRate` coming back as a string → `COERCE_DECIMAL_TO_STRING` did not land in Task 1.
- the query-count assertion → adjust the constant per the note, but only after confirming it does not grow with page size.

- [ ] **Step 7: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -q
git add apps/catalogue
git commit -m "Add the article read endpoints with annotated stock"
```

---

## Task 8: The article write path

**Files:**
- Modify: `apps/catalogue/serializers.py`, `apps/catalogue/views.py`
- Test: `apps/catalogue/tests/test_articles_write.py`

**Interfaces:**
- Consumes: `apps.stock.models.StockLevel`, `StockMovement`, `apps.catalogue.serializers.ArticleSerializer`.
- Produces: `ArticleSerializer.create` / `.update` handling `initial_quantity` and `reorder_threshold`.

`ArticleCreateDto` carries `initialQuantity` and `reorderThreshold`, which are not `Article` columns. Creation writes three rows in one transaction so a level can never exist without a matching ledger entry. `ArticleUpdateDto` omits `initialQuantity` by design — once an article exists, stock changes only through movements.

- [ ] **Step 1: Write the failing tests**

Create `apps/catalogue/tests/test_articles_write.py`:

```python
"""Article writes: creation side effects, validation, delete guard."""

import pytest

from apps.catalogue.models import Article
from apps.catalogue.tests.factories import (
    ArticleFactory,
    CategoryFactory,
    SupplierFactory,
)
from apps.stock.models import StockLevel, StockMovement
from apps.stock.tests.factories import StockMovementFactory

pytestmark = pytest.mark.django_db

LIST_URL = "/api/articles/"


def detail_url(article) -> str:
    return f"{LIST_URL}{article.id}/"


def payload(category, **overrides):
    body = {
        "sku": "EPI-001",
        "barcode": None,
        "name": "Sucre blanc",
        "description": "Sac de 1 kg.",
        "categoryId": str(category.id),
        "supplierId": None,
        "unit": "KG",
        "purchasePrice": 1000,
        "salePrice": 1500,
        "vatRate": 16,
        "isActive": True,
        "initialQuantity": 0,
        "reorderThreshold": 10,
    }
    body.update(overrides)
    return body


class TestCreate:
    def test_a_manager_can_create(self, auth_client, manager, site):
        category = CategoryFactory()
        response = auth_client(manager).post(
            LIST_URL, payload(category), format="json"
        )

        assert response.status_code == 201
        assert response.json()["sku"] == "EPI-001"
        assert response.json()["stock"]["reorderThreshold"] == 10

    def test_a_stock_level_is_written(self, auth_client, manager, site):
        category = CategoryFactory()
        auth_client(manager).post(
            LIST_URL, payload(category, reorderThreshold=25), format="json"
        )

        level = StockLevel.objects.get()
        assert level.site == site
        assert level.quantity == 0
        assert level.reorder_threshold == 25

    def test_no_opening_movement_when_initial_quantity_is_zero(
        self, auth_client, manager, site
    ):
        category = CategoryFactory()
        auth_client(manager).post(
            LIST_URL, payload(category, initialQuantity=0), format="json"
        )
        assert StockMovement.objects.count() == 0

    def test_an_opening_movement_is_written(self, auth_client, manager, site):
        category = CategoryFactory()
        response = auth_client(manager).post(
            LIST_URL,
            payload(category, initialQuantity=40, purchasePrice=1200),
            format="json",
        )

        assert response.json()["stock"]["quantity"] == 40

        movement = StockMovement.objects.get()
        assert movement.type == "IN"
        assert movement.reason == "PURCHASE"
        assert movement.quantity == 40
        assert movement.quantity_before == 0
        assert movement.quantity_after == 40
        assert movement.unit_cost == 1200
        assert movement.note == "Stock initial"
        assert movement.user == manager
        assert movement.user_name == manager.full_name

    def test_creation_is_atomic(self, auth_client, manager, site):
        """If the movement write fails the article must not survive."""
        from unittest import mock

        category = CategoryFactory()
        with mock.patch(
            "apps.stock.models.StockMovement.objects.create",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError):
                auth_client(manager).post(
                    LIST_URL, payload(category, initialQuantity=5), format="json"
                )

        assert Article.objects.count() == 0
        assert StockLevel.objects.count() == 0


class TestValidation:
    def test_a_duplicate_sku_is_rejected_case_insensitively(
        self, auth_client, manager, site
    ):
        category = CategoryFactory()
        ArticleFactory(sku="EPI-001")
        response = auth_client(manager).post(
            LIST_URL, payload(category, sku="epi-001"), format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["sku"] == [
            "Cette référence est déjà utilisée."
        ]

    def test_a_duplicate_barcode_is_rejected(self, auth_client, manager, site):
        category = CategoryFactory()
        ArticleFactory(barcode="1234567890123")
        response = auth_client(manager).post(
            LIST_URL, payload(category, barcode="1234567890123"), format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["barcode"] == [
            "Ce code-barres est déjà utilisé."
        ]

    @pytest.mark.parametrize("barcode", ["123", "12345678901234", "abcdefgh"])
    def test_a_malformed_barcode_is_rejected(self, auth_client, manager, site, barcode):
        category = CategoryFactory()
        response = auth_client(manager).post(
            LIST_URL, payload(category, barcode=barcode), format="json"
        )
        assert response.status_code == 400
        assert "barcode" in response.json()["fieldErrors"]

    @pytest.mark.parametrize("barcode", ["12345678", "1234567890123"])
    def test_eight_and_thirteen_digit_barcodes_are_accepted(
        self, auth_client, manager, site, barcode
    ):
        category = CategoryFactory()
        response = auth_client(manager).post(
            LIST_URL, payload(category, barcode=barcode), format="json"
        )
        assert response.status_code == 201

    def test_an_empty_barcode_is_stored_as_null(self, auth_client, manager, site):
        category = CategoryFactory()
        auth_client(manager).post(LIST_URL, payload(category, barcode=""), format="json")
        assert Article.objects.get().barcode is None

    def test_a_sale_price_below_the_purchase_price_is_rejected(
        self, auth_client, manager, site
    ):
        category = CategoryFactory()
        response = auth_client(manager).post(
            LIST_URL,
            payload(category, purchasePrice=2000, salePrice=1500),
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["salePrice"] == [
            "Le prix de vente doit être supérieur ou égal au prix d'achat."
        ]

    def test_equal_prices_are_accepted(self, auth_client, manager, site):
        category = CategoryFactory()
        response = auth_client(manager).post(
            LIST_URL,
            payload(category, purchasePrice=1500, salePrice=1500),
            format="json",
        )
        assert response.status_code == 201

    @pytest.mark.parametrize("rate", [-1, 101])
    def test_an_out_of_range_vat_rate_is_rejected(self, auth_client, manager, site, rate):
        category = CategoryFactory()
        response = auth_client(manager).post(
            LIST_URL, payload(category, vatRate=rate), format="json"
        )
        assert response.status_code == 400
        assert "vatRate" in response.json()["fieldErrors"]

    def test_a_decimal_vat_rate_is_accepted(self, auth_client, manager, site):
        category = CategoryFactory()
        response = auth_client(manager).post(
            LIST_URL, payload(category, vatRate=5.5), format="json"
        )
        assert response.status_code == 201
        assert response.json()["vatRate"] == 5.5


class TestUpdate:
    def test_the_reorder_threshold_is_editable(self, auth_client, manager, site):
        from apps.stock.tests.factories import StockLevelFactory

        article = ArticleFactory()
        StockLevelFactory(
            article=article, site=site, quantity=30, reorder_threshold=5
        )

        response = auth_client(manager).patch(
            detail_url(article), {"reorderThreshold": 50}, format="json"
        )

        assert response.status_code == 200
        assert response.json()["stock"]["reorderThreshold"] == 50
        assert response.json()["stock"]["quantity"] == 30

    def test_updating_the_threshold_does_not_touch_the_quantity(
        self, auth_client, manager, site
    ):
        from apps.stock.tests.factories import StockLevelFactory

        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=30)
        auth_client(manager).patch(
            detail_url(article), {"reorderThreshold": 50}, format="json"
        )
        assert StockLevel.objects.get().quantity == 30

    def test_initial_quantity_is_ignored_on_update(self, auth_client, manager, site):
        """Once an article exists, stock changes only through movements."""
        from apps.stock.tests.factories import StockLevelFactory

        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=30)

        auth_client(manager).patch(
            detail_url(article), {"initialQuantity": 999}, format="json"
        )

        assert StockLevel.objects.get().quantity == 30
        assert StockMovement.objects.count() == 0

    def test_an_article_can_be_archived(self, auth_client, manager, site):
        """The frontend's `archiveArticle` is exactly this PATCH."""
        article = ArticleFactory(is_active=True)
        response = auth_client(manager).patch(
            detail_url(article), {"isActive": False}, format="json"
        )
        assert response.status_code == 200
        article.refresh_from_db()
        assert article.is_active is False


class TestDelete:
    def test_an_owner_can_delete_an_article_with_no_movements(
        self, auth_client, owner, site
    ):
        from apps.stock.tests.factories import StockLevelFactory

        article = ArticleFactory()
        StockLevelFactory(article=article, site=site)

        response = auth_client(owner).delete(detail_url(article))

        assert response.status_code == 204
        assert Article.objects.count() == 0
        assert StockLevel.objects.count() == 0

    def test_an_article_with_movements_is_409(self, auth_client, owner, site):
        article = ArticleFactory()
        StockMovementFactory(article=article, site=site, user=owner)

        response = auth_client(owner).delete(detail_url(article))

        assert response.status_code == 409
        assert response.json()["code"] == "conflict"
        assert response.json()["message"] == (
            "Cet article possède un historique de mouvements et ne peut pas "
            "être supprimé. Vous pouvez l'archiver."
        )

    def test_an_article_created_with_opening_stock_can_never_be_deleted(
        self, auth_client, owner, manager, site
    ):
        """Inherited from the frontend, which behaves identically. Worth a
        test so nobody 'fixes' it later without deciding to."""
        category = CategoryFactory()
        created = auth_client(manager).post(
            LIST_URL, payload(category, initialQuantity=10), format="json"
        )

        response = auth_client(owner).delete(f"{LIST_URL}{created.json()['id']}/")

        assert response.status_code == 409
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/catalogue/tests/test_articles_write.py -v`
Expected: most FAIL — `initialQuantity` and `reorderThreshold` are not serializer fields yet.

- [ ] **Step 3: Extend `ArticleSerializer`**

In `apps/catalogue/serializers.py`, add to `ArticleSerializer` — the write-only virtual fields, the validators, and the two overrides:

```python
    initial_quantity = serializers.IntegerField(
        min_value=0, write_only=True, required=False, default=0
    )
    reorder_threshold = serializers.IntegerField(
        min_value=0, write_only=True, required=False
    )
    barcode = serializers.CharField(
        max_length=13, required=False, allow_blank=True, allow_null=True
    )
    description = serializers.CharField(
        max_length=500, required=False, allow_blank=True, allow_null=True
    )
    vat_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=100
    )
```

Add `"initial_quantity"` and `"reorder_threshold"` to `Meta.fields`.

Then the validation:

```python
    BARCODE_PATTERN = re.compile(r"^\d{8}$|^\d{13}$")

    def validate_sku(self, value):
        sku = value.strip()
        if not sku:
            raise serializers.ValidationError(_("La référence est obligatoire."))
        if len(sku) > 32:
            raise serializers.ValidationError(
                _("La référence ne peut pas dépasser 32 caractères.")
            )
        existing = Article.objects.filter(sku__iexact=sku)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError(_("Cette référence est déjà utilisée."))
        return sku

    def validate_barcode(self, value):
        if not value or not value.strip():
            return None
        barcode = value.strip()
        if not self.BARCODE_PATTERN.match(barcode):
            raise serializers.ValidationError(
                _("Le code-barres doit contenir 8 ou 13 chiffres.")
            )
        existing = Article.objects.filter(barcode=barcode)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError(_("Ce code-barres est déjà utilisé."))
        return barcode

    def validate_name(self, value):
        name = value.strip()
        if len(name) < 2:
            raise serializers.ValidationError(
                _("Le nom doit contenir au moins 2 caractères.")
            )
        return name

    def validate(self, attrs):
        if "description" in attrs:
            value = attrs["description"]
            attrs["description"] = value.strip() or None if value else None

        # Mirrors the frontend's cross-field refine. Resolved against the
        # instance on a PATCH that sends only one of the two.
        purchase = attrs.get(
            "purchase_price",
            self.instance.purchase_price if self.instance else 0,
        )
        sale = attrs.get(
            "sale_price", self.instance.sale_price if self.instance else 0
        )
        if sale < purchase:
            raise serializers.ValidationError(
                {
                    "sale_price": [
                        _(
                            "Le prix de vente doit être supérieur ou égal au "
                            "prix d'achat."
                        )
                    ]
                }
            )
        return attrs
```

And the two overrides:

```python
    @transaction.atomic
    def create(self, validated_data):
        from apps.stock.models import StockLevel, StockMovement

        initial_quantity = validated_data.pop("initial_quantity", 0)
        reorder_threshold = validated_data.pop("reorder_threshold", 0)

        site = self.context["site"]
        article = Article.objects.create(**validated_data)
        StockLevel.objects.create(
            article=article,
            site=site,
            quantity=initial_quantity,
            reorder_threshold=reorder_threshold,
        )

        # The article, its level and its opening movement are written
        # together: a level without a matching ledger entry is a stock figure
        # nothing accounts for.
        if initial_quantity > 0:
            user = self.context["request"].user
            StockMovement.objects.create(
                article=article,
                site=site,
                type="IN",
                reason="PURCHASE",
                quantity=initial_quantity,
                quantity_before=0,
                quantity_after=initial_quantity,
                unit_cost=article.purchase_price,
                note="Stock initial",
                user=user,
                user_name=user.full_name,
            )
        return article

    @transaction.atomic
    def update(self, instance, validated_data):
        from apps.stock.models import StockLevel

        # Silently dropped, not rejected: `ArticleUpdateDto` omits it by
        # design, so a client sending it is sending a field that does not
        # exist rather than making an error worth reporting.
        validated_data.pop("initial_quantity", None)
        reorder_threshold = validated_data.pop("reorder_threshold", None)

        article = super().update(instance, validated_data)

        if reorder_threshold is not None:
            # Only the threshold. Quantity has exactly one writer.
            StockLevel.objects.filter(
                article=article, site=self.context["site"]
            ).update(reorder_threshold=reorder_threshold)
        return article
```

Add `from django.db import transaction` and `import re` to the module imports if not already present.

- [ ] **Step 4: Add the article delete guard**

In `apps/catalogue/views.py`, add to `ArticleViewSet`:

```python
    def perform_destroy(self, instance):
        if instance.movements.exists():
            raise Conflict(
                _(
                    "Cet article possède un historique de mouvements et ne "
                    "peut pas être supprimé. Vous pouvez l'archiver."
                )
            )
        instance.delete()
```

- [ ] **Step 5: Handle the serializer re-read**

`create()` returns a plain `Article` without the annotations the response
serializer needs, so `obj.stock_quantity` raises `AttributeError`. Add to
`ArticleViewSet`:

```python
    def perform_create(self, serializer):
        # Re-read through the annotated queryset. `create()` returns a bare
        # Article, which has no `stock_quantity` attribute, and the response
        # serializer's `stock` field would raise AttributeError on it.
        instance = serializer.save()
        serializer.instance = self.get_queryset().get(pk=instance.pk)

    def perform_update(self, serializer):
        instance = serializer.save()
        serializer.instance = self.get_queryset().get(pk=instance.pk)
```

- [ ] **Step 6: Run the write tests**

Run: `~/.pyenv/versions/stock/bin/pytest apps/catalogue/tests/test_articles_write.py -v`
Expected: all PASS.

- [ ] **Step 7: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -q
git add apps/catalogue
git commit -m "Add the article write path with opening stock"
```

---

## Task 9: `apply_movement`

**Files:**
- Create: `apps/stock/services.py`
- Test: `apps/stock/tests/test_apply_movement.py`

**Interfaces:**
- Consumes: `apps.stock.models.StockLevel`, `StockMovement`; `apps.accounts.models.Site`.
- Produces:

```python
def apply_movement(
    *,
    article: Article,
    site: Site,
    type: str,
    reason: str,
    quantity: int,
    user,
    unit_cost: int | None = None,
    reference: str | None = None,
    note: str | None = None,
    field_prefix: str = "",
) -> StockMovement
```

Raises `rest_framework.serializers.ValidationError` keyed `f"{field_prefix}quantity"`.

This is the **only** code that changes a quantity after article creation. Sub-project 3's transactions and sub-project 4's sales both post through it. `field_prefix` exists now so sub-project 3 can route a line's error to `lines.2.quantity` without reworking the signature under a caller.

- [ ] **Step 1: Write the failing tests**

Create `apps/stock/tests/test_apply_movement.py`:

```python
"""The single writer of a stock quantity.

Mirrors `applyMovementLine` in the frontend's services/stock.ts, including
the ADJUSTMENT semantics: `quantity` is the counted *target*, and the
movement records the delta that was applied.
"""

import pytest
from rest_framework.serializers import ValidationError

from apps.catalogue.tests.factories import ArticleFactory
from apps.stock.models import StockLevel, StockMovement
from apps.stock.services import apply_movement
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db


def post(article, site, user, **kwargs):
    defaults = {
        "article": article,
        "site": site,
        "type": "IN",
        "reason": "PURCHASE",
        "quantity": 10,
        "user": user,
    }
    defaults.update(kwargs)
    return apply_movement(**defaults)


class TestIn:
    def test_adds_to_the_level(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=5)

        movement = post(article, site, owner, type="IN", quantity=10)

        assert movement.quantity_before == 5
        assert movement.quantity_after == 15
        assert movement.quantity == 10
        assert StockLevel.objects.get().quantity == 15

    def test_creates_the_level_when_absent(self, site, owner):
        article = ArticleFactory()
        movement = post(article, site, owner, type="IN", quantity=7)

        assert movement.quantity_before == 0
        assert movement.quantity_after == 7
        assert StockLevel.objects.get(article=article).quantity == 7


class TestOut:
    def test_subtracts_from_the_level(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=20)

        movement = post(article, site, owner, type="OUT", reason="SALE", quantity=8)

        assert movement.quantity_before == 20
        assert movement.quantity_after == 12
        assert movement.quantity == 8
        assert StockLevel.objects.get().quantity == 12

    def test_may_empty_the_level_exactly(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=8)
        movement = post(article, site, owner, type="OUT", reason="SALE", quantity=8)
        assert movement.quantity_after == 0

    def test_refuses_to_go_negative(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=3)

        with pytest.raises(ValidationError) as exc:
            post(article, site, owner, type="OUT", reason="SALE", quantity=4)

        assert exc.value.detail["quantity"][0] == (
            "Stock insuffisant : 3 unité(s) disponible(s) actuellement."
        )

    def test_a_refused_movement_writes_nothing(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=3)

        with pytest.raises(ValidationError):
            post(article, site, owner, type="OUT", reason="SALE", quantity=4)

        assert StockMovement.objects.count() == 0
        assert StockLevel.objects.get().quantity == 3


class TestAdjustment:
    def test_quantity_is_the_counted_target_not_a_delta(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=20)

        movement = post(
            article, site, owner,
            type="ADJUSTMENT", reason="COUNT_CORRECTION", quantity=14,
        )

        assert movement.quantity_before == 20
        assert movement.quantity_after == 14
        assert movement.quantity == 6      # the delta that was applied
        assert StockLevel.objects.get().quantity == 14

    def test_adjusting_upward(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=5)

        movement = post(
            article, site, owner,
            type="ADJUSTMENT", reason="COUNT_CORRECTION", quantity=12,
        )

        assert movement.quantity_after == 12
        assert movement.quantity == 7

    def test_adjusting_to_zero_is_allowed(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=5)
        movement = post(
            article, site, owner,
            type="ADJUSTMENT", reason="COUNT_CORRECTION", quantity=0,
        )
        assert movement.quantity_after == 0
        assert movement.quantity == 5

    def test_an_unchanged_count_is_rejected(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=9)

        with pytest.raises(ValidationError) as exc:
            post(
                article, site, owner,
                type="ADJUSTMENT", reason="COUNT_CORRECTION", quantity=9,
            )

        assert exc.value.detail["quantity"][0] == (
            "La quantité comptée est identique au stock actuel."
        )


class TestFieldPrefix:
    def test_routes_the_error_to_a_line(self, site, owner):
        """Sub-project 3 posts several lines at once and needs the error to
        land on the right form row."""
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=1)

        with pytest.raises(ValidationError) as exc:
            post(
                article, site, owner,
                type="OUT", reason="SALE", quantity=5, field_prefix="lines.2.",
            )

        assert "lines.2.quantity" in exc.value.detail


class TestRecordedFields:
    def test_the_user_name_is_denormalised(self, site, owner):
        article = ArticleFactory()
        movement = post(article, site, owner)
        assert movement.user_name == owner.full_name

    def test_blank_reference_and_note_become_null(self, site, owner):
        article = ArticleFactory()
        movement = post(article, site, owner, reference="  ", note="")
        assert movement.reference is None
        assert movement.note is None

    def test_the_reference_and_note_are_trimmed(self, site, owner):
        article = ArticleFactory()
        movement = post(article, site, owner, reference="  BL-42 ", note=" Reçu ")
        assert movement.reference == "BL-42"
        assert movement.note == "Reçu"
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/stock/tests/test_apply_movement.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.stock.services'`.

- [ ] **Step 3: Implement it**

Create `apps/stock/services.py`:

```python
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

from apps.stock.models import StockLevel, StockMovement


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
    field_prefix: str = "",
) -> StockMovement:
    """Post one movement and update the level it applies to.

    `quantity` is a delta for IN and OUT, and the counted *target* for
    ADJUSTMENT — the recorded quantity is then the delta that was applied.

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
        StockLevel.objects.create(
            article=article, site=site, quantity=quantity_after
        )
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
        user=user,
        user_name=user.full_name,
    )
```

- [ ] **Step 4: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/stock/tests/test_apply_movement.py -v`
Expected: all PASS.

- [ ] **Step 5: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -q
git add apps/stock
git commit -m "Add apply_movement, the single writer of a stock quantity"
```

---

## Task 10: Movement endpoints

**Files:**
- Create: `apps/stock/serializers.py`, `apps/stock/filters.py`, `apps/stock/views.py`, `apps/stock/urls.py`
- Modify: `stockmanager/urls.py`
- Test: `apps/stock/tests/test_movements.py`

**Interfaces:**
- Consumes: `apps.stock.services.apply_movement`, `apps.catalogue.serializers.ArticleRefSerializer`, `apps.common.dates.start_of_day` / `end_of_day`, `apps.common.views.CatalogueViewSet`.
- Produces: `apps.stock.serializers.StockMovementSerializer`, `MovementCreateSerializer`; `apps.stock.filters.MovementFilterSet`.

- [ ] **Step 1: Write the failing tests**

Create `apps/stock/tests/test_movements.py`:

```python
"""Movement endpoints."""

from datetime import datetime, timezone as dt_timezone

import pytest
from django.test import override_settings

from apps.catalogue.tests.factories import ArticleFactory
from apps.stock.models import StockLevel, StockMovement
from apps.stock.tests.factories import StockLevelFactory, StockMovementFactory

pytestmark = pytest.mark.django_db

URL = "/api/stock/movements/"


class TestCreate:
    def test_a_manager_can_post_an_in_movement(self, auth_client, manager, site):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=5)

        response = auth_client(manager).post(
            URL,
            {
                "articleId": str(article.id),
                "type": "IN",
                "reason": "PURCHASE",
                "quantity": 10,
                "unitCost": 1200,
                "reference": "BL-42",
                "note": "Livraison du matin",
            },
            format="json",
        )

        assert response.status_code == 201
        assert response.json()["quantityBefore"] == 5
        assert response.json()["quantityAfter"] == 15
        assert StockLevel.objects.get().quantity == 15

    def test_the_payload_matches_the_frontend_type(self, auth_client, manager, site):
        article = ArticleFactory()
        response = auth_client(manager).post(
            URL,
            {
                "articleId": str(article.id),
                "type": "IN",
                "reason": "PURCHASE",
                "quantity": 3,
                "unitCost": None,
                "reference": None,
                "note": None,
            },
            format="json",
        )

        assert set(response.json()) == {
            "id", "articleId", "article", "siteId", "type", "reason",
            "quantity", "quantityBefore", "quantityAfter", "unitCost",
            "reference", "note", "transactionId", "saleId",
            "userId", "userName", "createdAt",
        }
        assert set(response.json()["article"]) == {"id", "sku", "name", "unit"}

    def test_transaction_id_and_sale_id_are_null(self, auth_client, manager, site):
        """No columns yet — sub-projects 3 and 4 add them. The keys must still
        be present, because the frontend's StockMovement type requires them."""
        article = ArticleFactory()
        response = auth_client(manager).post(
            URL,
            {"articleId": str(article.id), "type": "IN", "reason": "PURCHASE",
             "quantity": 1},
            format="json",
        )
        assert response.json()["transactionId"] is None
        assert response.json()["saleId"] is None

    def test_insufficient_stock_is_400_on_quantity(self, auth_client, manager, site):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=2)

        response = auth_client(manager).post(
            URL,
            {"articleId": str(article.id), "type": "OUT", "reason": "SALE",
             "quantity": 5},
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["quantity"] == [
            "Stock insuffisant : 2 unité(s) disponible(s) actuellement."
        ]

    def test_a_negative_quantity_is_rejected(self, auth_client, manager, site):
        article = ArticleFactory()
        response = auth_client(manager).post(
            URL,
            {"articleId": str(article.id), "type": "IN", "reason": "PURCHASE",
             "quantity": -1},
            format="json",
        )
        assert response.status_code == 400
        assert "quantity" in response.json()["fieldErrors"]

    def test_zero_is_rejected_for_in_and_out(self, auth_client, manager, site):
        article = ArticleFactory()
        response = auth_client(manager).post(
            URL,
            {"articleId": str(article.id), "type": "IN", "reason": "PURCHASE",
             "quantity": 0},
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["quantity"] == [
            "La quantité doit être supérieure à zéro."
        ]

    def test_zero_is_allowed_for_an_adjustment(self, auth_client, manager, site):
        """Counting a shelf and finding it empty is a legitimate adjustment."""
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=5)

        response = auth_client(manager).post(
            URL,
            {"articleId": str(article.id), "type": "ADJUSTMENT",
             "reason": "COUNT_CORRECTION", "quantity": 0},
            format="json",
        )

        assert response.status_code == 201
        assert response.json()["quantityAfter"] == 0

    def test_an_unknown_article_is_400(self, auth_client, manager, site):
        import uuid

        response = auth_client(manager).post(
            URL,
            {"articleId": str(uuid.uuid4()), "type": "IN", "reason": "PURCHASE",
             "quantity": 1},
            format="json",
        )
        assert response.status_code == 400
        assert "articleId" in response.json()["fieldErrors"]

    def test_a_cashier_may_not_post(self, auth_client, cashier, site):
        article = ArticleFactory()
        response = auth_client(cashier).post(
            URL,
            {"articleId": str(article.id), "type": "IN", "reason": "PURCHASE",
             "quantity": 1},
            format="json",
        )
        assert response.status_code == 403


class TestList:
    def test_newest_first(self, auth_client, cashier, site, owner):
        first = StockMovementFactory(site=site, user=owner)
        second = StockMovementFactory(site=site, user=owner)

        response = auth_client(cashier).get(URL)

        assert [r["id"] for r in response.json()["results"]] == [
            str(second.id), str(first.id)
        ]

    def test_filter_by_article(self, auth_client, cashier, site, owner):
        wanted = ArticleFactory()
        StockMovementFactory(site=site, user=owner, article=wanted)
        StockMovementFactory(site=site, user=owner)

        response = auth_client(cashier).get(f"{URL}?articleId={wanted.id}")
        assert response.json()["count"] == 1

    def test_filter_by_type_and_reason(self, auth_client, cashier, site, owner):
        StockMovementFactory(site=site, user=owner, type="IN", reason="PURCHASE")
        StockMovementFactory(site=site, user=owner, type="OUT", reason="DAMAGE")
        client = auth_client(cashier)

        assert client.get(f"{URL}?type=OUT").json()["count"] == 1
        assert client.get(f"{URL}?reason=DAMAGE").json()["count"] == 1

    def test_search_covers_article_name_sku_and_reference(
        self, auth_client, cashier, site, owner
    ):
        article = ArticleFactory(name="Sucre blanc", sku="EPI-001")
        StockMovementFactory(site=site, user=owner, article=article, reference="BL-42")
        StockMovementFactory(site=site, user=owner)
        client = auth_client(cashier)

        assert client.get(f"{URL}?search=sucre").json()["count"] == 1
        assert client.get(f"{URL}?search=EPI-001").json()["count"] == 1
        assert client.get(f"{URL}?search=BL-42").json()["count"] == 1

    @pytest.mark.parametrize(
        ("param", "value"), [("type", "SIDEWAYS"), ("reason", "PARCE_QUE")]
    )
    def test_an_invalid_filter_value_is_400(
        self, auth_client, cashier, site, param, value
    ):
        response = auth_client(cashier).get(f"{URL}?{param}={value}")
        assert response.status_code == 400
        assert param in response.json()["fieldErrors"]

    def test_the_list_query_count_is_flat(
        self, auth_client, cashier, site, owner, django_assert_num_queries
    ):
        for _ in range(10):
            StockMovementFactory(site=site, user=owner)

        client = auth_client(cashier)
        client.get(URL)

        with django_assert_num_queries(4):
            response = client.get(f"{URL}?pageSize=10")

        assert len(response.json()["results"]) == 10


@override_settings(SHOP_TIME_ZONE="Africa/Kinshasa")
class TestDateBounds:
    """Kinshasa is UTC+1. A movement at 00:30 local on 2 July is 23:30 UTC on
    1 July — a UTC implementation files it under the wrong day, and these
    tests are the only thing that catches it."""

    def _movement_at(self, instant, site, owner):
        movement = StockMovementFactory(site=site, user=owner)
        StockMovement.objects.filter(pk=movement.pk).update(created_at=instant)
        return movement

    def test_date_from_includes_a_movement_early_in_the_local_morning(
        self, auth_client, cashier, site, owner
    ):
        self._movement_at(
            datetime(2026, 7, 1, 23, 30, tzinfo=dt_timezone.utc), site, owner
        )  # 2 July, 00:30 in Kinshasa

        response = auth_client(cashier).get(f"{URL}?dateFrom=2026-07-02")

        assert response.json()["count"] == 1

    def test_date_from_excludes_the_previous_local_day(
        self, auth_client, cashier, site, owner
    ):
        self._movement_at(
            datetime(2026, 7, 1, 22, 30, tzinfo=dt_timezone.utc), site, owner
        )  # 1 July, 23:30 in Kinshasa

        response = auth_client(cashier).get(f"{URL}?dateFrom=2026-07-02")

        assert response.json()["count"] == 0

    def test_date_to_is_inclusive_of_the_whole_local_day(
        self, auth_client, cashier, site, owner
    ):
        self._movement_at(
            datetime(2026, 7, 2, 22, 30, tzinfo=dt_timezone.utc), site, owner
        )  # 2 July, 23:30 in Kinshasa

        response = auth_client(cashier).get(f"{URL}?dateTo=2026-07-02")

        assert response.json()["count"] == 1

    def test_a_malformed_date_is_400(self, auth_client, cashier, site):
        response = auth_client(cashier).get(f"{URL}?dateFrom=le-2-juillet")
        assert response.status_code == 400
        assert "dateFrom" in response.json()["fieldErrors"]
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/stock/tests/test_movements.py -v`
Expected: FAIL — 404, no route.

- [ ] **Step 3: Write the serializers**

Create `apps/stock/serializers.py`:

```python
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.catalogue.models import Article
from apps.catalogue.serializers import ArticleRefSerializer
from apps.stock.models import StockMovement


class StockMovementSerializer(serializers.ModelSerializer):
    """The frontend's `StockMovement`."""

    article = ArticleRefSerializer(read_only=True)
    article_id = serializers.UUIDField(source="article.id", read_only=True)
    site_id = serializers.UUIDField(source="site.id", read_only=True)
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    # No columns yet. Sub-project 3 adds `transaction`, sub-project 4 adds
    # `sale`; each swaps one line here. The keys must be present now because
    # the frontend's StockMovement type requires them.
    transaction_id = serializers.SerializerMethodField()
    sale_id = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = [
            "id", "article_id", "article", "site_id", "type", "reason",
            "quantity", "quantity_before", "quantity_after", "unit_cost",
            "reference", "note", "transaction_id", "sale_id",
            "user_id", "user_name", "created_at",
        ]

    def get_transaction_id(self, obj) -> None:
        return None

    def get_sale_id(self, obj) -> None:
        return None


class MovementCreateSerializer(serializers.Serializer):
    """The frontend's `MovementCreateDto`.

    A plain Serializer, not a ModelSerializer: the write shape and the read
    shape genuinely differ — `quantity` means a target rather than a delta on
    an ADJUSTMENT, and `quantityBefore` / `quantityAfter` are derived by
    `apply_movement`, never supplied.
    """

    article_id = serializers.PrimaryKeyRelatedField(
        source="article", queryset=Article.objects.all()
    )
    type = serializers.ChoiceField(choices=StockMovement.Type.choices)
    reason = serializers.ChoiceField(choices=StockMovement.Reason.choices)
    quantity = serializers.IntegerField(min_value=0)
    unit_cost = serializers.IntegerField(
        min_value=0, required=False, allow_null=True, default=None
    )
    reference = serializers.CharField(
        max_length=40, required=False, allow_blank=True, allow_null=True, default=None
    )
    note = serializers.CharField(
        max_length=300, required=False, allow_blank=True, allow_null=True, default=None
    )

    def validate(self, attrs):
        # Zero is meaningful only for an ADJUSTMENT: counting a shelf and
        # finding it empty is a real correction, whereas an IN or OUT of zero
        # is a no-op the ledger should not record.
        if attrs["type"] != StockMovement.Type.ADJUSTMENT and attrs["quantity"] == 0:
            raise serializers.ValidationError(
                {"quantity": [_("La quantité doit être supérieure à zéro.")]}
            )
        return attrs
```

- [ ] **Step 4: Write the filterset**

Create `apps/stock/filters.py`:

```python
from django_filters import rest_framework as drf_filters

from apps.common.dates import end_of_day, start_of_day
from apps.stock.models import StockMovement


class MovementFilterSet(drf_filters.FilterSet):
    article_id = drf_filters.UUIDFilter(field_name="article_id")
    type = drf_filters.ChoiceFilter(choices=StockMovement.Type.choices)
    reason = drf_filters.ChoiceFilter(choices=StockMovement.Reason.choices)
    # Bare calendar dates, resolved in SHOP_TIME_ZONE. `date_to` is inclusive
    # of the whole local day, matching the frontend's picker.
    date_from = drf_filters.DateFilter(method="filter_date_from")
    date_to = drf_filters.DateFilter(method="filter_date_to")

    class Meta:
        model = StockMovement
        fields = ["article_id", "type", "reason", "date_from", "date_to"]

    def filter_date_from(self, queryset, name, value):
        return queryset.filter(created_at__gte=start_of_day(value))

    def filter_date_to(self, queryset, name, value):
        return queryset.filter(created_at__lte=end_of_day(value))
```

- [ ] **Step 5: Write the views and URLs**

Create `apps/stock/views.py`:

```python
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, mixins, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import Site
from apps.common.filters import CamelCaseQueryParamsMixin
from apps.common.pagination import StandardPagination
from apps.common.permissions import IsManagerOrAbove
from apps.stock.filters import MovementFilterSet
from apps.stock.models import StockMovement
from apps.stock.serializers import MovementCreateSerializer, StockMovementSerializer
from apps.stock.services import apply_movement


class MovementViewSet(
    CamelCaseQueryParamsMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """List and create only. Movements are append-only: nothing updates or
    deletes one, and a correction is a new compensating movement."""

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_class = MovementFilterSet
    search_fields = ["article__name", "article__sku", "reference"]

    def get_queryset(self):
        return StockMovement.objects.select_related("article", "site", "user")

    def get_serializer_class(self):
        if self.action == "create":
            return MovementCreateSerializer
        return StockMovementSerializer

    def get_permissions(self):
        classes = [IsManagerOrAbove] if self.action == "create" else [IsAuthenticated]
        return [permission() for permission in classes]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        movement = apply_movement(
            article=data["article"],
            site=Site.objects.current(),
            type=data["type"],
            reason=data["reason"],
            quantity=data["quantity"],
            unit_cost=data.get("unit_cost"),
            reference=data.get("reference"),
            note=data.get("note"),
            user=request.user,
        )

        return Response(StockMovementSerializer(movement).data, status=201)
```

Create `apps/stock/urls.py`:

```python
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.stock.views import MovementViewSet

router = DefaultRouter()
router.register("stock/movements", MovementViewSet, basename="movement")

urlpatterns = [path("", include(router.urls))]
```

Add to `stockmanager/urls.py`:

```python
    path("api/", include("apps.stock.urls")),
```

- [ ] **Step 6: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/stock/tests/test_movements.py -v`

Two failures to expect and fix:
- `test_an_unknown_article_is_400` — `PrimaryKeyRelatedField` produces the key `articleId` already; confirm the message and key, do not add a second lookup.
- the date-bound tests — if they fail by exactly one hour, `SHOP_TIME_ZONE` is not reaching `start_of_day`. Check `override_settings` is on the class and that `shop_timezone()` reads the setting at call time rather than at import time.

- [ ] **Step 7: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -q
git add apps/stock stockmanager/urls.py
git commit -m "Add the movement list and create endpoints"
```

---

## Task 11: Low-stock and dashboard

**Files:**
- Modify: `apps/stock/views.py`, `apps/stock/urls.py`
- Create: `apps/stock/predicates.py`
- Test: `apps/stock/tests/test_dashboard.py`

**Interfaces:**
- Consumes: `apps.catalogue.querysets.article_queryset`, `apps.catalogue.serializers.ArticleSerializer`, `apps.common.dates.today_start`.
- Produces: `apps.stock.predicates.low_stock_queryset(queryset)` — shared by both endpoints so the dashboard tile and the list it links to cannot disagree.

- [ ] **Step 1: Write the failing tests**

Create `apps/stock/tests/test_dashboard.py`:

```python
"""Low-stock and dashboard reads."""

from datetime import datetime, timezone as dt_timezone

import pytest
from django.test import override_settings

from apps.catalogue.tests.factories import ArticleFactory
from apps.stock.models import StockMovement
from apps.stock.tests.factories import StockLevelFactory, StockMovementFactory

pytestmark = pytest.mark.django_db

LOW_STOCK_URL = "/api/stock/low-stock/"
DASHBOARD_URL = "/api/stock/dashboard/"


def stocked(site, quantity, threshold, **article_kwargs):
    article = ArticleFactory(**article_kwargs)
    StockLevelFactory(
        article=article, site=site, quantity=quantity, reorder_threshold=threshold
    )
    return article


class TestLowStock:
    def test_returns_low_and_out_of_stock_only(self, auth_client, cashier, site):
        stocked(site, 0, 10)     # OUT_OF_STOCK
        stocked(site, 5, 10)     # LOW
        stocked(site, 50, 10)    # IN_STOCK

        response = auth_client(cashier).get(LOW_STOCK_URL)

        assert response.status_code == 200
        assert response.json()["count"] == 2

    def test_archived_articles_never_count(self, auth_client, cashier, site):
        """`isLowStockArticle` checks isActive first. An archived article is
        not something to reorder."""
        stocked(site, 0, 10, is_active=False)

        response = auth_client(cashier).get(LOW_STOCK_URL)

        assert response.json()["count"] == 0

    def test_ruptures_first_then_ascending_quantity(self, auth_client, cashier, site):
        stocked(site, 8, 10, name="Huit")
        stocked(site, 0, 10, name="Rupture")
        stocked(site, 3, 10, name="Trois")

        response = auth_client(cashier).get(LOW_STOCK_URL)

        assert [r["name"] for r in response.json()["results"]] == [
            "Rupture", "Trois", "Huit"
        ]

    def test_the_payload_is_the_article_shape(self, auth_client, cashier, site):
        stocked(site, 0, 10)
        row = auth_client(cashier).get(LOW_STOCK_URL).json()["results"][0]
        assert "stock" in row
        assert set(row["stock"]) == {
            "siteId", "quantity", "reorderThreshold", "status"
        }

    def test_search_is_supported(self, auth_client, cashier, site):
        stocked(site, 0, 10, name="Sucre", sku="EPI-1")
        stocked(site, 0, 10, name="Farine", sku="EPI-2")

        response = auth_client(cashier).get(f"{LOW_STOCK_URL}?search=sucre")

        assert response.json()["count"] == 1


class TestDashboard:
    def test_the_payload_matches_the_frontend_type(self, auth_client, cashier, site):
        response = auth_client(cashier).get(DASHBOARD_URL)

        assert response.status_code == 200
        assert set(response.json()) == {
            "articleCount", "stockValue", "lowStockCount", "movementsToday"
        }

    def test_article_count_excludes_archived(self, auth_client, cashier, site):
        ArticleFactory(is_active=True)
        ArticleFactory(is_active=True)
        ArticleFactory(is_active=False)

        response = auth_client(cashier).get(DASHBOARD_URL)

        assert response.json()["articleCount"] == 2

    def test_stock_value_is_quantity_times_purchase_price(
        self, auth_client, cashier, site
    ):
        stocked(site, 10, 0, purchase_price=1500)
        stocked(site, 4, 0, purchase_price=250)

        response = auth_client(cashier).get(DASHBOARD_URL)

        assert response.json()["stockValue"] == 10 * 1500 + 4 * 250

    def test_stock_value_counts_archived_articles(self, auth_client, cashier, site):
        """`getDashboardStats` sums every level without checking isActive —
        archived stock is still stock the shop owns."""
        stocked(site, 10, 0, purchase_price=1000, is_active=False)

        response = auth_client(cashier).get(DASHBOARD_URL)

        assert response.json()["stockValue"] == 10_000

    def test_low_stock_count_agrees_with_the_low_stock_list(
        self, auth_client, cashier, site
    ):
        stocked(site, 0, 10)
        stocked(site, 5, 10)
        stocked(site, 50, 10)
        stocked(site, 0, 10, is_active=False)

        client = auth_client(cashier)
        dashboard = client.get(DASHBOARD_URL)
        listing = client.get(LOW_STOCK_URL)

        assert dashboard.json()["lowStockCount"] == listing.json()["count"] == 2

    @override_settings(SHOP_TIME_ZONE="Africa/Kinshasa")
    def test_movements_today_uses_the_local_day(
        self, auth_client, cashier, site, owner
    ):
        from unittest import mock

        from django.utils import timezone as dj_timezone

        now = datetime(2026, 7, 2, 8, 0, tzinfo=dt_timezone.utc)  # 09:00 local

        today = StockMovementFactory(site=site, user=owner)
        yesterday = StockMovementFactory(site=site, user=owner)
        StockMovement.objects.filter(pk=today.pk).update(
            created_at=datetime(2026, 7, 1, 23, 30, tzinfo=dt_timezone.utc)
        )  # 2 July 00:30 local — today
        StockMovement.objects.filter(pk=yesterday.pk).update(
            created_at=datetime(2026, 7, 1, 22, 30, tzinfo=dt_timezone.utc)
        )  # 1 July 23:30 local — yesterday

        with mock.patch.object(dj_timezone, "now", return_value=now):
            response = auth_client(cashier).get(DASHBOARD_URL)

        assert response.json()["movementsToday"] == 1

    def test_an_empty_shop_returns_zeros_not_nulls(self, auth_client, cashier, site):
        response = auth_client(cashier).get(DASHBOARD_URL)
        assert response.json() == {
            "articleCount": 0,
            "stockValue": 0,
            "lowStockCount": 0,
            "movementsToday": 0,
        }

    def test_a_cashier_may_read_the_dashboard(self, auth_client, cashier, site):
        assert auth_client(cashier).get(DASHBOARD_URL).status_code == 200
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/stock/tests/test_dashboard.py -v`
Expected: FAIL — 404 on both URLs.

- [ ] **Step 3: Write the shared predicate**

Create `apps/stock/predicates.py`:

```python
"""Shared low-stock definition.

The dashboard tile links to the low-stock list. If they compute membership
separately they will eventually disagree, and the user sees a badge saying 4
above a list showing 3. One function, two callers.
"""

from django.db.models import F, Q, QuerySet


def low_stock_queryset(queryset: QuerySet) -> QuerySet:
    """Active articles that are out of stock or at or below their threshold.

    Expects the `stock_quantity` / `stock_threshold` annotations from
    `apps.catalogue.querysets.article_queryset`.

    Archived articles never count: `isLowStockArticle` in the frontend checks
    `isActive` first, and an archived article is not something to reorder.
    """
    return queryset.filter(
        Q(is_active=True)
        & (Q(stock_quantity__lte=0) | Q(stock_quantity__lte=F("stock_threshold")))
    )
```

- [ ] **Step 4: Write the two views**

Append to `apps/stock/views.py`:

```python
from django.db.models import Case, ExpressionWrapper, F, IntegerField, Sum, When
from rest_framework.generics import ListAPIView
from rest_framework.views import APIView

from apps.catalogue.querysets import article_queryset
from apps.catalogue.serializers import ArticleSerializer
from apps.common.dates import today_start
from apps.stock.models import StockLevel
from apps.stock.predicates import low_stock_queryset


class LowStockView(CamelCaseQueryParamsMixin, ListAPIView):
    serializer_class = ArticleSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "sku"]

    def get_queryset(self):
        return low_stock_queryset(article_queryset()).order_by(
            # Ruptures first, then ascending quantity. Not a cover ratio —
            # there is no consumption-rate data to compute one from.
            Case(
                When(stock_quantity__lte=0, then=0),
                default=1,
                output_field=IntegerField(),
            ),
            "stock_quantity",
            "name",
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["site"] = Site.objects.current()
        return context


class DashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        site = Site.objects.current()
        articles = article_queryset()

        # Summed in SQL rather than in Python: the frontend loops over every
        # level to compute this, which is fine against IndexedDB and is not
        # fine against a shop with a few thousand articles.
        #
        # `output_field` goes inside ExpressionWrapper, never as an annotate()
        # kwarg — as a kwarg it would silently create an annotation *named*
        # `output_field`. Both operands are PositiveIntegerField so Django can
        # resolve the type on its own; the wrapper is here to say so.
        stock_value = (
            StockLevel.objects.filter(site=site)
            .annotate(
                value=ExpressionWrapper(
                    F("quantity") * F("article__purchase_price"),
                    output_field=IntegerField(),
                )
            )
            .aggregate(total=Sum("value"))["total"]
            or 0
        )

        return Response(
            {
                "article_count": articles.filter(is_active=True).count(),
                "stock_value": stock_value,
                "low_stock_count": low_stock_queryset(articles).count(),
                "movements_today": StockMovement.objects.filter(
                    site=site, created_at__gte=today_start()
                ).count(),
            }
        )
```

Register both in `apps/stock/urls.py`:

```python
from apps.stock.views import DashboardView, LowStockView, MovementViewSet

urlpatterns = [
    path("stock/low-stock/", LowStockView.as_view(), name="low-stock"),
    path("stock/dashboard/", DashboardView.as_view(), name="dashboard"),
    path("", include(router.urls)),
]
```

> Order matters: the explicit paths must precede `include(router.urls)`, or
> the router's detail route can shadow them.

- [ ] **Step 5: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/stock/tests/test_dashboard.py -v`

If `test_low_stock_count_agrees_with_the_low_stock_list` fails, the two are not
using `low_stock_queryset` — that is the bug the test exists to catch, so fix
the caller rather than the assertion.

- [ ] **Step 6: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -q
git add apps/stock
git commit -m "Add the low-stock and dashboard endpoints"
```

---

## Task 12: Admin, README, and the wire check

**Files:**
- Create: `apps/catalogue/admin.py`, `apps/stock/admin.py`
- Modify: `README.md`
- Test: manual wire verification (documented below), then the full suite

**Interfaces:**
- Consumes: everything.
- Produces: nothing new.

- [ ] **Step 1: Register the admin**

Create `apps/catalogue/admin.py`:

```python
from django.contrib import admin

from apps.catalogue.models import Article, Category, Supplier


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "description"]
    search_fields = ["name"]


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["name", "contact_name", "phone", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "contact_name", "email"]


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ["sku", "name", "category", "sale_price", "is_active"]
    list_filter = ["is_active", "unit", "category"]
    search_fields = ["sku", "name", "barcode"]
    autocomplete_fields = ["category", "supplier"]
```

Create `apps/stock/admin.py`:

```python
from django.contrib import admin

from apps.stock.models import StockLevel, StockMovement


@admin.register(StockLevel)
class StockLevelAdmin(admin.ModelAdmin):
    list_display = ["article", "quantity", "reorder_threshold"]
    search_fields = ["article__sku", "article__name"]


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = [
        "created_at", "article", "type", "reason", "quantity",
        "quantity_before", "quantity_after", "user_name",
    ]
    list_filter = ["type", "reason"]
    search_fields = ["article__sku", "article__name", "reference"]
    # Append-only. The admin must not offer a way to rewrite the ledger.
    readonly_fields = [f.name for f in StockMovement._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

- [ ] **Step 2: Update the README**

Add a section documenting the new endpoints and the new setting. Follow the
existing README's structure and tone. It must state:

- the ten endpoints from the spec's §API surface, with their methods
- the permission rule: read for any authenticated user, write for Manager and above, `DELETE` for Owner only
- `SHOP_TIME_ZONE`, what it affects (`dateFrom` / `dateTo`, `movementsToday`) and what it does not (storage, which is UTC)
- that trailing slashes are mandatory, if that note is not already there

- [ ] **Step 3: Verify the wire format against the frontend contract**

Run the whole thing for real, not through the test client. Start the server:

```bash
~/.pyenv/versions/stock/bin/python manage.py migrate
~/.pyenv/versions/stock/bin/python manage.py bootstrap   # if no data yet
~/.pyenv/versions/stock/bin/python manage.py runserver
```

Then, in another shell, log in and check each payload's **exact key set**
against `types/domain.ts`:

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"email":"...","password":"..."}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["accessToken"])')

for path in categories suppliers articles stock/movements stock/low-stock; do
  echo "== $path"
  curl -s "http://127.0.0.1:8000/api/$path/" -H "Authorization: Bearer $TOKEN" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(sorted(d)); print(sorted(d["results"][0]) if d.get("results") else "(empty)")'
done

echo "== dashboard"
curl -s http://127.0.0.1:8000/api/stock/dashboard/ -H "Authorization: Bearer $TOKEN" \
  | python3 -c 'import json,sys; print(sorted(json.load(sys.stdin)))'
```

Confirm, key by key:
- every list envelope is exactly `['count', 'next', 'previous', 'results']`
- an article row carries `categoryId` as a plain string and `category` as `{id, name}`
- `vatRate` is a JSON number, not a quoted string
- `stock` is `['quantity', 'reorderThreshold', 'siteId', 'status']`
- the dashboard is exactly `['articleCount', 'lowStockCount', 'movementsToday', 'stockValue']`

Also check one error body:

```bash
curl -s "http://127.0.0.1:8000/api/articles/?isActive=banana" -H "Authorization: Bearer $TOKEN" \
  | python3 -m json.tool
```

Confirm it is `{"code": "validation_error", "message": ..., "fieldErrors": {"isActive": [...]}}` — the field key **camelCase**, not `is_active`. A snake_case key there is a silent failure: `lib/form-errors.ts` would set an error on a field that does not exist and the user would see nothing.

- [ ] **Step 4: Final checks**

```bash
~/.pyenv/versions/stock/bin/python manage.py check
~/.pyenv/versions/stock/bin/python manage.py makemigrations --check --dry-run
~/.pyenv/versions/stock/bin/pytest -q
```

All three must be clean. Report the actual test count from the output; do not
estimate it.

- [ ] **Step 5: Commit**

```bash
git add apps/catalogue/admin.py apps/stock/admin.py README.md
git commit -m "Register the admin and document the catalogue endpoints"
```

---

## Notes for the reviewer

Things worth checking that a passing suite does not prove:

- **The import direction.** `apps.catalogue` must not import `apps.stock` at module scope. Task 7's `article_queryset` and Task 8's serializer overrides both import inside the function body for this reason. `grep -n "from apps.stock" apps/catalogue/*.py` should return nothing outside a function.
- **Three copies of the status rule.** `StockLevel.status`, `StockSummarySerializer.get_status` and `ArticleFilterSet.filter_stock_status` all encode the same three inclusive boundaries. They are kept in step only by tests asserting the same boundaries in each. If a fourth copy appears, that is the moment to extract one definition.
- **`select_for_update` does nothing on SQLite.** Verified during design: `connection.features.has_select_for_update` is `False` and the call neither locks nor raises. Every concurrency claim in `apply_movement` is aspirational until Postgres.
- **Query-count bounds.** If an implementer raised one of the `django_assert_num_queries` constants, check whether the count grows with page size. Growing with page size means the annotation is not being used and the bound was raised to hide it.
