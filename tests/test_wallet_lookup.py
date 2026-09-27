import uuid

from django.http import Http404
from django.test import TestCase

from tenants.authentication import generate_api_key, hash_api_key
from tenants.models import Tenant
from wallets.models import User, Wallet
from wallets.services import get_wallet_for_tenant


def create_wallet(tenant):
    user = User.objects.create(tenant=tenant, name='Alice')
    return Wallet.objects.create(tenant=tenant, user=user)


class GetWalletForTenantTests(TestCase):
    def setUp(self):
        self.acme = Tenant.objects.create(name='Acme', api_key_hash=hash_api_key(generate_api_key()))
        self.globex = Tenant.objects.create(name='Globex', api_key_hash=hash_api_key(generate_api_key()))
        self.wallet = create_wallet(self.acme)

    def test_returns_own_wallet(self):
        self.assertEqual(get_wallet_for_tenant(self.acme, self.wallet.id), self.wallet)

    def test_other_tenants_wallet_is_not_found(self):
        with self.assertRaises(Http404):
            get_wallet_for_tenant(self.globex, self.wallet.id)

    def test_unknown_wallet_is_not_found(self):
        with self.assertRaises(Http404):
            get_wallet_for_tenant(self.acme, uuid.uuid4())
