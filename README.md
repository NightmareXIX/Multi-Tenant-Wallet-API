# Multi-Tenant Wallet API

A wallet and ledger REST API where many tenants (merchants or organizations) share one platform while their data
stays fully isolated. Tenants create users with wallets, then deposit, withdraw and transfer money. Every balance
change is written to an immutable ledger, and each money request is idempotent.

Built with Django 5.2, Django REST Framework and PostgreSQL.

## Quick start (Docker)

Requires Docker with Compose.

```bash
docker compose up --build
```

This starts Postgres and the API, applies migrations and serves on port 8000:

- API: `http://localhost:8000/api/v1`
- Swagger UI: http://localhost:8000/api/docs (click **Authorize** and paste an API key)

Run the tests:

```bash
docker compose run --rm web python manage.py test
```

If port 8000 or 5432 is taken, set `WEB_PORT` or `POSTGRES_PORT`, e.g. `WEB_PORT=8080 docker compose up --build`.

## Local development

Requires Python 3.13. Postgres still runs in Docker, since the tests need real row locking (SQLite ignores
`select_for_update`).

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
docker compose up -d db
python manage.py migrate
python manage.py runserver      # http://localhost:8000
python manage.py test
```

## API at a glance

All routes sit under `/api/v1`. Every route except `POST /tenants` needs the tenant's key in the `X-API-Key` header.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/tenants` | Create a tenant; returns its API key once |
| POST | `/users` | Create a user together with their wallet |
| GET | `/wallets/{wallet_id}` | Get a wallet and its balance |
| GET | `/wallets/{wallet_id}/transactions?page=N` | Transaction history, 10 per page, newest first |
| POST | `/wallets/{wallet_id}/deposit` | Deposit (needs `Idempotency-Key`) |
| POST | `/wallets/{wallet_id}/withdraw` | Withdraw (needs `Idempotency-Key`) |
| POST | `/transfers` | Transfer between two wallets (needs `Idempotency-Key`) |

- Amounts are integers in paisa: `15050` means ৳150.50. Strings and floats are rejected.
- Every error has the same shape: `{"error": {"code": "insufficient_funds", "message": "..."}}`.

The full request/response shapes and status codes are in
[docs/Multi-Tenant Wallet API — Route Design.md](<docs/Multi-Tenant Wallet API — Route Design.md>).

## curl walkthrough

With the API running on `localhost:8000`:

**1. Create a tenant** and copy the `api_key` from the response (it is shown only once):

```bash
curl -X POST http://localhost:8000/api/v1/tenants \
  -H "Content-Type: application/json" -d '{"name": "Acme"}'
# {"id": "...", "name": "Acme", "api_key": "sk_...", "created_at": "..."}

export API_KEY=sk_...
```

**2. Create two users.** Each response includes a nested `wallet`; copy both `wallet.id` values:

```bash
curl -X POST http://localhost:8000/api/v1/users \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d '{"name": "Alice"}'
curl -X POST http://localhost:8000/api/v1/users \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d '{"name": "Bob"}'

export ALICE=<alice's wallet id>
export BOB=<bob's wallet id>
```

**3. Deposit ৳500 into Alice's wallet.** Sending the same command again returns the same transaction and does
not deposit twice:

```bash
curl -X POST http://localhost:8000/api/v1/wallets/$ALICE/deposit \
  -H "X-API-Key: $API_KEY" -H "Idempotency-Key: deposit-1" \
  -H "Content-Type: application/json" -d '{"amount": 50000}'
```

**4. Transfer ৳200 from Alice to Bob, then withdraw ৳50 from Alice:**

```bash
curl -X POST http://localhost:8000/api/v1/transfers \
  -H "X-API-Key: $API_KEY" -H "Idempotency-Key: transfer-1" -H "Content-Type: application/json" \
  -d "{\"source_wallet_id\": \"$ALICE\", \"destination_wallet_id\": \"$BOB\", \"amount\": 20000}"

curl -X POST http://localhost:8000/api/v1/wallets/$ALICE/withdraw \
  -H "X-API-Key: $API_KEY" -H "Idempotency-Key: withdraw-1" \
  -H "Content-Type: application/json" -d '{"amount": 5000}'
```

**5. Check the balance and history.** Alice has `25000` paisa and three transactions:

```bash
curl http://localhost:8000/api/v1/wallets/$ALICE -H "X-API-Key: $API_KEY"
curl http://localhost:8000/api/v1/wallets/$ALICE/transactions -H "X-API-Key: $API_KEY"
```

Withdrawing more than the balance returns `422` with code `insufficient_funds`, and nothing changes.

## Assumptions

The brief leaves these points open, so these are the choices made. The full list is in
[docs/FR_CR_Assumptons.md](docs/FR_CR_Assumptons.md).

- **Tenant from the API key only.** The brief allows an API key or an `X-Tenant-ID` header. Only the key is used,
  because a tenant id can be guessed while a random key proves who is calling. Creating a tenant needs no key.
- **Cross-tenant access returns 404**, not 403, so a tenant cannot tell whether another tenant's wallet exists.
  This covers transfers into another tenant's wallet.
- **One wallet per user.** `POST /users` creates both together.
- **The idempotency key is an `Idempotency-Key` header** (the brief writes `idempotency_key`), following the Stripe
  convention. It is required on money routes, unique per tenant and shared across the three money routes.
- **Replays:** the same key with the same request returns the original response. The same key with a different
  request returns `422`. Only successful requests are remembered, so a failed request (e.g. insufficient funds)
  can be retried with the same key.
- **Money:** a single currency (BDT), stored as integer paisa. Amounts must be above zero; there is no business
  maximum.
- **History:** page-number pagination, 10 per page, newest first. A transfer is one record that appears in both
  wallets' histories.
- **A wallet cannot transfer to itself** (`400`).
- **The client is the tenant's backend.** End users never call the API, so there is no user-level login.

## Trade-offs

- **The balance is cached on the wallet; the ledger is the source of truth.** The balance is updated in the same
  database transaction as each ledger entry, so reads are fast and the balance can always be rebuilt from the
  ledger. The tests check that the two match after every money operation.
- **Immutability is enforced by the model and a Postgres trigger.** The `Transaction` model rejects updates and
  deletes, and a trigger rejects `UPDATE` and `DELETE` on the ledger table, so bulk queryset calls and raw SQL fail
  too. This ties the schema to Postgres, which row locking already needs. A database superuser can still drop the
  trigger or `TRUNCATE` the table.
- **API keys are hashed with SHA-256**, not bcrypt. The keys are long and random, so a slow hash adds cost to every
  request without adding real protection.
- **Idempotency keys never expire.** They live on the ledger transaction itself, which keeps the design simple but
  means a key can never be reused.
- **Single currency** (BDT), with no currency field.
- **No rate limiting.**
- **Development secrets in `docker-compose.yml`.** The secret key and database password there are for local use
  only; set real ones for any deployment.

## Project layout

```text
config/     settings and URLs
tenants/    Tenant model, API key authentication, POST /tenants
wallets/    User, Wallet and Transaction models; services.py holds all money logic
tests/      API, isolation, idempotency and concurrency tests
docs/       functional requirements, route design and development plan
```
