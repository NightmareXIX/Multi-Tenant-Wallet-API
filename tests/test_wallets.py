import uuid

from rest_framework.test import APITestCase

from tenants.authentication import generate_api_key, hash_api_key
from tenants.models import Tenant
from wallets.services import create_user


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
