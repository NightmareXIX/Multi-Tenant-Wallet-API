# Multi-Tenant Wallet API — Development Plan

Sep 27, 2026 · @Sadnan

## Overview

The build takes 8 phases. The foundation comes first (models, auth), then the risky part (money operations), then the tests that prove it. Tick a phase off once its "Done when" line holds.

- [ ] Phase 1: Setup
- [ ] Phase 2: Models and migrations
- [ ] Phase 3: Tenant creation and API key auth
- [ ] Phase 4: Users and read endpoints
- [ ] Phase 5: Money operations
- [ ] Phase 6: Error format
- [ ] Phase 7: Tests
- [ ] Phase 8: Docker and README

### Project layout

```text
wallet-api/
├── config/              # settings, urls, wsgi
├── tenants/             # Tenant model, API key auth, POST /tenants
├── wallets/
│   ├── models.py        # User, Wallet, Transaction
│   ├── services.py      # deposit / withdraw / transfer (all money logic)
│   ├── serializers.py
│   ├── views.py
│   └── exceptions.py    # custom errors + error-shape handler
├── tests/
├── docker-compose.yml
└── README.md
```

Views stay thin: they validate input and call `services.py`. All locking, idempotency and ledger writes live in one place.

## Phase 1: Setup

Stand up Django, DRF and PostgreSQL before writing any feature code.

- Create the Django project with DRF and the `tenants` and `wallets` apps.
- Run PostgreSQL in Docker Compose from the start. Concurrency tests need real Postgres, because SQLite ignores `select_for_update`.
- Load settings (database URL, secret key) from environment variables.
- Install `drf-spectacular` (not `drf-yasg`, which only speaks OpenAPI 2). Set it as `DEFAULT_SCHEMA_CLASS`, then serve the schema at `/api/schema` and Swagger UI at `/api/docs`. Annotate each view in the phase that builds it, not all at the end.

**Done when:** `docker compose up` starts Postgres, `python manage.py migrate` runs cleanly and `/api/docs` loads.

## Phase 2: Models and migrations

Four models, all with UUID ids and a `tenant` FK, so every query can filter by tenant directly. Push every rule you can into database constraints.

| Model | Fields | Constraints and indexes |
| --- | --- | --- |
| Tenant | `id`, `name`, `api_key_hash`, `created_at` | `api_key_hash` unique and indexed |
| User | `id`, `tenant`, `name`, `created_at` | Lives in the `wallets` app; leave `AUTH_USER_MODEL` alone |
| Wallet | `id`, `tenant`, `user` (OneToOne), `balance` (`BigIntegerField`, default 0), `created_at` | `CheckConstraint(balance >= 0)` |
| Transaction | `id`, `tenant`, `type`, `amount` (`BigIntegerField`), `source_wallet`, `destination_wallet` (nullable, `PROTECT`), `idempotency_key`, `created_at` | `UniqueConstraint(tenant, idempotency_key)` · `CheckConstraint(amount > 0)` · indexes on `(source_wallet, created_at)` and `(destination_wallet, created_at)` |

- The unique constraint on `(tenant, idempotency_key)` is the real idempotency guarantee. Code checks are only a fast path.
- Make transactions immutable: override `save()` to reject updates and `delete()` to raise an error.

**Done when:** migrations apply and the constraints show up in the database.

## Phase 3: Tenant creation and API key auth

The API key is the only way a request names its tenant, so this layer is the heart of isolation.

- `POST /tenants` generates a key with `"sk_" + secrets.token_urlsafe(32)`, stores its SHA-256 hash and returns the plain key once. SHA-256 is enough for a long random key; bcrypt would slow every request.
- `ApiKeyAuthentication` reads `X-API-Key`, hashes it, looks up the tenant and puts it on the request.
- One helper serves every view: `get_wallet_for_tenant(tenant, wallet_id)` filters by tenant and raises 404 when nothing matches. Never call `Wallet.objects.get(id=...)` without the tenant filter.
- Spectacular cannot describe a custom auth class. Write an `OpenApiAuthenticationExtension` that declares an `apiKey` scheme in the `X-API-Key` header, so Swagger's **Authorize** button works. `POST /tenants` sets `authentication_classes = []`, so it shows as public.

**Watch out:** DRF returns 403 instead of 401 unless the auth class implements `authenticate_header()`. Return `"X-API-Key"` from it.

**Watch out:** spectacular only finds the extension if its module is imported. Put it in `tenants/schema.py` and import that from `TenantsConfig.ready()`.

**Done when:** you can create a tenant, a request with a missing or wrong key gets 401, and a key pasted into **Authorize** is sent on requests from `/api/docs`.

## Phase 4: Users and read endpoints

Three simple routes that give you data to work with before touching money.

- `POST /users` creates the user and the wallet inside one `transaction.atomic()` block, so a user never exists without a wallet.
- `GET /wallets/{id}` returns the wallet with its balance.
- `GET /wallets/{id}/transactions` filters on `Q(source_wallet=w) | Q(destination_wallet=w)`, orders by `-created_at, -id` and uses `PageNumberPagination` with `page_size=10`. The `-id` tiebreaker keeps the order stable when timestamps match.
- Spectacular cannot infer the serializers of a plain `APIView`. Give those views `@extend_schema(request=..., responses=...)`. Paginated responses from generic views are documented automatically.

**Done when:** you can create a user, read the wallet (balance 0) and get an empty history page.

## Phase 5: Money operations

Deposit, withdraw and transfer all run the same service flow in `services.py`. Get this right and the rest is plumbing.

&#91;embedded content: money operation flow · 3 checks, 1 retry loop\]

A duplicate key that slips past the first check hits the unique constraint on insert. The whole atomic block rolls back, and the request re-checks the key to return the replay or a 422.

### Per operation

- **Deposit:** lock one wallet and add the amount.
- **Withdraw:** lock one wallet, check the balance and subtract.
- **Transfer:** reject source == destination with 400 before touching the database. Lock both wallets in sorted id order, so A→B and B→A running together cannot deadlock. Subtract and add in the same atomic block.

### Swagger

- Declare the `Idempotency-Key` header on all three views with `OpenApiParameter("Idempotency-Key", location=OpenApiParameter.HEADER, required=True)`. Without it, Swagger UI has no field for the key.
- Mark the strict amount field with `@extend_schema_field(OpenApiTypes.INT)`, so the schema shows `integer` rather than `string`.

### Watch out

- Catch `IntegrityError` outside the `atomic()` block, so the balance change rolls back with the failed insert.
- Keep `ATOMIC_REQUESTS` off. If every request is wrapped in a transaction, a caught `IntegrityError` leaves that outer transaction broken, and the re-read after a key clash fails.
- Read the balance from the locked row. If the wallet was fetched earlier (for example for the 404 check), check and update the instance `select_for_update` returned, never the earlier copy, or the lost-update bug comes back.
- DRF's `IntegerField` accepts `"100"` and `100.0`. Write a strict field that only takes a real `int`, and rejects `bool`, which Python counts as an int.
- Cap amounts at the BigInteger maximum, so a huge number returns 400 instead of 500.

**Done when:** all three operations work end to end, and resending a request returns the same body without a new transaction.

## Phase 6: Error format

Every error leaves the API as `{"error": {"code", "message", "fields"?}}`, produced by one custom DRF exception handler.

| Exception | Status | Error code |
| --- | --- | --- |
| `IdempotencyKeyMissing` | 400 | `idempotency_key_missing` |
| `SameWalletTransfer` | 400 | `same_wallet_transfer` |
| `InsufficientFunds` | 422 | `insufficient_funds` |
| `IdempotencyKeyMismatch` | 422 | `idempotency_key_mismatch` |
| DRF `ValidationError` | 400 | `validation_error` (+ `fields`) |
| DRF auth errors | 401 | `invalid_api_key` |
| `NotFound` / `Http404` | 404 | `not_found` |

Spectacular only knows DRF's default error bodies. Define an `ErrorSerializer` for this shape and list it in each view's `responses` under the statuses that view can return.

**Done when:** every row of the route design's status-code table returns the right shape and code, and `/api/docs` shows that same shape.

## Phase 7: Tests

The tests must prove the four flows the assessment names: insufficient funds, concurrent transfers, duplicate idempotency keys and blocked cross-tenant access.

- Use `APITestCase` for normal flows.
- Concurrency tests **must** use `TransactionTestCase`. `TestCase` wraps each test in a transaction that other threads cannot see.
- Start threads together with a `threading.Barrier`, and call `connection.close()` at the end of each thread.

| Area | Tests |
| --- | --- |
| Insufficient funds | Withdraw or transfer above the balance → 422, balance unchanged, no transaction |
| Concurrent transfers | Wallet with 1000, 10 threads each transfer 200 → exactly 5 succeed, balance ends at 0 |
| Deadlock safety | A→B and B→A in parallel → both finish |
| Mixed operations | Deposits, withdrawals and transfers hit one wallet in parallel → balance never negative, ledger check passes |
| Idempotency | Same key and request → same body, one transaction · same key, different amount → 422 · same key after a failure → executes · same key in 2 tenants → both work · same key sent concurrently → one transaction |
| Cross-tenant | Tenant B reads, deposits to or transfers into A's wallet → 404, A's balance unchanged |
| Auth | Missing or wrong key → 401 |
| Ledger check | Cached balance equals incoming minus outgoing transactions after every flow |

Write the ledger check as one helper and call it from many tests. It proves the ledger is the source of truth.

**Done when:** all tests pass against Postgres in Docker.

## Phase 8: Docker and README

A reviewer should be able to clone the repo and run everything with one command.

- `docker-compose.yml` runs Postgres and the web app. Document the commands to start the app, run migrations and run tests.
- The README covers setup steps and a short curl walkthrough: create a tenant, create a user, deposit, transfer, view history.
- It points to Swagger UI at `/api/docs` for trying the API in a browser.
- It summarises the assumptions, with a link to the FR doc.
- It lists the trade-offs:
  - The balance is a cached value; the ledger is the source of truth.
  - Immutability is enforced in the app, not by database triggers.
  - API keys are hashed with SHA-256.
  - Idempotency keys never expire.
  - There is one currency (BDT).
  - There is no rate limiting.

**Done when:** someone else can clone the repo and run it with one command.

## Working tips

- Keep views thin and money logic in `services.py`, so there is only one place to review for locking and idempotency.
- Commit with the `git-commit` skill (`.claude/skills/git-commit/SKILL.md`, kept local and gitignored). Commit whenever a self-contained change is done, such as a model with its migration, an endpoint with its tests or a fix with its regression test, not only when a phase ends. Messages follow `<type>(<scope>): <short description>` with types `feat`, `fix`, `refactor`, `test`, `docs`, `chore` and `build`, for example `feat(money): lock wallets in sorted id order for transfers`. One commit holds one logical change: no vague messages like "update" or "final", and no pile of micro-commits.
