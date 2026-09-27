from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from .exceptions import IdempotencyKeyMismatch, InsufficientFunds
from .models import Transaction, User, Wallet

# Largest value a BigIntegerField (Postgres bigint) can hold.
BIGINT_MAX = 2**63 - 1


def get_wallet_for_tenant(tenant, wallet_id, for_update=False):
    """The only way views look up a wallet.

    Another tenant's wallet raises 404 exactly like a missing one, so a tenant
    cannot tell whether it exists. Never query Wallet by id without the tenant.
    With for_update, the row stays locked until the surrounding atomic block ends.
    """
    wallets = Wallet.objects.select_for_update() if for_update else Wallet.objects
    return get_object_or_404(wallets, tenant=tenant, id=wallet_id)


def create_user(tenant, name):
    """Create a user and their one wallet together, so a user never exists without a wallet."""
    with transaction.atomic():
        user = User.objects.create(tenant=tenant, name=name)
        Wallet.objects.create(tenant=tenant, user=user)
    return user


def deposit(tenant, wallet_id, amount, idempotency_key):
    return _execute(tenant, idempotency_key, Transaction.Type.DEPOSIT, amount, None, wallet_id)


def withdraw(tenant, wallet_id, amount, idempotency_key):
    return _execute(tenant, idempotency_key, Transaction.Type.WITHDRAWAL, amount, wallet_id, None)


def _execute(tenant, idempotency_key, type, amount, source_id, destination_id):
    """Run a money operation at most once per idempotency key.

    Only successful operations store a key (on their ledger row), so a key whose
    request failed can be reused. The unique (tenant, idempotency_key) constraint
    is the real guarantee; the first lookup is only a fast path.
    """
    request = (type, amount, source_id, destination_id)
    existing = _find_existing(tenant, idempotency_key, request)
    if existing:
        return existing
    try:
        return _move_money(tenant, idempotency_key, *request)
    except IntegrityError:
        # A concurrent request with the same key committed first. Caught outside
        # the atomic block, so this request's balance changes are already rolled back.
        existing = _find_existing(tenant, idempotency_key, request)
        if existing is None:
            raise
        return existing


def _find_existing(tenant, idempotency_key, request):
    """Return the transaction stored under this key, or None if the key is new.

    A key reused for a different operation, wallet(s) or amount is rejected
    instead of replayed, so a client bug cannot hide behind a misleading success.
    """
    existing = Transaction.objects.filter(tenant=tenant, idempotency_key=idempotency_key).first()
    if existing is None:
        return None
    stored = (existing.type, existing.amount, existing.source_wallet_id, existing.destination_wallet_id)
    if stored != request:
        raise IdempotencyKeyMismatch()
    return existing


def _move_money(tenant, idempotency_key, type, amount, source_id, destination_id):
    """Move money and write its ledger row in one DB transaction.

    Balances are read and changed only on the instances select_for_update
    returned, so two requests on one wallet can never both spend the same money.
    """
    with transaction.atomic():
        wallet_ids = [wallet_id for wallet_id in (source_id, destination_id) if wallet_id]
        # Always lock in sorted id order, so two requests over the same wallets
        # (e.g. transfers A->B and B->A) take the locks in the same order and cannot deadlock.
        locked = {
            wallet_id: get_wallet_for_tenant(tenant, wallet_id, for_update=True)
            for wallet_id in sorted(wallet_ids)
        }
        source = locked.get(source_id)
        destination = locked.get(destination_id)

        if source:
            if source.balance < amount:
                raise InsufficientFunds()
            source.balance -= amount
            source.save(update_fields=['balance'])
        if destination:
            if destination.balance > BIGINT_MAX - amount:
                raise ValidationError({'amount': ['This would push the wallet balance past its maximum.']})
            destination.balance += amount
            destination.save(update_fields=['balance'])

        return Transaction.objects.create(
            tenant=tenant,
            type=type,
            amount=amount,
            source_wallet=source,
            destination_wallet=destination,
            idempotency_key=idempotency_key,
        )
