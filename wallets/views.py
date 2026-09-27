from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.pagination import PageNumberPagination

from .models import Transaction
from .serializers import TransactionSerializer, UserSerializer, WalletSerializer
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


class TransactionPagination(PageNumberPagination):
    page_size = 10


@extend_schema(summary="Get a wallet's transaction history", tags=['Wallets'])
class WalletTransactionListView(generics.ListAPIView):
    """Every transaction where the wallet is the source or the destination, newest first, 10 per page.

    A transfer is one record, so it appears in both wallets' histories.
    """

    serializer_class = TransactionSerializer
    pagination_class = TransactionPagination

    def get_queryset(self):
        wallet = get_wallet_for_tenant(self.request.auth, self.kwargs['wallet_id'])
        # The -id tiebreaker keeps the order stable when timestamps match.
        return Transaction.objects.filter(
            Q(source_wallet=wallet) | Q(destination_wallet=wallet)
        ).order_by('-created_at', '-id')
