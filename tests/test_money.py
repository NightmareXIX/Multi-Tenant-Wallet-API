import uuid

from rest_framework.test import APITestCase

from tenants.authentication import generate_api_key, hash_api_key
from tenants.models import Tenant
from wallets.models import Transaction
from wallets.services import BIGINT_MAX, create_user


def create_tenant(name):
    key = generate_api_key()
    return Tenant.objects.create(name=name, api_key_hash=hash_api_key(key)), key


class MoneyTestCase(APITestCase):
    """Acme (the caller) owns self.wallet; Globex is another tenant with its own key."""

    def setUp(self):
        self.acme, self.acme_key = create_tenant('Acme')
        self.globex, self.globex_key = create_tenant('Globex')
        self.wallet = create_user(self.acme, 'Alice').wallet
        self.client.credentials(HTTP_X_API_KEY=self.acme_key)

    def post(self, url, body, key=None):
        headers = {} if key is None else {'Idempotency-Key': key}
        return self.client.post(url, body, format='json', headers=headers)

    def deposit(self, wallet_id, amount, key=None):
        return self.post(f'/api/v1/wallets/{wallet_id}/deposit', {'amount': amount}, key or str(uuid.uuid4()))

    def withdraw(self, wallet_id, amount, key=None):
        return self.post(f'/api/v1/wallets/{wallet_id}/withdraw', {'amount': amount}, key or str(uuid.uuid4()))

    def balance(self, wallet):
        wallet.refresh_from_db()
        return wallet.balance


class DepositTests(MoneyTestCase):
    def test_deposit_returns_transaction_and_updates_balance(self):
        response = self.deposit(self.wallet.id, 15050, key='key-1')

        self.assertEqual(response.status_code, 201)
        transaction = Transaction.objects.get()
        self.assertEqual(
            response.data,
            {
                'id': str(transaction.id),
                'type': 'DEPOSIT',
                'amount': 15050,
                'source_wallet_id': None,
                'destination_wallet_id': str(self.wallet.id),
                'idempotency_key': 'key-1',
                'created_at': response.data['created_at'],
            },
        )
        self.assertEqual(transaction.tenant, self.acme)
        self.assertEqual(self.balance(self.wallet), 15050)

    def test_deposits_add_up(self):
        self.deposit(self.wallet.id, 100)
        self.deposit(self.wallet.id, 250)
        self.assertEqual(self.balance(self.wallet), 350)
        self.assertEqual(Transaction.objects.count(), 2)

    def test_invalid_amount_returns_400(self):
        for amount in ('100', 100.0, 100.5, True, 0, -5, BIGINT_MAX + 1, None):
            with self.subTest(amount=amount):
                response = self.deposit(self.wallet.id, amount)
                self.assertEqual(response.status_code, 400)
                self.assertIn('amount', response.data)
        response = self.post(f'/api/v1/wallets/{self.wallet.id}/deposit', {}, 'key-1')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.balance(self.wallet), 0)
        self.assertFalse(Transaction.objects.exists())

    def test_largest_amount_is_accepted(self):
        self.assertEqual(self.deposit(self.wallet.id, BIGINT_MAX).status_code, 201)
        self.assertEqual(self.balance(self.wallet), BIGINT_MAX)

    def test_deposit_past_the_maximum_balance_returns_400(self):
        self.deposit(self.wallet.id, BIGINT_MAX)

        response = self.deposit(self.wallet.id, 1)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.balance(self.wallet), BIGINT_MAX)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_other_tenants_wallet_returns_404(self):
        self.client.credentials(HTTP_X_API_KEY=self.globex_key)
        self.assertEqual(self.deposit(self.wallet.id, 100).status_code, 404)
        self.assertEqual(self.balance(self.wallet), 0)
        self.assertFalse(Transaction.objects.exists())

    def test_unknown_wallet_returns_404(self):
        self.assertEqual(self.deposit(uuid.uuid4(), 100).status_code, 404)

    def test_missing_api_key_returns_401(self):
        self.client.credentials()
        self.assertEqual(self.deposit(self.wallet.id, 100).status_code, 401)
        self.assertFalse(Transaction.objects.exists())


class WithdrawTests(MoneyTestCase):
    def setUp(self):
        super().setUp()
        self.deposit(self.wallet.id, 1000)

    def test_withdraw_returns_transaction_and_updates_balance(self):
        response = self.withdraw(self.wallet.id, 300, key='key-1')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['type'], 'WITHDRAWAL')
        self.assertEqual(response.data['amount'], 300)
        self.assertEqual(response.data['source_wallet_id'], str(self.wallet.id))
        self.assertIsNone(response.data['destination_wallet_id'])
        self.assertEqual(self.balance(self.wallet), 700)

    def test_withdraw_whole_balance(self):
        self.assertEqual(self.withdraw(self.wallet.id, 1000).status_code, 201)
        self.assertEqual(self.balance(self.wallet), 0)

    def test_insufficient_funds_returns_422_and_changes_nothing(self):
        response = self.withdraw(self.wallet.id, 1001)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.data['detail'].code, 'insufficient_funds')
        self.assertEqual(self.balance(self.wallet), 1000)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_invalid_amount_returns_400(self):
        for amount in ('100', 100.0, True, 0, -5):
            with self.subTest(amount=amount):
                self.assertEqual(self.withdraw(self.wallet.id, amount).status_code, 400)
        self.assertEqual(self.balance(self.wallet), 1000)

    def test_other_tenants_wallet_returns_404(self):
        self.client.credentials(HTTP_X_API_KEY=self.globex_key)
        self.assertEqual(self.withdraw(self.wallet.id, 100).status_code, 404)
        self.assertEqual(self.balance(self.wallet), 1000)


class IdempotencyKeyHeaderTests(MoneyTestCase):
    def test_missing_blank_or_too_long_key_returns_400(self):
        url = f'/api/v1/wallets/{self.wallet.id}/deposit'
        for key in (None, '', '   ', 'k' * 256):
            with self.subTest(key=key):
                response = self.post(url, {'amount': 100}, key)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['detail'].code, 'idempotency_key_missing')
        self.assertFalse(Transaction.objects.exists())

    def test_key_of_255_characters_is_accepted(self):
        response = self.deposit(self.wallet.id, 100, key='k' * 255)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['idempotency_key'], 'k' * 255)
