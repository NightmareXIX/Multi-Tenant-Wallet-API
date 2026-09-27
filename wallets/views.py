from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .exceptions import IdempotencyKeyMissing
from .models import Transaction
from .serializers import (
    AmountSerializer,
    ErrorSerializer,
    TransactionSerializer,
    TransferSerializer,
    UserSerializer,
    WalletSerializer,
)
from .services import get_wallet_for_tenant

IDEMPOTENCY_KEY = OpenApiParameter(
    'Idempotency-Key',
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description='Any string up to 255 characters, unique per request (a UUID is recommended). '
    'Resending the same request with the same key returns the original result without moving money again.',
)


def error(codes):
    """Document an error status: the error body, carrying one of these codes."""
    return OpenApiResponse(ErrorSerializer, description=codes)


UNAUTHORIZED = error('invalid_api_key')
NOT_FOUND = error('not_found: the wallet does not exist or belongs to another tenant')


def get_idempotency_key(request):
    key = request.headers.get('Idempotency-Key', '')
    if not key.strip() or len(key) > 255:
        raise IdempotencyKeyMissing()
    return key


@extend_schema(
    summary='Create a user and their wallet',
    tags=['Users'],
    responses={201: UserSerializer, 400: error('validation_error'), 401: UNAUTHORIZED},
)
class UserCreateView(generics.CreateAPIView):
    """Create a user in the calling tenant, together with their one wallet (balance 0).

    Keep the returned `wallet.id`: every money route takes it.
    """

    serializer_class = UserSerializer


@extend_schema(
    summary='Get a wallet and its balance',
    tags=['Wallets'],
    responses={200: WalletSerializer, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
class WalletDetailView(generics.RetrieveAPIView):
    """Return a wallet of the calling tenant. Another tenant's wallet is a 404, like a missing one."""

    serializer_class = WalletSerializer

    def get_object(self):
        return get_wallet_for_tenant(self.request.auth, self.kwargs['wallet_id'])


class TransactionPagination(PageNumberPagination):
    page_size = 10


@extend_schema(
    summary="Get a wallet's transaction history",
    tags=['Wallets'],
    responses={
        200: TransactionSerializer,
        401: UNAUTHORIZED,
        404: error('not_found: the wallet does not exist, belongs to another tenant, or the page is out of range'),
    },
)
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
    responses={
        201: TransactionSerializer,
        400: error('validation_error or idempotency_key_missing'),
        401: UNAUTHORIZED,
        404: NOT_FOUND,
        422: error('idempotency_key_mismatch'),
    },
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
    responses={
        201: TransactionSerializer,
        400: error('validation_error or idempotency_key_missing'),
        401: UNAUTHORIZED,
        404: NOT_FOUND,
        422: error('insufficient_funds or idempotency_key_mismatch'),
    },
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


@extend_schema(
    summary='Transfer between two wallets',
    tags=['Money'],
    parameters=[IDEMPOTENCY_KEY],
    request=TransferSerializer,
    responses={
        201: TransactionSerializer,
        400: error('validation_error, idempotency_key_missing or same_wallet_transfer'),
        401: UNAUTHORIZED,
        404: error('not_found: either wallet does not exist or belongs to another tenant'),
        422: error('insufficient_funds or idempotency_key_mismatch'),
    },
)
class TransferView(APIView):
    """Move `amount` paisa between two wallets of the calling tenant and return the new TRANSFER transaction.

    Both balances change together or not at all. A wallet in another tenant is a 404, like a missing one.
    """

    def post(self, request):
        key = get_idempotency_key(request)
        serializer = TransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        transaction = services.transfer(
            request.auth, data['source_wallet_id'], data['destination_wallet_id'], data['amount'], key
        )
        return Response(TransactionSerializer(transaction).data, status=status.HTTP_201_CREATED)
