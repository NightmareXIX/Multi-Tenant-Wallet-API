import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

from rest_framework.test import APITestCase

from tenants.authentication import generate_api_key, hash_api_key
from tenants.models import Tenant
from wallets.models import Transaction
from wallets.services import create_user

T0 = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)


def create_tenant(name):
    key = generate_api_key()
    return Tenant.objects.create(name=name, api_key_hash=hash_api_key(key)), key


class WalletTestCase(APITestCase):
    """Acme (the caller) owns self.wallet; Globex is another tenant with its own key."""

    def setUp(self):
        self.acme, self.acme_key = create_tenant('Acme')
        self.globex, self.globex_key = create_tenant('Globex')
        self.wallet = create_user(self.acme, 'Alice').wallet
        self.client.credentials(HTTP_X_API_KEY=self.acme_key)

    def record(self, type, amount=100, source=None, destination=None, at=T0):
        """Seed a ledger row directly; the money services arrive in Phase 5."""
        with mock.patch('django.utils.timezone.now', return_value=at):
            return Transaction.objects.create(
                tenant=source.tenant if source else destination.tenant,
                type=type,
                amount=amount,
                source_wallet=source,
                destination_wallet=destination,
                idempotency_key=str(uuid.uuid4()),
            )


class GetWalletTests(WalletTestCase):
    def url(self, wallet_id):
        return f'/api/v1/wallets/{wallet_id}'

    def test_returns_wallet_with_balance(self):
        response = self.client.get(self.url(self.wallet.id))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                'id': str(self.wallet.id),
                'user_id': str(self.wallet.user_id),
                'balance': 0,
                'created_at': response.data['created_at'],
            },
        )

    def test_other_tenants_wallet_returns_404(self):
        self.client.credentials(HTTP_X_API_KEY=self.globex_key)
        self.assertEqual(self.client.get(self.url(self.wallet.id)).status_code, 404)

    def test_unknown_wallet_returns_404(self):
        self.assertEqual(self.client.get(self.url(uuid.uuid4())).status_code, 404)

    def test_missing_key_returns_401(self):
        self.client.credentials()
        self.assertEqual(self.client.get(self.url(self.wallet.id)).status_code, 401)


class TransactionHistoryTests(WalletTestCase):
    def url(self, wallet_id):
        return f'/api/v1/wallets/{wallet_id}/transactions'

    def ids(self, response):
        return [row['id'] for row in response.data['results']]

    def test_new_wallet_has_empty_page(self):
        response = self.client.get(self.url(self.wallet.id))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'count': 0, 'next': None, 'previous': None, 'results': []})

    def test_lists_only_this_wallets_transactions(self):
        bob = create_user(self.acme, 'Bob').wallet
        carol = create_user(self.acme, 'Carol').wallet
        deposit = self.record('DEPOSIT', destination=self.wallet, at=T0)
        withdrawal = self.record('WITHDRAWAL', source=self.wallet, at=T0 + timedelta(seconds=1))
        sent = self.record('TRANSFER', source=self.wallet, destination=bob, at=T0 + timedelta(seconds=2))
        received = self.record('TRANSFER', source=bob, destination=self.wallet, at=T0 + timedelta(seconds=3))
        self.record('DEPOSIT', destination=bob)
        self.record('TRANSFER', source=bob, destination=carol)

        response = self.client.get(self.url(self.wallet.id))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 4)
        self.assertEqual(
            self.ids(response), [str(t.id) for t in (received, sent, withdrawal, deposit)]
        )

    def test_transfer_appears_in_both_histories(self):
        bob = create_user(self.acme, 'Bob').wallet
        transfer = self.record('TRANSFER', source=self.wallet, destination=bob)

        self.assertEqual(self.ids(self.client.get(self.url(self.wallet.id))), [str(transfer.id)])
        self.assertEqual(self.ids(self.client.get(self.url(bob.id))), [str(transfer.id)])

    def test_transaction_shape(self):
        deposit = self.record('DEPOSIT', amount=15050, destination=self.wallet)

        row = self.client.get(self.url(self.wallet.id)).data['results'][0]

        self.assertEqual(
            row,
            {
                'id': str(deposit.id),
                'type': 'DEPOSIT',
                'amount': 15050,
                'source_wallet_id': None,
                'destination_wallet_id': str(self.wallet.id),
                'idempotency_key': deposit.idempotency_key,
                'created_at': '2026-09-27T10:00:00Z',
            },
        )

    def test_paginates_ten_per_page_newest_first(self):
        rows = [
            self.record('DEPOSIT', destination=self.wallet, at=T0 + timedelta(seconds=i))
            for i in range(12)
        ]
        newest_first = [str(t.id) for t in reversed(rows)]

        first = self.client.get(self.url(self.wallet.id))
        self.assertEqual(first.data['count'], 12)
        self.assertEqual(self.ids(first), newest_first[:10])
        self.assertIsNone(first.data['previous'])
        self.assertTrue(first.data['next'].endswith(f'{self.url(self.wallet.id)}?page=2'))

        second = self.client.get(self.url(self.wallet.id), {'page': 2})
        self.assertEqual(self.ids(second), newest_first[10:])
        self.assertIsNone(second.data['next'])

    def test_equal_timestamps_are_ordered_by_id(self):
        rows = [self.record('DEPOSIT', destination=self.wallet, at=T0) for _ in range(3)]

        response = self.client.get(self.url(self.wallet.id))

        self.assertEqual(self.ids(response), sorted((str(t.id) for t in rows), reverse=True))

    def test_page_out_of_range_returns_404(self):
        self.record('DEPOSIT', destination=self.wallet)
        self.assertEqual(self.client.get(self.url(self.wallet.id), {'page': 2}).status_code, 404)

    def test_other_tenants_wallet_returns_404(self):
        self.record('DEPOSIT', destination=self.wallet)
        self.client.credentials(HTTP_X_API_KEY=self.globex_key)
        self.assertEqual(self.client.get(self.url(self.wallet.id)).status_code, 404)

    def test_unknown_wallet_returns_404(self):
        self.assertEqual(self.client.get(self.url(uuid.uuid4())).status_code, 404)

    def test_missing_key_returns_401(self):
        self.client.credentials()
        self.assertEqual(self.client.get(self.url(self.wallet.id)).status_code, 401)
