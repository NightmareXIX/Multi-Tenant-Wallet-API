from unittest import mock

from rest_framework.test import APITestCase

from tenants.authentication import generate_api_key, hash_api_key
from tenants.models import Tenant
from wallets.models import User, Wallet
from wallets.services import create_user

URL = '/api/v1/users'


def create_tenant(name):
    key = generate_api_key()
    return Tenant.objects.create(name=name, api_key_hash=hash_api_key(key)), key


class CreateUserTests(APITestCase):
    def setUp(self):
        self.tenant, key = create_tenant('Acme')
        self.client.credentials(HTTP_X_API_KEY=key)

    def test_creates_user_with_empty_wallet(self):
        response = self.client.post(URL, {'name': 'Alice'}, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.data), {'id', 'name', 'wallet', 'created_at'})
        self.assertEqual(response.data['name'], 'Alice')
        wallet = response.data['wallet']
        self.assertEqual(set(wallet), {'id', 'user_id', 'balance', 'created_at'})
        self.assertEqual(wallet['balance'], 0)
        self.assertEqual(wallet['user_id'], response.data['id'])

        user = User.objects.get(id=response.data['id'])
        self.assertEqual(user.tenant, self.tenant)
        self.assertEqual(user.wallet.tenant, self.tenant)
        self.assertEqual(str(user.wallet.id), wallet['id'])

    def test_invalid_name_returns_400(self):
        for body in ({}, {'name': ''}, {'name': '   '}, {'name': 'x' * 256}):
            with self.subTest(body=body):
                response = self.client.post(URL, body, format='json')
                self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.exists())
        self.assertFalse(Wallet.objects.exists())

    def test_missing_key_returns_401(self):
        self.client.credentials()
        response = self.client.post(URL, {'name': 'Alice'}, format='json')
        self.assertEqual(response.status_code, 401)
        self.assertFalse(User.objects.exists())


class CreateUserServiceTests(APITestCase):
    def test_user_is_rolled_back_when_wallet_creation_fails(self):
        tenant, _ = create_tenant('Acme')
        with mock.patch.object(Wallet.objects, 'create', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                create_user(tenant, 'Alice')
        self.assertFalse(User.objects.exists())
