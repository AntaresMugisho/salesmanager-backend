# Auto-generated article SKU — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Article.sku` a backend-allocated, immutable `ART-NNNNN`, removing the last hand-typed reference in the system.

**Architecture:** `apps/common/sequences.py` already serialises counter increments under a row lock inside the caller's transaction. Split its increment from its formatting so a second format can reuse the locking, then allocate in `Article.save()` — the same place `name_sort` is computed — so the API, the Django admin and the shell are all covered by one rule. The write serializer turns `sku` read-only and drops its uniqueness validator; the frontend drops the input.

**Tech Stack:** Django 6.0, Django REST Framework, `djangorestframework-camel-case`, pytest + pytest-django + factory_boy, uv. Frontend: Next.js 16, React 19, zod, react-hook-form, bun.

**Spec:** `docs/superpowers/specs/2026-08-11-article-sku-design.md`

## Global Constraints

- **Backend commands run through uv**, from `stockmanager-backend/`: `uv run pytest …`, `uv run python manage.py …`. `.venv/bin/pytest` is the equivalent direct path.
- **The full backend suite takes about 14 minutes.** Run the targeted files named in each task while working; run the whole suite once, at the end.
- **Frontend uses bun only** — never npm, yarn or npx.
- **No browser automation.** Verification is tests, typecheck, lint, build, and reading the diff. UI behaviour is checked by a human.
- **JSON is camelCase in both directions**, handled by `djangorestframework-camel-case`. Never hand-convert case.
- **User-facing strings are French.** Developer errors (`RuntimeError`) are English.
- **SKU format is `ART-` + the counter zero-padded to five digits.** `ART-00001`, widening past `ART-99999`.
- **The counter row is `DocumentSequence(prefix="ART", year=0)`.** `0` is a sentinel, not a year.
- Working branch is `feat/article-sku`, already created in the backend repo with the spec committed. Create a matching branch in the frontend repo at Task 5.

---

### Task 1: Allocate SKUs from the existing sequence machinery

**Files:**
- Modify: `apps/common/sequences.py` (whole file)
- Test: `apps/common/tests/test_sequences.py`

**Interfaces:**
- Consumes: `DocumentSequence` from `apps.common.models` (already imported).
- Produces: `next_sku() -> str`, importable as `from apps.common.sequences import next_sku`. Also `SKU_PREFIX = "ART"` and `SKU_YEAR = 0`. `next_reference(prefix: str, year: int) -> str` keeps its exact signature and output.

- [ ] **Step 1: Write the failing tests**

Add to `apps/common/tests/test_sequences.py`. Put `allocate_sku` next to the existing module-level `allocate` helper, and the new class after `TestSequencing`:

```python
def allocate_sku():
    with transaction.atomic():
        return next_sku()


class TestSku:
    """An article is not a document: its counter is not year-scoped."""

    def test_the_first_sku_is_one_padded_to_five_digits(self):
        assert allocate_sku() == "ART-00001"

    def test_consecutive_skus_increment(self):
        assert [allocate_sku() for _ in range(3)] == [
            "ART-00001",
            "ART-00002",
            "ART-00003",
        ]

    def test_padding_widens_past_five_digits(self):
        # update_or_create, not create: Task 2 adds a migration that seeds
        # this exact row, and from then on `create` would violate
        # `one_sequence_per_prefix_and_year`. This form works either way.
        DocumentSequence.objects.update_or_create(
            prefix="ART", year=0, defaults={"last_number": 99999}
        )
        assert allocate_sku() == "ART-100000"

    def test_skus_do_not_share_a_counter_with_documents(self):
        """The decoy: if next_sku reused the TR/FA counter, or passed the
        current year, this would come back as ART-00003 or ART-2026-0001."""
        allocate(prefix="TR", year=2026)
        allocate(prefix="TR", year=2026)
        assert allocate_sku() == "ART-00001"

    def test_a_rolled_back_sku_leaves_no_gap(self):
        allocate_sku()
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                next_sku()
                raise RuntimeError("something later in the write failed")
        assert allocate_sku() == "ART-00002"

    # `transaction=True` for the same reason as TestAtomicGuard below: the
    # ordinary django_db fixture already holds an atomic block open, so the
    # guard could never fire.
    @pytest.mark.django_db(transaction=True)
    def test_allocating_a_sku_outside_a_transaction_is_refused(self):
        with pytest.raises(RuntimeError, match="atomic"):
            next_sku()
```

Update the import at the top of the file:

```python
from apps.common.sequences import next_reference, next_sku
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest apps/common/tests/test_sequences.py -q`
Expected: collection error — `ImportError: cannot import name 'next_sku'`.

- [ ] **Step 3: Split increment from formatting and add `next_sku`**

Replace the body of `apps/common/sequences.py` below the module docstring. Keep the docstring, extending its first line to mention SKUs:

```python
"""Document reference and article SKU allocation.

`TR-YYYY-NNNN` for stock transactions, `FA-YYYY-NNNN` for sales invoices,
`ART-NNNNN` for article SKUs. One locking implementation, three formats.
"""

from django.db import connection

from apps.common.models import DocumentSequence

#: Article SKUs share the counter table but not its year-scoping: an article
#: does not belong to a financial year. Not NULL — Postgres treats NULLs as
#: distinct in a unique constraint, so a nullable year would permit two `ART`
#: rows and silently hand out duplicate numbers. 0 keeps
#: `one_sequence_per_prefix_and_year` doing its job, with no schema change.
SKU_PREFIX = "ART"
SKU_YEAR = 0


def _next_number(prefix: str, year: int) -> int:
    """Allocate and return the next raw counter value for `prefix`/`year`.

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
            "Sequence allocation must happen inside transaction.atomic()."
        )

    # get_or_create's documented IntegrityError-and-re-get path handles two
    # requests racing to create the first row of a year.
    sequence, _ = DocumentSequence.objects.get_or_create(prefix=prefix, year=year)

    locked = DocumentSequence.objects.select_for_update().get(pk=sequence.pk)
    locked.last_number += 1
    locked.save(update_fields=["last_number"])

    return locked.last_number


def next_reference(prefix: str, year: int) -> str:
    """Allocate the next `PREFIX-YYYY-NNNN`."""
    return f"{prefix}-{year}-{_next_number(prefix, year):04d}"


def next_sku() -> str:
    """Allocate the next `ART-NNNNN`."""
    return f"{SKU_PREFIX}-{_next_number(SKU_PREFIX, SKU_YEAR):05d}"
```

Note the `RuntimeError` message changed from naming `next_reference` to naming the operation, because two callers now raise it. The existing `TestAtomicGuard` matches on `"atomic"` and still passes — do not change that test.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest apps/common/tests/test_sequences.py -q`
Expected: PASS, including every pre-existing `next_reference` test unchanged. Those passing untouched is the evidence that the split was a refactor.

- [ ] **Step 5: Commit**

```bash
git add apps/common/sequences.py apps/common/tests/test_sequences.py
git commit -m "feat(sequences): allocate ART-NNNNN article SKUs

Split the locking increment out of next_reference so a second format can
reuse it. next_reference's signature and output are unchanged; its tests
pass untouched, which is what makes this a refactor."
```

---

### Task 2: Seed the counter past any legacy `ART-` SKU

**Files:**
- Create: `apps/catalogue/migrations/0003_seed_article_sku_sequence.py`

**Interfaces:**
- Consumes: nothing from Task 1 at runtime — the migration hardcodes `"ART"` and `0` rather than importing `SKU_PREFIX`/`SKU_YEAR`, because a migration must keep working if those constants are later renamed.
- Produces: a `DocumentSequence(prefix="ART", year=0)` row on every existing database.

Existing SKUs are never rewritten, so an article somebody already named `ART-7` is the one thing standing between the generator and an `IntegrityError` on `article_sku_unique_ci`.

- [ ] **Step 1: Write the migration**

```python
"""Seed the ART counter past any hand-typed `ART-<n>` SKU.

Legacy SKUs are kept as they are, so the generator must start above the
highest number already in use or its first allocation could collide with one.
"""

import re

from django.db import migrations

LEGACY_ART_SKU = re.compile(r"^ART-(\d+)$", re.IGNORECASE)


def seed_counter(apps, schema_editor):
    Article = apps.get_model("catalogue", "Article")
    DocumentSequence = apps.get_model("common", "DocumentSequence")

    highest = 0
    for sku in Article.objects.values_list("sku", flat=True):
        match = LEGACY_ART_SKU.match(sku or "")
        if match:
            highest = max(highest, int(match.group(1)))

    # get_or_create, not update_or_create: re-running must never wind an
    # existing counter backwards.
    DocumentSequence.objects.get_or_create(
        prefix="ART", year=0, defaults={"last_number": highest}
    )


def drop_counter(apps, schema_editor):
    DocumentSequence = apps.get_model("common", "DocumentSequence")
    DocumentSequence.objects.filter(prefix="ART", year=0).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("catalogue", "0002_add_name_sort"),
        ("common", "0001_initial"),
    ]

    operations = [migrations.RunPython(seed_counter, drop_counter)]
```

- [ ] **Step 2: Apply it to the dev database and read the counter back**

```bash
uv run python manage.py migrate
uv run python manage.py shell -c "from apps.common.models import DocumentSequence; print(list(DocumentSequence.objects.filter(prefix='ART').values()))"
```

Expected: one row, `{'prefix': 'ART', 'year': 0, 'last_number': N}` where `N` is the highest `ART-<digits>` number among existing articles, or `0` if none. **Report the actual number printed** — this migration has no honest unit test (migrations run against an empty test database, where the only assertable outcome is 0), so this output is the only evidence it works.

- [ ] **Step 3: Verify the migration is reversible and leaves no model drift**

```bash
uv run python manage.py migrate catalogue 0002
uv run python manage.py migrate
uv run python manage.py makemigrations --check --dry-run
```

Expected: both migrations run clean, and `makemigrations --check` reports no changes.

- [ ] **Step 4: Commit**

```bash
git add apps/catalogue/migrations/0003_seed_article_sku_sequence.py
git commit -m "feat(catalogue): seed the ART counter past legacy SKUs

Hand-typed SKUs are kept, so the generator must start above the highest
ART-<n> already in use."
```

---

### Task 3: Allocate the SKU in `Article.save()`

**Files:**
- Modify: `apps/catalogue/models.py` (imports, and the `Article` class)
- Modify: `apps/catalogue/tests/factories.py:40`
- Test: `apps/catalogue/tests/test_models.py`

**Interfaces:**
- Consumes: `next_sku()` from Task 1.
- Produces: `Article.save()` allocating a SKU when the row is new and `sku` is empty. Every later task depends on this: an `Article` created without a SKU has a generated one afterwards.

- [ ] **Step 1: Write the failing tests**

Add to `apps/catalogue/tests/test_models.py`, as a new class after `TestArticle`:

```python
class TestGeneratedSku:
    """The SKU is allocated once, at creation, and never changes."""

    def test_a_new_article_gets_a_generated_sku(self):
        article = Article.objects.create(
            name="Sucre blanc", category=CategoryFactory()
        )
        assert article.sku == "ART-00001"

    def test_consecutive_articles_get_consecutive_skus(self):
        category = CategoryFactory()
        first = Article.objects.create(name="Sucre", category=category)
        second = Article.objects.create(name="Farine", category=category)
        assert [first.sku, second.sku] == ["ART-00001", "ART-00002"]

    def test_an_explicit_sku_is_kept(self):
        """Legacy imports and the factories carry hand-typed references."""
        article = Article.objects.create(
            name="Sucre", category=CategoryFactory(), sku="EPI-001"
        )
        assert article.sku == "EPI-001"
        # Task 2's migration seeds this row at 0 on every database, including
        # the test one. Nothing here should have incremented it.
        assert DocumentSequence.objects.get(prefix="ART", year=0).last_number == 0

    def test_updating_an_article_does_not_allocate_a_new_number(self):
        """The decoy for `_state.adding`. Without that guard an update would
        burn a counter value, and the next article created would be ART-00003
        rather than ART-00002."""
        article = Article.objects.create(name="Sucre", category=CategoryFactory())
        article.name = "Sucre roux"
        article.save()

        article.refresh_from_db()
        assert article.sku == "ART-00001"
        assert DocumentSequence.objects.get(prefix="ART", year=0).last_number == 1
```

Add the import at the top of the file:

```python
from apps.common.models import DocumentSequence
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest apps/catalogue/tests/test_models.py -q`
Expected: FAIL. `test_a_new_article_gets_a_generated_sku` fails on `assert '' == 'ART-00001'`.

- [ ] **Step 3: Implement allocation in `save()`**

In `apps/catalogue/models.py`, add the import beneath the existing `apps.common.models` import:

```python
from apps.common.sequences import next_sku
```

Then add `save` to `Article`, between its `class Meta` block and `__str__`:

```python
    def save(self, **kwargs):
        # `_state.adding` is what makes the SKU immutable: an instance loaded
        # from the database never re-enters this branch, whatever a caller
        # does to the field. An explicit SKU is honoured so legacy rows and
        # the test factories can carry hand-typed references.
        #
        # next_sku raises outside an atomic block, so a bare
        # Article.objects.create() in a shell fails loudly rather than writing
        # a blank SKU. The API path is already @transaction.atomic and the
        # Django admin wraps its changeform view in one.
        if self._state.adding and not self.sku:
            self.sku = next_sku()
        super().save(**kwargs)
```

`super().save()` reaches `NameSortedModel.save()`, which computes `name_sort` — do not reorder those.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest apps/catalogue/tests/test_models.py -q`
Expected: PASS, including the pre-existing `test_skus_differing_only_in_case_collide`, which supplies explicit SKUs and is unaffected.

- [ ] **Step 5: Move the factory out of the generator's namespace**

`apps/catalogue/tests/factories.py:40` currently reads:

```python
    sku = factory.Sequence(lambda n: f"ART-{n:04d}")
```

Replace it with:

```python
    # Outside the generator's `ART-` namespace, and named for what it now
    # stands in for: a legacy hand-typed reference. Left as `ART-` it avoided
    # collision only by being four digits wide where the generator is five.
    sku = factory.Sequence(lambda n: f"LEG-{n:04d}")
```

- [ ] **Step 6: Run every test that builds articles**

Run: `uv run pytest apps/catalogue apps/stock apps/sales apps/reports -q`
Expected: PASS. Tests that assert on a specific SKU pass one explicitly and are unaffected; this run is what proves no test depended on the factory's old default.

- [ ] **Step 7: Commit**

```bash
git add apps/catalogue/models.py apps/catalogue/tests/factories.py apps/catalogue/tests/test_models.py
git commit -m "feat(catalogue): allocate the SKU in Article.save()

Model-level, like name_sort, so the API, the admin and the shell are all
covered by one rule. _state.adding is what makes it immutable."
```

---

### Task 4: Close the API and the admin

**Files:**
- Modify: `apps/catalogue/serializers.py` — `ArticleSerializer.Meta.read_only_fields`, and delete `validate_sku`
- Modify: `apps/catalogue/admin.py` — `ArticleAdmin`
- Test: `apps/catalogue/tests/test_articles_write.py`

**Interfaces:**
- Consumes: `Article.save()` from Task 3, and the seeded counter from Task 2.
- Produces: no new symbols. `POST`/`PATCH` on `/api/articles/` ignore any client-supplied `sku`; responses still carry it.

- [ ] **Step 1: Update the existing tests, and write the new failing ones**

Three edits to `apps/catalogue/tests/test_articles_write.py`:

**a.** In `payload()`, delete the line `"sku": "EPI-001",`. The helper's `**overrides` still lets a test inject one.

**b.** In `test_a_manager_can_create`, change the SKU assertion:

```python
        assert response.json()["sku"] == "ART-00001"
```

**c.** Delete `test_a_duplicate_sku_is_rejected_case_insensitively` entirely (in `TestValidation`). The validator it covers is being removed; the database constraint that replaces it is already covered by `test_skus_differing_only_in_case_collide` in `test_models.py`.

Then add to `TestCreate`:

```python
    def test_a_client_supplied_sku_is_ignored(self, auth_client, manager, site):
        """The decoy: asserting only the ART- pattern would still pass if the
        client's value were honoured whenever it happened to look generated."""
        category = CategoryFactory()
        response = auth_client(manager).post(
            LIST_URL, payload(category, sku="HACK-1"), format="json"
        )

        assert response.status_code == 201
        assert response.json()["sku"] == "ART-00001"
        assert not Article.objects.filter(sku="HACK-1").exists()

    def test_creating_without_a_sku_is_accepted(self, auth_client, manager, site):
        category = CategoryFactory()
        response = auth_client(manager).post(LIST_URL, payload(category), format="json")
        assert response.status_code == 201
```

And to `TestUpdate`:

```python
    def test_the_sku_cannot_be_changed(self, auth_client, manager, site):
        article = ArticleFactory(sku="LEG-0001")
        response = auth_client(manager).patch(
            detail_url(article), {"sku": "AUTRE-1"}, format="json"
        )

        assert response.status_code == 200
        article.refresh_from_db()
        assert article.sku == "LEG-0001"

    def test_a_generated_sku_cannot_be_changed(self, auth_client, manager, site):
        """Both paths, because a legacy SKU and a generated one reach the
        serializer through different histories."""
        article = Article.objects.create(name="Sucre", category=CategoryFactory())
        auth_client(manager).patch(
            detail_url(article), {"sku": "AUTRE-1"}, format="json"
        )
        article.refresh_from_db()
        assert article.sku == "ART-00001"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest apps/catalogue/tests/test_articles_write.py -q`
Expected: FAIL. `test_a_client_supplied_sku_is_ignored` returns `HACK-1`, and `test_creating_without_a_sku_is_accepted` returns 400 with « La référence est obligatoire. »

- [ ] **Step 3: Make `sku` read-only and delete its validator**

In `apps/catalogue/serializers.py`, in `ArticleSerializer.Meta`:

```python
        read_only_fields = ["id", "sku", "image_url", "created_at", "updated_at"]
```

`sku` stays in `fields` — that is what keeps it in every response.

Delete the whole `validate_sku` method:

```python
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
```

A value the client cannot send cannot be duplicated by a client, and `article_sku_unique_ci` remains as the backstop for anything reaching the model another way.

- [ ] **Step 4: Close the admin**

In `apps/catalogue/admin.py`, add one line to `ArticleAdmin`:

```python
@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ["sku", "name", "category", "sale_price", "is_active"]
    list_filter = ["is_active", "unit", "category"]
    search_fields = ["sku", "name", "barcode"]
    autocomplete_fields = ["category", "supplier"]
    # Without this the admin is a hole in a rule the rest of the system now
    # enforces. On the add form the field renders empty and read-only, and
    # save() fills it — the admin wraps its changeform view in a transaction,
    # which is what next_sku needs.
    readonly_fields = ["sku"]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest apps/catalogue/tests/test_articles_write.py -q`
Expected: PASS, with one fewer test than before (the deleted duplicate-SKU case).

- [ ] **Step 6: Commit**

```bash
git add apps/catalogue/serializers.py apps/catalogue/admin.py apps/catalogue/tests/test_articles_write.py
git commit -m "feat(api): make sku read-only and drop its validator

The client can no longer send a SKU, so it can no longer duplicate one.
article_sku_unique_ci stays as the backstop. The admin is closed too."
```

---

### Task 5: Remove the SKU input from the frontend

**Files** (all in `../stockmanager-frontend/`):
- Modify: `types/dto.ts` — `ArticleCreateDto`
- Modify: `features/articles/schema.ts` — `articleFormSchema`, `ARTICLE_FORM_DEFAULTS`
- Modify: `features/articles/components/article-form.tsx` — hydration map, submit map, the field itself

**Interfaces:**
- Consumes: the API from Task 4. `sku` is absent from every article write payload after this task.
- Produces: no new symbols. `ArticleUpdateDto` is `Partial<Omit<ArticleCreateDto, "initialQuantity">>` and follows automatically.

- [ ] **Step 1: Create the frontend branch**

```bash
cd ../stockmanager-frontend
git checkout -b feat/article-sku
```

- [ ] **Step 2: Drop `sku` from the DTO**

In `types/dto.ts`, delete the line `  sku: string;` from `ArticleCreateDto` (the first field of the interface).

- [ ] **Step 3: Drop `sku` from the form schema and defaults**

In `features/articles/schema.ts`, delete from `articleFormSchema`:

```typescript
    sku: z
      .string()
      .min(1, "La référence est obligatoire.")
      .max(32, "La référence ne peut pas dépasser 32 caractères."),
```

and from `ARTICLE_FORM_DEFAULTS` the line `  sku: "",`.

- [ ] **Step 4: Run the typechecker to find every remaining call site**

Run: `bun x tsc --noEmit`
Expected: FAIL, pointing at `article-form.tsx` — the hydration object and the `shared` submit object both still supply `sku`. This is the type system doing the work the spec relies on: a call site that still sends a SKU cannot compile.

- [ ] **Step 5: Update the form**

In `features/articles/components/article-form.tsx`:

**a.** In the `defaultValues` object, delete `          sku: article.sku,`.

**b.** In the `shared` object inside `onSubmit`, delete `      sku: values.sku,`.

**c.** Replace the whole SKU field block:

```tsx
          <div className="space-y-2">
            <Label htmlFor="sku">Référence (SKU)</Label>
            <Input
              id="sku"
              placeholder="ART-0001"
              aria-invalid={Boolean(errors.sku)}
              {...register("sku")}
            />
            {errors.sku ? (
              <p className="text-sm text-destructive">{errors.sku.message}</p>
            ) : null}
          </div>
```

with a read-only display. The cell is kept so the two-column grid does not reflow:

```tsx
          <div className="space-y-2">
            {/* Not a <Label>: there is no control to associate it with, which
                jsx-a11y/label-has-associated-control would flag. */}
            <p className="text-sm font-medium">Référence (SKU)</p>
            <p className="flex h-9 items-center text-sm text-muted-foreground">
              {article ? article.sku : "Générée automatiquement"}
            </p>
          </div>
```

- [ ] **Step 6: Run all four gates**

```bash
bun x tsc --noEmit
bun run lint
bun test
bun run build
```

Expected: all four clean. `bun test` should report the same count as before this task — no frontend test covers the article form.

- [ ] **Step 7: Commit**

```bash
git add types/dto.ts features/articles/schema.ts features/articles/components/article-form.tsx
git commit -m "feat(articles): drop the SKU input, the backend allocates it

The field becomes read-only text: « Générée automatiquement » on create,
the article's SKU on edit."
```

---

## Final verification

- [ ] **Backend, full suite** (about 14 minutes): `uv run pytest`
      Expected: all pass. Report the count.
- [ ] **No model drift**: `uv run python manage.py makemigrations --check --dry-run`
- [ ] **No `sku` left in any write path**: `grep -rn "sku" apps/catalogue/serializers.py` should show it only in `fields`, `read_only_fields` and `ArticleRefSerializer`. `grep -rn "sku" ../stockmanager-frontend/features/articles/` should show only reads — the table column, the detail header, and the form's read-only display.
- [ ] **Frontend**: `bun x tsc --noEmit`, `bun run lint`, `bun test`, `bun run build`.

## Known gaps, to state rather than paper over

- **The seeding migration has no unit test.** Migrations run against an empty test database, so a test could only assert that the counter seeds to 0. Task 2 Step 2's dev-database output is the evidence, and it must be reported as a number, not as "it worked".
- **`bulk_create` bypasses `save()`** and so allocates nothing. This mirrors `Site.save()`, whose invariant `bulk_create` already bypasses. Nothing in the codebase bulk-creates articles.
- **The admin add form is verified by reading the code, not by a test.** Writing a Django admin integration test for one `readonly_fields` entry costs more than it is worth; the risk if it is wrong is that an admin cannot create an article, which is loud rather than silent.

## Out of scope

- Regenerating `StockManager API.yaml`. It is already known to be stale — it mistypes `Article.stock` as a string — and the backend source is authoritative.
- Renumbering existing articles, or a management command to do so later.
- User management UI, the third feature requested alongside this one.
