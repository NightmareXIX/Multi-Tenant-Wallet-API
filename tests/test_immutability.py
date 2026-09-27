from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TestCase

from wallets.models import Transaction
from wallets.services import create_user, deposit

from .test_wallets import create_tenant


class LedgerImmutabilityTests(TestCase):
    """A ledger row can be inserted but never changed or removed, by the model or around it."""

    def setUp(self):
        tenant, _ = create_tenant('Acme')
        wallet = create_user(tenant, 'Alice').wallet
        deposit(tenant, wallet.id, 500, 'deposit-1')
        self.txn = Transaction.objects.get()

    def assertRejectedByDatabase(self, action):
        # A savepoint keeps the test's own transaction usable after the error.
        with self.assertRaises(DatabaseError) as caught, transaction.atomic():
            action()
        # services.py treats IntegrityError as an idempotency-key clash, so the trigger must not raise one.
        self.assertNotIsInstance(caught.exception, IntegrityError)

    def assertUnchanged(self):
        self.assertEqual(Transaction.objects.get(id=self.txn.id).amount, 500)

    def test_instance_save_is_rejected(self):
        self.txn.amount = 1
        with self.assertRaises(ValueError):
            self.txn.save()
        self.assertUnchanged()

    def test_instance_delete_is_rejected(self):
        with self.assertRaises(ValueError):
            self.txn.delete()
        self.assertUnchanged()

    def test_queryset_update_is_rejected(self):
        self.assertRejectedByDatabase(lambda: Transaction.objects.filter(id=self.txn.id).update(amount=1))
        self.assertUnchanged()

    def test_queryset_delete_is_rejected(self):
        self.assertRejectedByDatabase(lambda: Transaction.objects.filter(id=self.txn.id).delete())
        self.assertUnchanged()

    def test_raw_sql_update_is_rejected(self):
        def update():
            with connection.cursor() as cursor:
                cursor.execute('UPDATE wallets_transaction SET amount = 1 WHERE id = %s', [self.txn.id])

        self.assertRejectedByDatabase(update)
        self.assertUnchanged()

    def test_raw_sql_delete_is_rejected(self):
        def delete():
            with connection.cursor() as cursor:
                cursor.execute('DELETE FROM wallets_transaction WHERE id = %s', [self.txn.id])

        self.assertRejectedByDatabase(delete)
        self.assertUnchanged()
