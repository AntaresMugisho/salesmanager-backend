# Auto-generated article SKU — design

**Date:** 2026-08-11
**Status:** approved, ready for planning
**Repos:** `stockmanager-backend` (sections 1–4, 6), `stockmanager-frontend` (section 5)

Make `Article.sku` a backend-generated, immutable `ART-NNNNN`, so the catalogue
follows the rule the rest of the app already follows: a reference is allocated,
not typed.

## Context

Sales and stock transactions already get their references from the backend.
`apps/common/sequences.py` allocates `FA-YYYY-NNNN` and `TR-YYYY-NNNN` from a
single `DocumentSequence` counter row per `(prefix, year)`, under
`select_for_update` inside the caller's transaction.

`Article.sku` is the one reference still typed by a user. Today it is:

- required on create, and editable on update, in `ArticleSerializer`;
- validated by `validate_sku` — 14 lines of trimming, length and
  case-insensitive uniqueness checks with French error messages;
- guarded at the database by `UniqueConstraint(Lower("sku"), …)`;
- freely editable in the Django admin, which declares no `readonly_fields`.

## Decisions

Three choices frame everything below.

**The backend owns the SKU outright.** It is assigned once, at creation, and
never changes — like a sale's `FA-` reference. The field leaves the create and
edit forms entirely. A shop that needs its supplier's own reference has the
`barcode` field for that.

**The format is `ART-00001`, with no year.** An article is not a document: it
does not belong to a financial year, and a counter that resets each January
would say something untrue about the catalogue. This is the one place the SKU
diverges from `FA-`/`TR-`, and it is why section 1 exists.

**Existing hand-typed SKUs are never rewritten.** Anything already on a shelf
label or a supplier order stays valid. The cost is that two formats coexist in
the catalogue indefinitely, which is the correct trade: a uniform column is
worth less than a reference that still matches the physical world.

## 1. Allocation

`next_reference` currently does two jobs in one function: it serialises the
increment, and it formats the result. Only the formatting differs for SKUs, and
the serialisation is the part carrying the hard-won properties — the
open-transaction guard, the row lock, and the rollback that leaves no gap in
the sequence. Split them:

```python
def _next_number(prefix: str, year: int) -> int:
    """The existing body of next_reference, returning the raw counter."""

def next_reference(prefix: str, year: int) -> str:
    return f"{prefix}-{year}-{_next_number(prefix, year):04d}"

SKU_PREFIX = "ART"
#: Sentinel. `DocumentSequence` is keyed by (prefix, year) and an article has
#: no year. Not NULL: Postgres treats NULLs as distinct in a unique
#: constraint, so a nullable year would permit two `ART` counter rows and
#: silently hand out duplicate numbers. 0 keeps the constraint doing its job,
#: and needs no schema migration.
SKU_YEAR = 0

def next_sku() -> str:
    return f"{SKU_PREFIX}-{_next_number(SKU_PREFIX, SKU_YEAR):05d}"
```

`next_reference`'s signature, output and docstring are unchanged. Its existing
tests must pass untouched — that is the check that this refactor is a refactor.

Five digits allows 99 999 articles. Past that the number simply widens to six;
nothing overflows, and `sku` is a 32-character column.

## 2. Generation

In `Article.save()`, when the row is new and no SKU was supplied:

```python
def save(self, **kwargs):
    if self._state.adding and not self.sku:
        self.sku = next_sku()
    super().save(**kwargs)
```

**Why the model and not the serializer.** `NameSortedModel.save()` already
computes `name_sort` on every write, so model-level invariants are the
established pattern in this codebase. It is also the only single place that
covers the API, the Django admin, the shell and any future importer at once.

The `_state.adding` guard is what makes the SKU immutable: an instance loaded
from the database never re-enters the branch, whatever a caller does to the
field. It also removes any need to reconcile `update_fields`, unlike
`NameSortedModel.save()`, which must.

Three consequences, all acceptable and all stated here so they are not
discovered later:

- `Article.save()` can now issue a query it never issued before. On an update
  it does not, because of `_state.adding`.
- `next_sku` raises `RuntimeError` outside an atomic block, so a bare
  `Article.objects.create(...)` in a shell fails loudly rather than writing a
  blank SKU. The API path is already `@transaction.atomic`, and Django's admin
  wraps its changeform view in one.
- `bulk_create` does not call `save()` and so does not allocate. This mirrors
  `Site.save()`, whose invariant `bulk_create` already bypasses — documented in
  `apps/reports/tests/test_facts.py` rather than defended against. Nothing in
  the codebase bulk-creates articles.

## 3. Seeding, so generated SKUs cannot collide with legacy ones

Legacy SKUs are not rewritten, so an article somebody already named `ART-7` is
the one thing standing between the generator and an `IntegrityError`.

A data migration in `catalogue`, depending on `common`'s latest, seeds the
counter to the highest number already used by any `ART-<digits>` SKU, matched
case-insensitively, or 0 if there are none. It uses `get_or_create` rather than
`update_or_create`, so a re-run cannot wind an existing counter backwards.
Reverse migration deletes the row.

`ArticleFactory`'s default `sku` changes from `ART-{n:04d}` to `LEG-{n:04d}` —
outside the generator's namespace, and named for what it now stands in for: a
legacy hand-typed reference. As written, the factory mints values in `ART-` and
avoids collision only by the accident of being four digits wide where the
generator is five. Tests that assert on a specific SKU pass one explicitly and
are unaffected; the full suite is the check.

## 4. API surface

`sku` moves into `ArticleSerializer.Meta.read_only_fields`. It stays in
`fields`, so every response still carries it.

`validate_sku` is **deleted**. A value the client cannot send cannot be
duplicated by a client, and `article_sku_unique_ci` remains as the backstop
against anything reaching the model another way. This removes the API error
« Cette référence est déjà utilisée. »; nothing in the frontend will produce
the input that triggered it.

`ArticleAdmin` gains `readonly_fields = ["sku"]`. Without it the admin remains
a hole in a rule the rest of the system now enforces. On the add form the field
renders empty and read-only, and `save()` fills it.

## 5. Frontend

| File | Change |
|---|---|
| `types/dto.ts` | drop `sku` from `ArticleCreateDto` — `ArticleUpdateDto` is `Partial<Omit<…>>` of it and follows automatically |
| `features/articles/schema.ts` | drop `sku` from `articleFormSchema` and `ARTICLE_FORM_DEFAULTS` |
| `features/articles/components/article-form.tsx` | remove the input; drop `sku` from both the edit-hydration and submit mappings |

The form's SKU grid cell is kept and rendered as read-only text rather than
left as a hole: « Générée automatiquement » on create, the article's actual SKU
on edit. Removing the cell outright would reflow a two-column grid for no gain.

`Article.sku` stays in `types/domain.ts`. The catalogue table's « Référence »
column, the detail header, and the article picker's secondary line are all
reads and are untouched.

## 6. Testing

Backend, each with a decoy that fails if the rule is not really enforced:

- Two `next_sku()` calls inside one atomic block return consecutive numbers,
  zero-padded to five digits.
- `next_sku()` outside an atomic block raises `RuntimeError`.
- `next_reference`'s existing tests pass unchanged after the split.
- `POST /api/articles/` with `sku: "HACK-1"` in the body returns a generated
  `ART-\d{5}`, not `HACK-1`. Asserting only the pattern would pass even if the
  client's value were honoured for a client who sent a well-formed one.
- `PATCH` with a new `sku` leaves the stored value unchanged, for both a
  generated SKU and a legacy hand-typed one.
- Creating an article no longer requires `sku` in the payload.

The seeding migration is the one piece with no honest unit test: migrations run
against an empty database, so a test could only assert that the counter seeded
to 0. It is verified by running `migrate` against the dev database and reading
back the `DocumentSequence` row, and that result is reported rather than
assumed.

Frontend gates are the usual four: `bun test`, `bun x tsc --noEmit`,
`bun run lint`, `bun run build`. The type system does the real work here —
deleting `sku` from `ArticleCreateDto` makes any call site that still supplies
it fail to compile.

## Out of scope

- **Renumbering the existing catalogue.** Explicitly rejected above.
- **A management command to renumber later.** Code for a decision that may
  never be made; the migration pattern is there if it is.
- **Category-derived SKUs** (`BOI-0001`). Considered and rejected: the category
  is editable, so moving an article would leave its SKU asserting something
  false about where it belongs.
- **Making `barcode` generated.** It is a real-world scanned value, not ours to
  mint.
- **User management UI**, the third feature requested alongside the article
  picker and this one. It gets its own spec.
