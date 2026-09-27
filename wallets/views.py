from drf_spectacular.utils import extend_schema
from rest_framework import generics

from .serializers import UserSerializer, WalletSerializer
from .services import get_wallet_for_tenant


@extend_schema(summary='Create a user and their wallet', tags=['Users'])
class UserCreateView(generics.CreateAPIView):
    """Create a user in the calling tenant, together with their one wallet (balance 0).

    Keep the returned `wallet.id`: every money route takes it.
    """

    serializer_class = UserSerializer


@extend_schema(summary='Get a wallet and its balance', tags=['Wallets'])
class WalletDetailView(generics.RetrieveAPIView):
    """Return a wallet of the calling tenant. Another tenant's wallet is a 404, like a missing one."""

    serializer_class = WalletSerializer

    def get_object(self):
        return get_wallet_for_tenant(self.request.auth, self.kwargs['wallet_id'])
