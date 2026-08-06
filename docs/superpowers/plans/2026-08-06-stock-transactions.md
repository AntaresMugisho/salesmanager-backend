# Stock Transactions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement multi-line stock transactions with `TR-YYYY-NNNN` numbering, completing every function in the frontend's `services/stock.ts`.

**Architecture:** A `DocumentSequence` counter row per prefix and year in `apps/common/`, allocated under `select_for_update` inside the caller's atomic block — so a rejected transaction rolls the counter back and leaves no gap. `StockTransaction` lives in `apps/stock/` beside the movements that become its lines, and every line is posted through the existing `apply_movement`, which gains one optional argument.

**Tech Stack:** Django 6.0.7, DRF 3.17.1, django-filter 26.1, pytest 9.1.1 + pytest-django 4.12.0 + factory-boy 3.3.3. No new dependencies.

## Global Constraints

Every task's requirements implicitly include this section.

- **Read the spec first:** `docs/superpowers/specs/2026-08-06-stock-transactions-design.md`. Sub-project 1's spec has the wire conventions; sub-project 2's has the filter, permission and calendar-date conventions.
- **Python env:** pyenv's `stock`. Run everything as `~/.pyenv/versions/stock/bin/python` / `~/.pyenv/versions/stock/bin/pytest`. There is no `.venv`.
- **The suite takes ~4.5 minutes.** Run the focused file while iterating; run the whole thing before committing.
- **TDD, strictly.** Write the failing test, watch it fail for the right reason, then implement.
- **Every user-facing string is French**, via `gettext_lazy as _`.
- **Field-error keys must match react-hook-form's field names**, which are camelCase and dotted for array rows. Verified during planning: `flatten_errors` turns DRF's nested list errors into `lines.1.quantity` on its own, and `camelize` converts `lines.0.article_id` → `lines.0.articleId` while leaving the dots and indices alone.
- **`Site.objects.current()`** is how you get the site. Never thread a site id.
- **Models inherit `apps.common.models.UUIDModel`** — which supplies `id`, `created_at` and `updated_at` — *except* `DocumentSequence`, which is infrastructure rather than a domain object (Task 1 says why).
- **Optional strings:** column `null=True, blank=True`; serializer `required=False, allow_blank=True, allow_null=True`; normalise `""` to `None`. `apps.stock.services._clean` already does the normalising half.
- **Transactions are immutable.** No `PATCH`, no `DELETE`, ever. A correction is a new compensating transaction.
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
| `apps/common/models.py` | + `DocumentSequence` |
| `apps/common/sequences.py` | **new** — `next_reference(prefix, year)` |
| `apps/common/dates.py` | + `shop_today()`, with `today_start()` refactored onto it |
| `apps/stock/models.py` | + `StockTransaction`, + `StockMovement.transaction` |
| `apps/stock/services.py` | `apply_movement` gains `stock_transaction=`; + `create_transaction` |
| `apps/stock/serializers.py` | + transaction read, detail, line and create serializers |
| `apps/stock/filters.py` | + `TransactionFilterSet` |
| `apps/stock/views.py` | + `TransactionViewSet` |
| `apps/catalogue/views.py` | `SupplierViewSet` gains a transaction delete guard |

---

## Task 1: The document sequence

**Files:**
- Modify: `apps/common/models.py`, `apps/common/dates.py`
- Create: `apps/common/sequences.py`, `apps/common/migrations/` (first migration for this app)
- Test: `apps/common/tests/test_sequences.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `apps.common.models.DocumentSequence` — fields `prefix`, `year`, `last_number`.
  - `apps.common.sequences.next_reference(prefix: str, year: int) -> str`, returning e.g. `"TR-2026-0001"`. Raises `RuntimeError` if called outside an atomic block.
  - `apps.common.dates.shop_today() -> datetime.date`.

`apps.common` has no migrations directory yet — it has held only abstract models and helpers. Adding a concrete model means creating one.

- [ ] **Step 1: Write the failing test**

Create `apps/common/tests/test_sequences.py`:

```python
"""Document reference allocation.

The frontend counts rows to fake this and says so:

    Counting rows is adequate for a single-tab mock ONLY — the real backend
    owns numbering.

Allocation happens inside the caller's atomic block, which buys the property
asserted at the bottom of this file: a failed write rolls the counter back, so
a rejected document leaves no gap.
"""

import pytest
from django.db import transaction

from apps.common.models import DocumentSequence
from apps.common.sequences import next_reference

pytestmark = pytest.mark.django_db


def allocate(prefix="TR", year=2026):
    with transaction.atomic():
        return next_reference(prefix, year)


class TestFormat:
    def test_the_first_reference_of_a_year_is_one(self):
        assert allocate() == "TR-2026-0001"

    def test_numbers_are_padded_to_four_digits(self):
        DocumentSequence.objects.create(prefix="TR", year=2026, last_number=41)
        assert allocate() == "TR-2026-0042"

    def test_padding_widens_past_four_digits(self):
        DocumentSequence.objects.create(prefix="TR", year=2026, last_number=9999)
        assert allocate() == "TR-2026-10000"


class TestSequencing:
    def test_consecutive_allocations_increment(self):
        assert [allocate() for _ in range(3)] == [
            "TR-2026-0001",
            "TR-2026-0002",
            "TR-2026-0003",
        ]

    def test_a_new_year_restarts_at_one(self):
        allocate(year=2026)
        allocate(year=2026)
        assert allocate(year=2027) == "TR-2027-0001"

    def test_a_new_year_leaves_the_old_counter_untouched(self):
        allocate(year=2026)
        allocate(year=2027)
        assert allocate(year=2026) == "TR-2026-0002"

    def test_prefixes_count_independently(self):
        """Sub-project 4 allocates FA- from this same table."""
        allocate(prefix="TR")
        allocate(prefix="TR")
        assert allocate(prefix="FA") == "FA-2026-0001"


class TestRollback:
    def test_a_rolled_back_allocation_leaves_no_gap(self):
        """The property that matters for sub-project 4, where the number is
        an invoice number rather than a delivery-note number."""
        allocate()

        with pytest.raises(RuntimeError):
            with transaction.atomic():
                next_reference("TR", 2026)
                raise RuntimeError("something later in the write failed")

        assert allocate() == "TR-2026-0002"


class TestAtomicGuard:
    def test_allocating_outside_a_transaction_is_refused(self):
        """Called bare, the read-modify-write would race silently instead of
        failing. Developer error, never user-facing — hence a plain
        RuntimeError and an English message."""
        with pytest.raises(RuntimeError, match="atomic"):
            next_reference("TR", 2026)


class TestModel:
    def test_one_counter_per_prefix_and_year(self):
        from django.db import IntegrityError

        DocumentSequence.objects.create(prefix="TR", year=2026)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DocumentSequence.objects.create(prefix="TR", year=2026)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/common/tests/test_sequences.py -p no:warnings`
Expected: FAIL — `ImportError: cannot import name 'DocumentSequence'`.

- [ ] **Step 3: Add the model**

Append to `apps/common/models.py`:

```python
class DocumentSequence(models.Model):
    """One counter row per document prefix and year.

    Deliberately *not* a UUIDModel. This is infrastructure, not a domain
    object: nothing links to it, nothing serialises it, and no API exposes
    it. A plain auto pk is the honest shape.

    Sub-project 3 allocates `TR-`; sub-project 4 allocates `FA-` from this
    same table with no change.
    """

    prefix = models.CharField(max_length=8)
    year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "séquence de document"
        verbose_name_plural = "séquences de document"
        constraints = [
            models.UniqueConstraint(
                fields=["prefix", "year"],
                name="one_sequence_per_prefix_and_year",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.prefix}-{self.year}: {self.last_number}"
```

- [ ] **Step 4: Write the allocation service**

Create `apps/common/sequences.py`:

```python
"""Document reference allocation.

`TR-YYYY-NNNN` for stock transactions, `FA-YYYY-NNNN` for sales invoices in
sub-project 4. One implementation, two prefixes.
"""

from django.db import connection, transaction

from apps.common.models import DocumentSequence


def next_reference(prefix: str, year: int) -> str:
    """Allocate the next `PREFIX-YYYY-NNNN`.

    MUST be called inside an open `transaction.atomic()` block. Two
    consequences follow from that, and both are wanted:

    - The `select_for_update` below only serialises concurrent allocations if
      a transaction is already open. Called bare it would race silently.
    - The increment is rolled back with the caller's write, so a document that
      fails validation leaves no gap in the sequence.

    Note that `select_for_update` is a silent no-op on SQLite — verified,
    `connection.features.has_select_for_update` is False and the call neither
    locks nor raises. The serialisation is real only on PostgreSQL.
    """
    if not connection.in_atomic_block:
        raise RuntimeError(
            "next_reference must be called inside transaction.atomic()."
        )

    # get_or_create's documented IntegrityError-and-re-get path handles two
    # requests racing to create the first row of a year.
    sequence, _ = DocumentSequence.objects.get_or_create(prefix=prefix, year=year)

    locked = DocumentSequence.objects.select_for_update().get(pk=sequence.pk)
    locked.last_number += 1
    locked.save(update_fields=["last_number"])

    return f"{prefix}-{year}-{locked.last_number:04d}"
```

- [ ] **Step 5: Add `shop_today` to the date helpers**

In `apps/common/dates.py`, add `shop_today` and refactor `today_start` onto it — the transaction reference needs the shop's *calendar year*, and `today_start().year` would be wrong on 1 January, when local midnight is still 31 December in UTC:

```python
def shop_today() -> date:
    """The shop's current calendar date.

    Not `timezone.now().date()`, which is the UTC date: at 00h30 in Goma it
    is still yesterday in UTC, and a transaction created then would be
    numbered into the wrong year every 1 January.
    """
    return timezone.now().astimezone(shop_timezone()).date()


def today_start() -> datetime:
    """Local midnight of the shop's current day, as an aware UTC datetime."""
    return start_of_day(shop_today())
```

Replace the existing `today_start` body with the one above; it currently
inlines the conversion.

- [ ] **Step 6: Create the migration and run**

```bash
~/.pyenv/versions/stock/bin/python manage.py makemigrations common
~/.pyenv/versions/stock/bin/pytest apps/common/tests/test_sequences.py apps/common/tests/test_dates.py -p no:warnings
```

Expected: all PASS.

If `makemigrations` reports "No installed app with label 'common'", check
`apps/common/apps.py` — its `AppConfig` sets `label = "common"`, and the
migrations package needs `apps/common/migrations/__init__.py` to exist first:

```bash
mkdir -p apps/common/migrations && touch apps/common/migrations/__init__.py
```

- [ ] **Step 7: Full suite, migration check, commit**

```bash
~/.pyenv/versions/stock/bin/python manage.py makemigrations --check --dry-run
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/common
git commit -m "Add the document sequence and reference allocation"
```

---

## Task 2: The transaction model

**Files:**
- Modify: `apps/stock/models.py`
- Create: `apps/stock/migrations/0002_*.py` (generated)
- Modify: `apps/stock/tests/factories.py`
- Test: `apps/stock/tests/test_transaction_model.py`

**Interfaces:**
- Consumes: `apps.stock.models.StockMovement.Type`, `.Reason`; `apps.catalogue.models.Supplier`; `apps.accounts.models.Site`.
- Produces: `apps.stock.models.StockTransaction`; `StockMovement.transaction` (nullable FK, `related_name="lines"`); `apps.stock.tests.factories.StockTransactionFactory`.

**Declaration order matters and it points both ways.** `StockTransaction.type`
needs `StockMovement.Type`, while `StockMovement.transaction` needs
`StockTransaction`. Keep `StockMovement` first in the module and give its new
foreign key the lazy string form `"stock.StockTransaction"`.

- [ ] **Step 1: Write the failing test**

Create `apps/stock/tests/test_transaction_model.py`:

```python
"""StockTransaction invariants."""

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.catalogue.tests.factories import SupplierFactory
from apps.stock.models import StockMovement, StockTransaction
from apps.stock.tests.factories import StockMovementFactory, StockTransactionFactory

pytestmark = pytest.mark.django_db


class TestReference:
    def test_references_are_unique(self, site):
        StockTransactionFactory(reference="TR-2026-0001")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                StockTransactionFactory(reference="TR-2026-0001")


class TestSupplier:
    def test_supplier_is_optional(self, site):
        assert StockTransactionFactory(supplier=None).supplier is None

    def test_a_supplier_with_transactions_cannot_be_deleted(self, site):
        supplier = SupplierFactory()
        StockTransactionFactory(supplier=supplier, supplier_name=supplier.name)
        with pytest.raises(ProtectedError):
            supplier.delete()

    def test_the_supplier_name_is_snapshotted(self, site):
        """A rename must not rewrite what last year's delivery note says."""
        supplier = SupplierFactory(name="Brasimba")
        header = StockTransactionFactory(supplier=supplier, supplier_name="Brasimba")

        supplier.name = "Brasimba SARL"
        supplier.save()
        header.refresh_from_db()

        assert header.supplier_name == "Brasimba"


class TestUser:
    def test_a_user_with_transactions_cannot_be_deleted(self, site, owner):
        StockTransactionFactory(user=owner, user_name=owner.full_name)
        with pytest.raises(ProtectedError):
            owner.delete()


class TestLines:
    def test_movements_reach_their_header_through_lines(self, site, owner):
        header = StockTransactionFactory(user=owner)
        first = StockMovementFactory(site=site, user=owner, transaction=header)
        second = StockMovementFactory(site=site, user=owner, transaction=header)
        StockMovementFactory(site=site, user=owner)  # standalone

        assert set(header.lines.all()) == {first, second}

    def test_a_standalone_movement_has_no_transaction(self, site, owner):
        assert StockMovementFactory(site=site, user=owner).transaction is None

    def test_a_transaction_with_lines_cannot_be_deleted(self, site, owner):
        """PROTECT never fires today because nothing deletes a transaction.
        It is the honest declaration of that, rather than a CASCADE that would
        quietly delete ledger rows if a delete path ever appeared."""
        header = StockTransactionFactory(user=owner)
        StockMovementFactory(site=site, user=owner, transaction=header)

        with pytest.raises(ProtectedError):
            header.delete()


class TestChoices:
    def test_type_and_reason_reuse_the_movement_choices(self):
        """A transaction whose choices could drift from its own lines' choices
        is a bug waiting to happen."""
        transaction_types = dict(
            StockTransaction._meta.get_field("type").choices
        )
        movement_types = dict(StockMovement._meta.get_field("type").choices)
        assert transaction_types == movement_types

        transaction_reasons = dict(
            StockTransaction._meta.get_field("reason").choices
        )
        movement_reasons = dict(StockMovement._meta.get_field("reason").choices)
        assert transaction_reasons == movement_reasons


class TestOrdering:
    def test_newest_first(self, site, owner):
        first = StockTransactionFactory(user=owner, reference="TR-2026-0001")
        second = StockTransactionFactory(user=owner, reference="TR-2026-0002")
        assert list(StockTransaction.objects.all()) == [second, first]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/stock/tests/test_transaction_model.py -p no:warnings`
Expected: FAIL — `ImportError: cannot import name 'StockTransaction'`.

- [ ] **Step 3: Add the foreign key to `StockMovement`**

In `apps/stock/models.py`, inside `StockMovement`, add after the `note` field:

```python
    # Lazy string reference: StockTransaction is declared below, because it
    # needs this class's Type and Reason. PROTECT never fires today — nothing
    # deletes a transaction — and says so rather than letting a future delete
    # path quietly remove ledger rows.
    transaction = models.ForeignKey(
        "stock.StockTransaction",
        on_delete=models.PROTECT,
        related_name="lines",
        null=True,
        blank=True,
        verbose_name=_("transaction"),
    )
```

- [ ] **Step 4: Add `StockTransaction`**

Append to `apps/stock/models.py`, after `StockMovement`:

```python
class StockTransaction(UUIDModel):
    """A header grouping several movements written together.

    One type and one reason apply to every line — a design decision, not an
    omission. Immutable once created: correcting a transaction means posting a
    new, compensating one.
    """

    reference = models.CharField(_("référence"), max_length=20, unique=True)
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="transactions")
    # The user's own delivery-note number, distinct from `reference`, which
    # always holds the generated TR-YYYY-NNNN.
    user_reference = models.CharField(
        _("référence du document"), max_length=40, null=True, blank=True
    )
    type = models.CharField(
        _("type"), max_length=16, choices=StockMovement.Type.choices
    )
    reason = models.CharField(
        _("motif"), max_length=20, choices=StockMovement.Reason.choices
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="transactions",
        null=True,
        blank=True,
        verbose_name=_("fournisseur"),
    )
    # Snapshotted like `user_name` below: PROTECT stops a supplier being
    # deleted, and this stops a *rename* rewriting historical documents.
    supplier_name = models.CharField(
        _("fournisseur"), max_length=80, null=True, blank=True
    )
    note = models.CharField(_("note"), max_length=300, null=True, blank=True)
    # Denormalised at write time so the list view need not read the lines.
    # Safe only because a transaction is immutable; if an edit path is ever
    # added, these must be recomputed there.
    line_count = models.PositiveIntegerField(_("nombre de lignes"), default=0)
    total_quantity = models.PositiveIntegerField(_("quantité totale"), default=0)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="transactions"
    )
    user_name = models.CharField(_("auteur"), max_length=150)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = _("transaction de stock")
        verbose_name_plural = _("transactions de stock")

    def __str__(self) -> str:
        return self.reference
```

Add `from apps.catalogue.models import Article, Supplier` to the imports (the
module already imports `Article`).

- [ ] **Step 5: Add the factory**

Append to `apps/stock/tests/factories.py`:

```python
class StockTransactionFactory(DjangoModelFactory):
    class Meta:
        model = StockTransaction

    reference = factory.Sequence(lambda n: f"TR-2026-{n + 1:04d}")
    site = factory.SubFactory(SiteFactory)
    user = factory.SubFactory(UserFactory)
    user_name = factory.LazyAttribute(lambda obj: obj.user.full_name)
    user_reference = None
    type = StockMovement.Type.IN
    reason = StockMovement.Reason.PURCHASE
    supplier = None
    supplier_name = None
    note = None
    line_count = 0
    total_quantity = 0
```

Add `StockTransaction` to the `apps.stock.models` import at the top of the file.

- [ ] **Step 6: Migrate and run**

```bash
~/.pyenv/versions/stock/bin/python manage.py makemigrations stock
~/.pyenv/versions/stock/bin/pytest apps/stock/tests/test_transaction_model.py -p no:warnings
```

Expected: all PASS.

- [ ] **Step 7: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/python manage.py makemigrations --check --dry-run
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/stock
git commit -m "Add the StockTransaction model and the movement's transaction link"
```

---

## Task 3: Wire the movement to its header

**Files:**
- Modify: `apps/stock/services.py`, `apps/stock/serializers.py`
- Test: `apps/stock/tests/test_apply_movement.py` (extend), `apps/stock/tests/test_movements.py` (extend)

**Interfaces:**
- Consumes: `apps.stock.models.StockTransaction`.
- Produces: `apply_movement(..., stock_transaction=None, field_prefix="")` — the new keyword accepts a `StockTransaction` or `None` and is written to the movement's `transaction` column. `StockMovementSerializer.transaction_id` now carries a real value.

**The keyword is `stock_transaction`, not `transaction`.** That name is already
bound to `django.db.transaction` in this module, and the function it would
shadow is the one that opens the atomic block.

- [ ] **Step 1: Write the failing tests**

Append to `apps/stock/tests/test_apply_movement.py`:

```python
class TestTransactionLink:
    def test_a_movement_defaults_to_no_transaction(self, site, owner):
        article = ArticleFactory()
        assert post(article, site, owner).transaction is None

    def test_a_movement_can_be_linked_to_a_header(self, site, owner):
        from apps.stock.tests.factories import StockTransactionFactory

        article = ArticleFactory()
        header = StockTransactionFactory(user=owner)

        movement = post(article, site, owner, stock_transaction=header)

        assert movement.transaction == header
        assert list(header.lines.all()) == [movement]
```

Append to `apps/stock/tests/test_movements.py`, inside `TestCreate`:

```python
    def test_transaction_id_carries_a_value_for_a_line(
        self, auth_client, manager, site
    ):
        """Replaces the hardcoded null sub-project 2 shipped. `saleId` keeps
        its placeholder until sub-project 4."""
        from apps.catalogue.tests.factories import ArticleFactory
        from apps.stock.services import apply_movement
        from apps.stock.tests.factories import StockTransactionFactory

        header = StockTransactionFactory(user=manager)
        article = ArticleFactory()
        apply_movement(
            article=article,
            site=site,
            type="IN",
            reason="PURCHASE",
            quantity=5,
            user=manager,
            stock_transaction=header,
        )

        row = auth_client(manager).get(URL).json()["results"][0]

        assert row["transactionId"] == str(header.id)
        assert row["saleId"] is None
```

- [ ] **Step 2: Run and watch them fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/stock/tests/test_apply_movement.py -k TransactionLink apps/stock/tests/test_movements.py -k transaction_id -p no:warnings`
Expected: FAIL — `apply_movement() got an unexpected keyword argument 'stock_transaction'`.

- [ ] **Step 3: Extend `apply_movement`**

In `apps/stock/services.py`, add the parameter to the signature, after `note`:

```python
    stock_transaction=None,
```

Update the docstring to mention it:

```python
    `stock_transaction` links this movement to the header it is a line of.
    Named `stock_transaction` rather than `transaction` because that name is
    bound to `django.db.transaction` in this module — shadowing it inside the
    function that opens the atomic block is how a subtle bug gets written.
```

And pass it through in the `StockMovement.objects.create(...)` call, after
`note=_clean(note),`:

```python
        transaction=stock_transaction,
```

(`transaction=` there is a keyword argument name, not a variable reference, so
it does not shadow anything.)

- [ ] **Step 4: Make the serializer field real**

In `apps/stock/serializers.py`, replace the `transaction_id` declaration and
its method. Delete:

```python
    transaction_id = serializers.SerializerMethodField()
```

and

```python
    def get_transaction_id(self, obj) -> None:
        return None
```

Add in place of the declaration:

```python
    transaction_id = serializers.UUIDField(read_only=True)
```

It reads the model's `transaction_id` attname directly, and DRF renders a
`None` attribute as `null` without any help. Update the comment above the pair
so it refers only to `sale_id`:

```python
    # No column yet. Sub-project 4 adds `sale` and swaps this line. The key
    # must be present now because the frontend's StockMovement type requires
    # it.
    sale_id = serializers.SerializerMethodField()
```

- [ ] **Step 5: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/stock -p no:warnings`
Expected: all PASS. The existing `test_transaction_id_and_sale_id_are_null`
must still pass — a standalone movement still reports `null`.

- [ ] **Step 6: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/stock
git commit -m "Link movements to their transaction header"
```

---

## Task 4: The creation service

**Files:**
- Modify: `apps/stock/services.py`
- Test: `apps/stock/tests/test_create_transaction.py`

**Interfaces:**
- Consumes: `apps.common.sequences.next_reference`, `apps.common.dates.shop_today`, `apply_movement`.
- Produces:

```python
def create_transaction(
    *,
    type: str,
    reason: str,
    lines: list[dict],   # each {"article": Article, "quantity": int, "unit_cost": int | None}
    user,
    site,
    supplier=None,
    user_reference: str | None = None,
    note: str | None = None,
) -> StockTransaction
```

Raises `rest_framework.serializers.ValidationError` keyed `lines.N.quantity`
when a line fails. All-or-nothing.

- [ ] **Step 1: Write the failing test**

Create `apps/stock/tests/test_create_transaction.py`:

```python
"""Multi-line transaction creation.

Mirrors `createTransaction` in the frontend's services/stock.ts, with one
difference the spec calls out: numbering is real here.
"""

import pytest
from rest_framework.serializers import ValidationError

from apps.catalogue.tests.factories import ArticleFactory, SupplierFactory
from apps.common.models import DocumentSequence
from apps.stock.models import StockLevel, StockMovement, StockTransaction
from apps.stock.services import create_transaction
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db


def line(article, quantity, unit_cost=None):
    return {"article": article, "quantity": quantity, "unit_cost": unit_cost}


def build(site, user, lines, **kwargs):
    payload = {
        "type": "IN",
        "reason": "PURCHASE",
        "lines": lines,
        "user": user,
        "site": site,
    }
    payload.update(kwargs)
    return create_transaction(**payload)


class TestHeader:
    def test_the_reference_is_allocated(self, site, owner):
        header = build(site, owner, [line(ArticleFactory(), 5)])
        assert header.reference.startswith("TR-")
        assert header.reference.endswith("-0001")

    def test_consecutive_transactions_increment(self, site, owner):
        first = build(site, owner, [line(ArticleFactory(), 1)])
        second = build(site, owner, [line(ArticleFactory(), 1)])
        assert int(second.reference.split("-")[-1]) == int(
            first.reference.split("-")[-1]
        ) + 1

    def test_the_user_name_is_snapshotted(self, site, owner):
        header = build(site, owner, [line(ArticleFactory(), 1)])
        assert header.user_name == owner.full_name

    def test_the_supplier_name_is_snapshotted(self, site, owner):
        supplier = SupplierFactory(name="Brasimba")
        header = build(site, owner, [line(ArticleFactory(), 1)], supplier=supplier)
        assert header.supplier == supplier
        assert header.supplier_name == "Brasimba"

    def test_no_supplier_leaves_both_fields_null(self, site, owner):
        header = build(site, owner, [line(ArticleFactory(), 1)])
        assert header.supplier is None
        assert header.supplier_name is None

    def test_blank_strings_normalise_to_null(self, site, owner):
        header = build(
            site, owner, [line(ArticleFactory(), 1)], user_reference="  ", note=""
        )
        assert header.user_reference is None
        assert header.note is None


class TestCounts:
    def test_line_count_and_total_quantity(self, site, owner):
        header = build(
            site,
            owner,
            [line(ArticleFactory(), 4), line(ArticleFactory(), 6)],
        )
        assert header.line_count == 2
        assert header.total_quantity == 10
        assert header.lines.count() == 2

    def test_total_quantity_sums_derived_deltas_for_an_adjustment(self, site, owner):
        """An ADJUSTMENT line carries a counted *target*; the movement records
        the delta. The total must sum the deltas, not the targets."""
        first, second = ArticleFactory(), ArticleFactory()
        StockLevelFactory(article=first, site=site, quantity=20)
        StockLevelFactory(article=second, site=site, quantity=5)

        header = build(
            site,
            owner,
            [line(first, 14), line(second, 9)],
            type="ADJUSTMENT",
            reason="COUNT_CORRECTION",
        )

        # |14 - 20| = 6, |9 - 5| = 4
        assert header.total_quantity == 10


class TestReferenceSplit:
    def test_a_blank_user_reference_puts_the_tr_number_on_every_movement(
        self, site, owner
    ):
        header = build(site, owner, [line(ArticleFactory(), 1)])
        assert header.user_reference is None
        assert header.lines.get().reference == header.reference

    def test_a_supplied_user_reference_goes_to_the_movements(self, site, owner):
        header = build(
            site, owner, [line(ArticleFactory(), 1)], user_reference="BL-42"
        )
        assert header.reference.startswith("TR-")
        assert header.user_reference == "BL-42"
        assert header.lines.get().reference == "BL-42"


class TestLines:
    def test_every_line_becomes_a_movement_carrying_the_header(self, site, owner):
        header = build(
            site, owner, [line(ArticleFactory(), 3), line(ArticleFactory(), 7)]
        )
        assert {m.quantity for m in header.lines.all()} == {3, 7}
        assert all(m.transaction == header for m in header.lines.all())

    def test_stock_levels_move(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=10)

        build(site, owner, [line(article, 5)])

        assert StockLevel.objects.get(article=article).quantity == 15

    def test_the_unit_cost_reaches_the_movement(self, site, owner):
        article = ArticleFactory()
        header = build(site, owner, [line(article, 5, unit_cost=800)])
        assert header.lines.get().unit_cost == 800


class TestAllOrNothing:
    def test_an_insufficient_line_writes_nothing(self, site, owner):
        good, bad = ArticleFactory(), ArticleFactory()
        StockLevelFactory(article=good, site=site, quantity=50)
        StockLevelFactory(article=bad, site=site, quantity=2)

        with pytest.raises(ValidationError) as exc:
            build(
                site,
                owner,
                [line(good, 10), line(bad, 99)],
                type="OUT",
                reason="SALE",
            )

        assert "lines.1.quantity" in exc.value.detail
        assert StockTransaction.objects.count() == 0
        assert StockMovement.objects.count() == 0
        assert StockLevel.objects.get(article=good).quantity == 50
        assert StockLevel.objects.get(article=bad).quantity == 2

    def test_a_failed_create_leaves_no_gap_in_the_sequence(self, site, owner):
        good = ArticleFactory()
        StockLevelFactory(article=good, site=site, quantity=1)
        build(site, owner, [line(ArticleFactory(), 1)])  # TR-....-0001

        with pytest.raises(ValidationError):
            build(site, owner, [line(good, 99)], type="OUT", reason="SALE")

        header = build(site, owner, [line(ArticleFactory(), 1)])
        assert header.reference.endswith("-0002")

    def test_an_unchanged_adjustment_line_aborts_the_whole_transaction(
        self, site, owner
    ):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=9)

        with pytest.raises(ValidationError) as exc:
            build(
                site,
                owner,
                [line(article, 9)],
                type="ADJUSTMENT",
                reason="COUNT_CORRECTION",
            )

        assert "lines.0.quantity" in exc.value.detail
        assert StockTransaction.objects.count() == 0


class TestSequenceState:
    def test_the_counter_row_tracks_the_allocations(self, site, owner):
        build(site, owner, [line(ArticleFactory(), 1)])
        build(site, owner, [line(ArticleFactory(), 1)])

        sequence = DocumentSequence.objects.get(prefix="TR")
        assert sequence.last_number == 2
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/stock/tests/test_create_transaction.py -p no:warnings`
Expected: FAIL — `ImportError: cannot import name 'create_transaction'`.

- [ ] **Step 3: Implement it**

Append to `apps/stock/services.py`:

```python
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
```

Add to the module imports:

```python
from apps.common.dates import shop_today
from apps.common.sequences import next_reference
from apps.stock.models import StockLevel, StockMovement, StockTransaction
```

(the last line replaces the existing `StockLevel, StockMovement` import).

- [ ] **Step 4: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/stock/tests/test_create_transaction.py -p no:warnings`
Expected: all PASS.

If `test_a_failed_create_leaves_no_gap_in_the_sequence` fails, the allocation
is escaping the atomic block — check that `next_reference` is called *inside*
`create_transaction`, not by the caller.

- [ ] **Step 5: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/stock
git commit -m "Add create_transaction, the all-or-nothing multi-line writer"
```

---

## Task 5: The create endpoint

**Files:**
- Modify: `apps/stock/serializers.py`, `apps/stock/views.py`, `apps/stock/urls.py`
- Test: `apps/stock/tests/test_transactions_create.py`

**Interfaces:**
- Consumes: `create_transaction`.
- Produces: `apps.stock.serializers.TransactionLineInputSerializer`, `TransactionCreateSerializer`, `StockTransactionSerializer`; `apps.stock.views.TransactionViewSet` registered at `stock/transactions`.

Two error-shape facts, both verified during planning:

- `allow_empty=False` on the list produces `{"lines": {"non_field_errors": [...]}}`, which flattens to `lines.nonFieldErrors` — **not** the `lines` key the contract wants. Use the default `allow_empty=True` and reject in `validate_lines`, which produces `{"lines": [msg]}`.
- Per-line field errors need no help: DRF nests them as `{"lines": [{}, {"quantity": [...]}]}` and `flatten_errors` already turns that into `lines.1.quantity`.

- [ ] **Step 1: Write the failing test**

Create `apps/stock/tests/test_transactions_create.py`:

```python
"""POST /api/stock/transactions/."""

import uuid

import pytest

from apps.catalogue.tests.factories import ArticleFactory, SupplierFactory
from apps.stock.models import StockLevel, StockMovement, StockTransaction
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db

URL = "/api/stock/transactions/"


def body(lines, **overrides):
    payload = {
        "type": "IN",
        "reason": "PURCHASE",
        "supplierId": None,
        "reference": None,
        "note": None,
        "lines": lines,
    }
    payload.update(overrides)
    return payload


def line(article, quantity=5, unit_cost=None):
    return {
        "articleId": str(article.id),
        "quantity": quantity,
        "unitCost": unit_cost,
    }


class TestCreate:
    def test_a_manager_can_create(self, auth_client, manager, site):
        first, second = ArticleFactory(), ArticleFactory()

        response = auth_client(manager).post(
            URL, body([line(first, 4), line(second, 6)]), format="json"
        )

        assert response.status_code == 201
        assert response.json()["reference"].startswith("TR-")
        assert response.json()["lineCount"] == 2
        assert response.json()["totalQuantity"] == 10
        assert StockMovement.objects.count() == 2

    def test_the_payload_matches_the_frontend_type(self, auth_client, manager, site):
        response = auth_client(manager).post(
            URL, body([line(ArticleFactory())]), format="json"
        )

        assert set(response.json()) == {
            "id",
            "reference",
            "siteId",
            "userReference",
            "type",
            "reason",
            "supplierId",
            "supplierName",
            "note",
            "lineCount",
            "totalQuantity",
            "userId",
            "userName",
            "createdAt",
        }

    def test_a_supplier_is_recorded_by_id_and_name(self, auth_client, manager, site):
        supplier = SupplierFactory(name="Brasimba")

        response = auth_client(manager).post(
            URL,
            body([line(ArticleFactory())], supplierId=str(supplier.id)),
            format="json",
        )

        assert response.json()["supplierId"] == str(supplier.id)
        assert response.json()["supplierName"] == "Brasimba"

    def test_no_supplier_serialises_as_null(self, auth_client, manager, site):
        response = auth_client(manager).post(
            URL, body([line(ArticleFactory())]), format="json"
        )
        assert response.json()["supplierId"] is None
        assert response.json()["supplierName"] is None

    def test_the_user_reference_is_kept_separate_from_the_tr_number(
        self, auth_client, manager, site
    ):
        response = auth_client(manager).post(
            URL, body([line(ArticleFactory())], reference="BL-42"), format="json"
        )

        assert response.json()["reference"].startswith("TR-")
        assert response.json()["userReference"] == "BL-42"

    def test_a_cashier_may_not_create(self, auth_client, cashier, site):
        response = auth_client(cashier).post(
            URL, body([line(ArticleFactory())]), format="json"
        )
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"


class TestLineValidation:
    def test_no_lines_is_rejected(self, auth_client, manager, site):
        response = auth_client(manager).post(URL, body([]), format="json")

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines"] == [
            "Ajoutez au moins un article à la transaction."
        ]

    def test_a_duplicate_article_is_rejected(self, auth_client, manager, site):
        """Rejected rather than summed: summing makes the ledger ambiguous and
        raises an ordering question with no good answer."""
        article = ArticleFactory()

        response = auth_client(manager).post(
            URL, body([line(article), line(article)]), format="json"
        )

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.1.articleId"] == [
            "Cet article est déjà présent dans la transaction."
        ]

    def test_an_unknown_article_is_rejected_on_its_row(
        self, auth_client, manager, site
    ):
        response = auth_client(manager).post(
            URL,
            body(
                [
                    line(ArticleFactory()),
                    {"articleId": str(uuid.uuid4()), "quantity": 1, "unitCost": None},
                ]
            ),
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.1.articleId"] == [
            "Cet article n'existe plus."
        ]

    def test_a_negative_quantity_is_rejected_on_its_row(
        self, auth_client, manager, site
    ):
        response = auth_client(manager).post(
            URL,
            body([line(ArticleFactory()), line(ArticleFactory(), quantity=-3)]),
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.1.quantity"] == [
            "La quantité doit être un nombre entier positif."
        ]

    def test_zero_is_rejected_for_in_and_out(self, auth_client, manager, site):
        response = auth_client(manager).post(
            URL, body([line(ArticleFactory(), quantity=0)]), format="json"
        )

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.0.quantity"] == [
            "La quantité doit être supérieure à zéro."
        ]

    def test_zero_is_allowed_for_an_adjustment(self, auth_client, manager, site):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=7)

        response = auth_client(manager).post(
            URL,
            body(
                [line(article, quantity=0)],
                type="ADJUSTMENT",
                reason="COUNT_CORRECTION",
            ),
            format="json",
        )

        assert response.status_code == 201
        assert StockLevel.objects.get(article=article).quantity == 0

    def test_insufficient_stock_names_the_offending_row(
        self, auth_client, manager, site
    ):
        good, bad = ArticleFactory(), ArticleFactory()
        StockLevelFactory(article=good, site=site, quantity=50)
        StockLevelFactory(article=bad, site=site, quantity=2)

        response = auth_client(manager).post(
            URL,
            body(
                [line(good, 10), line(bad, 99)],
                type="OUT",
                reason="SALE",
            ),
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.1.quantity"] == [
            "Stock insuffisant : 2 unité(s) disponible(s) actuellement."
        ]
        assert StockTransaction.objects.count() == 0
        assert StockLevel.objects.get(article=good).quantity == 50

    def test_an_over_long_reference_is_rejected(self, auth_client, manager, site):
        response = auth_client(manager).post(
            URL, body([line(ArticleFactory())], reference="X" * 41), format="json"
        )
        assert response.status_code == 400
        assert "reference" in response.json()["fieldErrors"]


class TestImmutability:
    def test_patch_on_the_list_route_is_405(self, auth_client, manager, site):
        assert auth_client(manager).patch(URL, {}, format="json").status_code == 405

    def test_patch_on_a_transaction_is_405(self, auth_client, manager, site):
        created = auth_client(manager).post(
            URL, body([line(ArticleFactory())]), format="json"
        )
        detail = f"{URL}{created.json()['id']}/"

        assert auth_client(manager).patch(detail, {}, format="json").status_code == 405

    def test_delete_on_a_transaction_is_405(self, auth_client, owner, manager, site):
        created = auth_client(manager).post(
            URL, body([line(ArticleFactory())]), format="json"
        )
        detail = f"{URL}{created.json()['id']}/"

        assert auth_client(owner).delete(detail).status_code == 405
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/stock/tests/test_transactions_create.py -p no:warnings`
Expected: FAIL — 404, no route registered.

- [ ] **Step 3: Add the serializers**

Append to `apps/stock/serializers.py`:

```python
class StockTransactionSerializer(serializers.ModelSerializer):
    """The frontend's `StockTransaction`."""

    site_id = serializers.UUIDField(read_only=True)
    supplier_id = serializers.UUIDField(read_only=True)
    user_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = StockTransaction
        fields = [
            "id",
            "reference",
            "site_id",
            "user_reference",
            "type",
            "reason",
            "supplier_id",
            "supplier_name",
            "note",
            "line_count",
            "total_quantity",
            "user_id",
            "user_name",
            "created_at",
        ]


class TransactionLineInputSerializer(serializers.Serializer):
    """One row of `TransactionCreateDto.lines`."""

    # Both messages are overridden so the user reads the frontend's wording
    # rather than DRF's generic French. The spec's validation table promises
    # these exact strings.
    article_id = serializers.PrimaryKeyRelatedField(
        source="article",
        queryset=Article.objects.all(),
        error_messages={"does_not_exist": _("Cet article n'existe plus.")},
    )
    quantity = serializers.IntegerField(
        min_value=0,
        error_messages={
            "min_value": _("La quantité doit être un nombre entier positif."),
            "invalid": _("La quantité doit être un nombre entier positif."),
        },
    )
    unit_cost = serializers.IntegerField(
        min_value=0, required=False, allow_null=True, default=None
    )


class TransactionCreateSerializer(serializers.Serializer):
    """The frontend's `TransactionCreateDto`.

    `lines` deliberately keeps DRF's default `allow_empty=True` and rejects an
    empty list in `validate_lines` instead. `allow_empty=False` produces
    `{"lines": {"non_field_errors": [...]}}`, which reaches the client as
    `lines.nonFieldErrors` — a key no form field is mounted on, so the user
    would see nothing at all.
    """

    type = serializers.ChoiceField(choices=StockMovement.Type.choices)
    reason = serializers.ChoiceField(choices=StockMovement.Reason.choices)
    supplier_id = serializers.PrimaryKeyRelatedField(
        source="supplier",
        queryset=Supplier.objects.all(),
        required=False,
        allow_null=True,
        default=None,
    )
    reference = serializers.CharField(
        max_length=40, required=False, allow_blank=True, allow_null=True, default=None
    )
    note = serializers.CharField(
        max_length=300, required=False, allow_blank=True, allow_null=True, default=None
    )
    lines = TransactionLineInputSerializer(many=True)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError(
                _("Ajoutez au moins un article à la transaction.")
            )
        return value

    def validate(self, attrs):
        seen = set()
        for index, line in enumerate(attrs["lines"]):
            article = line["article"]
            if article.id in seen:
                raise serializers.ValidationError(
                    {
                        f"lines.{index}.article_id": [
                            _("Cet article est déjà présent dans la transaction.")
                        ]
                    }
                )
            seen.add(article.id)

            # Zero is meaningful only for an ADJUSTMENT: counting a shelf and
            # finding it empty is a real correction, whereas an IN or OUT of
            # zero is a no-op the ledger should not record.
            if (
                attrs["type"] != StockMovement.Type.ADJUSTMENT
                and line["quantity"] == 0
            ):
                raise serializers.ValidationError(
                    {
                        f"lines.{index}.quantity": [
                            _("La quantité doit être supérieure à zéro.")
                        ]
                    }
                )
        return attrs
```

Add to the module imports:

```python
from apps.catalogue.models import Article, Supplier
from apps.stock.models import StockMovement, StockTransaction
```

(replacing the existing `Article` and `StockMovement` imports).

- [ ] **Step 4: Add the viewset and route**

Append to `apps/stock/views.py`:

```python
class TransactionViewSet(
    CamelCaseQueryParamsMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Create, list and retrieve only.

    A transaction is immutable — correcting one means posting a new,
    compensating transaction. The absent update and destroy mixins are what
    make PATCH and DELETE return 405; no explicit handling is needed.
    """

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ["reference", "user_reference", "supplier_name", "note"]

    def get_queryset(self):
        return StockTransaction.objects.select_related("site", "supplier", "user")

    def get_serializer_class(self):
        if self.action == "create":
            return TransactionCreateSerializer
        return StockTransactionSerializer

    def get_permissions(self):
        classes = [IsManagerOrAbove] if self.action == "create" else [IsAuthenticated]
        return [permission() for permission in classes]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        header = create_transaction(
            type=data["type"],
            reason=data["reason"],
            lines=data["lines"],
            user=request.user,
            site=Site.objects.current(),
            supplier=data.get("supplier"),
            user_reference=data.get("reference"),
            note=data.get("note"),
        )

        return Response(StockTransactionSerializer(header).data, status=201)
```

Update the imports at the top of `apps/stock/views.py`:

```python
from apps.stock.models import StockLevel, StockMovement, StockTransaction
from apps.stock.serializers import (
    MovementCreateSerializer,
    StockMovementSerializer,
    StockTransactionSerializer,
    TransactionCreateSerializer,
)
from apps.stock.services import apply_movement, create_transaction
```

Register it in `apps/stock/urls.py`, alongside the movement route:

```python
from apps.stock.views import (
    DashboardView,
    LowStockView,
    MovementViewSet,
    TransactionViewSet,
)

router.register("stock/transactions", TransactionViewSet, basename="transaction")
```

- [ ] **Step 5: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/stock/tests/test_transactions_create.py -p no:warnings`
Expected: all PASS.

If `test_a_duplicate_article_is_rejected` reports the key `lines.1.articleId`
missing but shows `lines` present, check that `validate()` raises with the
dotted string key rather than a nested dict — `{"lines": {1: {...}}}` flattens
differently.

- [ ] **Step 6: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/stock
git commit -m "Add the transaction create endpoint"
```

---

## Task 6: List and detail

**Files:**
- Modify: `apps/stock/serializers.py`, `apps/stock/filters.py`, `apps/stock/views.py`
- Test: `apps/stock/tests/test_transactions_read.py`

**Interfaces:**
- Consumes: `apps.common.dates.start_of_day` / `end_of_day`; `apps.catalogue.serializers.ArticleRefSerializer`.
- Produces: `apps.stock.serializers.StockTransactionLineSerializer`, `StockTransactionDetailSerializer`; `apps.stock.filters.TransactionFilterSet`.

- [ ] **Step 1: Write the failing test**

Create `apps/stock/tests/test_transactions_read.py`:

```python
"""GET /api/stock/transactions/ and its detail route."""

import uuid
from datetime import datetime, timezone as dt_timezone

import pytest

from apps.catalogue.tests.factories import ArticleFactory, SupplierFactory
from apps.stock.models import StockTransaction
from apps.stock.services import create_transaction
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db

URL = "/api/stock/transactions/"


def make(site, user, quantities=(5,), **kwargs):
    lines = [
        {"article": ArticleFactory(), "quantity": q, "unit_cost": 800}
        for q in quantities
    ]
    payload = {
        "type": "IN",
        "reason": "PURCHASE",
        "lines": lines,
        "user": user,
        "site": site,
    }
    payload.update(kwargs)
    return create_transaction(**payload)


class TestList:
    def test_the_row_matches_the_frontend_type(self, auth_client, cashier, site, owner):
        make(site, owner)

        response = auth_client(cashier).get(URL)

        assert response.status_code == 200
        assert set(response.json()["results"][0]) == {
            "id",
            "reference",
            "siteId",
            "userReference",
            "type",
            "reason",
            "supplierId",
            "supplierName",
            "note",
            "lineCount",
            "totalQuantity",
            "userId",
            "userName",
            "createdAt",
        }

    def test_the_list_never_includes_lines(self, auth_client, cashier, site, owner):
        """That is what lineCount and totalQuantity are denormalised for."""
        make(site, owner, quantities=(1, 2, 3))
        assert "lines" not in auth_client(cashier).get(URL).json()["results"][0]

    def test_newest_first(self, auth_client, cashier, site, owner):
        first = make(site, owner)
        second = make(site, owner)

        response = auth_client(cashier).get(URL)

        assert [r["id"] for r in response.json()["results"]] == [
            str(second.id),
            str(first.id),
        ]

    def test_filter_by_type_and_reason(self, auth_client, cashier, site, owner):
        make(site, owner, type="IN", reason="PURCHASE")
        make(site, owner, type="ADJUSTMENT", reason="COUNT_CORRECTION")
        client = auth_client(cashier)

        assert client.get(f"{URL}?type=ADJUSTMENT").json()["count"] == 1
        assert client.get(f"{URL}?reason=PURCHASE").json()["count"] == 1

    @pytest.mark.parametrize(
        ("param", "value"), [("type", "SIDEWAYS"), ("reason", "PARCE_QUE")]
    )
    def test_an_invalid_filter_value_is_400(
        self, auth_client, cashier, site, param, value
    ):
        response = auth_client(cashier).get(f"{URL}?{param}={value}")
        assert response.status_code == 400
        assert param in response.json()["fieldErrors"]

    def test_search_covers_all_four_fields(self, auth_client, cashier, site, owner):
        supplier = SupplierFactory(name="Brasimba")
        make(site, owner, supplier=supplier, user_reference="BL-42", note="Matin")
        make(site, owner)
        client = auth_client(cashier)

        assert client.get(f"{URL}?search=BL-42").json()["count"] == 1
        assert client.get(f"{URL}?search=brasimba").json()["count"] == 1
        assert client.get(f"{URL}?search=matin").json()["count"] == 1

        reference = StockTransaction.objects.order_by("created_at").first().reference
        assert client.get(f"{URL}?search={reference}").json()["count"] == 1

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

    def test_a_cashier_may_read(self, auth_client, cashier, site, owner):
        make(site, owner)
        assert auth_client(cashier).get(URL).status_code == 200


class TestDateBounds:
    """Kinshasa is UTC+1, so a transaction at 00h30 local is 23h30 UTC the
    previous day. These fail against a UTC implementation."""

    @pytest.fixture(autouse=True)
    def _kinshasa(self, settings):
        settings.SHOP_TIME_ZONE = "Africa/Kinshasa"

    def _at(self, instant, site, owner):
        header = make(site, owner)
        StockTransaction.objects.filter(pk=header.pk).update(created_at=instant)
        return header

    def test_date_from_includes_the_early_local_morning(
        self, auth_client, cashier, site, owner
    ):
        self._at(datetime(2026, 7, 1, 23, 30, tzinfo=dt_timezone.utc), site, owner)
        response = auth_client(cashier).get(f"{URL}?dateFrom=2026-07-02")
        assert response.json()["count"] == 1

    def test_date_from_excludes_the_previous_local_day(
        self, auth_client, cashier, site, owner
    ):
        self._at(datetime(2026, 7, 1, 22, 30, tzinfo=dt_timezone.utc), site, owner)
        response = auth_client(cashier).get(f"{URL}?dateFrom=2026-07-02")
        assert response.json()["count"] == 0

    def test_date_to_is_inclusive_of_the_whole_local_day(
        self, auth_client, cashier, site, owner
    ):
        self._at(datetime(2026, 7, 2, 22, 30, tzinfo=dt_timezone.utc), site, owner)
        response = auth_client(cashier).get(f"{URL}?dateTo=2026-07-02")
        assert response.json()["count"] == 1


class TestDetail:
    def test_the_payload_adds_lines(self, auth_client, cashier, site, owner):
        header = make(site, owner, quantities=(4, 6))

        response = auth_client(cashier).get(f"{URL}{header.id}/")

        assert response.status_code == 200
        payload = response.json()
        assert "lines" in payload
        assert len(payload["lines"]) == 2
        assert set(payload["lines"][0]) == {
            "movementId",
            "article",
            "quantity",
            "quantityBefore",
            "quantityAfter",
            "unitCost",
        }
        assert set(payload["lines"][0]["article"]) == {"id", "sku", "name", "unit"}

    def test_the_line_figures_come_from_the_movement(
        self, auth_client, cashier, site, owner
    ):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=10)
        header = create_transaction(
            type="IN",
            reason="PURCHASE",
            lines=[{"article": article, "quantity": 5, "unit_cost": 800}],
            user=owner,
            site=site,
        )

        row = auth_client(cashier).get(f"{URL}{header.id}/").json()["lines"][0]

        assert row["quantity"] == 5
        assert row["quantityBefore"] == 10
        assert row["quantityAfter"] == 15
        assert row["unitCost"] == 800

    def test_lines_are_in_a_stable_order(self, auth_client, cashier, site, owner):
        header = make(site, owner, quantities=(1, 2, 3))

        first = auth_client(cashier).get(f"{URL}{header.id}/").json()["lines"]
        second = auth_client(cashier).get(f"{URL}{header.id}/").json()["lines"]

        assert [row["movementId"] for row in first] == [
            row["movementId"] for row in second
        ]

    def test_unknown_id_is_404_with_the_envelope(self, auth_client, cashier, site):
        response = auth_client(cashier).get(f"{URL}{uuid.uuid4()}/")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"

    def test_the_detail_query_count_is_flat(
        self, auth_client, cashier, site, owner, django_assert_num_queries
    ):
        header = make(site, owner, quantities=tuple(range(1, 11)))

        client = auth_client(cashier)
        client.get(f"{URL}{header.id}/")

        with django_assert_num_queries(3):
            # 1 user, 1 header, 1 lines-with-article — the select_related on
            # the lines query is what keeps this from growing.
            response = client.get(f"{URL}{header.id}/")

        assert len(response.json()["lines"]) == 10
```

> The `django_assert_num_queries(4)` bound on the detail route is an estimate.
> Run it, read the real number, and adjust **only** after confirming it does
> not grow with the line count — add ten more lines and check it is unchanged.
> Growth means the lines are not `select_related`, and the fix is the query,
> not the bound.

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/stock/tests/test_transactions_read.py -p no:warnings`
Expected: FAIL — the detail route 404s and the filters are unregistered.

- [ ] **Step 3: Add the line and detail serializers**

Append to `apps/stock/serializers.py`:

```python
class StockTransactionLineSerializer(serializers.ModelSerializer):
    """The frontend's `StockTransactionLine`, resolved back from its movement.

    `movementId` rather than `id`: a line has no identity of its own, and the
    frontend uses this to link a line back to the ledger.
    """

    movement_id = serializers.UUIDField(source="id", read_only=True)
    article = ArticleRefSerializer(read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "movement_id",
            "article",
            "quantity",
            "quantity_before",
            "quantity_after",
            "unit_cost",
        ]


class StockTransactionDetailSerializer(StockTransactionSerializer):
    """The frontend's `StockTransactionDetail` — the list shape plus lines."""

    lines = serializers.SerializerMethodField()

    class Meta(StockTransactionSerializer.Meta):
        fields = StockTransactionSerializer.Meta.fields + ["lines"]

    def get_lines(self, obj):
        # Oldest first, with `id` as the tiebreaker: SQLite can give two
        # movements written in one transaction the same microsecond, and the
        # frontend renders these in submission order.
        movements = obj.lines.select_related("article").order_by("created_at", "id")
        return StockTransactionLineSerializer(movements, many=True).data
```

- [ ] **Step 4: Add the filterset**

Append to `apps/stock/filters.py`:

```python
class TransactionFilterSet(drf_filters.FilterSet):
    type = drf_filters.ChoiceFilter(choices=StockMovement.Type.choices)
    reason = drf_filters.ChoiceFilter(choices=StockMovement.Reason.choices)
    date_from = drf_filters.DateFilter(method="filter_date_from")
    date_to = drf_filters.DateFilter(method="filter_date_to")

    class Meta:
        model = StockTransaction
        fields = ["type", "reason", "date_from", "date_to"]

    def filter_date_from(self, queryset, name, value):
        return queryset.filter(created_at__gte=start_of_day(value))

    def filter_date_to(self, queryset, name, value):
        return queryset.filter(created_at__lte=end_of_day(value))
```

Add `StockTransaction` to the module's `apps.stock.models` import.

- [ ] **Step 5: Wire them into the viewset**

In `apps/stock/views.py`, on `TransactionViewSet`, add the filterset and
extend `get_serializer_class`:

```python
    filterset_class = TransactionFilterSet
```

```python
    def get_serializer_class(self):
        if self.action == "create":
            return TransactionCreateSerializer
        if self.action == "retrieve":
            return StockTransactionDetailSerializer
        return StockTransactionSerializer
```

Extend the imports:

```python
from apps.stock.filters import MovementFilterSet, TransactionFilterSet
from apps.stock.serializers import (
    MovementCreateSerializer,
    StockMovementSerializer,
    StockTransactionDetailSerializer,
    StockTransactionSerializer,
    TransactionCreateSerializer,
)
```

- [ ] **Step 6: Run**

Run: `~/.pyenv/versions/stock/bin/pytest apps/stock/tests/test_transactions_read.py -p no:warnings`
Expected: all PASS, subject to the query-count note above.

- [ ] **Step 7: Full suite and commit**

```bash
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/stock
git commit -m "Add the transaction list and detail endpoints"
```

---

## Task 7: The supplier guard, admin and docs

**Files:**
- Modify: `apps/catalogue/views.py`, `apps/stock/admin.py`, `README.md`
- Test: `apps/catalogue/tests/test_suppliers.py` (extend)

**Interfaces:**
- Consumes: everything.
- Produces: nothing new.

`StockTransaction.supplier` is `PROTECT`, but `SupplierViewSet.perform_destroy`
counts only articles. Without a second guard, deleting a supplier that has
transactions but no articles raises `ProtectedError` — an unhandled 500 where
the frontend expects a 409.

- [ ] **Step 1: Write the failing test**

Append to `apps/catalogue/tests/test_suppliers.py`, inside `TestDelete`:

```python
    def test_a_supplier_with_transactions_is_409_not_500(
        self, auth_client, owner, site
    ):
        """StockTransaction.supplier is PROTECT. Without an explicit guard
        this surfaces as an unhandled ProtectedError."""
        from apps.catalogue.tests.factories import ArticleFactory
        from apps.stock.services import create_transaction

        supplier = SupplierFactory()
        create_transaction(
            type="IN",
            reason="PURCHASE",
            lines=[{"article": ArticleFactory(), "quantity": 1, "unit_cost": None}],
            user=owner,
            site=site,
            supplier=supplier,
        )

        response = auth_client(owner).delete(detail_url(supplier))

        assert response.status_code == 409
        assert response.json()["code"] == "conflict"
        assert response.json()["message"] == (
            "Ce fournisseur est lié à 1 transaction et ne peut pas être supprimé."
        )

    def test_the_transaction_message_is_plural(self, auth_client, owner, site):
        from apps.catalogue.tests.factories import ArticleFactory
        from apps.stock.services import create_transaction

        supplier = SupplierFactory()
        for _ in range(2):
            create_transaction(
                type="IN",
                reason="PURCHASE",
                lines=[
                    {"article": ArticleFactory(), "quantity": 1, "unit_cost": None}
                ],
                user=owner,
                site=site,
                supplier=supplier,
            )

        response = auth_client(owner).delete(detail_url(supplier))

        assert response.json()["message"] == (
            "Ce fournisseur est lié à 2 transactions et ne peut pas être supprimé."
        )

    def test_articles_are_reported_before_transactions(
        self, auth_client, owner, site
    ):
        """Both guards can trip at once. The article message is the one the
        user can act on — archive or reassign — so it wins."""
        from apps.stock.services import create_transaction

        supplier = SupplierFactory()
        ArticleFactory(supplier=supplier)
        create_transaction(
            type="IN",
            reason="PURCHASE",
            lines=[{"article": ArticleFactory(), "quantity": 1, "unit_cost": None}],
            user=owner,
            site=site,
            supplier=supplier,
        )

        response = auth_client(owner).delete(detail_url(supplier))

        assert "article" in response.json()["message"]
```

- [ ] **Step 2: Run and watch it fail**

Run: `~/.pyenv/versions/stock/bin/pytest apps/catalogue/tests/test_suppliers.py -k transaction -p no:warnings`
Expected: FAIL — 500, not 409.

- [ ] **Step 3: Add the second guard**

In `apps/catalogue/views.py`, extend `SupplierViewSet.perform_destroy`:

```python
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

        # StockTransaction.supplier is PROTECT, so without this the delete
        # raises ProtectedError and the envelope renders a 500.
        transactions = instance.transactions.count()
        if transactions:
            raise Conflict(
                _(
                    "Ce fournisseur est lié à %(count)d transaction%(plural)s "
                    "et ne peut pas être supprimé."
                )
                % {"count": transactions, "plural": "s" if transactions > 1 else ""}
            )

        instance.delete()
```

- [ ] **Step 4: Register the admin**

Append to `apps/stock/admin.py`:

```python
@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = [
        "reference",
        "created_at",
        "type",
        "reason",
        "supplier_name",
        "line_count",
        "total_quantity",
        "user_name",
    ]
    list_filter = ["type", "reason"]
    search_fields = ["reference", "user_reference", "supplier_name"]
    # Immutable, like the movements it heads.
    readonly_fields = [f.name for f in StockTransaction._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

Add `StockTransaction` to the `apps.stock.models` import.

Also register the sequence in `apps/common/admin.py` — create the file:

```python
from django.contrib import admin

from apps.common.models import DocumentSequence


@admin.register(DocumentSequence)
class DocumentSequenceAdmin(admin.ModelAdmin):
    list_display = ["prefix", "year", "last_number"]
    # Visible for support, never editable: hand-editing a counter mints a
    # duplicate reference the next time a document is created.
    readonly_fields = ["prefix", "year", "last_number"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
```

- [ ] **Step 5: Update the README**

In the endpoints table, add the three routes:

```
| `/api/stock/transactions/` | GET, POST | gérant |
| `/api/stock/transactions/{id}/` | GET | — |
```

And add a short section, in the README's existing French and tone, covering:
that a transaction is immutable and a correction is a new compensating one;
that `reference` is the generated `TR-YYYY-NNNN` while `userReference` is the
user's own delivery-note number; and that the sequence resets each calendar
year in `SHOP_TIME_ZONE`.

- [ ] **Step 6: Verify the wire format**

Start the server against a scratch database, as sub-project 2's Task 12 did,
then check the two payloads against `types/domain.ts`:

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8391/api/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"email":"...","password":"..."}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["accessToken"])')

curl -s http://127.0.0.1:8391/api/stock/transactions/ -H "Authorization: Bearer $TOKEN" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(sorted(d)); print(sorted(d["results"][0]))'
```

Confirm: the list envelope is exactly `['count','next','previous','results']`;
a row carries `reference` and `userReference` as separate keys; the detail
route adds `lines`, each with `movementId` and a nested `article`; and a
movement created as part of a transaction reports a non-null `transactionId`
while `saleId` stays `null`.

- [ ] **Step 7: Final checks and commit**

```bash
~/.pyenv/versions/stock/bin/python manage.py check
~/.pyenv/versions/stock/bin/python manage.py makemigrations --check --dry-run
~/.pyenv/versions/stock/bin/pytest -p no:warnings
git add apps/catalogue apps/stock apps/common README.md
git commit -m "Guard supplier deletion against transactions, register admin"
```

Report the actual test count from the output; do not estimate it.

---

## Notes for the reviewer

Things a passing suite does not prove:

- **The atomic guard earns its keep.** `next_reference` raises outside a
  transaction. Confirm `create_transaction` is what opens the block, not the
  view — if the view opened it, the guard would pass while the rollback
  property quietly depended on a caller nobody checks.
- **`stock_transaction`, not `transaction`.** Grep `apps/stock/services.py`
  for a local binding named `transaction`; the module imports
  `django.db.transaction` under that name and uses it as a decorator.
- **The `lines` error key.** `allow_empty=False` would produce
  `lines.nonFieldErrors`, which no form field is mounted on, so the user sees
  nothing. The test asserting the exact `lines` key is the only thing standing
  between that and a silent failure.
- **Query-count bounds.** If either was raised, check it does not grow with
  the number of rows or lines. Growth means a missing `select_related` and the
  bound was raised to hide it.
- **`line_count` / `total_quantity` are denormalised** and correct only
  because a transaction is immutable. Any future edit path must recompute
  them.

---

## Follow-ups

Recorded during execution. None blocks merge.

- **`DocumentSequence` is not scoped by site.** `(prefix, year)` is unique, so
  a genuine multi-site deployment would hand two shops the same
  `TR-2026-0001`. Harmless under the standing one-Site decision, and the fix
  is a third column plus a migration — but it is a decision the multi-site
  migration must not overlook.
- **Three hand-rolled `get_permissions`.** `MovementViewSet`,
  `TransactionViewSet` and `UserViewSet` each spell out their own map because
  none can subclass `CatalogueViewSet` — they use different mixin sets. The
  read/manager-writes split is now written three times. A small
  `RoleScopedPermissionMixin` would collapse them, and sub-project 4 will add
  a fourth.
- **The transaction list ignores `?ordering=` entirely.** It is fixed to
  `-createdAt`, matching `listTransactions`, and `AliasedOrderingFilter` is
  not on the viewset — so an unexpected `?ordering=` is silently dropped
  rather than 400ing, unlike `/api/articles/`. Same inconsistency as the
  `UserViewSet` item carried over from sub-project 2.
- **Creation is serialised by the sequence lock.** Holding it until commit is
  what makes the numbering gapless, and it is free at one shop's volume. Worth
  re-examining only if this backend ever serves many sites.
- **Carried over from sub-project 2, still open:** the stock-status rule has
  four encodings kept in step only by tests; `low_stock_queryset`'s first `Q`
  is redundant; `UserViewSet` still uses DRF's `OrderingFilter`.
