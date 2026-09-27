import uuid

from django.db import models
from django.db.models import F, Q


class User(models.Model):
    """A tenant's end user. Not a Django auth user; AUTH_USER_MODEL is untouched."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT, related_name='users')
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Wallet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT, related_name='wallets')
    user = models.OneToOneField(User, on_delete=models.PROTECT, related_name='wallet')
    # Paisa. A cached value: the ledger (Transaction) is the source of truth.
    balance = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(balance__gte=0), name='wallet_balance_non_negative'),
        ]

    def __str__(self):
        return f'Wallet {self.id}'


class Transaction(models.Model):
    """One immutable ledger entry. Every balance change creates exactly one.

    save() and delete() reject changes here; a Postgres trigger (migration 0002) also rejects
    UPDATE and DELETE on the table, so bulk queryset calls and raw SQL fail too.
    """

    class Type(models.TextChoices):
        DEPOSIT = 'DEPOSIT'
        WITHDRAWAL = 'WITHDRAWAL'
        TRANSFER = 'TRANSFER'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT, related_name='transactions')
    type = models.CharField(max_length=10, choices=Type.choices)
    # Paisa, always positive; the direction comes from the wallets.
    amount = models.BigIntegerField()
    source_wallet = models.ForeignKey(
        Wallet, on_delete=models.PROTECT, null=True, blank=True, related_name='outgoing_transactions'
    )
    destination_wallet = models.ForeignKey(
        Wallet, on_delete=models.PROTECT, null=True, blank=True, related_name='incoming_transactions'
    )
    idempotency_key = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # The real idempotency guarantee; code checks are only a fast path.
            models.UniqueConstraint(
                fields=['tenant', 'idempotency_key'],
                name='transaction_unique_idempotency_key_per_tenant',
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name='transaction_amount_positive'),
            models.CheckConstraint(
                condition=(
                    Q(
                        type='DEPOSIT',
                        source_wallet__isnull=True,
                        destination_wallet__isnull=False,
                    )
                    | Q(
                        type='WITHDRAWAL',
                        source_wallet__isnull=False,
                        destination_wallet__isnull=True,
                    )
                    | (
                        Q(
                            type='TRANSFER',
                            source_wallet__isnull=False,
                            destination_wallet__isnull=False,
                        )
                        & ~Q(source_wallet=F('destination_wallet'))
                    )
                ),
                name='transaction_wallets_match_type',
            ),
        ]
        indexes = [
            models.Index(fields=['source_wallet', 'created_at'], name='transaction_source_created_idx'),
            models.Index(fields=['destination_wallet', 'created_at'], name='transaction_dest_created_idx'),
        ]

    def __str__(self):
        return f'{self.type} {self.amount} ({self.id})'

    def save(self, *args, **kwargs):
        # A UUID pk is set before the first save, so check _state.adding, not pk.
        if not self._state.adding:
            raise ValueError('Transactions are immutable and cannot be updated.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('Transactions are immutable and cannot be deleted.')
