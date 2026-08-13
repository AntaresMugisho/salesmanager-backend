# Offline backend (sub-project 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a disconnected device record sales and stock transactions that
carry their own final reference numbers, and replay them to the server exactly
once, without the server's stock guard rejecting them.

**Architecture:** A device registers once and is assigned a short code (`C1`,
`C2`, …). Documents it records offline are numbered locally in its own series
(`FA-C2-2026-0007`). At sync it POSTs to the ordinary create endpoints with two
extra HTTP headers — `X-Device-Code` and `Idempotency-Key` — plus a
`reference` in the body. The presence of that trio *is* the offline path: it
switches off server-side reference allocation, switches off the stock
sufficiency guard, and makes the create idempotent. The online path is
byte-for-byte unchanged.

**Tech Stack:** Django 6.0.7, DRF, `djangorestframework-camel-case`,
PostgreSQL, pytest + factory_boy, `uv`.

**Spec:** `../../../stockmanager-frontend/docs/superpowers/specs/2026-08-12-offline-first-decomposition.md`
(sibling repo; the "Decisions" and "Sub-project 1" sections are what this plan
implements)

## Global Constraints

- **Run everything through `uv`.** Tests: `.venv/bin/pytest`. Never `pip`.
- **The full suite is ~892 tests and takes ~14 minutes.** Run targeted
  node IDs during a task; run the full suite once at the end of the plan.
- **camelCase at the boundary, snake_case inside.**
  `djangorestframework-camel-case` converts both directions automatically —
  write `client_uuid` in Python and it is `clientUuid` in JSON. Never hand-
  write a camelCase key in a serializer field name.
- **Money is integer cents.** Not touched by this plan, but do not "fix" any
  integer amount you meet.
- **User-facing strings are French**, wrapped in `gettext_lazy as _`.
  Validation messages included. Existing messages show the register: full
  sentences, « guillemets » where quoting, no exclamation marks.
- **`select_for_update` is a silent no-op on SQLite.** It is real only on
  PostgreSQL. Write it anyway; that is the established convention here
  (`apps/common/sequences.py` documents why).
- **Reference column is `max_length=20`.** `FA-C2-2026-0007` is 15 characters;
  the format has room for a three-digit device number.
- **Never allocate a sequence number outside `transaction.atomic()`.**
  `_next_number` raises `RuntimeError` if you do.

---

## File Structure

**New files**

| File | Responsibility |
|---|---|
| `apps/accounts/models.py` (append) | `Device` — install id, assigned code, label |
| `apps/accounts/serializers.py` (append) | `DeviceRegisterSerializer`, `DeviceSerializer` |
| `apps/accounts/views.py` (append) | `DeviceRegisterView` |
| `apps/common/references.py` | Parse and validate a device-series reference |
| `apps/accounts/tests/test_device_model.py` | Code allocation, uniqueness |
| `apps/accounts/tests/test_device_register.py` | The endpoint |
| `apps/common/tests/test_references.py` | The validator, in isolation |
| `apps/sales/tests/test_offline_sales.py` | Offline create: reference, replay, negative stock |
| `apps/stock/tests/test_offline_transactions.py` | Same for transactions |

**Modified**

| File | Change |
|---|---|
| `apps/common/sequences.py` | `next_device_code()` |
| `apps/stock/models.py:29,89,90` | Three `PositiveIntegerField` → `IntegerField` |
| `apps/stock/services.py:26` | `apply_movement(..., allow_negative=False)` |
| `apps/stock/services.py:~125` | `create_transaction(..., reference=, client_uuid=, allow_negative=)` |
| `apps/sales/services.py:25` | `create_sale(..., reference=, client_uuid=, allow_negative=)` |
| `apps/sales/models.py` | `client_uuid` column |
| `apps/stock/models.py` | `client_uuid` column on `StockTransaction` |
| `apps/sales/views.py:83` | Read the two headers in `create` |
| `apps/stock/views.py` | Same for the transaction create |
| `apps/accounts/urls.py` | `devices/register/` |

**Deliberately unchanged:** `SaleCreateSerializer` and
`TransactionCreateSerializer` gain a `document_reference` field but no sync
plumbing — device code and idempotency key are headers, so the serializers the
online path uses keep their present shape.

**Why `document_reference` and not `reference`:**
`TransactionCreateSerializer` **already has a field called `reference`**
(`apps/stock/serializers.py:149`), and it means something else entirely — the
supplier's delivery-note number, which the view passes as
`user_reference=data.get("reference")`. A second field named `reference` there
would collide. The sales serializer has no such clash, but the name is kept
identical on both so the client's outbox has one field name for one concept.
In JSON both are `documentReference`.

---

### Task 1: Device model and code allocation

**Files:**
- Modify: `apps/common/sequences.py`
- Modify: `apps/accounts/models.py`
- Create: `apps/accounts/migrations/000N_device.py` (generated)
- Test: `apps/accounts/tests/test_device_model.py`

**Interfaces:**
- Consumes: `apps.common.sequences._next_number`, `apps.common.models.UUIDModel`
- Produces:
  - `apps.common.sequences.next_device_code() -> str` — returns `"C1"`, `"C2"`, …
  - `apps.accounts.models.Device` with fields `install_id: UUID (unique)`,
    `code: str (unique, max_length=8)`, `label: str (max_length=60)`,
    `last_seen_at: datetime | None`

- [ ] **Step 1: Write the failing test**

Create `apps/accounts/tests/test_device_model.py`:

```python
"""Device registration primitives: code allocation and the model."""

import uuid

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import Device
from apps.common.sequences import next_device_code

pytestmark = pytest.mark.django_db


def test_codes_are_allocated_in_order():
    with transaction.atomic():
        first = next_device_code()
        second = next_device_code()

    assert first == "C1"
    assert second == "C2"


def test_allocation_requires_an_open_transaction():
    with pytest.raises(RuntimeError, match="atomic"):
        next_device_code()


def test_install_id_is_unique():
    install_id = uuid.uuid4()
    Device.objects.create(install_id=install_id, code="C1", label="Caisse 1")

    with pytest.raises(IntegrityError):
        Device.objects.create(install_id=install_id, code="C2", label="Caisse 2")


def test_code_is_unique():
    Device.objects.create(install_id=uuid.uuid4(), code="C1", label="Caisse 1")

    with pytest.raises(IntegrityError):
        Device.objects.create(install_id=uuid.uuid4(), code="C1", label="Caisse 2")


def test_str_is_code_and_label():
    device = Device.objects.create(
        install_id=uuid.uuid4(), code="C2", label="Caisse principale"
    )

    assert str(device) == "C2 — Caisse principale"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest apps/accounts/tests/test_device_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'Device'`

- [ ] **Step 3: Add the code allocator**

In `apps/common/sequences.py`, below `SKU_YEAR`, add the prefix constant:

```python
#: Device codes share the counter table on the same terms as SKUs: a till does
#: not belong to a financial year either. Registration is rare, but it is the
#: one moment two devices could collide, and this is already the module that
#: hands out a monotonic integer under a row lock.
DEVICE_PREFIX = "DEV"
DEVICE_YEAR = 0
```

And below `next_sku()`:

```python
def next_device_code() -> str:
    """Allocate the next device code, `C1`, `C2`, …

    Unpadded deliberately: the code is printed inside a reference on a
    customer's receipt (`FA-C2-2026-0007`), where `C0002` would be noise.
    """
    return f"C{_next_number(DEVICE_PREFIX, DEVICE_YEAR)}"
```

- [ ] **Step 4: Add the model**

In `apps/accounts/models.py`, append (after `Site`):

```python
class Device(UUIDModel):
    """One installation of the app that can record documents offline.

    `install_id` is minted on the device and is what makes registration
    idempotent — a device that re-registers gets its existing code back rather
    than a second one. `code` is assigned by the server so it is unique by
    construction, which is what lets every reference the device ever emits be
    unique without further coordination.
    """

    install_id = models.UUIDField(_("identifiant d'installation"), unique=True)
    code = models.CharField(_("code"), max_length=8, unique=True)
    label = models.CharField(_("libellé"), max_length=60)
    last_seen_at = models.DateTimeField(_("vu pour la dernière fois"), null=True, blank=True)

    class Meta:
        verbose_name = _("appareil")
        verbose_name_plural = _("appareils")
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} — {self.label}"
```

Check the imports at the top of the file already include `gettext_lazy as _`
and `UUIDModel`. They do — `Site` uses both.

- [ ] **Step 5: Generate the migration**

Run: `uv run python manage.py makemigrations accounts`
Expected: `Create model Device`

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest apps/accounts/tests/test_device_model.py -v`
Expected: 5 passed

- [ ] **Step 7: Commit**

```bash
git add apps/common/sequences.py apps/accounts/models.py \
        apps/accounts/migrations/ apps/accounts/tests/test_device_model.py
git commit -m "Add Device model and server-assigned device codes"
```

---

### Task 2: Registration endpoint

**Files:**
- Modify: `apps/accounts/serializers.py`
- Modify: `apps/accounts/views.py`
- Modify: `apps/accounts/urls.py`
- Test: `apps/accounts/tests/test_device_register.py`

**Interfaces:**
- Consumes: `Device`, `next_device_code()` from Task 1
- Produces: `POST /api/devices/register/`, body `{installId, label}`,
  responds `201 {id, code, label}` on first call and `200 {id, code, label}`
  on re-registration.

- [ ] **Step 1: Write the failing test**

Create `apps/accounts/tests/test_device_register.py`:

```python
"""POST /api/devices/register/ — called once per installation."""

import uuid

import pytest

from apps.accounts.models import Device

pytestmark = pytest.mark.django_db

URL = "/api/devices/register/"


def body(**overrides):
    payload = {"installId": str(uuid.uuid4()), "label": "Caisse principale"}
    payload.update(overrides)
    return payload


def test_first_registration_assigns_a_code(auth_client, cashier):
    response = auth_client(cashier).post(URL, body(), format="json")

    assert response.status_code == 201
    assert response.data["code"] == "C1"
    assert response.data["label"] == "Caisse principale"


def test_second_device_gets_the_next_code(auth_client, cashier):
    client = auth_client(cashier)
    client.post(URL, body(), format="json")

    response = client.post(URL, body(label="Caisse 2"), format="json")

    assert response.status_code == 201
    assert response.data["code"] == "C2"


def test_re_registration_returns_the_existing_code(auth_client, cashier):
    client = auth_client(cashier)
    install_id = str(uuid.uuid4())
    first = client.post(URL, body(installId=install_id), format="json")

    second = client.post(URL, body(installId=install_id), format="json")

    assert second.status_code == 200
    assert second.data["code"] == first.data["code"]
    assert Device.objects.count() == 1


def test_re_registration_updates_the_label(auth_client, cashier):
    client = auth_client(cashier)
    install_id = str(uuid.uuid4())
    client.post(URL, body(installId=install_id), format="json")

    response = client.post(
        URL, body(installId=install_id, label="Caisse du fond"), format="json"
    )

    assert response.data["label"] == "Caisse du fond"


def test_label_is_required(auth_client, cashier):
    response = auth_client(cashier).post(
        URL, {"installId": str(uuid.uuid4())}, format="json"
    )

    assert response.status_code == 400
    assert "label" in response.data


def test_anonymous_is_refused(api_client):
    response = api_client.post(URL, body(), format="json")

    assert response.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest apps/accounts/tests/test_device_register.py -v`
Expected: FAIL — all 404, the route does not exist

- [ ] **Step 3: Add the serializers**

In `apps/accounts/serializers.py`, append:

```python
class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = ["id", "code", "label"]


class DeviceRegisterSerializer(serializers.Serializer):
    install_id = serializers.UUIDField()
    label = serializers.CharField(max_length=60)
```

Add `Device` to the `apps.accounts.models` import at the top of the file.

- [ ] **Step 4: Add the view**

In `apps/accounts/views.py`, append:

```python
class DeviceRegisterView(APIView):
    """Assign this installation its numbering-series code.

    Idempotent on `install_id`: a device that reinstalls the app keeps its
    code, and a device that calls twice does not consume two. Any signed-in
    user may register the till they are standing at.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DeviceRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with transaction.atomic():
            device = Device.objects.filter(install_id=data["install_id"]).first()
            if device:
                device.label = data["label"]
                device.last_seen_at = timezone.now()
                device.save(update_fields=["label", "last_seen_at", "updated_at"])
                return Response(DeviceSerializer(device).data, status=200)

            device = Device.objects.create(
                install_id=data["install_id"],
                code=next_device_code(),
                label=data["label"],
                last_seen_at=timezone.now(),
            )

        return Response(DeviceSerializer(device).data, status=201)
```

Add to that file's imports, matching whatever import style is already there:

```python
from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.accounts.models import Device
from apps.accounts.serializers import DeviceRegisterSerializer, DeviceSerializer
from apps.common.sequences import next_device_code
```

Several of these are likely present already — check before adding, and do not
create a duplicate import line.

- [ ] **Step 5: Route it**

In `apps/accounts/urls.py`, add `DeviceRegisterView` to the import from
`apps.accounts.views`, then add to `urlpatterns` above the `include(router.urls)`
entry (which is a catch-all and must stay last):

```python
    path("devices/register/", DeviceRegisterView.as_view(), name="device-register"),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest apps/accounts/tests/test_device_register.py -v`
Expected: 6 passed

- [ ] **Step 7: Commit**

```bash
git add apps/accounts/
git commit -m "Add POST /api/devices/register/"
```

---

### Task 3: Let stock go negative

This is the task the decomposition spec underestimated. `StockLevel.quantity`,
`StockMovement.quantity_before` and `StockMovement.quantity_after` are
`PositiveIntegerField`. Relaxing the guard in `apply_movement` without changing
the columns produces an `IntegrityError` instead of a validation error — the
constraint is in PostgreSQL, not in Python.

**Files:**
- Modify: `apps/stock/models.py:29,89,90`
- Modify: `apps/stock/services.py:26`
- Create: `apps/stock/migrations/000N_allow_negative_stock.py` (generated)
- Test: `apps/stock/tests/test_apply_movement.py` (append)

**Interfaces:**
- Produces: `apply_movement(..., allow_negative: bool = False)`. When True, an
  `OUT` whose quantity exceeds the level on hand posts anyway and drives the
  level negative. Default False, so every existing caller is unaffected.

- [ ] **Step 1: Write the failing test**

Append to `apps/stock/tests/test_apply_movement.py` (reuse the factories and
fixtures already imported at the top of that file; do not re-import):

```python
def test_out_beyond_stock_is_refused_by_default(site, cashier):
    article = ArticleFactory()
    StockLevelFactory(article=article, site=site, quantity=3)

    with pytest.raises(serializers.ValidationError) as excinfo:
        apply_movement(
            article=article, site=site, type="OUT", reason="SALE",
            quantity=5, user=cashier,
        )

    assert "quantity" in excinfo.value.detail


def test_allow_negative_posts_the_movement_anyway(site, cashier):
    article = ArticleFactory()
    StockLevelFactory(article=article, site=site, quantity=3)

    movement = apply_movement(
        article=article, site=site, type="OUT", reason="SALE",
        quantity=5, user=cashier, allow_negative=True,
    )

    assert movement.quantity_before == 3
    assert movement.quantity_after == -2
    assert movement.quantity == 5


def test_allow_negative_writes_the_negative_level(site, cashier):
    article = ArticleFactory()
    StockLevelFactory(article=article, site=site, quantity=3)

    apply_movement(
        article=article, site=site, type="OUT", reason="SALE",
        quantity=5, user=cashier, allow_negative=True,
    )

    level = StockLevel.objects.get(article=article, site=site)
    assert level.quantity == -2


def test_allow_negative_from_a_level_that_does_not_exist(site, cashier):
    article = ArticleFactory()

    movement = apply_movement(
        article=article, site=site, type="OUT", reason="SALE",
        quantity=2, user=cashier, allow_negative=True,
    )

    assert movement.quantity_before == 0
    assert movement.quantity_after == -2


def test_allow_negative_does_not_affect_in_movements(site, cashier):
    article = ArticleFactory()
    StockLevelFactory(article=article, site=site, quantity=3)

    movement = apply_movement(
        article=article, site=site, type="IN", reason="PURCHASE",
        quantity=5, user=cashier, allow_negative=True,
    )

    assert movement.quantity_after == 8
```

Check the file's existing imports include `StockLevel` and `serializers`; add
whichever is missing to the existing import block.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest apps/stock/tests/test_apply_movement.py -v -k negative`
Expected: FAIL — `apply_movement() got an unexpected keyword argument 'allow_negative'`

- [ ] **Step 3: Widen the columns**

In `apps/stock/models.py`, change exactly three fields. `StockLevel.quantity`
(line 29):

```python
    # Signed, not Positive: a sale recorded offline is replayed after the fact
    # and may find the shelf already empty. Refusing it then helps nobody —
    # the money has changed hands. The discrepancy is surfaced for correction
    # instead. `reorder_threshold` below stays Positive; a negative threshold
    # is meaningless.
    quantity = models.IntegerField(_("quantité"), default=0)
```

`StockMovement.quantity_before` and `quantity_after` (lines 89-90):

```python
    quantity_before = models.IntegerField(_("quantité avant"))
    quantity_after = models.IntegerField(_("quantité après"))
```

Leave `StockMovement.quantity` (line 88) as `PositiveIntegerField` — it is a
magnitude, and it is never negative in any path.

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations stock`
Expected: three `Alter field` operations. Confirm it did **not** pick up
`StockMovement.quantity` or `reorder_threshold`.

- [ ] **Step 5: Add the parameter**

In `apps/stock/services.py`, add to `apply_movement`'s keyword-only signature
after `field_prefix`:

```python
    allow_negative: bool = False,
```

Document it in the docstring, after the `field_prefix` paragraph:

```
    `allow_negative` switches off the sufficiency check for OUT. It is set
    only by a write replayed from a device's offline queue: that sale already
    happened, so the honest record is a negative level someone corrects, not
    a refusal nobody can act on. Every online caller leaves it False.
```

Then change the `OUT` branch:

```python
    elif type == StockMovement.Type.OUT:
        if quantity > quantity_before and not allow_negative:
            raise serializers.ValidationError(
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest apps/stock/tests/test_apply_movement.py -v`
Expected: all pass, including the pre-existing tests

- [ ] **Step 7: Run the stock and sales suites**

Run: `.venv/bin/pytest apps/stock apps/sales -q`
Expected: all pass. These are the two apps whose fixtures touch quantities; a
failure here means the field change broke an assumption elsewhere, and it must
be understood, not worked around.

- [ ] **Step 8: Commit**

```bash
git add apps/stock/
git commit -m "Allow stock levels to go negative for replayed offline writes"
```

---

### Task 4: The reference validator

**Files:**
- Create: `apps/common/references.py`
- Test: `apps/common/tests/test_references.py`

**Interfaces:**
- Produces: `apps.common.references.validate_device_reference(reference: str,
  *, prefix: str, device_code: str, field: str = "reference") -> str`.
  Returns the reference unchanged, or raises
  `rest_framework.serializers.ValidationError` keyed on `field`.

- [ ] **Step 1: Write the failing test**

Create `apps/common/tests/test_references.py`:

```python
"""Validation of references minted on a device."""

import pytest
from rest_framework import serializers

from apps.common.references import validate_device_reference


def test_accepts_a_well_formed_reference():
    result = validate_device_reference(
        "FA-C2-2026-0007", prefix="FA", device_code="C2"
    )

    assert result == "FA-C2-2026-0007"


def test_accepts_a_multi_digit_device_code():
    result = validate_device_reference(
        "TR-C12-2026-0001", prefix="TR", device_code="C12"
    )

    assert result == "TR-C12-2026-0001"


@pytest.mark.parametrize(
    "reference",
    [
        "FA-2026-0007",        # the shared server series, not a device one
        "FA-C2-2026-7",        # number not padded to four digits
        "FA-C2-26-0007",       # two-digit year
        "fa-c2-2026-0007",     # lowercase
        "FA-C2-2026-0007 ",    # trailing space
        "FA-X2-2026-0007",     # code not of the C<n> shape
        "",
    ],
)
def test_rejects_malformed_references(reference):
    with pytest.raises(serializers.ValidationError) as excinfo:
        validate_device_reference(reference, prefix="FA", device_code="C2")

    assert "reference" in excinfo.value.detail


def test_rejects_the_wrong_document_prefix():
    with pytest.raises(serializers.ValidationError):
        validate_device_reference("TR-C2-2026-0007", prefix="FA", device_code="C2")


def test_rejects_another_devices_series():
    with pytest.raises(serializers.ValidationError) as excinfo:
        validate_device_reference("FA-C3-2026-0007", prefix="FA", device_code="C2")

    assert "reference" in excinfo.value.detail


def test_error_is_keyed_on_the_named_field():
    with pytest.raises(serializers.ValidationError) as excinfo:
        validate_device_reference(
            "nonsense", prefix="FA", device_code="C2", field="lines.0.reference"
        )

    assert "lines.0.reference" in excinfo.value.detail
```

Check `apps/common/tests/` has an `__init__.py`; every other test package here
has one. Create it empty if missing.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest apps/common/tests/test_references.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.common.references`

- [ ] **Step 3: Write the validator**

Create `apps/common/references.py`:

```python
"""Validation of references a device minted for itself while offline.

The server allocates `FA-YYYY-NNNN` under a row lock. A device offline cannot
reach that lock, so it numbers documents in a series of its own,
`FA-C2-YYYY-NNNN`, which no other device and no server allocation can collide
with. Nothing here allocates: by the time a reference reaches this module it
is already printed on a customer's receipt. This only checks that a device is
writing where it is entitled to write.
"""

import re

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

#: `FA-C2-2026-0007`. Anchored, and the number is exactly four digits: the
#: device pads its counter the same way `next_reference` does, so a reference
#: that does not match was not minted by our client.
DEVICE_REFERENCE = re.compile(r"^(?P<prefix>[A-Z]{2})-(?P<code>C\d+)-\d{4}-\d{4}$")


def validate_device_reference(
    reference: str,
    *,
    prefix: str,
    device_code: str,
    field: str = "reference",
) -> str:
    """Return `reference` if this device may write it, else raise.

    Two ways to fail, kept separate because they mean different things: a
    malformed reference is a client bug, while a well-formed reference in
    another device's series is a client writing outside its own numbering —
    the one thing that could produce a duplicate number on two receipts.
    """
    match = DEVICE_REFERENCE.match(reference or "")

    if not match or match.group("prefix") != prefix:
        raise serializers.ValidationError(
            {field: [_("Référence invalide pour un document hors ligne.")]}
        )

    if match.group("code") != device_code:
        raise serializers.ValidationError(
            {
                field: [
                    _("La référence « %(reference)s » n'appartient pas à la "
                      "série de cet appareil.")
                    % {"reference": reference}
                ]
            }
        )

    return reference
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest apps/common/tests/test_references.py -v`
Expected: 12 passed (7 of them parametrised)

- [ ] **Step 5: Commit**

```bash
git add apps/common/references.py apps/common/tests/
git commit -m "Add device-series reference validation"
```

---

### Task 5: Offline sales

**Files:**
- Modify: `apps/sales/models.py`
- Modify: `apps/sales/serializers.py`
- Modify: `apps/sales/services.py:25`
- Modify: `apps/sales/views.py:83`
- Create: `apps/sales/migrations/000N_sale_client_uuid.py` (generated)
- Test: `apps/sales/tests/test_offline_sales.py`

**Interfaces:**
- Consumes: `Device` (Task 1), `apply_movement(..., allow_negative=)` (Task 3),
  `validate_device_reference` (Task 4)
- Produces:
  - `Sale.client_uuid: UUID | None`, unique
  - `create_sale(..., reference: str | None = None, client_uuid=None,
    allow_negative: bool = False)`
  - `SaleCreateSerializer` gains an optional `document_reference` field
  - `POST /api/sales/` honours `X-Device-Code` and `Idempotency-Key`

- [ ] **Step 1: Write the failing test**

Create `apps/sales/tests/test_offline_sales.py`:

```python
"""Sales replayed from a device's offline queue."""

import uuid

import pytest

from apps.accounts.models import Device
from apps.catalogue.tests.factories import ArticleFactory
from apps.sales.models import Sale
from apps.stock.models import StockLevel
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db

URL = "/api/sales/"


@pytest.fixture
def device(db):
    return Device.objects.create(
        install_id=uuid.uuid4(), code="C2", label="Caisse principale"
    )


def stocked(site, quantity=100):
    article = ArticleFactory()
    StockLevelFactory(article=article, site=site, quantity=quantity)
    return article


def body(article, quantity=2, reference="FA-C2-2026-0007"):
    return {
        "customerId": None,
        "discount": 0,
        "discountRate": None,
        "note": None,
        "documentReference": reference,
        "lines": [
            {"articleId": str(article.id), "quantity": quantity, "unitPrice": 5_000}
        ],
    }


def headers(device, key=None):
    return {
        "HTTP_X_DEVICE_CODE": device.code,
        "HTTP_IDEMPOTENCY_KEY": str(key or uuid.uuid4()),
    }


def test_offline_sale_keeps_the_reference_it_arrived_with(
    auth_client, cashier, site, device
):
    article = stocked(site)

    response = auth_client(cashier).post(
        URL, body(article), format="json", **headers(device)
    )

    assert response.status_code == 201
    assert response.data["reference"] == "FA-C2-2026-0007"


def test_online_sale_is_still_server_numbered(auth_client, cashier, site):
    article = stocked(site)
    payload = body(article)
    del payload["documentReference"]

    response = auth_client(cashier).post(URL, payload, format="json")

    assert response.status_code == 201
    assert response.data["reference"].startswith("FA-2")
    assert "-C" not in response.data["reference"]


def test_replay_returns_the_same_sale_without_creating_a_second(
    auth_client, cashier, site, device
):
    article = stocked(site)
    client = auth_client(cashier)
    key = uuid.uuid4()

    first = client.post(URL, body(article), format="json", **headers(device, key))
    second = client.post(URL, body(article), format="json", **headers(device, key))

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.data["id"] == first.data["id"]
    assert Sale.objects.count() == 1


def test_replay_does_not_move_stock_twice(auth_client, cashier, site, device):
    article = stocked(site, quantity=10)
    client = auth_client(cashier)
    key = uuid.uuid4()

    client.post(URL, body(article), format="json", **headers(device, key))
    client.post(URL, body(article), format="json", **headers(device, key))

    assert StockLevel.objects.get(article=article, site=site).quantity == 8


def test_offline_sale_may_oversell(auth_client, cashier, site, device):
    article = stocked(site, quantity=1)

    response = auth_client(cashier).post(
        URL, body(article, quantity=3), format="json", **headers(device)
    )

    assert response.status_code == 201
    assert StockLevel.objects.get(article=article, site=site).quantity == -2


def test_online_sale_may_not_oversell(auth_client, cashier, site):
    article = stocked(site, quantity=1)
    payload = body(article, quantity=3)
    del payload["documentReference"]

    response = auth_client(cashier).post(URL, payload, format="json")

    assert response.status_code == 400
    assert StockLevel.objects.get(article=article, site=site).quantity == 1


def test_another_devices_reference_is_refused(auth_client, cashier, site, device):
    article = stocked(site)

    response = auth_client(cashier).post(
        URL,
        body(article, reference="FA-C9-2026-0007"),
        format="json",
        **headers(device),
    )

    assert response.status_code == 400
    assert Sale.objects.count() == 0


def test_unknown_device_code_is_refused(auth_client, cashier, site, device):
    article = stocked(site)

    response = auth_client(cashier).post(
        URL,
        body(article),
        format="json",
        HTTP_X_DEVICE_CODE="C99",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )

    assert response.status_code == 400
    assert Sale.objects.count() == 0


def test_reference_without_a_device_header_is_refused(auth_client, cashier, site):
    article = stocked(site)

    response = auth_client(cashier).post(URL, body(article), format="json")

    assert response.status_code == 400
    assert Sale.objects.count() == 0


def test_duplicate_reference_is_refused(auth_client, cashier, site, device):
    article = stocked(site)
    client = auth_client(cashier)
    client.post(URL, body(article), format="json", **headers(device))

    response = client.post(URL, body(article), format="json", **headers(device))

    assert response.status_code == 400
    assert Sale.objects.count() == 1
```

Note the last two tests together pin the intended behaviour: a *different*
idempotency key with the *same* reference is a client bug and must be refused,
while the *same* key is a replay and must succeed. `headers()` mints a fresh
key each call, which is what makes `test_duplicate_reference_is_refused` a
different request rather than a replay.

**That last test needs an explicit check to pass, not just the column's unique
constraint.** `SaleCreateSerializer` is a plain `serializers.Serializer`, not a
`ModelSerializer`, so it runs no uniqueness validation. Without the check added
in Step 6, a duplicate reference reaches Postgres and raises `IntegrityError`,
which DRF renders as **500, not 400** — and the test asserts 400. Step 6 adds
it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest apps/sales/tests/test_offline_sales.py -v`
Expected: FAIL — the `reference` field is rejected as unknown or silently
ignored, and the offline tests get a server-allocated reference

- [ ] **Step 3: Add the column**

In `apps/sales/models.py`, on `Sale`, below `reference`:

```python
    #: Set only on a sale replayed from a device's offline queue: it is the id
    #: the device gave the sale before it could reach the server, and it is
    #: what makes the replay idempotent. NULL for every online sale, and
    #: Postgres treats NULLs as distinct in a unique constraint — which is the
    #: property wanted here, and the opposite of the one that made
    #: `SKU_YEAR = 0` a sentinel rather than NULL.
    client_uuid = models.UUIDField(_("identifiant client"), null=True, blank=True, unique=True)
```

Run: `uv run python manage.py makemigrations sales`

- [ ] **Step 4: Accept the reference in the serializer**

In `apps/sales/serializers.py`, on `SaleCreateSerializer`, add:

```python
    # Present only on a replayed offline sale; the view refuses it without an
    # X-Device-Code header, and validates it against that device's series.
    # Named `document_reference` rather than `reference` to stay identical to
    # the transaction serializer, where plain `reference` is already taken by
    # the supplier's delivery-note number.
    document_reference = serializers.CharField(
        required=False, allow_null=True, max_length=20
    )
```

- [ ] **Step 5: Thread it through the service**

In `apps/sales/services.py`, add to `create_sale`'s keyword-only signature:

```python
    reference: str | None = None,
    client_uuid=None,
    allow_negative: bool = False,
```

Replace line 86:

```python
    reference = reference or next_reference("FA", shop_today().year)
```

Add `client_uuid=client_uuid,` to the `Sale.objects.create(...)` call, and
`allow_negative=allow_negative,` to the `apply_movement(...)` call inside the
line loop.

- [ ] **Step 6: Read the headers in the view**

In `apps/sales/views.py`, replace the body of `SaleViewSet.create`:

```python
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        device, client_uuid = resolve_offline_write(request)
        reference = data.get("document_reference")

        if reference and not device:
            raise serializers.ValidationError(
                {
                    "documentReference": [
                        _("Un numéro de document exige l'en-tête X-Device-Code.")
                    ]
                }
            )
        if reference:
            validate_device_reference(
                reference,
                prefix="FA",
                device_code=device.code,
                field="documentReference",
            )
            # Explicit, because SaleCreateSerializer is a plain Serializer and
            # validates no uniqueness of its own. Without this the duplicate
            # reaches the column's unique constraint and DRF renders the
            # IntegrityError as a 500. A device replaying with a fresh
            # idempotency key but a reference it already used is a client bug,
            # and it should read as one.
            if Sale.objects.filter(reference=reference).exists():
                raise serializers.ValidationError(
                    {
                        "documentReference": [
                            _("Ce numéro de document a déjà été enregistré.")
                        ]
                    }
                )

        if client_uuid:
            existing = sale_queryset().filter(client_uuid=client_uuid).first()
            if existing:
                # A replay: the queue is retrying a sale the server already
                # committed. Returning it — rather than 409 — is what lets the
                # client drain its queue after a sync that died half way.
                return Response(
                    SaleSerializer(existing, context=self.get_serializer_context()).data,
                    status=200,
                )

        sale = create_sale(
            lines=data["lines"],
            user=request.user,
            site=Site.objects.current(),
            customer=data.get("customer"),
            discount=data.get("discount", 0),
            discount_rate=data.get("discount_rate"),
            note=data.get("note"),
            reference=reference,
            client_uuid=client_uuid,
            allow_negative=bool(device),
        )

        annotated = sale_queryset().get(pk=sale.pk)
        return Response(
            SaleSerializer(annotated, context=self.get_serializer_context()).data,
            status=201,
        )
```

- [ ] **Step 7: Write the header helper**

Append to `apps/common/references.py`:

```python
def resolve_offline_write(request):
    """Return `(device, client_uuid)` for a write replayed from a queue.

    `(None, None)` for an ordinary online write, which is every request that
    sends neither header. A device code that names no registered device is an
    error rather than a silent fall-back to the online path: it would other-
    wise allocate a server reference for a sale whose receipt is already
    printed with a different number.
    """
    from apps.accounts.models import Device

    code = request.headers.get("X-Device-Code")
    key = request.headers.get("Idempotency-Key")

    if not code:
        return None, None

    device = Device.objects.filter(code=code).first()
    if device is None:
        raise serializers.ValidationError(
            {"deviceCode": [_("Appareil inconnu. Enregistrez-le à nouveau.")]}
        )

    return device, key or None
```

The `Device` import is deferred to the function body to keep
`apps.common` from importing `apps.accounts` at module scope — `common` is
imported by every app and a top-level import would make the dependency
circular.

Add the imports the view now needs to `apps/sales/views.py`:

```python
from rest_framework import serializers

from apps.common.references import resolve_offline_write, validate_device_reference
from apps.sales.models import Customer, Sale   # `Sale` is new; `Customer` is already imported
```

The file imports `from apps.sales.models import Customer` today — extend that
line rather than adding a second import from the same module. `serializers` is
not currently imported there; `filters` and `mixins` are, from the same
package.

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/pytest apps/sales/tests/test_offline_sales.py -v`
Expected: 10 passed

- [ ] **Step 9: Run the whole sales suite**

Run: `.venv/bin/pytest apps/sales -q`
Expected: all pass — the online path must be untouched

- [ ] **Step 10: Commit**

```bash
git add apps/sales/ apps/common/references.py
git commit -m "Accept device-numbered, idempotent sales from an offline queue"
```

---

### Task 6: Offline stock transactions

The same three mechanisms on the transaction endpoint. Written out rather than
cross-referenced, because the shapes differ in one dangerous way:
`TransactionCreateSerializer` **already has a field named `reference`**
(`apps/stock/serializers.py:149`) and it is the *supplier's delivery-note
number*, passed through as `user_reference=data.get("reference")` at
`apps/stock/views.py:194`. The offline document number is a different thing and
is called `document_reference`. Confusing the two writes a delivery-note number
into a customer-facing invoice reference.

Names verified by reading the code: `TransactionViewSet`,
`TransactionCreateSerializer`, `StockTransactionSerializer`, route
`/api/stock/transactions/` (registered with `basename="transaction"`). Unlike
the sale viewset, `TransactionViewSet.create` returns
`StockTransactionSerializer(header)` directly — there is no annotated re-read
to imitate.

**Files:**
- Modify: `apps/stock/models.py` (`StockTransaction`)
- Modify: `apps/stock/serializers.py`
- Modify: `apps/stock/services.py:~125`
- Modify: `apps/stock/views.py`
- Create: `apps/stock/migrations/000N_transaction_client_uuid.py` (generated)
- Test: `apps/stock/tests/test_offline_transactions.py`

**Interfaces:**
- Consumes: everything from Tasks 1, 3, 4, and `resolve_offline_write` added to
  `apps/common/references.py` in Task 5
- Produces: `StockTransaction.client_uuid`, and
  `create_transaction(..., reference=None, client_uuid=None, allow_negative=False)`

- [ ] **Step 1: Write the failing test**

Create `apps/stock/tests/test_offline_transactions.py`:

```python
"""Stock transactions replayed from a device's offline queue."""

import uuid

import pytest

from apps.accounts.models import Device
from apps.catalogue.tests.factories import ArticleFactory
from apps.stock.models import StockLevel, StockTransaction
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db

URL = "/api/stock/transactions/"


@pytest.fixture
def device(db):
    return Device.objects.create(
        install_id=uuid.uuid4(), code="C2", label="Caisse principale"
    )


def stocked(site, quantity=100):
    article = ArticleFactory()
    StockLevelFactory(article=article, site=site, quantity=quantity)
    return article


def body(article, quantity=5, type="IN", reason="PURCHASE",
         reference="TR-C2-2026-0003"):
    return {
        "type": type,
        "reason": reason,
        "supplierId": None,
        # `reference` here is the supplier's delivery-note number, which is
        # what this endpoint has always meant by the word. The offline
        # document number is `documentReference`.
        "reference": None,
        "note": None,
        "documentReference": reference,
        "lines": [
            {"articleId": str(article.id), "quantity": quantity, "unitCost": 1_000}
        ],
    }


def headers(device, key=None):
    return {
        "HTTP_X_DEVICE_CODE": device.code,
        "HTTP_IDEMPOTENCY_KEY": str(key or uuid.uuid4()),
    }


def test_offline_transaction_keeps_its_reference(auth_client, manager, site, device):
    article = stocked(site)

    response = auth_client(manager).post(
        URL, body(article), format="json", **headers(device)
    )

    assert response.status_code == 201
    assert response.data["reference"] == "TR-C2-2026-0003"


def test_online_transaction_is_still_server_numbered(auth_client, manager, site):
    article = stocked(site)
    payload = body(article)
    del payload["documentReference"]

    response = auth_client(manager).post(URL, payload, format="json")

    assert response.status_code == 201
    assert "-C" not in response.data["reference"]


def test_replay_returns_the_same_transaction(auth_client, manager, site, device):
    article = stocked(site)
    client = auth_client(manager)
    key = uuid.uuid4()

    first = client.post(URL, body(article), format="json", **headers(device, key))
    second = client.post(URL, body(article), format="json", **headers(device, key))

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.data["id"] == first.data["id"]
    assert StockTransaction.objects.count() == 1


def test_replay_does_not_move_stock_twice(auth_client, manager, site, device):
    article = stocked(site, quantity=10)
    client = auth_client(manager)
    key = uuid.uuid4()

    client.post(URL, body(article), format="json", **headers(device, key))
    client.post(URL, body(article), format="json", **headers(device, key))

    assert StockLevel.objects.get(article=article, site=site).quantity == 15


def test_offline_out_transaction_may_go_negative(auth_client, manager, site, device):
    article = stocked(site, quantity=2)

    response = auth_client(manager).post(
        URL,
        body(article, quantity=5, type="OUT", reason="LOSS"),
        format="json",
        **headers(device),
    )

    assert response.status_code == 201
    assert StockLevel.objects.get(article=article, site=site).quantity == -3


def test_another_devices_reference_is_refused(auth_client, manager, site, device):
    article = stocked(site)

    response = auth_client(manager).post(
        URL,
        body(article, reference="TR-C9-2026-0003"),
        format="json",
        **headers(device),
    )

    assert response.status_code == 400
    assert StockTransaction.objects.count() == 0


def test_a_sale_reference_is_refused_on_a_transaction(
    auth_client, manager, site, device
):
    article = stocked(site)

    response = auth_client(manager).post(
        URL,
        body(article, reference="FA-C2-2026-0007"),
        format="json",
        **headers(device),
    )

    assert response.status_code == 400
    assert StockTransaction.objects.count() == 0
```

Add a duplicate-reference test matching the sale one, for the same reason —
`TransactionCreateSerializer` is also a plain `Serializer`:

```python
def test_duplicate_reference_is_refused(auth_client, manager, site, device):
    article = stocked(site)
    client = auth_client(manager)
    client.post(URL, body(article), format="json", **headers(device))

    response = client.post(URL, body(article), format="json", **headers(device))

    assert response.status_code == 400
    assert StockTransaction.objects.count() == 1
```

Cross-check the line field names (`unitCost`, `articleId`) against the existing
`apps/stock/tests/test_transactions_create.py` before running. That file is the
authority on this endpoint's body — if it disagrees, it is right and this is
wrong. Fix this file, not that one.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest apps/stock/tests/test_offline_transactions.py -v`
Expected: FAIL — the reference is ignored and server-allocated

- [ ] **Step 3: Add the column**

In `apps/stock/models.py`, on `StockTransaction`, below `reference`:

```python
    #: Set only on a transaction replayed from a device's offline queue. See
    #: the identical field on `Sale` for why NULL rather than a sentinel.
    client_uuid = models.UUIDField(_("identifiant client"), null=True, blank=True, unique=True)
```

Run: `uv run python manage.py makemigrations stock`

- [ ] **Step 4: Accept the reference in the serializer**

In `apps/stock/serializers.py`, on `TransactionCreateSerializer` (line 129),
add a field **beside** the existing `reference` at line 149 — do not modify or
replace it:

```python
    # The document's own number, present only on a replayed offline
    # transaction. The `reference` field above is a different thing entirely:
    # the supplier's delivery-note number, which the user types in.
    document_reference = serializers.CharField(
        required=False, allow_null=True, max_length=20
    )
```

- [ ] **Step 5: Thread it through the service**

In `apps/stock/services.py`, add to `create_transaction`'s keyword-only
signature:

```python
    reference: str | None = None,
    client_uuid=None,
    allow_negative: bool = False,
```

Note this function already has a `user_reference` parameter and a local
`cleaned_reference` derived from it. The new `reference` parameter is the
document's own number and must not touch either. Replace:

```python
    reference = next_reference("TR", shop_today().year)
```

with:

```python
    reference = reference or next_reference("TR", shop_today().year)
```

Leave the line below it alone — `reference=cleaned_reference or reference` in
the `apply_movement` call still means "the delivery-note number if the user
gave one, else the document's number", and that stays correct.

Add `client_uuid=client_uuid,` to `StockTransaction.objects.create(...)`, and
`allow_negative=allow_negative,` to the `apply_movement(...)` call in the line
loop.

- [ ] **Step 6: Read the headers in the view**

Replace `TransactionViewSet.create` (`apps/stock/views.py:183`) entirely:

```python
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        device, client_uuid = resolve_offline_write(request)
        document_reference = data.get("document_reference")

        if document_reference and not device:
            raise serializers.ValidationError(
                {
                    "documentReference": [
                        _("Un numéro de document exige l'en-tête X-Device-Code.")
                    ]
                }
            )
        if document_reference:
            validate_device_reference(
                document_reference,
                prefix="TR",
                device_code=device.code,
                field="documentReference",
            )
            if StockTransaction.objects.filter(reference=document_reference).exists():
                raise serializers.ValidationError(
                    {
                        "documentReference": [
                            _("Ce numéro de document a déjà été enregistré.")
                        ]
                    }
                )

        if client_uuid:
            existing = StockTransaction.objects.filter(client_uuid=client_uuid).first()
            if existing:
                return Response(StockTransactionSerializer(existing).data, status=200)

        header = create_transaction(
            type=data["type"],
            reason=data["reason"],
            lines=data["lines"],
            user=request.user,
            site=Site.objects.current(),
            supplier=data.get("supplier"),
            # Unchanged: the supplier's delivery-note number, not the
            # document's own reference.
            user_reference=data.get("reference"),
            note=data.get("note"),
            reference=document_reference,
            client_uuid=client_uuid,
            allow_negative=bool(device),
        )

        return Response(StockTransactionSerializer(header).data, status=201)
```

Add to that file's imports (`serializers` and `_` may already be present —
check before adding):

```python
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.common.references import resolve_offline_write, validate_device_reference
from apps.stock.models import StockTransaction
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/pytest apps/stock/tests/test_offline_transactions.py -v`
Expected: 8 passed

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass. This takes ~14 minutes; it is the last gate and worth it —
this plan changed three column types and two service signatures that the whole
codebase calls.

- [ ] **Step 9: Commit**

```bash
git add apps/stock/
git commit -m "Accept device-numbered, idempotent stock transactions"
```

---

## What this plan does not do

- **No sync endpoint.** The queue replays to the ordinary create endpoints one
  document at a time. A batch endpoint would need its own partial-failure
  semantics, and there is no evidence yet that per-document POSTs are too slow
  for a queue of a shift's sales.
- **No device management UI.** Registration is a client call; there is no list,
  rename or revoke. Sub-project 5 is where a device that has gone missing
  becomes visible.
- **No `last_seen_at` maintenance beyond registration.** The column exists so
  sub-project 5 has somewhere to write; nothing updates it on sync yet.
- **No negative-stock reporting.** Levels can now go below zero, and nothing
  surfaces that. Sub-project 5's job, and the reason it exists.

## Self-review notes

Five things checked against the code rather than assumed. The last three were
found by reviewing this plan against the source and each one had already been
written wrong:

1. `create_sale` already runs under `@transaction.atomic`, so the replay
   look-up and the create cannot interleave with a second request holding the
   same key. The unique constraint on `client_uuid` is the real guarantee; the
   look-up is the fast path that turns a race into a 200 instead of a 500.
2. `apps/common` must not import `apps.accounts` at module scope, hence the
   function-body import in `resolve_offline_write`.
3. **`StockLevel.quantity` was `PositiveIntegerField`**, along with
   `quantity_before` and `quantity_after`. Task 3 exists entirely because of
   this, and the decomposition spec did not anticipate it. Relaxing only the
   Python guard would have produced `IntegrityError`s in production and passing
   tests on SQLite.
4. **`TransactionCreateSerializer.reference` already exists** and means the
   supplier's delivery-note number. The first draft of Task 6 added a second
   field of the same name. Both new fields are `document_reference`.
5. **A duplicate reference would have been a 500, not a 400.** Both create
   serializers are plain `serializers.Serializer`, so neither validates
   uniqueness; the duplicate would have reached the column constraint. Tasks 5
   and 6 add an explicit existence check before calling the service.

Nothing is left for the executor to guess. Every class name, route and field
name in this plan was read from the source.
