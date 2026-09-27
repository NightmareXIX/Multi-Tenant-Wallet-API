# Multi-Tenant Wallet API — Route Design

Sep 27, 2026 · @Sadnan

## Overview

The API exposes 7 routes under one versioned base path. One route creates tenants; the other 6 are scoped to the calling tenant.

- **Base path:** `/api/v1`
- **Format:** JSON request and response bodies.
- **Money:** every `amount` and `balance` is an integer in paisa (1 Taka = 100 paisa). `15050` means ৳150.50. Floats and strings are rejected.
- **IDs:** every resource id is a UUID, so ids cannot be guessed by counting.
- **Timestamps:** ISO 8601 in UTC, e.g. `2026-09-27T10:15:00Z`.

## Authentication

Every route except tenant creation requires the tenant's API key in the `X-API-Key` header. The key alone decides which tenant the request acts for (FR-7.2).

```
X-API-Key: sk_live_8f2c...
```

- The key is returned once, in the response to `POST /tenants` (FR-7.3). It cannot be retrieved again.
- A missing or unknown key returns `401 Unauthorized`.
- No route accepts a tenant id in the path, body or query. A client cannot point a request at another tenant, even by mistake.
- Any wallet id that belongs to another tenant is treated as if it does not exist: `404 Not Found` (FR-7.5).

## Routes at a glance

| # | Method | Path | Purpose | API key | Idempotency-Key | FRs |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | POST | `/tenants` | Create a tenant | No | No | 1.1, 1.2, 7.3 |
| 2 | POST | `/users` | Create a user and their wallet | Yes | No | 2.1, 2.2 |
| 3 | GET | `/wallets/{wallet_id}` | Get a wallet and its balance | Yes | No | 6.1 |
| 4 | GET | `/wallets/{wallet_id}/transactions` | Get paginated transaction history | Yes | No | 6.2–6.4 |
| 5 | POST | `/wallets/{wallet_id}/deposit` | Deposit into a wallet | Yes | Required | 3.1 |
| 6 | POST | `/wallets/{wallet_id}/withdraw` | Withdraw from a wallet | Yes | Required | 4.1, 4.2 |
| 7 | POST | `/transfers` | Move money between two wallets | Yes | Required | 5.1–5.5 |

All paths sit under `/api/v1`.

## Endpoints

Each route lists its request, its success response and the errors it can return. Resource shapes are defined in the next section.

### 1. Create a tenant

`POST /tenants` — public, no API key.

| Request field | Type | Rules |
| --- | --- | --- |
| `name` | string | Required, non-empty |

**Success:** `201 Created` → a Tenant, plus `api_key` in plain text. This is the only time the key is shown.

**Errors:** `400` invalid name.

### 2. Create a user and wallet

`POST /users`

| Request field | Type | Rules |
| --- | --- | --- |
| `name` | string | Required, non-empty |

Creates the user and their one wallet together (FR-2.2). The wallet starts at balance 0.

**Success:** `201 Created` → a User with its `wallet` nested inside. The client keeps `wallet.id` for all money routes.

**Errors:** `400` invalid name · `401` bad API key.

### 3. Get a wallet

`GET /wallets/{wallet_id}`

**Success:** `200 OK` → a Wallet, including `balance`.

**Errors:** `401` bad API key · `404` wallet not found or owned by another tenant.

### 4. Get transaction history

`GET /wallets/{wallet_id}/transactions?page=1`

| Query param | Type | Rules |
| --- | --- | --- |
| `page` | integer | Optional, default 1 |

Returns every transaction where the wallet is the source or the destination, newest first, 10 per page. A transfer appears in both wallets' histories as the same record (FR-6.4).

**Success:** `200 OK` → a page of Transactions (see Pagination).

**Errors:** `401` bad API key · `404` wallet not found, other tenant, or page out of range.

### 5. Deposit

`POST /wallets/{wallet_id}/deposit` — header `Idempotency-Key` required.

| Request field | Type | Rules |
| --- | --- | --- |
| `amount` | integer | Required, paisa, greater than 0 |

**Success:** `201 Created` → the new Transaction (type `DEPOSIT`).

**Errors:** `400` missing key or invalid amount · `401` bad API key · `404` wallet not found · `422` key reused with a different request.

### 6. Withdraw

`POST /wallets/{wallet_id}/withdraw` — header `Idempotency-Key` required.

| Request field | Type | Rules |
| --- | --- | --- |
| `amount` | integer | Required, paisa, greater than 0 |

**Success:** `201 Created` → the new Transaction (type `WITHDRAWAL`).

**Errors:** `400` missing key or invalid amount · `401` bad API key · `404` wallet not found · `422` insufficient funds, or key reused with a different request.

### 7. Transfer

`POST /transfers` — header `Idempotency-Key` required.

| Request field | Type | Rules |
| --- | --- | --- |
| `source_wallet_id` | UUID | Required, wallet of the calling tenant |
| `destination_wallet_id` | UUID | Required, wallet of the calling tenant, not the source |
| `amount` | integer | Required, paisa, greater than 0 |

Both sides succeed or neither does (FR-5.4). A destination in another tenant is indistinguishable from a missing wallet (FR-5.3).

**Success:** `201 Created` → the new Transaction (type `TRANSFER`).

**Errors:** `400` missing key, invalid amount, or source equals destination · `401` bad API key · `404` either wallet not found or in another tenant · `422` insufficient funds, or key reused with a different request.

## Resource shapes

These are the objects the API returns. The tenant id never appears in responses, since the caller is always that tenant.

### Tenant

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID |  |
| `name` | string |  |
| `api_key` | string | Only in the `POST /tenants` response |
| `created_at` | timestamp |  |

### User

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID |  |
| `name` | string |  |
| `wallet` | Wallet | The user's one wallet, nested |
| `created_at` | timestamp |  |

### Wallet

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Used in all money routes |
| `user_id` | UUID | Owner |
| `balance` | integer | Paisa, always 0 or more |
| `created_at` | timestamp |  |

### Transaction

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID |  |
| `type` | enum | `DEPOSIT`, `WITHDRAWAL` or `TRANSFER` |
| `amount` | integer | Paisa, always positive |
| `source_wallet_id` | UUID or null | Null for deposits |
| `destination_wallet_id` | UUID or null | Null for withdrawals |
| `idempotency_key` | string | The key the client sent |
| `created_at` | timestamp |  |

A transaction is read-only. No route updates or deletes one (FR-8.2).

## Idempotency

Deposit, withdraw and transfer require an `Idempotency-Key` header, so a retried request never moves money twice.

```
Idempotency-Key: 3f9b1c2e-7a4d-4e1f-9c21-5d8e6f7a8b90
```

What the API does when a key arrives:

| Situation | Response | FR |
| --- | --- | --- |
| Header missing, empty, or over 255 characters | `400` | 9.4, 9.5 |
| Key not seen before in this tenant | Execute; `201` with the new Transaction | 9.1 |
| Key already used, same operation, wallet(s) and amount | No new transaction; same `201` and body as the original | 9.2, 9.7 |
| Key already used, anything different | `422`, nothing executed | 9.8 |
| Earlier request with this key failed (e.g. insufficient funds) | Treated as a new key; executes again | 9.6 |
| Two requests with the same key at the same moment | One executes; the other gets its result | 9.9 |

- A key is unique per tenant and shared across all three routes. The same key on deposit and then withdraw is a mismatch (`422`).
- Two tenants may use the same key string without conflict (FR-9.3).
- Keys never expire (FR-9.10).

## Pagination and errors

### Pagination

The history route returns pages of 10, newest first, selected with `?page=N`.

```json
{
  "count": 42,
  "next": "/api/v1/wallets/{wallet_id}/transactions?page=3",
  "previous": "/api/v1/wallets/{wallet_id}/transactions?page=1",
  "results": [ /* up to 10 Transactions */ ]
}
```

### Error body

Every error uses one shape: a stable machine-readable `code` and a human-readable `message`.

```json
{
  "error": {
    "code": "insufficient_funds",
    "message": "Wallet balance is lower than the requested amount."
  }
}
```

Validation errors may add a `fields` object naming each bad field and its problem.

### Status codes

| Status | Error code | When |
| --- | --- | --- |
| `400` | `validation_error` | Bad body or query: missing field, amount ≤ 0, non-integer amount |
| `400` | `idempotency_key_missing` | Money route without a valid `Idempotency-Key` |
| `400` | `same_wallet_transfer` | Transfer source equals destination |
| `401` | `invalid_api_key` | `X-API-Key` missing or unknown |
| `404` | `not_found` | Wallet does not exist or belongs to another tenant; page out of range |
| `422` | `insufficient_funds` | Withdrawal or transfer larger than the balance |
| `422` | `idempotency_key_mismatch` | Key reused with a different request |

## Design decisions

These route-level choices are new in this doc; the FR doc covers the rest.

| Decision | Why |
| --- | --- |
| API key sent in `X-API-Key` | Simple, explicit, and distinct from any future user-level auth in `Authorization`. |
| No tenant id in any URL | The tenant comes only from the key, so no request can name another tenant. |
| `POST /users` also creates the wallet | One user has exactly one wallet (FR-2.2); two calls would leave a window with a walletless user. |
| Deposit and withdraw nested under the wallet | Each acts on one wallet, which reads naturally as `/wallets/{id}/deposit`. |
| Transfer as a top-level `/transfers` | It involves two wallets equally; nesting under the source would make the destination look secondary. |
| Money routes return the Transaction, `201` | Each call creates one ledger record; returning it lets a replay return the same body (FR-9.7). |
| Balance read from `GET /wallets/{id}` | The balance is a property of the wallet, not a separate resource. |
| Insufficient funds is `422`, not `400` | The request is well-formed; it fails on the wallet's current state. The error `code` separates it from a key mismatch. |
| UUID ids | Ids cannot be enumerated, adding a second layer on top of tenant scoping. |
| No list, update or delete routes | The PDF does not ask for them; transactions must never be updated or deleted. |
