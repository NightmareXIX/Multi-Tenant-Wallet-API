import uuid
from unittest import mock

from rest_framework.test import APITestCase

from tenants.authentication import generate_api_key, hash_api_key
from tenants.models import Tenant
from wallets.models import Transaction
from wallets import services
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

    def transfer(self, source_id, destination_id, amount, key=None):
        body = {'source_wallet_id': str(source_id), 'destination_wallet_id': str(destination_id), 'amount': amount}
        return self.post('/api/v1/transfers', body, key or str(uuid.uuid4()))

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
                self.assertIn('amount', response.data['error']['fields'])
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
        self.assertEqual(response.data['error']['code'], 'insufficient_funds')
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



class TransferTests(MoneyTestCase):
    def setUp(self):
        super().setUp()
        self.bob = create_user(self.acme, 'Bob').wallet
        self.deposit(self.wallet.id, 1000)

    def test_transfer_moves_money_and_records_one_transaction(self):
        response = self.transfer(self.wallet.id, self.bob.id, 400, key='key-1')

        self.assertEqual(response.status_code, 201)
        transfer = Transaction.objects.get(type='TRANSFER')
        self.assertEqual(
            response.data,
            {
                'id': str(transfer.id),
                'type': 'TRANSFER',
                'amount': 400,
                'source_wallet_id': str(self.wallet.id),
                'destination_wallet_id': str(self.bob.id),
                'idempotency_key': 'key-1',
                'created_at': response.data['created_at'],
            },
        )
        self.assertEqual(self.balance(self.wallet), 600)
        self.assertEqual(self.balance(self.bob), 400)

    def test_transfer_works_in_both_directions(self):
        self.transfer(self.wallet.id, self.bob.id, 1000)
        self.assertEqual(self.transfer(self.bob.id, self.wallet.id, 300).status_code, 201)
        self.assertEqual(self.balance(self.wallet), 300)
        self.assertEqual(self.balance(self.bob), 700)

    def test_insufficient_funds_returns_422_and_changes_nothing(self):
        response = self.transfer(self.wallet.id, self.bob.id, 1001)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.data['error']['code'], 'insufficient_funds')
        self.assertEqual(self.balance(self.wallet), 1000)
        self.assertEqual(self.balance(self.bob), 0)
        self.assertFalse(Transaction.objects.filter(type='TRANSFER').exists())

    def test_same_wallet_returns_400_without_touching_the_database(self):
        key = str(uuid.uuid4())
        # Only the auth lookup of the API key runs.
        with self.assertNumQueries(1):
            response = self.transfer(self.wallet.id, self.wallet.id, 100, key=key)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error']['code'], 'same_wallet_transfer')
        self.assertEqual(self.balance(self.wallet), 1000)

    def test_invalid_body_returns_400(self):
        valid = {'source_wallet_id': str(self.wallet.id), 'destination_wallet_id': str(self.bob.id), 'amount': 100}
        for field, value in (
            ('amount', '100'),
            ('amount', 1.5),
            ('amount', False),
            ('amount', 0),
            ('source_wallet_id', 'not-a-uuid'),
            ('destination_wallet_id', None),
        ):
            with self.subTest(field=field, value=value):
                response = self.post('/api/v1/transfers', {**valid, field: value}, str(uuid.uuid4()))
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data['error']['fields'])
        self.assertEqual(self.balance(self.wallet), 1000)

    def test_destination_in_another_tenant_returns_404(self):
        globex_wallet = create_user(self.globex, 'Gina').wallet

        response = self.transfer(self.wallet.id, globex_wallet.id, 100)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.balance(self.wallet), 1000)
        self.assertEqual(self.balance(globex_wallet), 0)

    def test_source_in_another_tenant_returns_404(self):
        globex_wallet = create_user(self.globex, 'Gina').wallet
        self.client.credentials(HTTP_X_API_KEY=self.globex_key)

        response = self.transfer(self.wallet.id, globex_wallet.id, 100)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.balance(self.wallet), 1000)
        self.assertEqual(self.balance(globex_wallet), 0)

    def test_unknown_wallet_returns_404(self):
        self.assertEqual(self.transfer(self.wallet.id, uuid.uuid4(), 100).status_code, 404)
        self.assertEqual(self.transfer(uuid.uuid4(), self.bob.id, 100).status_code, 404)
        self.assertEqual(self.balance(self.wallet), 1000)

    def test_transfer_past_the_destination_maximum_returns_400_and_changes_nothing(self):
        self.deposit(self.bob.id, BIGINT_MAX)

        response = self.transfer(self.wallet.id, self.bob.id, 1)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.balance(self.wallet), 1000)
        self.assertEqual(self.balance(self.bob), BIGINT_MAX)

    def test_replay_returns_same_body_without_moving_money_again(self):
        first = self.transfer(self.wallet.id, self.bob.id, 400, key='key-1')
        second = self.transfer(self.wallet.id, self.bob.id, 400, key='key-1')

        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.data, first.data)
        self.assertEqual(self.balance(self.wallet), 600)
        self.assertEqual(self.balance(self.bob), 400)

    def test_same_key_in_reverse_direction_returns_422(self):
        self.transfer(self.wallet.id, self.bob.id, 400, key='key-1')
        self.assertEqual(self.transfer(self.bob.id, self.wallet.id, 400, key='key-1').status_code, 422)

    def test_missing_api_key_returns_401(self):
        self.client.credentials()
        self.assertEqual(self.transfer(self.wallet.id, self.bob.id, 100).status_code, 401)

class IdempotencyKeyHeaderTests(MoneyTestCase):
    def test_missing_blank_or_too_long_key_returns_400(self):
        url = f'/api/v1/wallets/{self.wallet.id}/deposit'
        for key in (None, '', '   ', 'k' * 256):
            with self.subTest(key=key):
                response = self.post(url, {'amount': 100}, key)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['error']['code'], 'idempotency_key_missing')
        self.assertFalse(Transaction.objects.exists())

    def test_key_of_255_characters_is_accepted(self):
        response = self.deposit(self.wallet.id, 100, key='k' * 255)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['idempotency_key'], 'k' * 255)


class IdempotencyTests(MoneyTestCase):
    def test_same_key_and_request_replays_without_a_new_transaction(self):
        first = self.deposit(self.wallet.id, 500, key='key-1')
        second = self.deposit(self.wallet.id, 500, key='key-1')

        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.data, first.data)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(self.balance(self.wallet), 500)

    def test_same_key_with_different_amount_returns_422(self):
        self.deposit(self.wallet.id, 500, key='key-1')

        response = self.deposit(self.wallet.id, 600, key='key-1')

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.data['error']['code'], 'idempotency_key_mismatch')
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(self.balance(self.wallet), 500)

    def test_same_key_on_another_wallet_returns_422(self):
        bob = create_user(self.acme, 'Bob').wallet
        self.deposit(self.wallet.id, 500, key='key-1')

        self.assertEqual(self.deposit(bob.id, 500, key='key-1').status_code, 422)
        self.assertEqual(self.balance(bob), 0)

    def test_same_key_on_another_operation_returns_422(self):
        self.deposit(self.wallet.id, 500, key='key-1')

        self.assertEqual(self.withdraw(self.wallet.id, 500, key='key-1').status_code, 422)
        self.assertEqual(self.balance(self.wallet), 500)

    def test_key_of_a_failed_request_can_be_reused(self):
        self.assertEqual(self.withdraw(self.wallet.id, 500, key='key-1').status_code, 422)
        self.deposit(self.wallet.id, 500)

        response = self.withdraw(self.wallet.id, 500, key='key-1')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.balance(self.wallet), 0)

    def test_two_tenants_can_use_the_same_key(self):
        globex_wallet = create_user(self.globex, 'Gina').wallet
        self.assertEqual(self.deposit(self.wallet.id, 500, key='key-1').status_code, 201)

        self.client.credentials(HTTP_X_API_KEY=self.globex_key)
        self.assertEqual(self.deposit(globex_wallet.id, 700, key='key-1').status_code, 201)

        self.assertEqual(self.balance(self.wallet), 500)
        self.assertEqual(self.balance(globex_wallet), 700)
        self.assertEqual(Transaction.objects.filter(idempotency_key='key-1').count(), 2)

    def key_hidden_from_first_check(self):
        """Simulate a concurrent twin that commits the key right after this request's first lookup.

        Only the unique constraint can then stop a second execution.
        """
        find_existing = services._find_existing
        calls = []

        def first_lookup_misses(*args):
            calls.append(args)
            return None if len(calls) == 1 else find_existing(*args)

        return mock.patch.object(services, '_find_existing', side_effect=first_lookup_misses)

    def test_key_that_slips_past_the_first_check_is_caught_by_the_constraint(self):
        original = self.deposit(self.wallet.id, 500, key='key-1')

        with self.key_hidden_from_first_check():
            response = self.deposit(self.wallet.id, 500, key='key-1')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data, original.data)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(self.balance(self.wallet), 500)

    def test_mismatched_key_that_slips_past_the_first_check_returns_422(self):
        self.deposit(self.wallet.id, 500, key='key-1')

        with self.key_hidden_from_first_check():
            response = self.deposit(self.wallet.id, 900, key='key-1')

        self.assertEqual(response.status_code, 422)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(self.balance(self.wallet), 500)
