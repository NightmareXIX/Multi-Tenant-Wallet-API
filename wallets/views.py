from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .exceptions import IdempotencyKeyMissing
from .models import Transaction
from .serializers import AmountSerializer, TransactionSerializer, UserSerializer, WalletSerializer
from .services import get_wallet_for_tenant

IDEMPOTENCY_KEY = OpenApiParameter(
    'Idempotency-Key',
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description='Any string up to 255 characters, unique per request (a UUID is recommended). '
    'Resending the same request with the same key returns the original result without moving money again.',
)


def get_idempotency_key(request):
    key = request.headers.get('Idempotency-Key', '')
    if not key.strip() or len(key) > 255:
        raise IdempotencyKeyMissing()
    return key


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


@extend_schema(
    summary='Deposit into a wallet',
    tags=['Money'],
    parameters=[IDEMPOTENCY_KEY],
    request=AmountSerializer,
    responses={201: TransactionSerializer},
)
class DepositView(APIView):
    """Add `amount` paisa to a wallet of the calling tenant and return the new DEPOSIT transaction."""

    def post(self, request, wallet_id):
        key = get_idempotency_key(request)
        serializer = AmountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transaction = services.deposit(request.auth, wallet_id, serializer.validated_data['amount'], key)
        return Response(TransactionSerializer(transaction).data, status=status.HTTP_201_CREATED)


@extend_schema(
    summary='Withdraw from a wallet',
    tags=['Money'],
    parameters=[IDEMPOTENCY_KEY],
    request=AmountSerializer,
    responses={201: TransactionSerializer},
)
class WithdrawView(APIView):
    """Take `amount` paisa out of a wallet of the calling tenant and return the new WITHDRAWAL transaction.

    Fails with 422 if the balance is lower than the amount; nothing changes then.
    """

    def post(self, request, wallet_id):
        key = get_idempotency_key(request)
        serializer = AmountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transaction = services.withdraw(request.auth, wallet_id, serializer.validated_data['amount'], key)
        return Response(TransactionSerializer(transaction).data, status=status.HTTP_201_CREATED)
