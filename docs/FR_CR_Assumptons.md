# Multi-Tenant Wallet API — Functional Requirements

Source: Cashless Ai Backend Take-Home Assessment (PDF).
Items marked **(assumption)** are decisions we made where the PDF is silent.

---

## 1. Tenants

- **FR-1.1** The system can create a tenant (a merchant or organization).
- **FR-1.2** Creating a tenant is not scoped to a tenant. **(assumption)**

## 2. Users / Wallets

- **FR-2.1** The system can create a user / wallet under a tenant.
- **FR-2.2** Each user has exactly one wallet. **(assumption)**

## 3. Deposit

- **FR-3.1** A client can deposit funds into a wallet.

## 4. Withdraw

- **FR-4.1** A client can withdraw funds from a wallet.
- **FR-4.2** A withdrawal is rejected if the wallet balance is insufficient.

## 5. Transfer

- **FR-5.1** A client can transfer funds between two wallets.
- **FR-5.2** Both wallets must belong to the same tenant.
- **FR-5.3** A transfer across different tenants is rejected with 404 Not Found. **(assumption: status code)**
- **FR-5.4** A transfer is atomic: both sides succeed, or neither does.
- **FR-5.5** A wallet cannot transfer to itself. **(assumption)**

## 6. Balance and History

- **FR-6.1** A client can get a wallet's balance.
- **FR-6.2** A client can get a wallet's transaction history.
- **FR-6.3** The transaction history is paginated: page numbers, 10 items per page, newest first. **(assumption: style, size, order)**
- **FR-6.4** A transfer is recorded as one transaction and appears in the history of both wallets. **(assumption)**

## 7. Tenant Scoping and Isolation

- **FR-7.1** Every request (except tenant creation) is scoped to a tenant.
- **FR-7.2** The tenant is resolved from an API key. The `X-Tenant-ID` header is not used. **(assumption)**
- **FR-7.3** A random API key is generated when a tenant is created and returned to the caller. **(assumption)**
- **FR-7.4** A tenant can never read or affect another tenant's wallets, users, or transactions.
- **FR-7.5** Any request touching another tenant's data returns 404 Not Found, so a tenant cannot tell whether that data exists. **(assumption)**

## 8. Ledger

- **FR-8.1** Every balance change is recorded as a transaction.
- **FR-8.2** Transactions are immutable.
- **FR-8.3** The ledger (the list of transactions) is the source of truth for balances, not just a mutable balance field.

## 9. Idempotency

- **FR-9.1** Deposit, withdraw, and transfer accept a client-provided idempotency key, sent in the `Idempotency-Key` request header. **(assumption: header instead of a body field)**
- **FR-9.2** A retried request with the same key never charges twice.
- **FR-9.3** Idempotency keys are scoped per tenant. One key can be used once across all three endpoints. **(assumption: shared across endpoints)**
- **FR-9.4** The key is required. A request without it is rejected with 400 Bad Request. **(assumption)**
- **FR-9.5** A key is any string up to 255 characters. UUIDs are recommended but not enforced. **(assumption)**
- **FR-9.6** Only successful requests are remembered. A failed request (e.g. insufficient funds) can be retried with the same key. **(assumption)**
- **FR-9.7** A retry with the same key and the same request returns the same status code and body as the original. **(assumption)**
- **FR-9.8** A reused key with a different request (different operation, wallet(s), or amount) is rejected with 422 Unprocessable Entity. **(assumption)**
- **FR-9.9** If two requests with the same key arrive at the same time, only one is executed. The other returns the result of the one that was executed. **(assumption)**
- **FR-9.10** Keys do not expire. **(assumption)**

## 10. Money

- **FR-10.1** The system uses a single currency: Bangladeshi Taka (BDT). **(assumption)**
- **FR-10.2** Money is stored as integer paisa (1 Taka = 100 paisa).
- **FR-10.3** Money is never stored as a float.

## 11. Validation and Errors

- **FR-11.1** Zero or negative amounts are rejected. **(assumption)**
- **FR-11.2** There is no maximum amount. **(assumption)**
- **FR-11.3** Errors return clear responses using standard HTTP status codes. **(assumption: format)**

---

## Core Entities

### Tenant
A merchant or organization using the platform.

| Field | Description |
|---|---|
| id | Unique identifier |
| name | Tenant name |
| api_key | Used to identify the tenant on every request (stored as a hash) |
| created_at | When the tenant was created |

### User
A user belonging to one tenant.

| Field | Description |
|---|---|
| id | Unique identifier |
| tenant | The tenant this user belongs to |
| name | User name |
| created_at | When the user was created |

### Wallet
Holds a user's money. Each user has exactly one wallet.

| Field | Description |
|---|---|
| id | Unique identifier |
| tenant | The tenant this wallet belongs to |
| user | The owner of the wallet |
| balance | Current balance in paisa, kept in sync with the ledger |
| created_at | When the wallet was created |

### Transaction
One immutable ledger entry. Every balance change creates one.

| Field | Description |
|---|---|
| id | Unique identifier |
| tenant | The tenant this transaction belongs to |
| type | `DEPOSIT`, `WITHDRAWAL`, or `TRANSFER` |
| amount | Amount in paisa (always positive) |
| source_wallet | Wallet money leaves from (empty for deposits) |
| destination_wallet | Wallet money goes to (empty for withdrawals) |
| idempotency_key | Client-provided key, unique per tenant |
| created_at | When the transaction happened |

When a request arrives with a key that already exists, its operation, wallet(s), and amount are compared with this transaction's `type`, `source_wallet`, `destination_wallet`, and `amount`. If they match, the original result is returned (FR-9.7). If not, the request is rejected with 422 (FR-9.8).

### Relationships

- A tenant has many users.
- A user has one wallet.
- A wallet appears in many transactions, as source or destination.
- Every user, wallet, and transaction belongs to exactly one tenant.

---

## Assumptions

- **Only functional items are listed.** Row locking (`select_for_update`), tests, README, the Django + DRF stack, PostgreSQL, and Docker are left out because they describe how to build or what to deliver, not what the system does.
- **Money and validation are included** because they directly affect what the API accepts.
- **The "client"** is the tenant's own backend, which calls the API on behalf of its users. End users do not call the API directly, so user-level authentication is out of scope. The PDF only requires isolation between tenants.
- **Tenant creation** sits outside "every request is scoped to a tenant". It creates the tenant that later requests are scoped to.
- **One currency** (BDT / paisa) for the whole system.
- **Pagination** is page-number based, 10 items per page, newest first.
- **Transfers** are one transaction record, shown in both wallets' histories.
- **API key only.** The PDF allows an API key or an `X-Tenant-ID` header. We use only the API key, because a tenant ID can be guessed and sent by anyone, while a random key proves who is calling.
- **404 for cross-tenant access** rather than 403, so another tenant's data is indistinguishable from data that does not exist.
- **`Idempotency-Key` header.** The PDF writes `idempotency_key`, which reads like a body field. We use the `Idempotency-Key` header instead, following the common convention (Stripe, IETF draft).
- **Idempotency behaviour** (FR-9.3 to FR-9.10) follows common practice from Stripe and the IETF Idempotency-Key draft:
  - Reusing a key with a different request is rejected (422) instead of replayed, so a client bug cannot be hidden behind a misleading success.
  - Only successes are remembered, so the key can live on the ledger transaction itself and can never exist without its transaction.
  - Keys never expire, because they are stored permanently with the transaction.
- **User and Wallet are separate entities** in a one-to-one relationship, because the PDF names users and wallets separately.
- **Users only have a name.** The PDF gives no user fields, so we keep the minimum.
- **`tenant` is stored on every entity**, not just on the tenant's users, so every query can be filtered by tenant directly.
- **Wallet `balance` is a cached value.** The ledger is the source of truth. The balance is updated in the same database transaction as each ledger entry, and it can always be recalculated from the ledger.
- **API keys are stored as a hash.** The plain key is shown only once, when the tenant is created.
- **Idempotency keys live on the Transaction**, since only successful requests are remembered (FR-9.6). A replayed response is rebuilt from the stored transaction.
- **Timestamps (`created_at`)** are added to every entity. The PDF doesn't mention them, but they are needed to order the transaction history.
