from django.urls import path

from .views import (
    DepositView,
    TransferView,
    UserCreateView,
    WalletDetailView,
    WalletTransactionListView,
    WithdrawView,
)

urlpatterns = [
    path('users', UserCreateView.as_view(), name='user-create'),
    path('wallets/<uuid:wallet_id>', WalletDetailView.as_view(), name='wallet-detail'),
    path(
        'wallets/<uuid:wallet_id>/transactions',
        WalletTransactionListView.as_view(),
        name='wallet-transactions',
    ),
    path('wallets/<uuid:wallet_id>/deposit', DepositView.as_view(), name='wallet-deposit'),
    path('wallets/<uuid:wallet_id>/withdraw', WithdrawView.as_view(), name='wallet-withdraw'),
    path('transfers', TransferView.as_view(), name='transfer'),
]
