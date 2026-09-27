from django.urls import path

from .views import UserCreateView, WalletDetailView, WalletTransactionListView

urlpatterns = [
    path('users', UserCreateView.as_view(), name='user-create'),
    path('wallets/<uuid:wallet_id>', WalletDetailView.as_view(), name='wallet-detail'),
    path(
        'wallets/<uuid:wallet_id>/transactions',
        WalletTransactionListView.as_view(),
        name='wallet-transactions',
    ),
]
