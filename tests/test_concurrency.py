import threading
import uuid

from django.db import connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from tenants.authentication import generate_api_key, hash_api_key
from tenants.models import Tenant
from tests.ledger import LedgerAssertions
from wallets import services
from wallets.models import Transaction


def create_tenant(name):
    key = generate_api_key()
    return Tenant.objects.create(name=name, api_key_hash=hash_api_key(key)), key


def run_concurrently(requests):
    """Send each request from its own thread, all released together by a barrier; return the responses in order.

    Each thread closes its DB connection, or the test database cannot be dropped afterwards.
    An exception in a thread (e.g. a deadlock surfacing as a 500) is re-raised in the test.
    """
    barrier = threading.Barrier(len(requests), timeout=10)
    results = [None] * len(requests)

    def send(index, request):
        try:
            client = APIClient()
            barrier.wait()
            results[index] = request(client)
        except Exception as exc:
            results[index] = exc
        finally:
            connection.close()

    threads = [threading.Thread(target=send, args=(i, request)) for i, request in enumerate(requests)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    for result in results:
        if isinstance(result, Exception):
            raise result
    return results


class ConcurrencyTests(LedgerAssertions, TransactionTestCase):
    """Real parallel requests. TransactionTestCase, because TestCase's wrapping transaction hides rows from other threads."""

    def setUp(self):
        self.tenant, self.key = create_tenant('Acme')
        self.alice = services.create_user(self.tenant, 'Alice').wallet
        self.bob = services.create_user(self.tenant, 'Bob').wallet

    def seed(self, wallet, amount):
        services.deposit(self.tenant, wallet.id, amount, str(uuid.uuid4()))

    def request(self, url, body, key=None):
        headers = {'X-API-Key': self.key, 'Idempotency-Key': key or str(uuid.uuid4())}
        return lambda client: client.post(url, body, format='json', headers=headers)

    def deposit(self, wallet, amount, key=None):
        return self.request(f'/api/v1/wallets/{wallet.id}/deposit', {'amount': amount}, key)

    def withdraw(self, wallet, amount):
        return self.request(f'/api/v1/wallets/{wallet.id}/withdraw', {'amount': amount})

    def transfer(self, source, destination, amount):
        body = {'source_wallet_id': str(source.id), 'destination_wallet_id': str(destination.id), 'amount': amount}
        return self.request('/api/v1/transfers', body)

    def balance(self, wallet):
        wallet.refresh_from_db()
        return wallet.balance

    def test_concurrent_transfers_never_overdraw(self):
        self.seed(self.alice, 1000)

        responses = run_concurrently([self.transfer(self.alice, self.bob, 200) for _ in range(10)])

        self.assertEqual(sorted(r.status_code for r in responses), [201] * 5 + [422] * 5)
        for response in responses:
            if response.status_code == 422:
                self.assertEqual(response.data['error']['code'], 'insufficient_funds')
        self.assertEqual(self.balance(self.alice), 0)
        self.assertEqual(self.balance(self.bob), 1000)
        self.assertEqual(Transaction.objects.filter(type='TRANSFER').count(), 5)
        self.assertLedgerMatches()

    def test_opposite_transfers_do_not_deadlock(self):
        self.seed(self.alice, 1000)
        self.seed(self.bob, 1000)

        responses = run_concurrently(
            [self.transfer(self.alice, self.bob, 100), self.transfer(self.bob, self.alice, 100)] * 5
        )

        self.assertEqual([r.status_code for r in responses], [201] * 10)
        self.assertEqual(self.balance(self.alice), 1000)
        self.assertEqual(self.balance(self.bob), 1000)
        self.assertLedgerMatches()

    def test_mixed_operations_never_go_negative(self):
        self.seed(self.alice, 1000)
        self.seed(self.bob, 1000)

        # Alice is asked for far more than she can ever hold, so some requests must fail.
        responses = run_concurrently(
            [
                self.deposit(self.alice, 100),
                self.withdraw(self.alice, 300),
                self.transfer(self.alice, self.bob, 300),
                self.transfer(self.bob, self.alice, 100),
            ]
            * 5
        )

        self.assertLessEqual({r.status_code for r in responses}, {201, 422})
        self.assertGreaterEqual(self.balance(self.alice), 0)
        self.assertGreaterEqual(self.balance(self.bob), 0)
        self.assertLedgerMatches()

