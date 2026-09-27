from django.shortcuts import get_object_or_404

from .models import Wallet


def get_wallet_for_tenant(tenant, wallet_id):
    """The only way views look up a wallet.

    Another tenant's wallet raises 404 exactly like a missing one, so a tenant
    cannot tell whether it exists. Never query Wallet by id without the tenant.
    """
    return get_object_or_404(Wallet, tenant=tenant, id=wallet_id)
