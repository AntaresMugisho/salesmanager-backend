# Sub-project 1 — Foundation & Auth

Design, 2026-08-03.

## Context

`stockmanager-frontend` is a complete Next.js application running against
mocked services backed by IndexedDB. Its `types/domain.ts`, `types/dto.ts` and
the thirteen modules in `services/` already define every payload, filter and
error shape the backend must produce. The frontend was written against DRF
conventions on purpose: `Paginated<T>` is documented as the
"DRF PageNumberPagination envelope", `FieldErrors` "mirrors DRF's validation
shape", and `ordering` uses DRF's `-field` syntax.

**The contract is therefore given, not designed.** This backend implements it.
Where a change to the frontend's types is unavoidable, this document names it
explicitly; there are two, both in this sub-project.

The whole backend is too large for one spec. It is split into six sub-projects,
each with its own spec, plan and implementation cycle:

1. **Foundation & auth** — this document
2. Catalogue & stock — categories, suppliers, articles, single movements
3. Stock transactions — multi-line transactions, `TR-YYYY-NNNN`
4. Customers & sales — sales, line snapshots, `FA-YYYY-NNNN`, payments
5. Expenses & finance — expenses CRUD, summary / series / breakdown
6. Reports — result, sales, profitability, stock

Sub-project 1 ships no business domain. It exists to establish the identity
model and the wire conventions that the other five inherit. Its real
deliverable is the set of decisions in §5, which are expensive to change once
five apps depend on them.

## Decisions taken

Settled during brainstorming, recorded here because later sub-projects assume
them:

| Question | Decision |
|---|---|
| Finance & report arithmetic | **Server-side.** Endpoints return finished `FinanceSummary` / `SalesReport` shapes. The frontend's `features/*/lib/*.ts` calculation modules retire when sub-projects 5 and 6 land. |
| Multi-site | **One site, field retained.** A single `Site` row per deployment. The API keeps returning `siteId` so no frontend code changes, but nothing is scoped by it. |
| Users | **Real users with roles:** Owner / Manager / Cashier. |
| Testing | **TDD**, pytest + pytest-django + factory-boy, API-level tests. |
| App layout | **Domain apps** under an `apps/` package, one per sub-project. |
| camelCase | **`djangorestframework-camel-case`** renderer/parser, plus a hand-written mixin for query params. |
| Database | **SQLite now, PostgreSQL-ready.** `DATABASE_URL` from `.env`, no SQLite-only constructs. |
| Login response | **Composite** — one round-trip returning user, site and both tokens. |
| User management | **Full CRUD API now**, owner-only. |
| Dev seed | **Bootstrap command only** — one Site, one Owner. No demo catalogue. |

## Scope

**In:** project configuration, custom user model with roles, the `Site`
singleton, JWT auth (login / refresh / logout / me), owner-only user CRUD,
settings read & update, and the shared conventions — error envelope, camelCase
translation, pagination, permissions, French messages.

**Out, deliberately:** password reset, email sending, avatar upload, rate
limiting, refresh-token rotation, OpenAPI schema generation, Docker, CI. None
is required by any frontend screen that exists today. Rate limiting and refresh
rotation are the two most likely to be pulled forward; both are additive and
neither changes the data model.

## Architecture

```
stockmanager-backend/
  manage.py  .env  .env.example  pytest.ini  requirements.txt
  stockmanager/
    settings.py        reads .env: DEBUG, SECRET_KEY, DATABASE_URL, CORS, JWT lifetimes
    urls.py            /api/ -> apps.accounts.urls; /admin/
  apps/
    common/
      models.py        UUIDModel abstract base
      pagination.py    PageNumberPagination, page_size 20, ?pageSize override, max 100
      exceptions.py    custom handler -> { code, message, fieldErrors }
      filters.py       camelCase query-param mixin
      permissions.py   IsOwner, IsManagerOrAbove, ReadOnlyForCashier
    accounts/
      models.py        User, Site
      serializers.py   UserSerializer, UserWriteSerializer, LoginSerializer, SiteSerializer
      views.py         auth views, /users/, /settings/
      admin.py
      management/commands/bootstrap.py
      tests/           factories.py + test modules
```

`apps/` is a package on the import path. Each `AppConfig` declares an explicit
`label` (`accounts`, not `apps.accounts`) so migration paths and FK references
stay short.

**Why domain apps rather than one `api` app:** each sub-project adds or fills
exactly one app, so migrations stay small and local to the work in flight.
`common/` holds only what more than one app needs, and every module in it is
depended upon by all five later sub-projects — which is why its behaviour is
tested directly rather than through a domain endpoint.

### `apps/common/models.py`

```python
class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
```

Every domain model in every sub-project inherits this. UUID primary keys
because the frontend's `UUID` type says so, and because they let the frontend
generate optimistic ids if it ever needs to.

## Data model

### `Site`

One row, enforced. Fields mirror the frontend's `Site` interface exactly:
`id`, `name`, `address`, `phone?`, `email?`, `tax_number?`, `invoice_footer?`,
`is_default`.

Singularity is enforced two ways: a partial unique index on `is_default=True`,
and a `save()` guard refusing to create a second row. The index is the real
constraint; the guard exists to raise a comprehensible error rather than an
`IntegrityError`.

`Site.objects.current()` returns the single row. **Later sub-projects call this
instead of threading `siteId` through their signatures.** A `siteId` arriving
in a request body or query string is accepted and ignored — never used to
filter — so that the frontend needs no change today and real scoping remains a
migration rather than a rewrite.

Nullable text fields are `null=True` rather than `blank=""`, because the
frontend's types promise `string | null` and `services/settings.ts` already
coalesces `undefined` to `null` defensively. The serializer must emit `null`,
not `""`.

### `User`

Replaces `django.contrib.auth.User` via `AUTH_USER_MODEL`. **Set in this
sub-project because swapping it after other apps hold FKs to it is a rewrite,
not a migration.** This is the single most expensive decision here to reverse.

| field | notes |
|---|---|
| `id` | UUID pk, from `UUIDModel` |
| `email` | unique, `USERNAME_FIELD`, case-insensitive lookup and uniqueness |
| `full_name` | one field — the frontend only ever renders `fullName` |
| `role` | `TextChoices`: `OWNER` / `MANAGER` / `CASHIER` |
| `avatar_url` | nullable URL; no upload handling in this sub-project |
| `is_active` | `False` means deactivated; the row is never destroyed |
| `is_staff`, `date_joined` | standard, for the admin |

No `username` field. `REQUIRED_FIELDS = ["full_name"]`.

Case-insensitive email matters in both directions: `alice@shop.com` and
`Alice@Shop.com` must be the same account at login and must collide at
creation. Postgres would use `CITEXT` or a functional unique index; SQLite has
neither reliably, so uniqueness is enforced by normalising to lowercase on
save, and lookups go through the manager. This is the one place the
"PostgreSQL-ready" promise costs something, and it is deliberate.

A custom `UserManager` provides `create_user` and `create_superuser`; a
superuser is always `role=OWNER`.

### Roles

| | Owner | Manager | Cashier |
|---|---|---|---|
| Users & roles | yes | — | — |
| Settings | yes | — | — |
| Articles, categories: write | yes | yes | — |
| Articles: read | yes | yes | yes |
| Stock movements & transactions | yes | yes | — |
| Create sale | yes | yes | yes |
| Record payment | yes | yes | yes |
| Cancel sale | yes | yes | — |
| Customers / suppliers | yes | yes | read |
| Expenses | yes | yes | — |
| Finance & reports | yes | yes | — |

Only the Owner and Settings rows are enforceable in this sub-project; the rest
is recorded here so the later sub-projects have one authoritative table to
implement against rather than rediscovering the line each time.

Roles are a model field, not Django groups. The permission surface here is
*action*-shaped ("may cancel a sale", "may see finance"), and Django's
per-model CRUD permissions fit that badly enough that the mapping would need
explaining in every view anyway.

### Frontend type changes required

Two, both unavoidable:

1. `User` gains `role: "OWNER" | "MANAGER" | "CASHIER"`.
2. `Session.token: string` becomes `accessToken: string` and
   `refreshToken: string`.

Neither is in this repository. They are noted so the frontend cutover has a
complete list.

## API surface

All paths under `/api/`. All responses camelCase.

| method | path | who | returns |
|---|---|---|---|
| POST | `/auth/login/` | public | `{ user, siteId, accessToken, refreshToken }` |
| POST | `/auth/refresh/` | public | `{ accessToken }` |
| POST | `/auth/logout/` | authenticated | 204, refresh token blacklisted |
| GET | `/auth/me/` | authenticated | `User` |
| GET | `/settings/` | authenticated | `Site` |
| PATCH | `/settings/` | owner | `Site` |
| GET | `/users/` | owner | paginated `User` |
| POST | `/users/` | owner | `User`, 201 |
| GET | `/users/{id}/` | owner | `User` |
| PATCH | `/users/{id}/` | owner | `User` |
| DELETE | `/users/{id}/` | owner | 204 |

### Auth

Login takes `{ email, password }` and returns everything the frontend's session
store needs in one round-trip. `siteId` comes from `Site.objects.current()`.

Failure returns 400 `invalid_credentials` with

```json
{ "code": "invalid_credentials",
  "message": "Identifiants invalides.",
  "fieldErrors": { "email": ["Aucun compte ne correspond à ces identifiants."] } }
```

An unknown email, a wrong password and an inactive account all produce this
identical response. Distinguishing them would let an unauthenticated caller
enumerate accounts, and the frontend's login form shows the error under the
email field regardless.

`/auth/logout/` blacklists the presented refresh token, which requires
`rest_framework_simplejwt.token_blacklist` in `INSTALLED_APPS`. Logout is
idempotent: an already-blacklisted or malformed token still returns 204, since
the client's only sensible reaction either way is to drop its session.

Access-token lifetime 60 minutes, refresh 7 days, both from `.env`. No
rotation — out of scope, and adding it later invalidates nothing.

### Settings

`/settings/` is a singleton: no id in the path. GET resolves
`Site.objects.current()`; PATCH updates it and is owner-only. `name` and
`address` are required and non-blank, matching the validation
`services/settings.ts` already performs client-side. The other four fields are
optional and normalise `""` to `null` on write.

`SettingsUpdateDto` carries every field, so the frontend submits the whole
form. PATCH is used rather than PUT because partial updates are harmless here
and PUT would demand fields the API can perfectly well leave alone.

### Users

Owner-only, all five actions. `POST` takes `{ email, fullName, password, role,
avatarUrl? }`; password is write-only and validated against
`AUTH_PASSWORD_VALIDATORS`. `PATCH` may change `fullName`, `role`,
`avatarUrl` and `isActive`; changing a password goes through a separate
write-only `password` field on the same endpoint.

**DELETE deactivates rather than destroys** (`is_active = False`, 204). Every
later sub-project stamps `userId` and `userName` onto movements, sales and
expenses; destroying the row would break those historical reads. Nothing in the
system hard-deletes a user.

**Last-owner guard.** An owner may not deactivate, delete, or demote the last
active owner — including themselves. Violations return 409 `conflict` with a
French message. Without this a single misclick locks every owner-only endpoint,
including the one that would undo it, leaving the admin as the only recovery
path.

## Conventions

This section is the sub-project's real output. Five later sub-projects inherit
every rule in it.

### Error envelope

One exception handler renders every failure as the frontend's `ApiError`:

```json
{ "code": "validation_error",
  "message": "Les données envoyées sont invalides.",
  "fieldErrors": { "email": ["Cette adresse e-mail est déjà utilisée."] } }
```

| code | status | raised by |
|---|---|---|
| `validation_error` | 400 | serializer validation |
| `invalid_credentials` | 400 | login only |
| `authentication_failed` | 401 | missing or invalid token |
| `permission_denied` | 403 | role check |
| `not_found` | 404 | missing object |
| `conflict` | 409 | last-owner guard, second-Site guard |
| `server_error` | 500 | anything unhandled |

`fieldErrors` appears only on 400s carrying field detail. DRF's
`non_field_errors` key renders as `nonFieldErrors`.

**Field-error keys must match the frontend's react-hook-form field names,**
which are camelCase — `lib/form-errors.ts` calls `setError(field)` with the key
verbatim, and a key matching no mounted field renders nothing anywhere. The
camel-case renderer handles this, since it converts error bodies like any
other. A serializer field whose name differs from the form's field name is a
silent failure: the user sees no feedback at all.

Unhandled exceptions are logged with a traceback and returned as a bare 500
`server_error`. Never a traceback in the response, `DEBUG` regardless.

### camelCase

`djangorestframework-camel-case` provides the renderer and parser globally, so
serializers stay idiomatic snake_case and request bodies, response bodies and
error bodies all convert automatically.

**It does not touch query parameters.** The frontend sends camelCase filters —
`categoryId`, `pageSize`, `dateFrom`, `stockStatus` — and camelCase `ordering`
values such as `-createdAt`. `apps/common/filters.py` supplies a mixin that
translates incoming parameter names and `ordering` values to snake_case before
the filter backend sees them.

This mixin is the one place the contract can drift without any test failing in
either repository, because a mistranslated filter silently returns unfiltered
results rather than erroring. It is tested directly, on its own, and every
later sub-project's list endpoint uses it.

### French

`LANGUAGE_CODE = "fr-fr"`, `USE_I18N = True`. Django and DRF ship French
translations for their built-in validation messages; every custom message is
written in French. The frontend renders `error.message` straight into a toast,
so an English string is a user-visible bug rather than a cosmetic one.

`TIME_ZONE` stays `UTC` with `USE_TZ = True` — the frontend's `ISODateTime` is
documented as a `Z`-suffixed instant, and formatting for display is its job.

### Pagination

DRF `PageNumberPagination`, default page size 20 to match the frontend's
`DEFAULT_PAGE_SIZE`, `?page=` and `?pageSize=`, maximum 100. `next` and
`previous` are absolute URLs. The envelope is exactly
`{ count, next, previous, results }`.

### Permissions

`apps/common/permissions.py` holds `IsOwner`, `IsManagerOrAbove` and
`ReadOnlyForCashier`, expressed against `request.user.role`. The default is
`IsAuthenticated`; `DEFAULT_AUTHENTICATION_CLASSES` is SimpleJWT only, with no
session-auth fallback, so a stale admin cookie can never authenticate an API
call.

### CORS

`django-cors-headers`, allowed origins from `.env`, `http://localhost:3000` in
development. Credentials are not used — the frontend sends a bearer token — so
`CORS_ALLOW_CREDENTIALS` stays `False`.

### Configuration

`.env` via the already-vendored `antares-dotenv`, with a committed
`.env.example`. `SECRET_KEY`, `DEBUG`, `DATABASE_URL`, `ALLOWED_HOSTS`,
`CORS_ALLOWED_ORIGINS` and the two JWT lifetimes are read from the environment.
The scaffold's hardcoded `django-insecure-` key is removed in this sub-project;
`SECRET_KEY` has no default and fails loudly if unset.

### `bootstrap` command

`python manage.py bootstrap` creates the `Site` and one Owner, prompting for
email and password, and is idempotent — re-running it against a populated
database reports what exists and changes nothing. It exists so a fresh clone
can reach a working login without the admin.

## Testing

pytest, pytest-django, factory-boy, pytest-cov. Tests are written before the
implementation they cover.

`apps/accounts/tests/factories.py` provides `UserFactory` (role-parameterised,
with `OwnerFactory` / `ManagerFactory` / `CashierFactory` traits) and
`SiteFactory`. **Every later sub-project builds on these two**, so they are
designed to be imported rather than copied.

Tests hit the API surface through DRF's test client rather than calling
serializers directly: the wire format is the contract, and a serializer test
would pass while the renderer mangles the payload.

Coverage for this sub-project:

- **Auth** — login success; unknown email, wrong password and inactive account
  each returning the identical `invalid_credentials` body; refresh; refresh
  rejected after logout; logout idempotent; `/auth/me/` authenticated and
  anonymous.
- **Permissions** — the full matrix on `/users/` and `/settings/` for all three
  roles and for an anonymous caller.
- **Guards** — last active owner cannot be deactivated, deleted or demoted,
  including by themselves; a second `Site` cannot be created.
- **Users** — creation rejects a duplicate email differing only in case; DELETE
  deactivates and leaves the row; password validators apply.
- **Envelope** — one test per error code asserting `code`, `message` and the
  presence or absence of `fieldErrors`; an unhandled exception yields a bare
  500 with no traceback under both `DEBUG` settings.
- **camelCase** — round-trip through request body, response body and error
  body; and the query-param mixin tested directly, including `ordering`
  values.

The French-message requirement is asserted where a message is custom; DRF's own
translated strings are taken on trust.

## Risks

**`AUTH_USER_MODEL` is set once.** Five sub-projects will hold foreign keys to
`User`. Changing it after sub-project 2 lands means rebuilding the migration
history. This is why it is here rather than deferred.

**The query-param mixin fails silently.** A mistranslated filter returns
unfiltered results — a wrong answer, not an error, and one no frontend type
check catches. Hence the direct tests.

**Case-insensitive email on SQLite** rests on normalisation at save time rather
than a database constraint. A row written outside the ORM could violate it. The
Postgres migration should add a functional unique index and drop the
normalisation's load-bearing role.

**Roles were chosen before any frontend screen enforces them.** The API is the
enforcement point and is correct regardless, but the frontend will show a
cashier buttons that return 403 until it grows role-aware rendering. That work
is not in this repository and is not scheduled here.
